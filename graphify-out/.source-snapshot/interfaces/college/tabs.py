"""Native read views and shared catalog controls; mutations stay in the API."""
import copy
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from interfaces.college.dialogs import EditDialog
from interfaces.college import viewmodel as vm


def table(master, columns, height=8):
    frame = ttk.Frame(master, style='Panel.TFrame')
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show='headings', selectmode='browse', height=height)
    for key, label, width in columns:
        tree.heading(key, text=label)
        tree.column(key, width=width, minwidth=65)
    tree.grid(row=0, column=0, sticky='nsew')
    vertical = ttk.Scrollbar(frame, command=tree.yview)
    horizontal = ttk.Scrollbar(frame, command=tree.xview, orient='horizontal')
    vertical.grid(row=0, column=1, sticky='ns')
    horizontal.grid(row=1, column=0, sticky='ew')
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    return frame, tree


def panel(master, title, row, column, columnspan=1):
    frame = ttk.Frame(master, padding=18, style='Panel.TFrame')
    frame.grid(row=row, column=column, columnspan=columnspan, sticky='nsew', padx=6, pady=6)
    frame.columnconfigure(0, weight=1)
    ttk.Label(frame, text=title, style='Field.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 10))
    return frame


class Home(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=(0, 6))
        self.app, self.data, self.busy, self.link = app, None, False, None
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(1, weight=1)
        card = panel(self, 'YOUR DAY / COLLEGE', 0, 0)
        self.title = ttk.Label(card, text='Loading your day…', style='Editor.TLabel', wraplength=580)
        self.title.grid(row=1, column=0, sticky='w')
        self.details = ttk.Label(card, text='The next class follows FRIDAY’s saved effective timetable.', style='Hint.TLabel', wraplength=580)
        self.details.grid(row=2, column=0, sticky='w', pady=(10, 8))
        self.join = ttk.Button(card, text='Join class', command=self.open_link, style='Accent.TButton', state='disabled')
        self.join.grid(row=3, column=0, sticky='w')
        exam = panel(self, 'NEXT EXAM', 0, 1)
        self.exam = ttk.Label(exam, text='No upcoming exams saved', style='Editor.TLabel', wraplength=360)
        self.exam.grid(row=1, column=0, sticky='w')
        self.exam_detail = ttk.Label(exam, text='Add an exam in the Exams tab.', style='Hint.TLabel', wraplength=360)
        self.exam_detail.grid(row=2, column=0, sticky='w', pady=10)
        today = panel(self, 'TODAY’S TIMELINE', 1, 0)
        today.rowconfigure(1, weight=1)
        frame, self.timeline = table(today, [('time', 'Time', 125), ('subject', 'Subject', 180), ('faculty', 'Faculty / room', 200)])
        frame.grid(row=1, column=0, sticky='nsew')
        self.notice = ttk.Label(today, text='', style='Hint.TLabel', wraplength=550)
        self.notice.grid(row=2, column=0, sticky='ew', pady=(8, 0))
        upcoming = panel(self, 'DUE SOON / NEXT 7 DAYS', 1, 1)
        upcoming.rowconfigure(1, weight=1)
        frame, self.due = table(upcoming, [('title', 'Work', 200), ('due', 'Time left', 130)], height=5)
        frame.grid(row=1, column=0, sticky='nsew')
        events = panel(self, 'UPCOMING EVENTS', 2, 0, 2)
        self.events = ttk.Label(events, text='No upcoming events saved', style='Hint.TLabel', wraplength=1000)
        self.events.grid(row=1, column=0, sticky='ew')

    def load(self):
        if self.busy:
            return
        self.busy = True
        client = self.app.client
        self.app.submit(lambda: client.load('overview'), self.finished)

    def finished(self, data, error):
        self.busy = False
        if error:
            self.app.failure(error)
            if self.data is None:
                self.title.configure(text='FRIDAY backend is not running')
                self.details.configure(text='Start FRIDAY and select Retry. You can keep this window open.')
            return
        self.data = data
        card = vm.class_card(data)
        self.title.configure(text=card['title'])
        self.details.configure(text=card['details'])
        self.link = card['link']
        self.join.configure(state='normal' if vm.safe_join(self.link) else 'disabled')
        self.timeline.delete(*self.timeline.get_children())
        for i, row in enumerate(data['today']):
            self.timeline.insert('', 'end', iid=str(i), values=(row['start'] + '–' + row['end'], row['subject'],
                ' · '.join(v for v in (row.get('faculty'), row.get('room')) if v) or 'Details not saved'))
        self.notice.configure(text='\n'.join(f'{f["from"]}–{f["through"]}: {f["subject"]} cancelled (read-only)'
                                           for f in data.get('cancellations', [])[:2]) or ('No classes today.' if not data['today'] else ''))
        self.due.delete(*self.due.get_children())
        for row in data['due_soon']:
            self.due.insert('', 'end', values=(vm.short(row['what'], 26), vm.countdown(row['due'], datetime_from(data['now']))))
        if data['exams']:
            row = data['exams'][0]
            self.exam.configure(text=row['what'])
            self.exam_detail.configure(text=vm.countdown(row['due'], datetime_from(data['now'])) + '\n' + vm.date_time(row['due']) +
                                       ('\n' + row['venue'] if row.get('venue') else ''))
        else:
            self.exam.configure(text='No upcoming exams')
            self.exam_detail.configure(text='Add your next exam in the Exams tab.')
        self.events.configure(text='\n'.join(f'{r["date"]} · {r["start"]}  {r["title"]}' +
                (f' · {r["location"]}' if r.get('location') else '') for r in data['events'][:3]) or 'No upcoming events saved')
        self.app.connected()

    def open_link(self):
        if vm.safe_join(self.link):
            link = self.link
            self.app.submit(lambda: webbrowser.open(link), lambda data, error: self.app.failure(error) if error else None)


def datetime_from(value):
    from datetime import datetime
    return datetime.fromisoformat(value)


class Catalog(ttk.Frame):
    def __init__(self, master, app, section):
        super().__init__(master, padding=(6, 10))
        self.app, self.section, self.data, self.busy = app, section, None, False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.subject, self.status, self.kind = tk.StringVar(self), tk.StringVar(self, 'All'), tk.StringVar(self, 'All')
        actions = ttk.Frame(self)
        actions.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        ttk.Button(actions, text='+ New', command=self.new, style='Accent.TButton').pack(side='left')
        ttk.Button(actions, text='Edit', command=self.edit).pack(side='left', padx=8)
        if section in {'deadlines', 'exams'}:
            ttk.Button(actions, text='Mark done', command=self.complete).pack(side='left')
        ttk.Button(actions, text='Delete', command=self.delete, style='Danger.TButton').pack(side='right')
        filters = ttk.Frame(self)
        filters.grid(row=1, column=0, sticky='ew', pady=(0, 12))
        if section == 'deadlines':
            ttk.Label(filters, text='Subject').pack(side='left', padx=(0, 8))
            ttk.Entry(filters, textvariable=self.subject, width=24).pack(side='left')
            ttk.Label(filters, text='Status').pack(side='left', padx=(18, 8))
            ttk.Combobox(filters, textvariable=self.status, values=('All', 'Open', 'Done'), state='readonly', width=10).pack(side='left')
            ttk.Label(filters, text='Kind').pack(side='left', padx=(18, 8))
            ttk.Combobox(filters, textvariable=self.kind, values=('All', *vm.KINDS), state='readonly', width=15).pack(side='left')
        else:
            ttk.Label(filters, text='Changes here are shared with FRIDAY. Double-click an entry to edit.', style='Muted.TLabel').pack(side='left')
        if section == 'events':
            columns = [('title', 'Event', 260), ('date', 'Date', 125), ('time', 'Time', 140), ('location', 'Location', 220)]
        else:
            columns = [('title', 'Work' if section == 'deadlines' else 'Exam', 270), ('subject', 'Subject', 130),
                       ('kind', 'Kind', 105), ('due', 'Due / start', 175), ('left', 'Countdown', 120), ('status', 'Status', 90)]
        frame, self.tree = table(self, columns, height=12)
        frame.grid(row=2, column=0, sticky='nsew')
        self.message = ttk.Label(self, text='Loading…', style='Muted.TLabel', wraplength=1000)
        self.message.grid(row=3, column=0, sticky='ew', pady=12)
        for variable in (self.subject, self.status, self.kind):
            variable.trace_add('write', lambda *args: self.populate())
        self.tree.bind('<Double-1>', lambda event: self.edit())
        self.tree.bind('<Return>', lambda event: self.edit())
        self.tree.bind('<Delete>', lambda event: self.delete())

    def load(self):
        if self.busy:
            return
        self.busy = True
        client, section = self.app.client, self.section
        self.app.submit(lambda: client.load(section), self.finished)

    def finished(self, data, error):
        self.busy = False
        if error:
            self.app.failure(error)
            self.message.configure(text=str(error))
            return
        self.data = data
        self.populate()
        self.message.configure(text=data.get('message') or f'{len(data["items"])} saved entries · Ctrl+N to add')
        self.app.connected()

    def populate(self):
        if self.data is None:
            return
        old = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in vm.filtered(self.data['items'], self.subject.get(), self.status.get(), self.kind.get()):
            if self.section == 'events':
                values = (row['title'], row['date'], row['start'] + ('–' + row['end'] if row['end'] else ''), row['location'])
            else:
                values = (row['what'], row.get('subject', ''), row.get('kind', 'other'), vm.date_time(row['due']),
                          vm.countdown(row['due'], done=row.get('done')), 'Done' if row.get('done') else 'Open')
            self.tree.insert('', 'end', iid=row['id'], values=values)
        if old and self.tree.exists(old[0]):
            self.tree.selection_set(old)

    def selected(self):
        selection = self.tree.selection()
        return next((copy.deepcopy(r) for r in (self.data or {}).get('items', []) if selection and r['id'] == selection[0]), None)

    def new(self):
        self.editor(None)

    def edit(self):
        row = self.selected()
        if row:
            self.editor(row)

    def editor(self, row):
        if self.data is None or self.busy:
            self.app.status.set('Load this tab before editing. Use Retry if FRIDAY is offline.')
            return
        open_editor(self.app, self.section, row, self.data['revision'])

    def complete(self):
        row = self.selected()
        if not row or row.get('done') or self.busy:
            return
        values = vm.defaults(self.section, row)
        values['done'] = True
        payload = vm.payload(self.section, values, row)
        client, section, revision = self.app.client, self.section, self.data['revision']
        self.busy = True
        self.app.submit(lambda: client.save(section, row['id'], payload, revision), self.finished, write=True)

    def delete(self):
        row = self.selected()
        if row and not self.busy and messagebox.askyesno('Delete entry', 'Delete this saved entry?', parent=self.app.root):
            client, section, revision = self.app.client, self.section, self.data['revision']
            self.busy = True
            self.app.submit(lambda: client.delete(section, row['id'], revision), self.finished, write=True)


def open_editor(app, section, row, revision):
    state = {'revision': revision, 'row': copy.deepcopy(row)}
    client, identifier = app.client, row['id'] if row else None
    def save(values, callback):
        payload = vm.payload(section, values, state['row'])
        current = state['revision']
        app.submit(lambda: client.save(section, identifier, payload, current), callback, write=True)
    def review(dialog):
        def loaded(data, error):
            if dialog.closed:
                return
            if error:
                dialog.message.set(str(error))
                return
            current = next((r for r in data['items'] if r['id'] == identifier), None)
            if identifier is not None and current is None:
                dialog.message.set('That entry was removed. Close this draft and create a new entry if needed.')
                return
            if section == 'timetable' and row is not None and current != row:
                dialog.message.set('The weekly template changed or moved. Close this draft and select its current slot.')
                return
            detail = '\n'.join(f'{label}: {vm.defaults(section, current).get(key, "")}' for key, label, _ in vm.FIELDS[section])
            if messagebox.askyesno('Review current version', 'Current saved values:\n' + detail[:1800] +
                                  '\n\nKeep your draft and use this version as its base?', parent=dialog.window):
                state['revision'] = data['revision']
                state['row'] = copy.deepcopy(current)
                dialog.reviewed()
        app.submit(lambda: client.load(section), loaded)
    return EditDialog(app, ('Edit ' if row else 'New ') + {'deadlines': 'assignment / homework', 'subjects': 'subject details',
        'timetable': 'weekly slot', 'exams': 'exam', 'events': 'event'}[section], vm.FIELDS[section], vm.defaults(section, row), save, review)
