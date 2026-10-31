"""Weekly day/time grid and separate subject-details editor."""
import copy
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import messagebox, ttk

from interfaces.college import viewmodel as vm
from interfaces.college.dialogs import EditDialog
from interfaces.college.tabs import open_editor, table


class Week(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=(6, 10))
        self.app, self.data, self.subjects, self.busy = app, None, None, False
        self.cells = {}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=3)
        self.rowconfigure(4, weight=2)
        actions = ttk.Frame(self)
        actions.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        ttk.Button(actions, text='+ Weekly slot', style='Accent.TButton', command=self.new).pack(side='left')
        ttk.Button(actions, text='Edit slot', command=self.edit).pack(side='left', padx=8)
        ttk.Button(actions, text='Change this date only', command=self.move_date).pack(side='left')
        ttk.Button(actions, text='Remove slot', command=self.delete, style='Danger.TButton').pack(side='right')
        columns = [('time', 'Time', 125), *((day, day[:3].title(), 125) for day in vm.DAYS)]
        frame, self.grid = table(self, columns, height=6)
        frame.grid(row=1, column=0, sticky='nsew')
        self.grid.bind('<ButtonRelease-1>', self.pick)
        self.grid.bind('<Double-1>', lambda event: self.edit())
        self.grid.bind('<Return>', lambda event: self.edit())
        self.grid.bind('<Delete>', lambda event: self.delete())
        selection = ttk.Frame(self)
        selection.grid(row=2, column=0, sticky='ew', pady=8)
        ttk.Label(selection, text='Selected day').pack(side='left')
        self.day = tk.StringVar(self, vm.DAYS[datetime.now().weekday()])
        ttk.Combobox(selection, textvariable=self.day, values=vm.DAYS, state='readonly', width=14).pack(side='left', padx=10)
        ttk.Label(selection, text='Select a time row and day, or click a class cell.', style='Muted.TLabel').pack(side='left')
        subjects = ttk.Frame(self)
        subjects.grid(row=3, column=0, sticky='ew', pady=(8, 10))
        ttk.Label(subjects, text='SUBJECT DETAILS', style='Brand.TLabel').pack(side='left')
        ttk.Button(subjects, text='+ Subject details', command=lambda: self.subject_editor(None)).pack(side='right')
        ttk.Button(subjects, text='Edit faculty / room', command=self.edit_subject).pack(side='right', padx=8)
        frame, self.subject_tree = table(self, [('subject', 'Subject', 200), ('faculty', 'Faculty', 230),
                                               ('room', 'Room', 130), ('email', 'Email', 250)], height=4)
        frame.grid(row=4, column=0, sticky='nsew')
        self.subject_tree.bind('<Double-1>', lambda event: self.edit_subject())
        self.subject_tree.bind('<Return>', lambda event: self.edit_subject())
        self.subject_tree.bind('<Delete>', lambda event: self.delete_subject())
        self.message = ttk.Label(self, text='Loading…', style='Muted.TLabel', wraplength=1050)
        self.message.grid(row=5, column=0, sticky='ew', pady=8)

    def load(self):
        if self.busy:
            return
        self.busy = True
        client = self.app.client
        def operation():
            return client.load('timetable'), client.load('subjects')
        self.app.submit(operation, self.finished)

    def finished(self, data, error):
        self.busy = False
        if error:
            self.message.configure(text=str(error))
            self.app.failure(error)
            return
        self.data, self.subjects = data
        self.grid.delete(*self.grid.get_children())
        rows, self.cells = vm.grid_rows(self.data['items'])
        for identifier, values in rows:
            self.grid.insert('', 'end', iid=identifier, values=values)
        self.subject_tree.delete(*self.subject_tree.get_children())
        for row in self.subjects['items']:
            self.subject_tree.insert('', 'end', iid=row['id'], values=(row['subject'], row.get('faculty', ''), row.get('room', ''), row.get('email', '')))
        facts = self.data.get('cancellations', [])
        cancellations = [f'{f["from"]}–{f["through"]}: {f["subject"]} unavailable (read-only)' for f in facts if not f.get('classes_available', True)]
        self.message.configure(text='\n'.join(cancellations[:2]) or 'Faculty and room details stay separate from weekly slots and dated corrections.')
        self.app.connected()

    def pick(self, event):
        column = self.grid.identify_column(event.x)
        index = int(column[1:]) - 2 if column.startswith('#') else -1
        if 0 <= index < len(vm.DAYS):
            self.day.set(vm.DAYS[index])

    def selected(self):
        selection = self.grid.selection()
        identifier = self.cells.get((selection[0], self.day.get())) if selection else None
        return next((copy.deepcopy(r) for r in (self.data or {}).get('items', []) if r['id'] == identifier), None)

    def new(self):
        if self.data is not None and not self.busy:
            open_editor(self.app, 'timetable', None, self.data['revision'])

    def edit(self):
        row = self.selected()
        if row and not self.busy:
            open_editor(self.app, 'timetable', row, self.data['revision'])

    def delete(self):
        row = self.selected()
        if row and not self.busy and messagebox.askyesno('Remove weekly slot', 'Remove this weekly class slot?', parent=self.app.root):
            client, revision = self.app.client, self.data['revision']
            self.busy = True
            def finished(data, error):
                self.busy = False
                if error:
                    self.app.failure(error)
                self.load()
            self.app.submit(lambda: client.delete('timetable', row['id'], revision), finished, write=True)

    def edit_subject(self):
        selection = self.subject_tree.selection()
        row = next((r for r in (self.subjects or {}).get('items', []) if selection and r['id'] == selection[0]), None)
        if row:
            self.subject_editor(copy.deepcopy(row))

    def subject_editor(self, row):
        if self.subjects is not None and not self.busy:
            open_editor(self.app, 'subjects', row, self.subjects['revision'])

    def delete_subject(self):
        selection = self.subject_tree.selection()
        if not selection or self.subjects is None or self.busy:
            return
        if messagebox.askyesno('Remove subject details', 'Remove the selected subject’s saved faculty and room details?', parent=self.app.root):
            client, identifier, revision = self.app.client, selection[0], self.subjects['revision']
            self.busy = True
            def finished(data, error):
                self.busy = False
                if error:
                    self.app.failure(error)
                self.load()
            self.app.submit(lambda: client.delete('subjects', identifier, revision), finished, write=True)

    def move_date(self):
        row = self.selected()
        if row is None or self.busy:
            return
        today = datetime.now().date()
        target = today + timedelta(days=(vm.DAYS.index(row['day']) - today.weekday()) % 7 or 7)
        state = {'revision': self.data['revision']}
        client = self.app.client
        def save(values, callback):
            revision = state['revision']
            self.app.submit(lambda: client.move_date(row['id'], values['date'], values['start'], revision), callback, write=True)
        def review(dialog):
            def loaded(data, error):
                if dialog.closed:
                    return
                if error:
                    dialog.message.set(str(error))
                    return
                current = next((r for r in data['items'] if r['id'] == row['id']), None)
                if current != row:
                    dialog.message.set('The weekly template changed. Close this draft and select its current slot.')
                    return
                if messagebox.askyesno('Review current schedule', 'Current effective sessions:\n' +
                        '\n'.join(f'{r["subject"]}: {r["start"]}–{r["end"]}' for r in data.get('effective', [])) +
                        '\n\nKeep your draft and use this schedule version?', parent=dialog.window):
                    state['revision'] = data['revision']
                    dialog.reviewed()
            target_date = dialog.values()['date']
            self.app.submit(lambda: client.load('timetable?date=' + target_date), loaded)
        EditDialog(self.app, 'Change one dated class time', [('date', 'Occurrence date (YYYY-MM-DD)', None),
                   ('start', 'New start (24h HH:MM; duration is preserved)', None)],
                   {'date': target.isoformat(), 'start': row['start']}, save, review)
