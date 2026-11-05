"""Conversation, confirmations and explicitly targeted desktop input."""
import tkinter as tk
from tkinter import messagebox, ttk

from interfaces.control_center import focus
from interfaces.settings.app import PANEL, TEXT, ACCENT, MUTED


class Chat(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.busy, self.steps = app, False, []
        self.awaiting, self.active_job = False, None
        self.job_desktop = False
        self.confirm_yes, self.confirm_no, self.last_progress = 'yes', 'no', ''
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        top = ttk.Frame(self)
        top.grid(row=0, sticky='ew', pady=(0, 12))
        ttk.Label(top, text='Provider', style='Muted.TLabel').pack(side='left', padx=(0, 8))
        self.provider = tk.StringVar(self, 'Backend default')
        self.providers = ttk.Combobox(top, textvariable=self.provider, state='readonly', width=18,
                                     values=('Backend default', 'openrouter', 'anthropic', 'openai', 'ollama'))
        self.providers.pack(side='left')
        self.speak = tk.BooleanVar(self, False)
        ttk.Checkbutton(top, text='Speak this chat’s replies', variable=self.speak).pack(side='left', padx=14)
        ttk.Button(top, text='Load history', command=self.history).pack(side='right')
        area = ttk.Frame(self)
        area.grid(row=1, sticky='nsew')
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        self.transcript = tk.Text(area, bg=PANEL, fg=TEXT, wrap='word', relief='flat', bd=0,
                                  font=('Segoe UI', 11), padx=20, pady=15, spacing3=9,
                                  selectbackground='#294c63', state='disabled')
        self.transcript.grid(row=0, column=0, sticky='nsew')
        bar = ttk.Scrollbar(area, command=self.transcript.yview)
        bar.grid(row=0, column=1, sticky='ns')
        self.transcript.configure(yscrollcommand=bar.set)
        self.transcript.tag_configure('role', foreground=ACCENT, font=('Segoe UI Semibold', 10), spacing1=14)
        self.transcript.tag_configure('system', foreground=MUTED)
        self.confirm = ttk.Frame(self)
        self.confirm.grid(row=2, sticky='ew', pady=(10, 0))
        ttk.Label(self.confirm, text='FRIDAY is waiting for your reply.', style='Brand.TLabel').pack(side='left')
        self.yes_button = ttk.Button(self.confirm, text='Yes', command=lambda: self.answer(self.confirm_yes))
        self.yes_button.pack(side='right')
        self.no_button = ttk.Button(self.confirm, text='No / cancel', command=lambda: self.answer(self.confirm_no))
        self.no_button.pack(side='right', padx=8)
        self.confirm.grid_remove()
        self.input = tk.Text(self, height=3, wrap='word', bg='#111e31', fg=TEXT,
                             insertbackground=TEXT, relief='flat', bd=0, padx=14, pady=12,
                             font=('Segoe UI', 11), undo=True)
        self.input.grid(row=3, sticky='ew', pady=(12, 8))
        self.input.bind('<Control-Return>', lambda event: self.send() or 'break')
        self.input.bind('<KeyRelease>', lambda event: self.count())
        actions = ttk.Frame(self)
        actions.grid(row=4, sticky='ew')
        self.send_button = ttk.Button(actions, text='Send  ·  Ctrl+Enter', style='Accent.TButton', command=self.send)
        self.send_button.pack(side='right')
        self.target_button = ttk.Button(actions, text='Target app (3s) → Send', command=self.target_send)
        self.target_button.pack(side='right', padx=8)
        self.apply_button = ttk.Button(actions, text='Apply prepared input to app (3s)', command=self.type_steps)
        self.apply_button.pack(side='left')
        self.apply_button.configure(state='disabled')
        self.counter = ttk.Label(self, text='0 / 4000', style='Muted.TLabel')
        self.counter.grid(row=5, sticky='w', pady=(8, 0))
        self.hint = ttk.Label(self, text='Enter adds a line. Examples are drafts. Target app: this window minimizes; click your destination within 3 seconds.',
                              style='Muted.TLabel', wraplength=760)
        self.hint.grid(row=6, sticky='ew', pady=(4, 0))
        self.append('FRIDAY', 'Ready when you are. Ask a question, type a command, or explore Capabilities for examples.')

    def append(self, role, text):
        self.transcript.configure(state='normal')
        self.transcript.insert('end', role.upper() + '\n', 'role')
        self.transcript.insert('end', str(text) + '\n')
        self.transcript.configure(state='disabled')
        self.transcript.see('end')

    def draft(self, text):
        self.input.delete('1.0', 'end')
        self.input.insert('1.0', text)
        self.input.focus_set()
        self.count()

    def count(self):
        length = len(self.input.get('1.0', 'end-1c'))
        self.counter.configure(text=f'{length} / 4000' + (' · shorten before sending' if length > 4000 else ''))

    def enabled(self, on):
        for button in (self.send_button, self.target_button, self.yes_button, self.no_button):
            button.configure(state='normal' if on else 'disabled')
        self.apply_button.configure(state='normal' if on and self.steps else 'disabled')
        self.input.configure(state='normal' if on else 'disabled')

    def answer(self, text):
        if not self.busy:
            self.draft(text)
            if focus.requires_target(text):
                self.target_send()
            else:
                self.send()

    def _valid(self):
        message = self.input.get('1.0', 'end-1c').strip()
        if not message or len(message) > 4000 or '\x00' in message:
            self.app.message.set('Enter a message of 1–4000 characters without null bytes.')
            return None
        return message

    def send(self, target=None):
        if self.busy or not (message := self._valid()):
            return
        if focus.requires_target(message) and target is None:
            self.app.message.set('This command uses the active app. Choose Target app, then click its window during the countdown.')
            return
        self.busy = True
        self.enabled(False)
        self.steps = []
        self.active_job = None
        self.set_awaiting(False)
        self.append('You', message)
        self.app.message.set('FRIDAY is working… Commands are submitted once; failed requests are never automatically retried.')
        provider = None if self.provider.get() == 'Backend default' else self.provider.get()
        speak = self.speak.get()

        def work():
            if target is not None:
                focus.verify(target)
            return self.app.client.chat(message, provider, speak)

        def done(result, error):
            self.busy = False
            self.enabled(True)
            if target is not None:
                self.app.root.deiconify()
            if error:
                self.append('Request status', str(error) + '\nYour draft is kept. Check the result before retrying an action.')
                self.app.message.set(str(error))
                return
            self.input.delete('1.0', 'end')
            self.count()
            self.append('FRIDAY · private' if result.get('private') else 'FRIDAY', result.get('response', 'No reply returned.'))
            self.steps = result.get('keyboard') or []
            if self.steps:
                preview = '\n'.join(step.get('text', '') or ('Keys: ' + str(step.get('keys', ''))) for step in self.steps)
                self.append('Prepared input · review before applying', preview)
                self.apply_button.configure(state='normal')
            self.active_job = result.get('automation_job')
            from services.browser.commands import is_desktop_command
            self.job_desktop = bool(self.active_job and is_desktop_command(message))
            computer = message.strip().startswith('\\c')
            self.confirm_yes = 'desktop yes' if self.job_desktop else 'browser yes' if self.active_job else '\\c yes' if computer else 'yes'
            self.confirm_no = 'desktop stop' if self.job_desktop else 'browser stop' if self.active_job else '\\c stop' if computer else 'no'
            self.set_awaiting(result.get('awaiting_reply', False))
            self.app.message.set('Reply received.' + (' Review the question before answering.' if self.awaiting else ''))
            self.app.refresh()

        self.app.work('chat', work, done)

    def set_awaiting(self, awaiting):
        self.awaiting = bool(awaiting)
        self.yes_button.configure(text=self.confirm_yes.capitalize())
        self.no_button.configure(text=self.confirm_no.capitalize() if self.confirm_no != 'no' else 'No / cancel')
        if self.awaiting:
            self.confirm.grid()
        else:
            self.confirm.grid_remove()

    def progress(self, status):
        if self.busy or not self.active_job or status.get('job_id') != self.active_job:
            return
        response = status.get('response', '')
        if response and response != self.last_progress:
            self.append('Task progress', response)
            self.last_progress = response
        self.confirm_yes, self.confirm_no = ('desktop yes', 'desktop stop') if self.job_desktop else ('browser yes', 'browser stop')
        self.set_awaiting(status.get('awaiting_reply', False))
        if not status.get('active'):
            self.active_job = None

    def countdown(self, callback):
        if self.busy:
            return
        self.busy = True
        self.enabled(False)
        self.app.message.set('Click your destination app now. Capturing the active window in 3 seconds…')
        self.app.root.iconify()

        def capture():
            self.busy = False
            self.enabled(True)
            try:
                target = focus.capture()
            except Exception as error:
                self.app.root.deiconify()
                self.app.message.set(str(error))
                return
            callback(target)
        self.app.later(3000, capture)

    def target_send(self):
        if not self.busy and self._valid():
            self.countdown(lambda target: self.send(target))

    def type_steps(self):
        if not self.steps or self.busy:
            return
        steps = self.steps

        def submit(target):
            self.steps = []
            self.busy = True
            self.enabled(False)

            def done(result, error):
                self.busy = False
                self.enabled(True)
                self.app.root.deiconify()
                self.append('Input status', str(error) if error else result)
                self.app.message.set(str(error) if error else result)
            self.app.work('typing', lambda: focus.apply(target, steps), done)
        self.countdown(submit)

    def history(self):
        if self.busy:
            return
        if not messagebox.askyesno('Load shared history', 'Replace this view with the last 30 saved chat messages? Your unsent draft will be kept.', parent=self.app.root):
            return
        self.busy = True
        self.enabled(False)

        def done(rows, error):
            self.busy = False
            self.enabled(True)
            if error:
                self.app.message.set(str(error))
                return
            self.transcript.configure(state='normal')
            self.transcript.delete('1.0', 'end')
            self.transcript.configure(state='disabled')
            self.steps, self.active_job = [], None
            self.apply_button.configure(state='disabled')
            self.set_awaiting(False)
            for row in rows:
                self.append(row['role'], row['content'])
            self.app.message.set('Loaded shared backend history. Private replies are not added by this interface.')
        self.app.work('history', self.app.client.history, done)

    def clear_history(self):
        if self.busy or not messagebox.askyesno('Clear shared history',
                'Clear shared chat history, related conversation context and caches? Saved personal facts are kept.', parent=self.app.root):
            return
        self.busy = True
        self.enabled(False)

        def done(result, error):
            self.busy = False
            self.enabled(True)
            if not error:
                self.steps, self.awaiting, self.active_job = [], False, None
                self.confirm.grid_remove()
                self.apply_button.configure(state='disabled')
                self.transcript.configure(state='normal')
                self.transcript.delete('1.0', 'end')
                self.transcript.configure(state='disabled')
            self.app.message.set(str(error) if error else 'Shared chat history cleared; personal facts kept.')
        self.app.work('history', self.app.client.clear_history, done)
