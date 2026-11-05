"""Modal drafts keep values on validation or storage failures."""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from interfaces.productivity.style import BG, PANEL, TEXT, MUTED, LINE, theme


class Editor:
    def __init__(self, app, kind, item=None):
        self.app, self.kind, self.item, self.busy = app, kind, item or {}, False
        self.root = tk.Toplevel(app.root)
        self.root.title('FRIDAY / ' + ('Edit ' if item else 'New ') + kind)
        theme(self.root)
        self.root.geometry('570x620')
        self.root.minsize(510, 520)
        self.root.transient(app.root)
        self.root.grab_set()
        self.frame = ttk.Frame(self.root, padding=26)
        self.frame.pack(fill='both', expand=True)
        self.frame.columnconfigure(0, weight=1)
        ttk.Label(self.frame, text='MAKE ROOM FOR WHAT MATTERS', style='Brand.TLabel').grid(row=0, sticky='w')
        ttk.Label(self.frame, text=('Edit ' if item else 'New ') + kind, style='Title.TLabel').grid(row=1, sticky='w', pady=(8, 18))
        self.name = tk.StringVar(self.root, self.item.get('name', self.item.get('title', '')))
        self.field('Habit name' if kind == 'habit' else 'Task name', 2)
        self.entry = ttk.Entry(self.frame, textvariable=self.name)
        self.entry.grid(row=3, sticky='ew', pady=(4, 14))
        self.days = []
        if kind == 'habit':
            self.field('Repeat on', 4)
            week = ttk.Frame(self.frame, style='Card.TFrame')
            week.grid(row=5, sticky='ew', pady=(6, 14))
            for i, name in enumerate(['M', 'T', 'W', 'T', 'F', 'S', 'S']):
                var = tk.BooleanVar(self.root, i in self.item.get('weekdays', range(7)))
                self.days.append(var)
                ttk.Checkbutton(week, text=name, variable=var).pack(side='left', expand=True)
            ttk.Label(self.frame, text='Daily check-ins · streaks skip your rest days', style='Muted.TLabel').grid(row=6, sticky='w')
        else:
            self.field('Due date (YYYY-MM-DD, optional)', 4)
            self.due = tk.StringVar(self.root, self.item.get('due', ''))
            ttk.Entry(self.frame, textvariable=self.due).grid(row=5, sticky='ew', pady=(4, 10))
            self.priority = tk.StringVar(self.root, self.item.get('priority', 'normal'))
            self.field('Priority', 6)
            ttk.Combobox(self.frame, textvariable=self.priority, values=['low', 'normal', 'high'], state='readonly').grid(row=7, sticky='ew', pady=(4, 10))
        self.field('Notes (optional)', 8)
        self.notes = tk.Text(self.frame, height=4, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief='flat', padx=12, pady=10, wrap='word', font=('Segoe UI', 10), undo=True)
        self.notes.insert('1.0', self.item.get('notes', ''))
        self.notes.grid(row=9, sticky='nsew', pady=(5, 12))
        self.frame.rowconfigure(9, weight=1)
        self.error = tk.StringVar(self.root)
        ttk.Label(self.frame, textvariable=self.error, foreground='#ff9ba9', wraplength=500).grid(row=10, sticky='ew', pady=4)
        self.save_button = ttk.Button(self.frame, text='Save ' + kind, style='Accent.TButton', command=self.save)
        self.save_button.grid(row=11, sticky='e', pady=(12, 0))
        self.root.bind('<Control-Return>', lambda e: self.save())
        self.root.bind('<Escape>', lambda e: self.close())
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.entry.focus_set()
        self.original = self.values()
        app.dialogs.append(self)

    def field(self, name, row):
        ttk.Label(self.frame, text=name).grid(row=row, sticky='w')

    def values(self):
        value = {'name' if self.kind == 'habit' else 'title': self.name.get(), 'notes': self.notes.get('1.0', 'end-1c')}
        if self.kind == 'habit':
            value['weekdays'] = [i for i, var in enumerate(self.days) if var.get()]
        else:
            value.update(due=self.due.get().strip(), priority=self.priority.get())
        return value

    def save(self):
        if self.busy:
            return
        self.busy = True
        self.save_button.state(['disabled'])
        value = self.values()
        self.freeze(self.frame, True)
        if self.item:
            value.update(ident=self.item['id'], revision=self.item.get('revision', self.item.get('updated')))
        operation = self.app.store.save_habit if self.kind == 'habit' else self.app.store.save_task
        def finished(result, error):
            self.busy = False
            self.freeze(self.frame, False)
            self.save_button.state(['!disabled'])
            if error:
                self.error.set(str(error))
                return
            self.close(force=True)
            self.app.refresh('Saved. FRIDAY shares this update.')
        self.app.submit(lambda: operation(**value), finished)

    @staticmethod
    def freeze(parent, frozen):
        for child in parent.winfo_children():
            if isinstance(child, ttk.Combobox):
                child.configure(state='disabled' if frozen else 'readonly')
            elif isinstance(child, (ttk.Entry, ttk.Checkbutton, ttk.Button)):
                child.configure(state='disabled' if frozen else 'normal')
            elif isinstance(child, tk.Text):
                child.configure(state='disabled' if frozen else 'normal')
            else:
                Editor.freeze(child, frozen)

    def close(self, force=False):
        if self.busy:
            self.error.set('Saving your changes. Please wait a moment.')
            return
        if not force and self.values() != self.original and not messagebox.askyesno('Discard draft?', 'Close without saving your changes?', parent=self.root):
            return
        self.app.dialogs.remove(self)
        self.root.destroy()


