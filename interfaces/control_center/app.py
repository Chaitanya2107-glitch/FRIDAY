"""Tkinter home for FRIDAY's controls, capabilities and help."""
from datetime import datetime
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from core.logger import logger
from interfaces.control_center.catalog import CAPABILITIES, GUIDES
from interfaces.control_center.chat import Chat
from interfaces.control_center.client import Client
from interfaces.control_center.launcher import TITLE, open_editor, start_desktop
from interfaces.control_center.library import Document, Guides, Library, ScrollPage
from interfaces.settings.app import BG, PANEL, TEXT, MUTED, ACCENT, theme


class ControlCenter:
    def __init__(self, root, client=None):
        self.root, self.client = root, client or Client()
        self.closed, self.running = False, set()
        self.results, self.timers, self.pages, self.nav = queue.Queue(), set(), {}, {}
        self.state = {}
        theme(root)
        style = ttk.Style(root)
        style.configure('Hero.TLabel', font=('Segoe UI Semibold', 27), background=PANEL)
        style.configure('CardTitle.TLabel', font=('Segoe UI Semibold', 14), background=PANEL)
        style.configure('CardText.TLabel', foreground=MUTED, background=PANEL, font=('Segoe UI', 10))
        style.configure('CardValue.TLabel', foreground=ACCENT, background=PANEL, font=('Segoe UI Semibold', 16))
        style.configure('TCheckbutton', background=BG, foreground=TEXT)
        style.map('TCheckbutton', background=[('active', BG)])
        style.configure('TCombobox', fieldbackground=PANEL, foreground=TEXT, padding=6)
        style.map('TCombobox', fieldbackground=[('readonly', PANEL)], foreground=[('readonly', TEXT)])
        root.title(TITLE)
        width, height = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f'{min(1380, width - 80)}x{min(920, height - 100)}')
        root.minsize(min(1080, width - 50), min(720, height - 70))
        root.configure(bg=BG)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        sidebar = tk.Frame(root, bg='#080f1c', width=192)
        sidebar.grid(row=0, column=0, sticky='ns')
        sidebar.grid_propagate(False)
        tk.Label(sidebar, text='F R I D A Y', bg='#080f1c', fg=ACCENT,
                 font=('Segoe UI Semibold', 19)).pack(anchor='w', padx=23, pady=(32, 3))
        tk.Label(sidebar, text='CONTROL CENTER', bg='#080f1c', fg=MUTED,
                 font=('Segoe UI', 9)).pack(anchor='w', padx=25, pady=(0, 33))
        for key, label in (('home', '01   Overview'), ('library', '02   Capabilities'),
                           ('chat', '03   Command chat'), ('guides', '04   How to use'),
                           ('tools', '05   Tools & controls'), ('status', '06   Live status')):
            button = tk.Button(sidebar, text=label, anchor='w', bg='#080f1c', fg=MUTED,
                               activebackground=PANEL, activeforeground=ACCENT, relief='flat', bd=0,
                               font=('Segoe UI Semibold', 10), padx=14, pady=14, cursor='hand2',
                               command=lambda k=key: self.show(k))
            button.pack(fill='x', padx=10, pady=3)
            self.nav[key] = button
        tk.Label(sidebar, text='YOUR ASSISTANT.\nONE PLACE TO EXPLORE.', bg='#080f1c', fg=MUTED,
                 font=('Segoe UI', 9), justify='left').pack(side='bottom', anchor='w', padx=24, pady=28)
        self.connection = tk.StringVar(root, '○  Checking backend')
        tk.Label(sidebar, textvariable=self.connection, bg='#080f1c', fg=ACCENT,
                 font=('Segoe UI', 10), wraplength=154, justify='left').pack(side='bottom', anchor='w', padx=24)

        main = ttk.Frame(root, padding=(25, 23, 25, 0))
        main.grid(row=0, column=1, sticky='nsew')
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)
        top = ttk.Frame(main)
        top.grid(row=0, sticky='ew')
        ttk.Label(top, text='PERSONAL AI ASSISTANT / WORKSPACE', style='Brand.TLabel').pack(side='left')
        ttk.Button(top, text='↻ Refresh', command=self.refresh).pack(side='right')
        self.heading = ttk.Label(main, style='Title.TLabel')
        self.heading.grid(row=1, sticky='w', pady=(16, 18))
        self.content = ttk.Frame(main)
        self.content.grid(row=2, sticky='nsew')
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)
        self.message = tk.StringVar(root, 'Browse every capability offline. Start FRIDAY when you want to run commands.')
        message_label = ttk.Label(main, textvariable=self.message, style='Muted.TLabel', wraplength=800,
                                  padding=(0, 12))
        message_label.grid(row=3, sticky='ew')
        message_label.bind('<Configure>', lambda event: message_label.configure(wraplength=max(250, event.width-4)))

        self.build_home()
        self.pages['library'] = Library(self.content, self)
        self.pages['chat'] = Chat(self.content, self)
        self.pages['guides'] = Guides(self.content, self)
        self.build_tools()
        self.build_status()
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky='nsew')
        self.view = 'home'
        self.show('home')
        root.bind('<Control-k>', lambda event: self.search())
        root.bind('<Control-l>', lambda event: self.chat_focus())
        root.bind('<F1>', lambda event: self.open_guide('CONTROL_CENTER.md'))
        root.bind('<F5>', lambda event: self.refresh())
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.later(40, self.poll)
        self.later(8000, self.tick)
        self.refresh()

    def frame(self, key, scroll=False):
        frame = ScrollPage(self.content) if scroll else ttk.Frame(self.content)
        self.pages[key] = frame
        return frame.inner if scroll else frame

    @staticmethod
    def button(parent, text, command, accent=False):
        return ttk.Button(parent, text=text, command=command,
                          style='Accent.TButton' if accent else 'TButton')

    def build_home(self):
        frame = self.frame('home', scroll=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        hero = ttk.Frame(frame, style='Panel.TFrame', padding=25)
        hero.grid(row=0, sticky='ew')
        hero.columnconfigure(0, weight=1)
        ttk.Label(hero, text='MEET YOUR EVERYDAY ASSISTANT', style='Brand.TLabel', background=PANEL).grid(sticky='w')
        ttk.Label(hero, text='A little help.\nA lot of possibilities.', style='Hero.TLabel').grid(sticky='w', pady=(9, 12))
        ttk.Label(hero, text='Explore what FRIDAY can do, learn the commands,\nand put your assistant to work.',
                  style='CardText.TLabel').grid(sticky='w')
        actions = ttk.Frame(hero, style='Panel.TFrame')
        actions.grid(sticky='w', pady=(20, 0))
        self.button(actions, 'Explore capabilities →', lambda: self.show('library'), True).pack(side='left')
        self.button(actions, 'Start FRIDAY', self.start).pack(side='left', padx=10)
        orbit = tk.Canvas(hero, width=170, height=180, bg=PANEL, highlightthickness=0)
        orbit.grid(row=0, column=1, rowspan=4, padx=(15, 0))
        for radius, color in ((76, '#263b51'), (59, '#345569'), (37, ACCENT)):
            orbit.create_oval(85-radius, 87-radius, 85+radius, 87+radius, outline=color, width=2)
        orbit.create_text(85, 87, text='F', font=('Segoe UI Semibold', 31), fill=ACCENT)
        orbit.create_oval(139, 36, 151, 48, fill=ACCENT, outline=PANEL)
        counts = ttk.Frame(frame)
        counts.grid(row=1, sticky='ew', pady=15)
        for index, (value, title) in enumerate(((len(CAPABILITIES), 'capabilities'),
                    (sum(len(item.examples) for item in CAPABILITIES), 'example commands'), (len(GUIDES), 'local guides'))):
            counts.columnconfigure(index, weight=1, uniform='count')
            card = ttk.Frame(counts, padding=(20, 12), style='Panel.TFrame')
            card.grid(row=0, column=index, sticky='ew', padx=(0 if index == 0 else 10, 0))
            ttk.Label(card, text=str(value), style='CardValue.TLabel').pack(anchor='w')
            ttk.Label(card, text=title, style='CardText.TLabel').pack(anchor='w')
        bottom = ttk.Frame(frame)
        bottom.grid(row=2, sticky='nsew')
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=1)
        card = ttk.Frame(bottom, padding=18, style='Panel.TFrame')
        card.grid(row=0, column=0, sticky='nsew', padx=(0, 14))
        ttk.Label(card, text='A good place to start', style='CardTitle.TLabel').pack(anchor='w', pady=(0, 8))
        for title, command in (('Plan your day', 'brief me'), ('Check your next class', "what's my next class"),
                               ('See your reminders', 'list reminders')):
            self.button(card, title + '  →', lambda c=command: self.prepare(c)).pack(fill='x', pady=4)
        card = ttk.Frame(bottom, padding=18, style='Panel.TFrame')
        card.grid(row=0, column=1, sticky='nsew')
        ttk.Label(card, text='Connected to your FRIDAY', style='CardTitle.TLabel').pack(anchor='w')
        self.home_status = ttk.Label(card, text='Checking backend…', style='CardText.TLabel', justify='left', wraplength=360)
        self.home_status.pack(anchor='w', pady=12)
        self.remote_status = ttk.Label(card, text='Remote OFF', style='CardText.TLabel', justify='left', wraplength=360)
        self.remote_status.pack(anchor='w', pady=(0, 12))
        self.button(card, 'Getting started & shortcuts', lambda: self.open_guide('CONTROL_CENTER.md')).pack(anchor='w')

    def build_tools(self):
        frame = self.frame('tools', scroll=True)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        for index, (title, description, key) in enumerate((
                ('Customize FRIDAY', 'Contacts, routines, project folders, modes and screen access rules.', 'customization'),
                ('College Schedules', 'Timetable, assignments, exams, events and document upload previews.', 'college'),
                ('Habits & To-do', 'Daily dashboard, check-ins, streaks and your explicit task list.', 'productivity'))):
            card = ttk.Frame(frame, padding=18, style='Panel.TFrame')
            card.grid(row=index // 2, column=index % 2, sticky='nsew', padx=(0, 12), pady=(0, 12))
            ttk.Label(card, text=title, style='CardTitle.TLabel').pack(anchor='w')
            ttk.Label(card, text=description, wraplength=350, style='CardText.TLabel').pack(anchor='w', pady=8)
            self.button(card, 'Open editor →', lambda k=key: self.editor(k)).pack(anchor='w')
        card = ttk.Frame(frame, padding=18, style='Panel.TFrame')
        card.grid(row=1, column=1, sticky='nsew', padx=(0, 12), pady=(0, 12))
        ttk.Label(card, text='Memory & conversation', style='CardTitle.TLabel').pack(anchor='w')
        ttk.Label(card, text='Inspect memory through chat. Clear shared chat only when you choose.',
                  wraplength=350, style='CardText.TLabel').pack(anchor='w', pady=8)
        self.button(card, 'Show personal memory', lambda: self.prepare('what do you remember about me')).pack(anchor='w')
        self.button(card, 'Clear shared chat history…', lambda: self.pages['chat'].clear_history()).pack(anchor='w', pady=(8, 0))
        controls = ttk.Frame(frame, padding=18, style='Panel.TFrame')
        controls.grid(row=2, column=0, columnspan=2, sticky='ew', padx=(0, 12))
        ttk.Label(controls, text='Desktop & voice controls', style='CardTitle.TLabel').grid(row=0, column=0, columnspan=4, sticky='w')
        ttk.Label(controls, text='Uses FRIDAY’s existing desktop controller. Live status shows the resulting state.',
                  style='CardText.TLabel').grid(row=1, column=0, columnspan=4, sticky='w', pady=(6, 12))
        entries = (('Listen / stop', 'listen'), ('Hey Friday on / off', 'wake'),
                   ('Conversation on / off', 'conversation'), ('Stop speech', 'speech_stop'),
                   ('Show / hide body', 'body'), ('All desktop controls', 'controls'),
                   ('Stop automation', 'automation_stop'), ('Restart backend…', 'restart'))
        for index, (title, action) in enumerate(entries):
            controls.columnconfigure(index % 4, weight=1)
            self.button(controls, title, lambda a=action: self.control(a)).grid(row=2+index//4, column=index%4, sticky='ew', padx=(0, 8), pady=4)
        self.voice_status = ttk.Label(frame, text='Desktop state is checked through the local controller.', style='Muted.TLabel', wraplength=800)
        self.voice_status.grid(row=3, column=0, columnspan=2, sticky='w', pady=12)

    def build_status(self):
        frame = self.frame('status')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.status_document = Document(frame)
        self.status_document.grid(row=0, sticky='nsew')
        self.status_document.render('# Live status\nChecking the local backend…')

    def show(self, key):
        self.view = key
        for name, page in self.pages.items():
            if name == key:
                page.grid()
            else:
                page.grid_remove()
        self.heading.configure(text={'home': 'Your FRIDAY, at a glance.', 'library': 'What can FRIDAY do?',
            'chat': 'Let’s get something done.', 'guides': 'A guide for everything.',
            'tools': 'Your tools, in one place.', 'status': 'What’s connected right now.'}[key])
        for name, button in self.nav.items():
            button.configure(bg=PANEL if name == key else '#080f1c', fg=ACCENT if name == key else MUTED)

    def prepare(self, command):
        if self.pages['chat'].busy:
            self.message.set('Wait for the current chat request before preparing another command.')
            return
        if self.pages['chat'].input.get('1.0', 'end-1c').strip() and not messagebox.askyesno(
                'Replace draft', 'Replace your unsent draft with this example?', parent=self.root):
            return
        self.show('chat')
        self.pages['chat'].draft(command)
        self.message.set('Example prepared. Edit names, dates or details, then choose Send.')

    def search(self):
        self.show('library')
        self.pages['library'].search.focus_set()

    def chat_focus(self):
        self.show('chat')
        self.pages['chat'].input.focus_set()

    def open_guide(self, key):
        self.show('guides')
        self.pages['guides'].open(key)

    def editor(self, key):
        self.work('editor', lambda: open_editor(key), self.action_done)

    def start(self):
        self.message.set('Requesting FRIDAY desktop…')
        self.work('start', start_desktop, self.action_done)

    def control(self, action):
        if action == 'restart' and not messagebox.askyesno('Restart FRIDAY',
                'Restart the managed backend? Active conversations and tasks may be interrupted.', parent=self.root):
            return
        self.work('control', lambda: self.client.control(action), self.action_done)

    def action_done(self, result, error):
        self.message.set(str(error) if error else (result.get('text', 'Requested. Refresh checks the result.') if isinstance(result, dict) else str(result)))
        self.refresh()

    def refresh(self):
        self.work('status', self.client.snapshot, self.render_status)

    def render_status(self, state, error):
        if error:
            state = {'online': False, 'error': str(error)}
        self.state = state
        online = state.get('online', False)
        self.connection.set('●  Backend online' if online else '○  Backend offline')
        providers, system, desktop = (state.get(key, {}) for key in ('providers', 'system', 'desktop'))
        mode = system.get('mode', {}).get('name') or 'Unavailable'
        self.home_status.configure(text=(f'Backend online\nProvider: {providers.get("active", "Unavailable")}\nMode: {mode.title()}\nLast checked {datetime.now():%H:%M:%S}'
            if online else 'Backend offline\nCapabilities and guides still work.\nChoose Start FRIDAY to run commands.'))
        available = providers.get('available', [])
        if available:
            names = [row['name'] if isinstance(row, dict) else row for row in available]
            self.pages['chat'].providers.configure(values=('Backend default', *names))
        voice = ', '.join(f'{label}: {"on" if desktop.get(key) else "off"}' for key, label in
                          (('listening', 'Listening'), ('wake', 'Hey Friday'), ('conversation', 'Conversation')))
        self.voice_status.configure(text=voice if desktop.get('connected') else 'Desktop controller unavailable. Start FRIDAY desktop for shared voice controls.')
        spotify = system.get('spotify', {})
        spotify_text = 'Connected (saved authorization)' if spotify.get('connected') else 'Not connected' if spotify.get('connected') is False else 'Unavailable'
        screen = system.get('screen_watch', {})
        remote = system.get('remote', {})
        remote_text = (f'{"ON" if remote.get("enabled") else "OFF"} · {remote.get("devices", 0)} paired devices\n'
                       f'Last command: {remote.get("last_command") or "none"}\n{remote.get("warning", "")}')
        if hasattr(self, 'remote_status'):
            self.remote_status.configure(text='Remote ' + remote_text, foreground='#ff5c5c' if remote.get('warning') else MUTED)
        files, automation = state.get('files', {}), state.get('automation', {})
        self.pages['chat'].progress(automation)
        source = (f'# Live status\nChecked locally at {datetime.now():%H:%M:%S}. Configured services may still require a successful action.\n\n'
                  f'## Backend\n{"Online" if online else "Offline"}\n{state.get("error", "")}\n'
                  f'## AI provider\n{providers.get("active", "Unavailable")}\n'
                  f'## Desktop & voice\n{voice if desktop.get("connected") else "Desktop controller unavailable"}\n'
                  f'## Mode\n{mode}\n## Spotify\n{spotify_text}\n'
                  f'## Screen awareness\n{screen.get("state", "Unavailable")}\n'
                  f'## Remote access\n{remote_text}\n'
                  f'## File index\n{str(files.get("files", "Unavailable")) + " files" if files else "Unavailable"}\n'
                  f'## Browser / research task\n{automation.get("state", "Unavailable")}\n{automation.get("response", "")}\n'
                  '## Computer resources\n' + '\n'.join(state.get('stats', {}).get('lines', ['Unavailable'])))
        if state.get('errors'):
            source += '\n## Unavailable status reads\n' + '\n'.join(f'{key}: {value}' for key, value in state['errors'].items())
        self.status_document.render(source)

    def work(self, key, operation, callback):
        if self.closed or key in self.running:
            return False
        self.running.add(key)
        logger.debug('Control center operation started: %s', key)

        def run():
            try:
                result, error = operation(), None
            except Exception as caught:
                result, error = None, caught
                logger.debug('Control center operation failed: %s (%s)', key, type(caught).__name__)
            self.results.put((key, callback, result, error))
        threading.Thread(target=run, name='control-center-' + key, daemon=True).start()
        return True

    def poll(self):
        if self.closed:
            return
        while True:
            try:
                key, callback, result, error = self.results.get_nowait()
            except queue.Empty:
                break
            self.running.discard(key)
            callback(result, error)
        self.later(40, self.poll)

    def later(self, milliseconds, callback):
        if self.closed:
            return
        def run():
            self.timers.discard(timer)
            if not self.closed:
                callback()
        timer = self.root.after(milliseconds, run)
        self.timers.add(timer)

    def tick(self):
        if self.view in {'home', 'tools', 'status'} or self.pages['chat'].active_job:
            self.refresh()
        self.later(8000, self.tick)

    def close(self):
        if self.pages['chat'].busy and not messagebox.askyesno('Request in progress',
                'Close this window? A submitted backend command may still complete; it will not be retried.', parent=self.root):
            return
        self.closed = True
        for timer in self.timers:
            self.root.after_cancel(timer)
        self.timers.clear()
        self.root.destroy()
