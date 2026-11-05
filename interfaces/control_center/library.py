"""Searchable offline features and readable local documentation."""
import re
import tkinter as tk
from tkinter import ttk
from pathlib import PurePosixPath

from interfaces.control_center import catalog
from interfaces.settings.app import BG, PANEL, TEXT, MUTED, ACCENT


class ScrollPage(ttk.Frame):
    """Keep dashboard/tool controls reachable at small sizes and high DPI."""
    def __init__(self, parent):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        bar = ttk.Scrollbar(self, command=self.canvas.yview)
        bar.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=bar.set)
        self.inner = ttk.Frame(self.canvas)
        window = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(window, width=event.width))
        self.inner.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.winfo_toplevel().bind('<MouseWheel>', self.wheel, add='+')

    def wheel(self, event):
        if self.winfo_ismapped() and self.inner.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(-int(event.delta / 120), 'units')


class Document(ttk.Frame):
    def __init__(self, parent, open_guide=None):
        super().__init__(parent)
        self.open_guide = open_guide
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.text = tk.Text(self, wrap='word', bg=PANEL, fg=TEXT, relief='flat', bd=0, width=1, height=1,
                            font=('Segoe UI', 11), padx=20, pady=15, spacing3=7,
                            insertbackground=TEXT, selectbackground='#294c63', cursor='arrow')
        self.text.grid(row=0, column=0, sticky='nsew')
        bar = ttk.Scrollbar(self, command=self.text.yview)
        bar.grid(row=0, column=1, sticky='ns')
        self.text.configure(yscrollcommand=bar.set)
        for tag, size in (('h1', 23), ('h2', 17), ('h3', 13)):
            self.text.tag_configure(tag, font=('Segoe UI Semibold', size), spacing1=14, spacing3=10)
        self.text.tag_configure('code', font=('Consolas', 10), foreground=ACCENT)
        self.text.tag_configure('table', font=('Consolas', 10))
        self.text.tag_configure('muted', foreground=MUTED)
        self.text.tag_configure('blank', font=('Segoe UI', 3), spacing1=0, spacing3=2)
        self.text.tag_configure('match', background='#6ee7d2', foreground='#082325')
        self.text.configure(state='disabled')

    def render(self, source):
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        for tag in self.text.tag_names():
            if tag.startswith('link_'):
                self.text.tag_delete(tag)
        fenced, links = False, 0
        for line in source.splitlines():
            if line.startswith('```'):
                fenced = not fenced
                continue
            if line.strip() in {'---', '***'}:
                continue
            if not line.strip():
                self.text.insert('end', '\n', 'blank')
                continue
            heading = re.match(r'^(#{1,6})\s+(.+)', line)
            tag = 'code' if fenced else 'table' if line.startswith('|') else ''
            if heading:
                tag = 'h' + str(min(3, len(heading[1])))
                line = heading[2]
            line = re.sub(r'\*\*(.*?)\*\*', r'\1', line)
            if line.startswith('- '):
                line = '•  ' + line[2:]
            cursor = 0
            for match in re.finditer(r'`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)', line):
                self.text.insert('end', line[cursor:match.start()], tag)
                if match[1] is not None:
                    self.text.insert('end', match[1], 'code')
                else:
                    key = PurePosixPath(match[3].split('#')[0]).name
                    if key == 'README.md' and 'island' in match[3]:
                        key = 'island'
                    link_tag = f'link_{links}'
                    links += 1
                    self.text.insert('end', match[2], (tag, link_tag))
                    if self.open_guide and key in catalog.GUIDES:
                        self.text.tag_configure(link_tag, foreground=ACCENT, underline=True)
                        self.text.tag_bind(link_tag, '<Button-1>', lambda e, k=key: self.open_guide(k))
                cursor = match.end()
            self.text.insert('end', line[cursor:] + '\n', tag)
        self.text.configure(state='disabled')
        self.text.yview_moveto(0)

    def find(self, query):
        self.text.tag_remove('match', '1.0', 'end')
        if not query:
            return 0
        index, found = '1.0', []
        while index := self.text.search(query, index, stopindex='end', nocase=True):
            end = f'{index}+{len(query)}c'
            self.text.tag_add('match', index, end)
            found.append(index)
            index = end
        if found:
            self.text.see(found[0])
        return len(found)