class Importer:
    def __init__(self, app):
        self.app, self.busy, self.csv = app, False, False
        self.root = tk.Toplevel(app.root)
        theme(self.root)
        self.root.title('FRIDAY / Load habits')
        self.root.geometry('610x560')
        self.root.transient(app.root)
        self.root.grab_set()
        frame = ttk.Frame(self.root, padding=26)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Bring your habits along', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(frame, text='Paste one habit per line, or open a TXT / CSV file.\nDuplicates are skipped; existing habits and history are kept.', style='Muted.TLabel').pack(anchor='w', pady=12)
        self.input = tk.Text(frame, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief='flat', padx=12, pady=12, font=('Segoe UI', 11), wrap='word', undo=True)
        self.input.pack(fill='both', expand=True)
        self.message = tk.StringVar(self.root, 'Plain text · one habit per line · daily schedule')
        ttk.Label(frame, textvariable=self.message, wraplength=550).pack(anchor='w', pady=10)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        self.open_button = ttk.Button(buttons, text='Open TXT / CSV', command=self.open)
        self.open_button.pack(side='left')
        self.save_button = ttk.Button(buttons, text='Import habits', style='Accent.TButton', command=self.save)
        self.save_button.pack(side='right')
        self.original = ''
        app.dialogs.append(self)
        self.root.protocol('WM_DELETE_WINDOW', self.close)

    def open(self):
        if self.busy:
            return
        filename = filedialog.askopenfilename(parent=self.root, filetypes=[('Habit lists', '*.txt *.csv')])
        if not filename:
            return
        self.busy = True
        self.open_button.state(['disabled'])
        self.save_button.state(['disabled'])
        self.input.configure(state='disabled')
        def read():
            with Path(filename).resolve().open('rb') as source:
                data = source.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError('Choose a file smaller than 1 MB.')
            return data.decode('utf-8-sig')
        def loaded(content, error):
            self.busy = False
            self.open_button.state(['!disabled'])
            self.save_button.state(['!disabled'])
            self.input.configure(state='normal')
            if error:
                self.message.set(str(error))
                return
            self.csv = Path(filename).suffix.lower() == '.csv'
            self.input.delete('1.0', 'end')
            self.input.insert('1.0', content)
            self.message.set('CSV columns: name, weekdays, notes. Weekdays: "0,1,2,3,4" (Monday=0).' if self.csv else 'Plain text · one habit per line · daily schedule')
        self.app.submit(read, loaded)

    def save(self):
        if self.busy:
            return
        content = self.input.get('1.0', 'end-1c')
        self.busy = True
        self.save_button.state(['disabled'])
        self.open_button.state(['disabled'])
        self.input.configure(state='disabled')
        def finished(result, error):
            self.busy = False
            self.save_button.state(['!disabled'])
            self.open_button.state(['!disabled'])
            self.input.configure(state='normal')
            if error:
                self.message.set(str(error))
                return
            self.close(force=True)
            self.app.refresh(f'Imported {result[0]} habits; skipped {result[1]} duplicates.')
        self.app.submit(lambda: self.app.store.import_habits(content, self.csv), finished)

    def values(self):
        return self.input.get('1.0', 'end-1c')

    def close(self, force=False):
        if self.busy:
            self.message.set('Finishing this request. Please wait.')
            return
        if not force and self.values() and not messagebox.askyesno('Discard import?', 'Close without importing this list?', parent=self.root):
            return
        self.app.dialogs.remove(self)
        self.root.destroy()
