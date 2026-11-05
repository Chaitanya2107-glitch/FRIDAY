"""A local-first Tkinter workspace for habits and tasks, sharing FRIDAY's store."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import logging
import queue
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from interfaces.productivity import dialogs
from interfaces.productivity.style import (BG, PANEL, SIDEBAR, TEXT, MUTED, ACCENT, GOLD,
                                            Ring, label, table, theme)
from services.productivity.store import tracker


class ProductivityWindow:
    def __init__(self, root, store=None, view='today'):
        self.root, self.store = root, store or tracker
        self.closed, self.pending, self.loading = False, 0, False
        self.dialogs, self.callback_errors, self.timers = [], [], []
        self.data = {'date': date.today().isoformat(), 'habits': [], 'tasks': []}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='tracker-io')
        self.results = queue.Queue()
        theme(root)
        root.title('FRIDAY - Habits & To-do')
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f'{min(1260, sw - 70)}x{min(880, sh - 90)}')
        root.minsize(min(1000, sw - 70), min(710, sh - 90))
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        self.sidebar = tk.Frame(root, bg=SIDEBAR, width=206)
        self.sidebar.grid(row=0, column=0, sticky='ns')
        self.sidebar.grid_propagate(False)
        label(self.sidebar, 'F R I D A Y', 17, ACCENT, SIDEBAR).pack(anchor='w', padx=25, pady=(35, 4))
        label(self.sidebar, 'YOUR DAILY SPACE', 8, MUTED, SIDEBAR).pack(anchor='w', padx=27, pady=(0, 38))
        self.nav = {}
        for key, title in [('today', '01   Today'), ('habits', '02   Habit tracker'), ('tasks', '03   To-do list')]:
            button = tk.Button(self.sidebar, text=title, anchor='w', bg=SIDEBAR, fg=MUTED, activebackground=PANEL,
                               activeforeground=ACCENT, relief='flat', bd=0, padx=24, pady=17,
                               font=('Segoe UI Semibold', 11), cursor='hand2', command=lambda k=key: self.show(k))
            button.pack(fill='x', padx=10, pady=3)
            self.nav[key] = button
        label(self.sidebar, 'Small steps.\nLasting change.', 14, TEXT, SIDEBAR, justify='left').pack(side='bottom', anchor='w', padx=25, pady=30)
        label(self.sidebar, '●  Shared with FRIDAY\nSaved on this computer', 9, ACCENT, SIDEBAR, justify='left').pack(side='bottom', anchor='w', padx=25)
        main = ttk.Frame(root, padding=(28, 24, 28, 0))
        main.grid(row=0, column=1, sticky='nsew')
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)
        top = ttk.Frame(main)
        top.grid(row=0, sticky='ew')
        self.date_label = ttk.Label(top, text='', style='Brand.TLabel')
        self.date_label.pack(side='left')
        self.refresh_button = ttk.Button(top, text='↻  Refresh', command=self.refresh)
        self.refresh_button.pack(side='right')
        heading = ttk.Frame(main)
        heading.grid(row=1, sticky='ew', pady=(15, 17))
        self.title = ttk.Label(heading, style='Title.TLabel')
        self.title.pack(anchor='w')
        self.subtitle = ttk.Label(heading, style='Muted.TLabel')
        self.subtitle.pack(anchor='w', pady=(5, 0))
        tools = ttk.Frame(main)
        tools.grid(row=2, sticky='ew', pady=(0, 16))
        self.query = tk.StringVar(root)
        ttk.Label(tools, text='Search', style='Muted.TLabel').pack(side='left', padx=(0, 8))
        self.search = ttk.Entry(tools, textvariable=self.query, width=23)
        self.search.pack(side='left')
        self.filter = tk.StringVar(root, 'Active')
        self.filters = ttk.Combobox(tools, textvariable=self.filter, state='readonly', width=12)
        self.filters.pack(side='left', padx=10)
        self.new_button = ttk.Button(tools, text='+ New habit', style='Accent.TButton', command=self.new)
        self.new_button.pack(side='right')
        self.import_button = ttk.Button(tools, text='Load habits', command=self.load_habits)
        self.import_button.pack(side='right', padx=8)
        self.content = ttk.Frame(main)
        self.content.grid(row=3, sticky='nsew')
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)
        self.views = {}
        self.build_today()
        self.build_habits()
        self.build_tasks()
        self.status = tk.StringVar(root, 'Loading your habits and tasks…')
        ttk.Label(main, textvariable=self.status, style='Muted.TLabel', wraplength=900, padding=(0, 13)).grid(row=4, sticky='ew')
        self.query.trace_add('write', lambda *args: self.render())
        self.filter.trace_add('write', lambda *args: self.render())
        root.bind('<Control-n>', lambda e: self.new())
        root.bind('<Control-f>', lambda e: self.search.focus_set())
        root.bind('<F5>', lambda e: self.refresh())
        root.bind('<Configure>', self.fit_layout, add='+')
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.view = view if view in self.views else 'today'
        self.show(self.view)
        self.poll_timer = root.after(30, self.poll)
        self.tick_timer = root.after(15_000, self.tick)
        self.refresh()

    def frame(self, key):
        frame = ttk.Frame(self.content)
        frame.grid(row=0, column=0, sticky='nsew')
        self.views[key] = frame
        return frame

    def build_today(self):
        frame = self.frame('today')
        hero = tk.Frame(frame, bg=PANEL, padx=24, pady=16)
        self.hero = hero
        hero.pack(fill='x', pady=(0, 18))
        self.ring = Ring(hero)
        self.ring.pack(side='right', padx=(20, 0))
        label(hero, 'A LITTLE BETTER, EVERY DAY', 9, ACCENT).pack(anchor='w', pady=(9, 10))
        label(hero, 'Build a day you feel good about.', 20).pack(anchor='w')
        self.hero_hint = label(hero, 'Your habits and tasks, together in one place.', 10, MUTED)
        self.hero_hint.pack(anchor='w', pady=(10, 0))
        stats = tk.Frame(frame, bg=BG)
        self.stats_panel = stats
        stats.pack(fill='x', pady=(0, 17))
        self.stats = []
        for name in ['HABITS TODAY', 'OPEN TASKS', 'BEST CURRENT STREAK']:
            card = tk.Frame(stats, bg=PANEL, padx=18, pady=10)
            card.pack(side='left', fill='x', expand=True, padx=(0, 8))
            value = label(card, '—', 23)
            value.pack(anchor='w')
            label(card, name, 8, MUTED).pack(anchor='w', pady=(4, 0))
            self.stats.append(value)
        ttk.Label(frame, text='Your next small steps', style='Heading.TLabel').pack(anchor='w', pady=(0, 8))
        self.today_tree = table(frame, [('kind', 'TYPE', 85), ('name', 'HABIT / TASK', 300), ('detail', 'TODAY', 180)])
        self.today_tree.bind('<Double-1>', lambda e: self.today_action())
        self.today_tree.bind('<Return>', lambda e: self.today_action())
        bottom = ttk.Frame(frame)
        bottom.pack(fill='x', pady=10)
        ttk.Label(bottom, text='Select a habit to check in, or a task to finish.', style='Muted.TLabel').pack(side='left')
        ttk.Button(bottom, text='Check in / Finish', command=self.today_action).pack(side='right')

    def fit_layout(self, event=None):
        if event is not None and event.widget is not self.root:
            return
        # Keep the list and action controls usable on laptop-sized windows.
        compact = self.root.winfo_height() < 810
        if compact and self.hero.winfo_manager():
            self.hero.pack_forget()
        elif not compact and not self.hero.winfo_manager():
            self.hero.pack(fill='x', pady=(0, 18), before=self.stats_panel)

    def build_habits(self):
        frame = self.frame('habits')
        self.habit_tree = table(frame, [('name', 'HABIT', 300), ('schedule', 'REPEAT', 155), ('streak', 'STREAK', 90), ('today', 'TODAY', 110)])
        self.habit_tree.bind('<<TreeviewSelect>>', lambda e: self.habit_details())
        self.habit_tree.bind('<Double-1>', lambda e: self.check_habit())
        self.habit_tree.bind('<space>', lambda e: self.check_habit())
        detail = tk.Frame(frame, bg=PANEL, padx=20, pady=15)
        detail.pack(fill='x', pady=(12, 0))
        self.habit_note = label(detail, 'Select a habit to see its history.', 10, MUTED, anchor='w', justify='left', wraplength=800)
        self.habit_note.pack(anchor='w')
        self.history = tk.Frame(detail, bg=PANEL)
        self.history.pack(fill='x', pady=(12, 0))
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=(12, 0))
        ttk.Button(buttons, text='✓  Check in / Undo today', style='Accent.TButton', command=self.check_habit).pack(side='left')
        ttk.Button(buttons, text='Edit habit', command=lambda: self.edit('habit')).pack(side='left', padx=8)
        self.archive_button = ttk.Button(buttons, text='Archive habit', command=self.archive)
        self.archive_button.pack(side='right')

    def build_tasks(self):
        frame = self.frame('tasks')
        self.task_tree = table(frame, [('name', 'TASK', 320), ('priority', 'PRIORITY', 95), ('due', 'DUE', 110), ('state', 'STATUS', 100)])
        self.task_tree.bind('<<TreeviewSelect>>', lambda e: self.task_details())
        self.task_tree.bind('<Double-1>', lambda e: self.edit('task'))
        self.task_tree.bind('<Return>', lambda e: self.finish_task())
        self.task_note = ttk.Label(frame, text='Select a task for details.', style='Muted.TLabel', wraplength=850, padding=(0, 12))
        self.task_note.pack(fill='x')
        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=(0, 5))
        ttk.Button(actions, text='✓  Finish / Next step', style='Accent.TButton', command=self.finish_task).pack(side='left')
        ttk.Button(actions, text='Edit', command=lambda: self.edit('task')).pack(side='left', padx=8)
        ttk.Button(actions, text='Pause / Resume', command=self.pause_task).pack(side='left')
        ttk.Button(actions, text='Cancel task', command=self.cancel_task).pack(side='right')

    def show(self, key):
        self.view = key
        self.views[key].tkraise()
        titles = {'today': ('Make today count.', 'A clear view of the things that matter.'), 'habits': ('Consistency starts here.', 'Check in, keep your rhythm, and watch your progress grow.'), 'tasks': ('A little less on your mind.', 'Your to-dos and FRIDAY tasks, always in the same place.')}
        self.title.configure(text=titles[key][0])
        self.subtitle.configure(text=titles[key][1])
        for name, button in self.nav.items():
            button.configure(bg=PANEL if name == key else SIDEBAR, fg=ACCENT if name == key else MUTED)
        self.filters.configure(values=['Active', 'Archived', 'All'] if key == 'habits' else ['Open', 'Due today', 'High priority', 'Completed', 'All'])
        if key == 'today':
            self.filters.pack_forget()
        else:
            self.filters.pack(side='left', padx=10, after=self.search)
        self.filter.set('Active' if key == 'habits' else 'Open')
        self.new_button.configure(text='+ New task' if key == 'tasks' else '+ New habit')
        self.render()

    def new(self):
        if not self.dialogs:
            dialogs.Editor(self, 'task' if self.view == 'tasks' else 'habit')

    def load_habits(self):
        if not self.dialogs:
            dialogs.Importer(self)

    def selected(self, kind):
        tree = self.habit_tree if kind == 'habit' else self.task_tree
        selection = tree.selection()
        if not selection:
            self.status.set(f'Select a {kind} first.')
            return None
        return next((r for r in self.data[kind + 's'] if str(r['id']) == selection[0]), None)

    def edit(self, kind):
        item = self.selected(kind)
        if item and not self.dialogs:
            if kind == 'task' and item['status'] in {'completed', 'cancelled'}:
                self.status.set('Finished tasks are read-only. Add a new task to continue.')
            else:
                dialogs.Editor(self, kind, item)

    def render(self):
        if not hasattr(self, 'view'):
            return
        today = date.fromisoformat(self.data['date'])
        self.date_label.configure(text=today.strftime('%A, %d %B %Y').upper())
        habits = [h for h in self.data['habits'] if not h['archived']]
        due = [h for h in habits if today.weekday() in h['weekdays']]
        done = sum(self.data['date'] in h['checks'] for h in due)
        tasks = [t for t in self.data['tasks'] if t['status'] not in {'completed', 'cancelled'}]
        today_tasks = [t for t in self.data['tasks'] if t['due'] == self.data['date'] and t['status'] != 'cancelled']
        self.ring.draw(done + sum(t['status'] == 'completed' for t in today_tasks), len(due) + len(today_tasks))
        for widget, value in zip(self.stats, [f'{done} / {len(due)}', str(len(tasks)), f'{max((h["streak"] for h in habits), default=0)} days']):
            widget.configure(text=value)
        self.hero_hint.configure(text=f'{len(due) - done} habits left today · {len(today_tasks)} tasks due today' if due or today_tasks else 'Your next chapter starts with one habit. Add yours above.')
        query, mode = self.query.get().casefold(), self.filter.get()
        hs = [h for h in self.data['habits'] if query in h['name'].casefold() and (self.view != 'habits' or mode == 'All' or bool(h['archived']) == (mode == 'Archived'))]
        ts = [t for t in self.data['tasks'] if query in t['title'].casefold() and (mode == 'All' or mode == 'Completed' and t['status'] == 'completed' or mode in {'Open', 'Due today', 'High priority'} and t['status'] not in {'completed', 'cancelled'} and (mode != 'Due today' or t['due'] == self.data['date']) and (mode != 'High priority' or t['priority'] == 'high'))]
        self.replace(self.habit_tree, [(str(h['id']), (h['name'], self.schedule(h), f'{h["streak"]} days', 'Archived' if h['archived'] else 'Done' if self.data['date'] in h['checks'] else 'Rest day' if today.weekday() not in h['weekdays'] else 'To do'), 'done' if self.data['date'] in h['checks'] else 'muted' if h['archived'] else '') for h in hs])
        self.replace(self.task_tree, [(str(t['id']), (t['title'], t['priority'].title(), t['due'] or 'Anytime', t['status'].title()), 'done' if t['status'] == 'completed' else 'overdue' if t['due'] and t['due'] < self.data['date'] and t['status'] not in {'completed', 'cancelled'} else '') for t in ts])
        today_rows = [('h' + str(h['id']), ('Habit', h['name'], 'Done' if self.data['date'] in h['checks'] else f'{h["streak"]} day streak'), 'done' if self.data['date'] in h['checks'] else '') for h in due if query in h['name'].casefold()]
        today_rows += [('t' + str(t['id']), ('Task', t['title'], t['due'] or 'Anytime'), 'overdue' if t['due'] and t['due'] < self.data['date'] else '') for t in sorted(tasks, key=lambda t: (t['due'] or '9999', {'high': 0, 'normal': 1, 'low': 2}[t['priority']])) if query in t['title'].casefold()]
        self.replace(self.today_tree, today_rows)
        self.habit_details()
        self.task_details()

    @staticmethod
    def schedule(habit):
        return 'Every day' if len(habit['weekdays']) == 7 else ' '.join(['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'][d] for d in habit['weekdays'])

    @staticmethod
    def replace(tree, rows):
        selection = tree.selection()
        tree.delete(*tree.get_children())
        for ident, values, tag in rows:
            tree.insert('', 'end', iid=ident, values=values, tags=(tag,))
        if selection and tree.exists(selection[0]):
            tree.selection_set(selection[0])

    def habit_details(self):
        for widget in self.history.winfo_children():
            widget.destroy()
        selection = self.habit_tree.selection()
        habit = next((h for h in self.data['habits'] if selection and str(h['id']) == selection[0]), None)
        self.habit_note.configure(text=(habit['notes'] or 'Last 14 days · select a scheduled date to check in or undo.') if habit else 'Select a habit to see its history. Add your first habit with + New habit.')
        if not habit:
            return
        self.archive_button.configure(text='Restore habit' if habit['archived'] else 'Archive habit')
        today = date.fromisoformat(self.data['date'])
        for offset in range(13, -1, -1):
            day = today - timedelta(days=offset)
            active = day.weekday() in habit['weekdays'] and day.isoformat() >= habit['created'] and not habit['archived']
            done = day.isoformat() in habit['checks']
            button = tk.Button(self.history, text=day.strftime('%d') + ('\n✓' if done else '\n·'), bg=ACCENT if done else SIDEBAR,
                               fg='#09271f' if done else TEXT, relief='flat', bd=0, font=('Segoe UI', 9), padx=4, pady=5,
                               state='normal' if active else 'disabled', disabledforeground='#64758c',
                               command=lambda d=day.isoformat(), h=habit: self.mutate(lambda: self.store.check(h['id'], d, d not in h['checks'], h['revision'])))
            button.pack(side='left', fill='x', expand=True, padx=2)

    def task_details(self):
        selection = self.task_tree.selection()
        task = next((t for t in self.data['tasks'] if selection and str(t['id']) == selection[0]), None)
        if task:
            step = task['steps'][task['cursor']] if task['cursor'] < len(task['steps']) else 'No pending planned steps'
            self.task_note.configure(text=f'#{task["id"]} · {task["cursor"]}/{len(task["steps"])} steps · {step}\n' + (task['blocker'] or task['notes'] or 'Changes are shared with FRIDAY.'))
        else:
            self.task_note.configure(text='Select a task for details. Add a task here or tell FRIDAY: start task: <name>.')

    def check_habit(self, habit=None):
        habit = habit or self.selected('habit')
        if habit:
            day = self.data['date']
            self.mutate(lambda: self.store.check(habit['id'], day, day not in habit['checks'], habit['revision']))

    def archive(self):
        habit = self.selected('habit')
        if habit and messagebox.askyesno('Restore habit?' if habit['archived'] else 'Archive habit?', 'Your check-in history will be kept.', parent=self.root):
            self.mutate(lambda: self.store.archive(habit['id'], not habit['archived'], habit['revision']))

    def finish_task(self, task=None):
        task = task or self.selected('task')
        if not task:
            return
        if task['status'] != 'active':
            self.status.set('Resume a paused or blocked task before finishing it. Finished tasks are read-only.')
            return
        planned = task['cursor'] < len(task['steps'])
        note = simpledialog.askstring('Complete next step' if planned else 'Finish task', ('What did you finish?\n' + task['steps'][task['cursor']]) if planned else 'Optional completion note:', parent=self.root)
        if note is not None:
            self.mutate(lambda: self.store.task_action(task['id'], 'step' if planned else 'completed', note or 'Marked done by owner in the to-do app.', task['updated']))

    def pause_task(self):
        task = self.selected('task')
        if task:
            self.mutate(lambda: self.store.task_action(task['id'], 'paused' if task['status'] == 'active' else 'active', revision=task['updated']))

    def cancel_task(self):
        task = self.selected('task')
        if task and messagebox.askyesno('Cancel task?', 'Keep this task in history and mark it cancelled?', parent=self.root):
            self.mutate(lambda: self.store.task_action(task['id'], 'cancelled', revision=task['updated']))

    def today_action(self):
        selection = self.today_tree.selection()
        if selection:
            kind, ident = selection[0][0], int(selection[0][1:])
            item = next(r for r in self.data['habits' if kind == 'h' else 'tasks'] if r['id'] == ident)
            self.check_habit(item) if kind == 'h' else self.finish_task(item)

    def submit(self, operation, callback):
        if self.closed:
            return
        self.pending += 1
        def run():
            try:
                result, error = operation(), None
            except Exception as exc:
                logging.getLogger(__name__).exception('Tracker operation failed')
                result, error = None, exc
            self.results.put((callback, result, error))
        self.executor.submit(run)

    def poll(self):
        while not self.results.empty():
            callback, result, error = self.results.get_nowait()
            self.pending -= 1
            try:
                callback(result, error)
            except Exception as exc:
                logging.getLogger(__name__).exception('Tracker display callback failed')
                self.callback_errors.append(exc)
                self.status.set('Could not display this response. Press F5 to refresh.')
        if not self.closed:
            self.poll_timer = self.root.after(30, self.poll)

    def refresh(self, message=None):
        if self.closed or self.loading:
            return
        self.loading = True
        def loaded(data, error):
            self.loading = False
            if error:
                self.status.set('Could not load your data: ' + str(error) + ' Press F5 to retry.')
                return
            self.data = data
            self.render()
            self.status.set(message or 'Up to date · shared with FRIDAY · Ctrl+N New · Ctrl+F Search · F5 Refresh')
        self.submit(self.store.snapshot, loaded)

    def mutate(self, operation):
        if self.pending or self.dialogs:
            self.status.set('Please wait for the current request or close the draft first.')
            return
        def finished(result, error):
            self.refresh(str(error) if error else 'Saved. FRIDAY shares this update.')
        self.submit(operation, finished)

    def tick(self):
        if not self.dialogs and not self.pending:
            self.refresh()
        if not self.closed:
            self.tick_timer = self.root.after(15_000, self.tick)

    def close(self):
        if self.pending:
            self.status.set('Finishing your current request. Please close again in a moment.')
            return
        for dialog in list(self.dialogs):
            dialog.close()
            if dialog in self.dialogs:
                return
        self.closed = True
        self.root.after_cancel(self.poll_timer)
        self.root.after_cancel(self.tick_timer)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()
