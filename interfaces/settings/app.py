"""Native configuration editors with background I/O and retained drafts."""
from concurrent.futures import ThreadPoolExecutor
import queue
import tkinter as tk
from tkinter import messagebox, ttk

from interfaces.settings.client import Client
from interfaces.settings.forms import Form, SECTIONS
from interfaces.settings.launcher import TITLE, instance

BG, PANEL, TEXT, MUTED, ACCENT = '#0b1220', '#152136', '#edf5ff', '#a6b7ce', '#6ee7d2'


def theme(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Segoe UI', 10), background=BG, foreground=TEXT)
    style.configure('TFrame', background=BG)
    style.configure('Panel.TFrame', background=PANEL)
    for name in ('Panel.TLabel', 'Field.TLabel', 'Hint.TLabel'):
        style.configure(name, background=PANEL)
    style.configure('Hint.TLabel', foreground=MUTED, font=('Segoe UI', 9))
    style.configure('Field.TLabel', font=('Segoe UI Semibold', 10))
    style.configure('Title.TLabel', font=('Segoe UI Semibold', 22))
    style.configure('Brand.TLabel', foreground=ACCENT, font=('Segoe UI Semibold', 9))
    style.configure('Muted.TLabel', foreground=MUTED)
    style.configure('Editor.TLabel', background=PANEL, font=('Segoe UI Semibold', 17))
    style.configure('TEntry', fieldbackground='#0b1424', foreground=TEXT, padding=8, bordercolor='#30415a')
    style.map('TEntry', fieldbackground=[('readonly', '#1c2c43'), ('disabled', PANEL)],
              foreground=[('disabled', MUTED), ('readonly', TEXT)])
    style.configure('TButton', padding=(13, 8), background='#253750', foreground=TEXT, borderwidth=0)
    style.map('TButton', background=[('active', '#344e6b'), ('disabled', '#1b293c')], foreground=[('disabled', '#8090a8')])
    style.configure('Accent.TButton', background=ACCENT, foreground='#082325', font=('Segoe UI Semibold', 10))
    style.map('Accent.TButton', background=[('active', '#a0f5e5'), ('disabled', '#29464c')])
    style.configure('Danger.TButton', foreground='#ffb6b8')
    style.configure('TNotebook', borderwidth=0, tabmargins=(0, 4, 0, 10), bordercolor='#30415a')
    style.configure('TNotebook.Tab', padding=(18, 8), background=BG, foreground=MUTED,
                    lightcolor='#30415a', darkcolor='#30415a', bordercolor='#30415a')
    style.map('TNotebook.Tab', background=[('selected', PANEL)], foreground=[('selected', ACCENT)])
    style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                    rowheight=36, borderwidth=0, font=('Segoe UI', 10))
    style.map('Treeview', background=[('selected', '#294c63')], foreground=[('selected', TEXT)])
    style.configure('Panel.TCheckbutton', background=PANEL, foreground=TEXT, padding=(0, 5))
    style.map('Panel.TCheckbutton', background=[('active', PANEL)])


