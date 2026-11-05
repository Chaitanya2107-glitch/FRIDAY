"""Reusable native field dialogs with draft protection and inline server errors."""
import tkinter as tk
from tkinter import messagebox, ttk

from interfaces.college import viewmodel as vm
from interfaces.settings.app import BG, PANEL


class EditDialog:
    def __init__(self, app, title, fields, initial, save, review=None):
        self.app, self.save_action, self.review_action = app, save, review
        self.window = tk.Toplevel(app.root)
        self.window.title(title)
        self.window.configure(bg=BG)
        self.window.transient(app.root)
        self.window.geometry(f'580x{min(720, app.root.winfo_screenheight() - 120)}')
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)
        self.busy, self.closed = False, False
        self.fields, self.controls, self.widgets = fields, {}, []
        ttk.Label(self.window, text=title, style='Editor.TLabel', padding=16).grid(row=0, column=0, sticky='ew')
        container = ttk.Frame(self.window, style='Panel.TFrame')
        container.grid(row=1, column=0, sticky='nsew', padx=16)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        canvas = tk.Canvas(container, background=PANEL, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(container, command=canvas.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        canvas.configure(yscrollcommand=scroll.set)
        form = ttk.Frame(canvas, padding=14, style='Panel.TFrame')
        form.columnconfigure(0, weight=1)
        item = canvas.create_window(0, 0, window=form, anchor='nw')
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        form.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        for index, (key, label, kind) in enumerate(fields):
            ttk.Label(form, text=label, style='Field.TLabel').grid(row=index * 2, column=0, sticky='w', pady=(8, 3))
            if kind == 'text':
                control = tk.Text(form, height=3, wrap='word', background='#0b1424', foreground='#edf5ff',
                                  insertbackground='#6ee7d2', font=('Segoe UI', 10), relief='flat', padx=8, pady=6)
                control.insert('1.0', initial.get(key, ''))
                self.controls[key] = control
                control.bind('<Tab>', lambda event: event.widget.tk_focusNext().focus_set() or 'break')
                control.bind('<Shift-Tab>', lambda event: event.widget.tk_focusPrev().focus_set() or 'break')
            else:
                variable = tk.BooleanVar(form, bool(initial.get(key))) if kind == 'bool' else tk.StringVar(form, initial.get(key, ''))
                if kind == 'bool':
                    control = ttk.Checkbutton(form, variable=variable, text='Mark as completed', style='Panel.TCheckbutton')
                elif isinstance(kind, (tuple, list)):
                    control = ttk.Combobox(form, textvariable=variable, values=kind, state='readonly')
                else:
                    control = ttk.Entry(form, textvariable=variable)
                self.controls[key] = variable
            control.grid(row=index * 2 + 1, column=0, sticky='ew', pady=(0, 5))
            self.widgets.append((control, kind))
            if index == 0:
                control.focus_set()
        self.baseline = self.values()
        self.message = tk.StringVar(self.window, 'Changes are saved only when you choose Save.')
        ttk.Label(self.window, textvariable=self.message, wraplength=530, padding=(16, 12)).grid(row=2, column=0, sticky='ew')
        actions = ttk.Frame(self.window, padding=16)
        actions.grid(row=3, column=0, sticky='ew')
        self.review_button = ttk.Button(actions, text='Review current version', command=self.review, state='disabled')
        self.review_button.pack(side='left')
        ttk.Button(actions, text='Cancel', command=self.close).pack(side='right', padx=(8, 0))
        self.save_button = ttk.Button(actions, text='Save', command=self.save, style='Accent.TButton')
        self.save_button.pack(side='right')
        self.window.bind('<Escape>', lambda event: self.close())
        self.window.bind('<Return>', self.enter)
        self.window.bind('<Control-Return>', lambda event: self.save())
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.grab_set()
        app.dialogs.append(self)

    def values(self):
        return {key: control.get('1.0', 'end-1c').strip() if isinstance(control, tk.Text) else control.get()
                for key, control in self.controls.items()}

    def dirty(self):
        return self.values() != self.baseline

    def enter(self, event):
        if not isinstance(event.widget, tk.Text):
            self.save()
            return 'break'

    def save(self):
        if self.busy or str(self.save_button['state']) == 'disabled':
            return
        values = self.values()
        self.busy = True
        self.enable_fields(False)
        self.save_button.configure(state='disabled')
        self.message.set('Saving…')
        self.save_action(values, self.finished)

    def finished(self, data, error):
        if self.closed:
            return
        self.busy = False
        if error:
            self.enable_fields(True)
            self.message.set(str(error))
            conflict = getattr(error, 'status', None) == 409
            self.save_button.configure(state='disabled' if conflict else 'normal')
            if conflict and self.review_action:
                self.review_button.configure(state='normal')
                self.app.refresh()
            return
        self.app.status.set(data.get('message', 'Changes saved.'))
        self.close(force=True)
        self.app.refresh()

    def enable_fields(self, enabled):
        for widget, kind in self.widgets:
            widget.configure(state=('readonly' if isinstance(kind, (tuple, list)) else 'normal') if enabled else 'disabled')

    def review(self):
        if self.review_action and not self.busy:
            self.review_action(self)

    def reviewed(self):
        self.save_button.configure(state='normal')
        self.review_button.configure(state='disabled')
        self.message.set('Current version reviewed. Your draft is kept; choose Save to apply it.')

    def close(self, force=False):
        if self.closed:
            return True
        if self.busy and not force:
            self.message.set('A request is finishing. You can continue using FRIDAY.')
            return False
        if not force and self.dirty() and not messagebox.askyesno('Unsaved changes', 'Discard this unsaved draft?', parent=self.window):
            return False
        self.closed = True
        self.app.dialogs.remove(self)
        self.window.grab_release()
        self.window.destroy()
        return True
