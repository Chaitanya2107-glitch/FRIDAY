"""Labeled native controls; one line per command or website."""
import tkinter as tk
from tkinter import filedialog, ttk

SECTIONS = {
    'contacts': ('Contacts', 'People you message',
                 'Save contact names and WhatsApp numbers. Saving does not send a message.'),
    'routines': ('Routines', 'Your everyday shortcuts',
                 'One command per line, in execution order. Save here; run from the tray or chat.'),
    'projects': ('Projects', 'Keep your work together',
                 'Choose a project folder, its websites and optional resume steps.'),
    'modes': ('Modes', 'Set the tone for your session',
              'Save startup commands and quiet preferences. Changes apply the next time you start the mode.'),
}
FIELDS = {
    'contacts': [('number', 'Phone / WhatsApp number', 'entry', '+91 98765 43210')],
    'routines': [('steps', 'Commands · one per line', 'text', 'open vs code\nset volume to 30\nwait 2 seconds')],
    'projects': [('path', 'Project folder', 'folder', 'Choose an existing folder'),
                 ('repo', 'GitHub repository · optional', 'entry', 'owner/repository'),
                 ('sites', 'Websites · one domain or HTTP/HTTPS URL per line', 'text', 'example.com or https://example.com/dashboard'),
                 ('resume', 'Resume commands · optional, one per line', 'text', 'Blank uses the standard project resume steps')],
    'modes': [('steps', 'Startup commands · one per line', 'text', 'open vs code\nset volume to 25'),
              ('quiet', 'Quiet mode · hold proactive nudges and speech', 'bool', '')],
}


class Form(ttk.Frame):
    def __init__(self, master, section):
        super().__init__(master, style='Panel.TFrame')
        self.section, self.controls, self.variables = section, {}, {}
        self.columnconfigure(0, weight=1)
        row = 0
        for key, label, kind, hint in [('name', 'Name', 'entry', ''), *FIELDS[section]]:
            if kind == 'folder':
                hint = ''
            if kind == 'bool':
                variable = tk.BooleanVar(self)
                control = ttk.Checkbutton(self, text=label, variable=variable, style='Panel.TCheckbutton')
                control.grid(row=row, column=0, sticky='w', pady=(4, 3))
                self.variables[key] = variable
            else:
                ttk.Label(self, text=label, style='Field.TLabel').grid(row=row, column=0, sticky='w', pady=(6, 4))
                row += 1
                if kind == 'text':
                    control = tk.Text(self, height=2 if section == 'projects' else 4,
                        wrap='word', undo=True, bg='#0b1424', fg='#edf5ff', insertbackground='#6ee7d2',
                        selectbackground='#294c63', relief='flat', borderwidth=0,
                        highlightthickness=1, highlightbackground='#30415a', highlightcolor='#6ee7d2',
                        font=('Segoe UI', 10), padx=10, pady=6)
                    control.grid(row=row, column=0, sticky='ew')
                else:
                    variable = tk.StringVar(self)
                    self.variables[key] = variable
                    holder = ttk.Frame(self, style='Panel.TFrame')
                    holder.columnconfigure(0, weight=1)
                    holder.grid(row=row, column=0, sticky='ew')
                    control = ttk.Entry(holder, textvariable=variable)
                    control.grid(row=0, column=0, sticky='ew')
                    if kind == 'folder':
                        button = ttk.Button(holder, text='Browse…', command=self.browse)
                        button.grid(row=0, column=1, padx=(8, 0))
                        self.controls['_browse'] = button
                row += 1
                if hint:
                    ttk.Label(self, text=hint, style='Hint.TLabel', wraplength=600).grid(row=row, column=0, sticky='w', pady=(4, 0))
            self.controls[key] = control
            row += 1

    def browse(self):
        folder = filedialog.askdirectory(parent=self.winfo_toplevel(), title='Choose the project folder', mustexist=True)
        if folder:
            self.variables['path'].set(folder)

    def read(self):
        value = {key: variable.get() for key, variable in self.variables.items()}
        for key, _, kind, _ in FIELDS[self.section]:
            if kind == 'text':
                value[key] = [line.strip() for line in self.controls[key].get('1.0', 'end-1c').splitlines() if line.strip()]
        name = value.pop('name').strip()
        return name, value

    def fill(self, name='', value=None):
        value = value or {}
        for key, variable in self.variables.items():
            default = False if isinstance(variable, tk.BooleanVar) else ''
            variable.set(name if key == 'name' else value.get(key, default))
        for key, _, kind, _ in FIELDS[self.section]:
            if kind == 'text':
                control = self.controls[key]
                control.configure(state='normal')
                control.delete('1.0', 'end')
                control.insert('1.0', '\n'.join(value.get(key, [])))

    def enable(self, enabled):
        for key, control in self.controls.items():
            state = 'normal' if enabled else 'disabled'
            control.configure(state=state)