class Editor(ttk.Frame):
    def __init__(self, master, app, section):
        super().__init__(master, padding=(0, 8, 0, 0))
        self.app, self.section = app, section
        self.data, self.original, self.baseline = None, None, None
        self.busy, self.updating = False, False
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        left = ttk.Frame(self, padding=16, style='Panel.TFrame', width=270)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 14))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(3, weight=1)
        ttk.Label(left, text='SAVED ' + SECTIONS[section][0].upper(), style='Field.TLabel').grid(row=0, column=0, sticky='w')
        self.search = tk.StringVar(self)
        entry = ttk.Entry(left, textvariable=self.search, width=24)
        entry.grid(row=1, column=0, sticky='ew', pady=(12, 5))
        ttk.Label(left, text='Type to filter the list', style='Hint.TLabel').grid(row=2, column=0, sticky='w', pady=(0, 9))
        self.list = ttk.Treeview(left, show='tree', selectmode='browse', height=9)
        self.list.column('#0', width=235, stretch=True)
        self.list.grid(row=3, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(left, command=self.list.yview)
        scroll.grid(row=3, column=1, sticky='ns')
        self.list.configure(yscrollcommand=scroll.set)
        self.count = ttk.Label(left, text='Loading…', style='Hint.TLabel')
        self.count.grid(row=4, column=0, sticky='w', pady=(12, 0))
        self.list.bind('<<TreeviewSelect>>', self.select)
        self.list.bind('<Delete>', lambda event: self.delete())
        self.search.trace_add('write', lambda *args: self.populate())

        right = ttk.Frame(self, padding=18, style='Panel.TFrame')
        right.grid(row=0, column=1, sticky='nsew')
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        self.title = ttk.Label(right, text=SECTIONS[section][1], style='Editor.TLabel')
        self.title.grid(row=0, column=0, sticky='w')
        ttk.Label(right, text=SECTIONS[section][2], style='Hint.TLabel', wraplength=650).grid(row=1, column=0, sticky='w', pady=(5, 12))
        canvas = tk.Canvas(right, bg=PANEL, highlightthickness=0, borderwidth=0)
        self.canvas = canvas
        canvas.grid(row=2, column=0, sticky='nsew')
        bar = ttk.Scrollbar(right, orient='vertical', command=canvas.yview)
        bar.grid(row=2, column=1, sticky='ns')
        canvas.configure(yscrollcommand=bar.set)
        self.form = Form(canvas, section)
        window = canvas.create_window((0, 0), window=self.form, anchor='nw')
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
        self.form.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        self.message = ttk.Label(right, text='Select an entry, or create a new one.', style='Hint.TLabel', wraplength=630)
        self.message.grid(row=3, column=0, sticky='ew', pady=(12, 8))
        actions = ttk.Frame(right, style='Panel.TFrame')
        actions.grid(row=4, column=0, sticky='ew')
        actions.columnconfigure(2, weight=1)
        self.new_button = ttk.Button(actions, text='+ New', command=self.new)
        self.new_button.grid(row=0, column=0, padx=(0, 8))
        self.reload_button = ttk.Button(actions, text='Reload', command=self.reload)
        self.reload_button.grid(row=0, column=1)
        self.delete_button = ttk.Button(actions, text='Delete',
                                       style='Danger.TButton', command=self.delete)
        self.delete_button.grid(row=0, column=3, padx=(8, 8))
        self.save_button = ttk.Button(actions, text='Save changes', style='Accent.TButton', command=self.save)
        self.save_button.grid(row=0, column=4)
        self.buttons = (self.new_button, self.reload_button, self.delete_button, self.save_button)
        self.form.fill()
        self.baseline = self.form.read()
        self.enabled(False)

    def dirty(self):
        return self.baseline is not None and self.form.read() != self.baseline

    def discard(self):
        return not self.dirty() or messagebox.askyesno('Unsaved changes', 'Discard the unsaved changes in this tab?', parent=self.app.root)

    def enabled(self, enabled):
        self.form.enable(enabled)
        for button in self.buttons:
            button.configure(state='normal' if enabled else 'disabled')
        # Reload remains useful when the backend is offline.
        self.reload_button.configure(state='disabled' if self.busy else 'normal')
        if self.original is None:
            self.delete_button.configure(state='disabled')

    def populate(self):
        if self.data is None:
            return
        self.updating = True
        try:
            self.list.delete(*self.list.get_children())
            query = self.search.get().casefold()
            for item in self.data['items']:
                label = item.get('label', item['name'])
                if query in (item['name'] + ' ' + label).casefold():
                    suffix = ' · active' if item['name'] == self.data.get('active') else ''
                    self.list.insert('', 'end', iid=item['name'], text=label + suffix)
            if self.original and self.list.exists(self.original):
                self.list.selection_set(self.original)
            self.count.configure(text=f"{len(self.list.get_children())} of {len(self.data['items'])} saved entries")
        finally:
            self.updating = False

    def fill(self, name=None):
        row = next((item for item in self.data['items'] if item['name'] == name), None) if self.data else None
        self.original = row['name'] if row else None
        self.form.fill(self.original or '', row['value'] if row else None)
        self.baseline = self.form.read()
        self.title.configure(text=self.original or 'New ' + {'contacts': 'contact', 'routines': 'routine',
                             'projects': 'project', 'modes': 'mode', 'screen_apps': 'app rule'}[self.section])
        self.enabled(self.data is not None and not self.busy)

    def select(self, event=None):
        if self.updating or self.busy:
            return
        selected = self.list.selection()
        if not selected or selected[0] == self.original:
            return
        if not self.discard():
            if self.original and self.list.exists(self.original):
                self.list.selection_set(self.original)
            else:
                self.list.selection_remove(*self.list.selection())
            return
        self.fill(selected[0])
        self.message.configure(text='Edit the fields, then save your changes.')

    def new(self):
        if self.busy or not self.discard():
            return
        self.fill()
        self.list.selection_remove(*self.list.selection())
        self.form.controls['name'].focus_set()
        self.message.configure(text='Choose a unique name for the new entry.')

    def reload(self):
        if not self.busy and self.discard():
            self.work(lambda: self.app.client.load(self.section), 'Settings loaded.')

    def revision(self):
        return self.data['revision']

    def save(self):
        if self.busy or self.data is None:
            return
        name, value = self.form.read()
        if not name:
            self.message.configure(text='Enter a name before saving.')
            self.form.controls['name'].focus_set()
            return
        self.work(lambda: self.app.client.save(self.section, self.original, name, value, self.revision()), 'Changes saved.')

    def delete(self):
        if self.busy or self.original is None:
            return
        if not messagebox.askyesno('Delete entry', f'Delete “{self.original}”?\nThis removes the saved entry.', parent=self.app.root):
            return
        self.work(lambda: self.app.client.delete(self.section, self.original, self.revision()), 'Delete completed.')

    def work(self, operation, success):
        self.busy = True
        self.enabled(False)
        self.message.configure(text='Working…')
        def finished(data, error):
            self.busy = False
            if error:
                self.message.configure(text=str(error))
                status = getattr(error, 'status', None)
                self.app.connection.set('Backend unavailable' if status is None or status >= 500 else
                                        'Restart FRIDAY' if status == 404 else
                                        'Changed elsewhere · draft kept' if status == 409 else 'Please check the form')
                if self.data is None:
                    self.count.configure(text='Not loaded · choose Reload to retry')
                self.enabled(self.data is not None)
                return
            old = self.original
            self.data = data
            name = data.get('selected', old)
            if not any(item['name'] == name for item in data['items']):
                name = data['items'][0]['name'] if data['items'] else None
            self.fill(name)
            self.populate()
            self.message.configure(text=data.get('warning') or success)
            self.app.connection.set('Connected · saved locally')
        self.app.submit(operation, finished)


class SettingsWindow:
    def __init__(self, root, client=None):
        self.root, self.client = root, client or Client()
        self.executor, self.results = ThreadPoolExecutor(max_workers=1, thread_name_prefix='settings-io'), queue.Queue()
        self.closed = False
        theme(root)
        root.title(TITLE)
        width, height = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f'{min(1120, width - 60)}x{min(800, height - 80)}')
        root.minsize(min(980, width - 60), min(700, height - 80))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        header = ttk.Frame(root, padding=(26, 14, 26, 10))
        header.grid(row=0, column=0, sticky='ew')
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text='F R I D A Y  /  PERSONAL SETUP', style='Brand.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(header, text='Make FRIDAY yours', style='Title.TLabel').grid(row=1, column=0, sticky='w', pady=(3, 2))
        ttk.Label(header, text='Your people, shortcuts and workspaces. All in one place.', style='Muted.TLabel').grid(row=2, column=0, sticky='w')
        self.connection = tk.StringVar(root, 'Connecting…')
        ttk.Label(header, textvariable=self.connection, style='Brand.TLabel').grid(row=1, column=1, padx=(12, 0))
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=1, column=0, sticky='nsew', padx=24)
        self.editors = {}
        for section, (label, _, _) in SECTIONS.items():
            editor = Editor(self.notebook, self, section)
            self.editors[section] = editor
            self.notebook.add(editor, text=label)
        self.notebook.bind('<<NotebookTabChanged>>', self.changed)
        ttk.Label(root, text='Ctrl+S  Save     Ctrl+N  New     F5  Reload', style='Muted.TLabel',
                  padding=(26, 12)).grid(row=2, column=0, sticky='w')
        root.bind('<Control-s>', lambda event: self.current().save())
        root.bind('<Control-n>', lambda event: self.current().new())
        root.bind('<F5>', lambda event: self.current().reload())
        root.bind('<MouseWheel>', self.scroll)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.timer = root.after(50, self.poll)

    def current(self):
        return list(self.editors.values())[self.notebook.index('current')]

    def changed(self, event=None):
        editor = self.current()
        if editor.data is None and not editor.busy:
            editor.reload()

    def scroll(self, event):
        if not isinstance(event.widget, (tk.Text, ttk.Treeview)):
            self.current().canvas.yview_scroll(-int(event.delta / 120), 'units')

    def submit(self, operation, callback):
        def run():
            try:
                data, error = operation(), None
            except Exception as failure:
                data, error = None, failure
            self.results.put((callback, data, error))
        self.executor.submit(run)

    def poll(self):
        while not self.results.empty():
            callback, data, error = self.results.get_nowait()
            callback(data, error)
        if not self.closed:
            self.timer = self.root.after(50, self.poll)

    def close(self):
        if any(editor.busy for editor in self.editors.values()):
            messagebox.showinfo('Please wait', 'A settings request is still finishing. Please try closing again in a moment.', parent=self.root)
            return
        if any(editor.dirty() for editor in self.editors.values()) and not messagebox.askyesno(
                'Unsaved changes', 'Close and discard unsaved changes?', parent=self.root):
            return
        self.closed = True
        self.root.after_cancel(self.timer)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    handle = instance()
    if not handle:
        return
    root = tk.Tk()
    SettingsWindow(root)
    root.mainloop()


if __name__ == '__main__':
    main()
