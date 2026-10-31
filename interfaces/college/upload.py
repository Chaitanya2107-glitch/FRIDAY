"""Choose bytes, edit a table, review a diff and explicitly confirm publication."""
import copy
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from interfaces.college import viewmodel as vm
from interfaces.college.dialogs import EditDialog
from interfaces.college.tabs import table


class Upload(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=(6, 10))
        self.app, self.data, self.busy = app, None, False
        self.staged, self.rows, self.reviewed = None, [], None
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)
        controls = ttk.Frame(self)
        controls.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        ttk.Button(controls, text='Choose file…', style='Accent.TButton', command=self.choose).pack(side='left')
        self.extract_button = ttk.Button(controls, text='Read with vision…', command=self.extract, state='disabled')
        self.extract_button.pack(side='left', padx=8)
        ttk.Button(controls, text='Discard preview', command=self.discard).pack(side='left')
        ttk.Label(controls, text='Timetable · up to 10 MB', style='Muted.TLabel').pack(side='right')
        self.message = tk.StringVar(self, 'Choose CSV, XLSX, DOCX, PDF, PNG or JPG. Nothing is saved before Confirm.')
        ttk.Label(self, textvariable=self.message, style='Muted.TLabel', wraplength=1060).grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        left = ttk.Frame(self, padding=(0, 0, 12, 0))
        left.grid(row=2, column=0, sticky='nsew')
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text='CONFIRMED UPLOADS', style='Brand.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 8))
        frame, self.files = table(left, [('file', 'File', 215), ('size', 'KB', 60)], height=7)
        frame.grid(row=1, column=0, sticky='nsew')
        ttk.Button(left, text='Delete saved upload', style='Danger.TButton', command=self.delete).grid(row=2, column=0, sticky='w', pady=8)
        self.files.bind('<Delete>', lambda event: self.delete())
        right = ttk.Frame(self)
        right.grid(row=2, column=1, sticky='nsew')
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        actions = ttk.Frame(right)
        actions.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        ttk.Label(actions, text='EDITABLE PREVIEW', style='Brand.TLabel').pack(side='left')
        ttk.Button(actions, text='+ Row', command=self.new).pack(side='right')
        ttk.Button(actions, text='Edit row', command=self.edit).pack(side='right', padx=8)
        ttk.Button(actions, text='Remove row', command=self.remove).pack(side='right')
        frame, self.tree = table(right, [('day', 'Day', 95), ('start', 'Start', 75), ('end', 'End', 75),
            ('subject', 'Subject', 150), ('room', 'Room', 80), ('warnings', 'Warnings', 275)], height=7)
        frame.grid(row=1, column=0, sticky='nsew')
        self.tree.bind('<Double-1>', lambda event: self.edit())
        self.tree.bind('<Return>', lambda event: self.edit())
        self.tree.bind('<Delete>', lambda event: self.remove())
        bottom = ttk.Frame(self)
        bottom.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(12, 8))
        self.mode = tk.StringVar(self, 'merge')
        ttk.Label(bottom, text='Confirm mode').pack(side='left')
        ttk.Combobox(bottom, textvariable=self.mode, values=('merge', 'replace'), state='readonly', width=12).pack(side='left', padx=10)
        ttk.Button(bottom, text='Review diff', command=self.review).pack(side='left')
        self.confirm_button = ttk.Button(bottom, text='Confirm import', style='Accent.TButton', command=self.confirm, state='disabled')
        self.confirm_button.pack(side='right')
        diff_frame = ttk.Frame(self)
        diff_frame.grid(row=4, column=0, columnspan=2, sticky='ew')
        diff_frame.columnconfigure(0, weight=1)
        self.diff = tk.Text(diff_frame, height=5, wrap='word', background='#152136', foreground='#edf5ff',
                            font=('Segoe UI', 10), relief='flat', padx=10, pady=8, state='disabled')
        self.diff.grid(row=0, column=0, sticky='ew')
        scroll = ttk.Scrollbar(diff_frame, command=self.diff.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.diff.configure(yscrollcommand=scroll.set)
        self.mode.trace_add('write', lambda *args: self.invalidate())

    def dirty(self):
        return self.staged is not None

    def invalidate(self):
        self.reviewed = None
        self.confirm_button.configure(state='disabled')

    def show_diff(self, text):
        self.diff.configure(state='normal')
        self.diff.delete('1.0', 'end')
        self.diff.insert('1.0', text)
        self.diff.configure(state='disabled')

    def load(self):
        if self.busy:
            return
        client = self.app.client
        self.busy = True
        self.app.submit(lambda: client.load('uploads'), self.loaded)

    def loaded(self, data, error):
        self.busy = False
        if error:
            self.app.failure(error)
            return
        self.data = data
        self.files.delete(*self.files.get_children())
        for row in data['items']:
            self.files.insert('', 'end', iid=row['id'], values=(row['filename'], round(row['size'] / 1024)))
        self.app.connected()

    def populate(self, warnings=None):
        self.tree.delete(*self.tree.get_children())
        warnings = warnings if warnings is not None else (self.staged or {}).get('warnings', [])
        for i, row in enumerate(self.rows):
            self.tree.insert('', 'end', iid=str(i), values=tuple(row.get(k) or '' for k in ('day', 'start', 'end', 'subject', 'room')) +
                             ('; '.join(warnings[i]) if i < len(warnings) else 'Review diff to validate',))

    def choose(self):
        if self.busy or (self.dirty() and not messagebox.askyesno('Unsaved preview', 'Discard this preview and choose another file?', parent=self.app.root)):
            return
        filename = filedialog.askopenfilename(parent=self.app.root, title='Choose college timetable',
            filetypes=[('Timetables', '*.png *.jpg *.jpeg *.pdf *.docx *.xlsx *.csv'), ('All files', '*.*')])
        if not filename:
            return
        client, old = self.app.client, self.staged['token'] if self.staged else None
        self.busy = True
        self.message.set('Reading file…')
        def operation():
            if old:
                client.discard(old)
            return client.upload(filename)
        self.app.submit(operation, self.received)

    def received(self, data, error):
        self.busy = False
        if error:
            self.message.set(str(error))
            self.app.failure(error)
            return
        self.staged, self.rows = data, copy.deepcopy(data['rows'])
        self.invalidate()
        self.populate()
        self.extract_button.configure(state='normal' if data.get('requires_vision') else 'disabled')
        self.message.set(data['filename'] + ' · ' + data.get('notice', 'Editable preview. Nothing is saved yet.'))
        self.show_diff('Edit any incorrect cells with Edit row, then Review diff.\n' +
                       ('This image/scanned PDF needs provider consent before extraction.' if data.get('requires_vision') else 'Merge keeps other weekly slots. Replace uses only these rows.'))

    def extract(self):
        if not self.staged or self.busy:
            return
        client, token = self.app.client, self.staged['token']
        self.busy = True
        def consent(data, error):
            self.busy = False
            if error:
                self.message.set(str(error))
                return
            if not data['available']:
                self.message.set('Vision unavailable: ' + data['reason'] + ' You can enter rows manually.')
                return
            selected = data['selected']
            if messagebox.askyesno('Consent to timetable extraction', f'Send this file’s image/pages to {selected["provider"]} '
                f'({selected["model"]})?\n{data["notice"]}\n\nThe result is an editable preview; it is saved only after Confirm.', parent=self.app.root):
                self.busy = True
                self.message.set('Reading timetable with ' + selected['provider'] + '…')
                approved = data['consent']
                self.app.submit(lambda: client.extract(token, approved), self.received)
        self.app.submit(client.vision, consent)

    def new(self):
        if self.staged is not None and not self.busy:
            self.row_editor(None)

    def edit(self):
        selected = self.tree.selection()
        if selected and not self.busy:
            self.row_editor(int(selected[0]))

    def row_editor(self, index):
        initial = copy.deepcopy(self.rows[index]) if index is not None else {'day': 'monday', 'start': '09:00', 'end': '10:00', 'subject': '', 'room': ''}
        fields = [*vm.FIELDS['timetable'], ('room', 'Room (optional)', None)]
        initial['room'] = initial.get('room') or ''
        def save(values, callback):
            values['room'] = values['room'] or None
            if index is None:
                self.rows.append(values)
            else:
                self.rows[index] = values
            self.invalidate()
            self.populate([])
            callback({'message': 'Preview row edited; nothing saved. Choose Review diff.'}, None)
        EditDialog(self.app, 'Edit preview row', fields, initial, save)

    def remove(self):
        selected = self.tree.selection()
        if selected and not self.busy and messagebox.askyesno('Remove preview row', 'Remove this row from the preview?', parent=self.app.root):
            self.rows.pop(int(selected[0]))
            self.invalidate()
            self.populate([])

    def review(self):
        if not self.staged or not self.rows or self.busy:
            self.message.set('Choose a file and enter at least one class row first.')
            return
        client, token, rows = self.app.client, self.staged['token'], copy.deepcopy(self.rows)
        revision, mode = self.staged['revision'], self.mode.get()
        self.busy = True
        def finished(data, error):
            self.busy = False
            if error:
                self.message.set(str(error))
                if getattr(error, 'status', None) == 409:
                    def reloaded(current, failure):
                        if not failure and self.staged and self.staged['token'] == token:
                            self.staged['revision'] = current['revision']
                            self.message.set('Timetable changed. Your rows are kept; current version loaded. Review diff again.')
                        elif failure:
                            self.app.failure(failure)
                    self.app.submit(lambda: client.load('timetable'), reloaded)
                return
            self.populate(data['warnings'])
            self.message.set(data['message'])
            self.reviewed = {'rows': rows, 'mode': mode, 'revision': revision, 'review': data['review']} if data['valid'] else None
            self.confirm_button.configure(state='normal' if data['valid'] else 'disabled')
            self.show_diff(vm.review_text(data['diff']) if data['valid'] else data['message'])
        self.app.submit(lambda: client.preview(token, rows, revision, mode), finished)

    def confirm(self):
        if self.busy or not self.staged or not self.reviewed:
            return
        reviewed = copy.deepcopy(self.reviewed)
        if reviewed['rows'] != self.rows or reviewed['mode'] != self.mode.get():
            self.invalidate()
            return
        if not messagebox.askyesno('Confirm timetable import', 'Save the reviewed ' + reviewed['mode'] + ' import to FRIDAY?', parent=self.app.root):
            return
        client, token = self.app.client, self.staged['token']
        self.busy = True
        def finished(data, error):
            self.busy = False
            if error:
                self.message.set(str(error))
                self.invalidate()
                return
            self.staged, self.rows = None, []
            self.invalidate()
            self.populate([])
            self.loaded(data['uploads'], None)
            self.message.set(data['message'])
            self.show_diff('Confirmed. The timetable is shared with FRIDAY.')
            self.app.refresh()
        self.app.submit(lambda: client.confirm(token, reviewed['rows'], reviewed['revision'], reviewed['mode'], reviewed['review']), finished, write=True)

    def discard(self):
        if self.busy or not self.staged or not messagebox.askyesno('Discard preview', 'Discard this unsaved upload preview?', parent=self.app.root):
            return
        client, token = self.app.client, self.staged['token']
        self.staged, self.rows = None, []
        self.invalidate()
        self.populate([])
        self.extract_button.configure(state='disabled')
        self.show_diff('')
        self.message.set('Preview discarded. Nothing was saved.')
        self.app.submit(lambda: client.discard(token), lambda data, error: None)

    def delete(self):
        selected = self.files.selection()
        if self.data is None or not selected or self.busy:
            return
        if messagebox.askyesno('Delete uploaded file', 'Delete this saved original file? Its imported classes remain in the timetable.', parent=self.app.root):
            client, identifier, revision = self.app.client, selected[0], self.data['revision']
            self.busy = True
            self.app.submit(lambda: client.delete_upload(identifier, revision), self.loaded, write=True)