class Library(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.current = app, None
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        tools = ttk.Frame(self)
        tools.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 15))
        tools.columnconfigure(0, weight=1)
        self.query = tk.StringVar(self)
        self.search = ttk.Entry(tools, textvariable=self.query)
        self.search.grid(row=0, column=0, sticky='ew', padx=(0, 10))
        self.category = tk.StringVar(self, catalog.CATEGORIES[0])
        ttk.Combobox(tools, textvariable=self.category, values=catalog.CATEGORIES,
                     state='readonly', width=22).grid(row=0, column=1)
        left = ttk.Frame(self)
        left.grid(row=1, column=0, sticky='nsew', padx=(0, 14))
        left.rowconfigure(0, weight=1)
        self.list = ttk.Treeview(left, show='tree', selectmode='browse', height=12)
        self.list.column('#0', width=240, minwidth=170)
        self.list.grid(row=0, column=0, sticky='nsew')
        bar = ttk.Scrollbar(left, command=self.list.yview)
        bar.grid(row=0, column=1, sticky='ns')
        self.list.configure(yscrollcommand=bar.set)
        right = ttk.Frame(self)
        right.grid(row=1, column=1, sticky='nsew')
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=3, minsize=200)
        right.rowconfigure(2, weight=1, minsize=100)
        self.detail = Document(right, app.open_guide)
        self.detail.grid(row=0, column=0, sticky='nsew')
        ttk.Label(right, text='EXAMPLE COMMANDS · select one to prepare a draft', style='Brand.TLabel').grid(row=1, sticky='w', pady=(15, 8))
        self.examples = ttk.Treeview(right, show='tree', selectmode='browse', height=3)
        self.examples.column('#0', width=300, minwidth=80)
        self.examples.grid(row=2, column=0, sticky='nsew')
        bar = ttk.Scrollbar(right, command=self.examples.yview)
        bar.grid(row=2, column=1, sticky='ns')
        self.examples.configure(yscrollcommand=bar.set)
        actions = ttk.Frame(right)
        actions.grid(row=3, column=0, sticky='ew', pady=(12, 0))
        ttk.Button(actions, text='Use command →', style='Accent.TButton', command=self.use).pack(side='left')
        ttk.Button(actions, text='Copy', command=self.copy).pack(side='left', padx=8)
        self.guide_button = ttk.Button(actions, text='Read full guide', command=self.guide)
        self.guide_button.pack(side='right')
        self.count = ttk.Label(self, style='Muted.TLabel')
        self.count.grid(row=2, column=0, columnspan=2, sticky='w', pady=(12, 0))
        self.list.bind('<<TreeviewSelect>>', self.select)
        self.examples.bind('<Double-1>', lambda event: self.use())
        self.query.trace_add('write', lambda *args: self.populate())
        self.category.trace_add('write', lambda *args: self.populate())
        self.populate()

    def populate(self):
        rows = catalog.search(self.query.get(), self.category.get())
        self.list.delete(*self.list.get_children())
        for item in rows:
            self.list.insert('', 'end', iid=item.key, text=item.title)
        self.count.configure(text=f'{len(rows)} of {len(catalog.CAPABILITIES)} capabilities · guide available offline')
        if rows:
            key = self.current.key if self.current in rows else rows[0].key
            self.list.selection_set(key)
            self.select()
        else:
            self.current = None
            self.examples.delete(*self.examples.get_children())
            self.detail.render('# No matches\nTry an app, action, command, or a different category.')

    def select(self, event=None):
        selected = self.list.selection()
        if not selected:
            return
        self.current = next(item for item in catalog.CAPABILITIES if item.key == selected[0])
        item = self.current
        self.detail.render(f'# {item.title}\n{item.category}\n\n## What it does\n{item.description}\n\n'
                           f'## How to use it\n{item.how}\n\n## What it needs\n{item.requires}')
        self.examples.delete(*self.examples.get_children())
        for index, example in enumerate(item.examples):
            self.examples.insert('', 'end', iid=str(index), text=example)
        if item.examples:
            self.examples.selection_set('0')

    def example(self):
        selected = self.examples.selection()
        return self.current.examples[int(selected[0])] if selected and self.current else None

    def use(self):
        if command := self.example():
            self.app.prepare(command)

    def copy(self):
        if command := self.example():
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(command)
            self.app.message.set('Example copied. Edit names and dates before sending.')

    def guide(self):
        if self.current:
            self.app.open_guide(self.current.guide)


class Guides(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self.query = tk.StringVar(self)
        top = ttk.Frame(self)
        top.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 14))
        ttk.Label(top, text='Find in this guide', style='Muted.TLabel').pack(side='left', padx=(0, 10))
        self.search = ttk.Entry(top, textvariable=self.query, width=28)
        self.search.pack(side='left')
        self.matches = ttk.Label(top, style='Muted.TLabel')
        self.matches.pack(side='left', padx=10)
        self.list = ttk.Treeview(self, show='tree', selectmode='browse', height=13)
        self.list.column('#0', width=260, minwidth=170)
        self.list.grid(row=1, column=0, sticky='nsew', padx=(0, 14))
        for key, title in catalog.GUIDES.items():
            self.list.insert('', 'end', iid=key, text=title)
        bar = ttk.Scrollbar(self, command=self.list.yview)
        bar.grid(row=1, column=0, sticky='nse', padx=(0, 14))
        self.list.configure(yscrollcommand=bar.set)
        self.document = Document(self, app.open_guide)
        self.document.grid(row=1, column=1, sticky='nsew')
        self.list.bind('<<TreeviewSelect>>', self.select)
        self.query.trace_add('write', lambda *args: self.find())
        self.open('CONTROL_CENTER.md')

    def find(self):
        count = self.document.find(self.query.get())
        self.matches.configure(text=f'{count} matches' if self.query.get() else '')

    def open(self, key):
        if key in catalog.GUIDES:
            self.list.selection_set(key)
            self.list.see(key)
            self.select()

    def select(self, event=None):
        if not self.list.selection():
            return
        key = self.list.selection()[0]
        try:
            self.document.render(catalog.read_guide(key))
        except (OSError, ValueError) as error:
            self.document.render(f'# Guide unavailable\n{error}\nRestore this guide in the docs folder and select it again.')
        self.find()
