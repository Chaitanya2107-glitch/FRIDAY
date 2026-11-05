"""Responsive native College Schedules window, following Customize FRIDAY."""
from concurrent.futures import ThreadPoolExecutor
import queue
import logging
import time
import tkinter as tk
from tkinter import messagebox, ttk

from interfaces.college.client import Client
from interfaces.college import launcher
from interfaces.college.tabs import Catalog, Home
from interfaces.college.upload import Upload
from interfaces.college.week import Week
from interfaces.settings.app import theme, TEXT, PANEL


class CollegeWindow:
    def __init__(self, root, client=None, ensure_backend=False):
        self.root, self.client = root, client or Client()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='college-io')
        self.results, self.dialogs, self.closed = queue.Queue(), [], False
        self.pending_writes, self.callback_errors = 0, []
        self.focus_timer, self.last_focus = None, 0
        theme(root)
        style = ttk.Style(root)
        style.configure('TCombobox', fieldbackground='#0b1424', background='#253750', foreground=TEXT, padding=5)
        style.map('TCombobox', fieldbackground=[('readonly', '#0b1424')], foreground=[('readonly', TEXT)],
                  selectbackground=[('readonly', '#294c63')], selectforeground=[('readonly', TEXT)])
        root.option_add('*TCombobox*Listbox.background', PANEL)
        root.option_add('*TCombobox*Listbox.foreground', TEXT)
        root.title(launcher.TITLE)
        width, height = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f'{min(1240, width - 80)}x{min(880, height - 100)}')
        root.minsize(min(1000, width - 80), min(680, height - 100))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        header = ttk.Frame(root, padding=(24, 16, 24, 8))
        header.grid(row=0, column=0, sticky='ew')
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text='F R I D A Y  /  COLLEGE', style='Brand.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(header, text='College Schedules', style='Title.TLabel').grid(row=1, column=0, sticky='w', pady=4)
        ttk.Label(header, text='Your classes, work and campus plans. Shared with FRIDAY.', style='Muted.TLabel').grid(row=2, column=0, sticky='w')
        self.connection = tk.StringVar(root, 'Connecting…')
        ttk.Label(header, textvariable=self.connection, style='Brand.TLabel').grid(row=0, column=1, sticky='e')
        ttk.Button(header, text='Retry / Refresh', command=self.refresh).grid(row=1, column=1, sticky='e')
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=1, column=0, sticky='nsew', padx=18)
        self.tabs = {'home': Home(self.notebook, self), 'timetable': Week(self.notebook, self),
                     'deadlines': Catalog(self.notebook, self, 'deadlines'), 'exams': Catalog(self.notebook, self, 'exams'),
                     'events': Catalog(self.notebook, self, 'events'), 'uploads': Upload(self.notebook, self)}
        for key, title in [('home', 'Home'), ('timetable', 'Timetable'), ('deadlines', 'Assignments & Homework'),
                           ('exams', 'Exams'), ('events', 'Events'), ('uploads', 'Upload')]:
            self.notebook.add(self.tabs[key], text=title)
        self.status = tk.StringVar(root, 'Ctrl+N  New     Enter  Edit     Delete  Remove     F5  Refresh  ·  Refreshes every 60 seconds')
        ttk.Label(root, textvariable=self.status, style='Muted.TLabel', wraplength=1120, padding=(24, 10)).grid(row=2, column=0, sticky='ew')
        self.notebook.bind('<<NotebookTabChanged>>', self.changed)
        root.bind('<Control-n>', lambda event: self.new())
        root.bind('<F5>', lambda event: self.refresh())
        root.bind('<FocusIn>', self.focused, add='+')
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_timer = root.after(30, self.poll)
        self.refresh_timer = root.after(60_000, self.tick)
        if ensure_backend:
            def started(data, error):
                if error:
                    self.failure(error)
                self.refresh()
                # Managed startup can take a few seconds; bounded background reads retry.
                self.focus_timer = root.after(5000, self.refresh)
            self.submit(launcher.ensure_backend, started)
        else:
            self.tabs['home'].load()

    def current(self):
        return list(self.tabs.values())[self.notebook.index('current')]

    def changed(self, event=None):
        if hasattr(self, 'status'):
            tab = self.current()
            if tab.data is None and not tab.busy:
                tab.load()

    def submit(self, operation, callback, write=False):
        if self.closed:
            return
        if write:
            self.pending_writes += 1
        results = self.results
        def run():
            try:
                data, error = operation(), None
            except Exception as failure:
                data, error = None, failure
            results.put((callback, data, error, write))
        self.executor.submit(run)

    def poll(self):
        while not self.results.empty():
            callback, data, error, write = self.results.get_nowait()
            if write:
                self.pending_writes -= 1
            if not self.closed:
                try:
                    callback(data, error)
                except Exception as failure:
                    self.callback_errors.append(type(failure).__name__)
                    logging.getLogger(__name__).exception('College window response callback failed')
                    self.status.set('This response could not be displayed. Choose Retry / Refresh.')
        if not self.closed:
            self.poll_timer = self.root.after(30, self.poll)

    def failure(self, error):
        self.connection.set('Backend unavailable' if getattr(error, 'status', None) is None else 'Please review')
        self.status.set(str(error))

    def connected(self):
        self.connection.set('Connected · saved locally')

    def refresh(self, automatic=False):
        if self.closed or (automatic and self.dialogs):
            return
        self.tabs['home'].load()
        tab = self.current()
        if tab is not self.tabs['home']:
            if automatic and hasattr(tab, 'dirty') and tab.dirty():
                return
            tab.load()

    def tick(self):
        self.refresh(automatic=True)
        if not self.closed:
            self.refresh_timer = self.root.after(60_000, self.tick)

    def focused(self, event=None):
        if self.closed or time.monotonic() - self.last_focus < 2:
            return
        self.last_focus = time.monotonic()
        if self.focus_timer:
            self.root.after_cancel(self.focus_timer)
        self.focus_timer = self.root.after(150, lambda: self.refresh(automatic=True))

    def new(self):
        if self.dialogs:
            return
        tab = self.current()
        if not hasattr(tab, 'new'):
            tab = self.tabs['deadlines']
            self.notebook.select(tab)
        if isinstance(tab, Catalog) and tab.data is None:
            client, section = self.client, tab.section
            def loaded(data, error):
                tab.finished(data, error)
                if not error:
                    tab.new()
            self.submit(lambda: client.load(section), loaded)
        else:
            tab.new()

    def close(self):
        if self.pending_writes or any(dialog.busy for dialog in self.dialogs):
            self.status.set('A save request is finishing. Try closing again in a moment.')
            return
        dirty = any(dialog.dirty() for dialog in self.dialogs) or self.tabs['uploads'].dirty()
        if dirty and not messagebox.askyesno('Unsaved changes', 'Close and discard unsaved drafts and the upload preview?', parent=self.root):
            return
        for dialog in list(self.dialogs):
            dialog.close(force=True)
        self.closed = True
        for timer in (self.poll_timer, self.refresh_timer, self.focus_timer):
            if timer:
                self.root.after_cancel(timer)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main(ensure_backend=False):
    handle = launcher.acquire_instance()
    if handle is None:
        if ensure_backend:
            launcher.ensure_backend()  # This duplicate process has no Tk event loop.
        return
    try:
        launcher.dpi_awareness()
        root = tk.Tk()
        CollegeWindow(root, ensure_backend=ensure_backend)
        root.mainloop()
    finally:
        launcher.release_instance(handle)
