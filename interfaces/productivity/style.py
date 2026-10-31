"""Native Tk widgets, restrained colors, spacious typography and a progress ring."""
import tkinter as tk
from tkinter import ttk

BG, PANEL, SIDEBAR = '#0c1422', '#152237', '#101b2c'
TEXT, MUTED, ACCENT, LINE = '#edf4ff', '#a4b5ce', '#7ce3c1', '#293c55'
GOLD, RED = '#f2cb80', '#ff9ba9'


def theme(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Segoe UI', 10), background=BG, foreground=TEXT)
    style.configure('TFrame', background=BG)
    style.configure('Card.TFrame', background=PANEL)
    style.configure('TLabel', background=BG, foreground=TEXT)
    style.configure('Muted.TLabel', foreground=MUTED)
    style.configure('Title.TLabel', font=('Segoe UI Semibold', 28))
    style.configure('Heading.TLabel', font=('Segoe UI Semibold', 15))
    style.configure('Brand.TLabel', foreground=ACCENT, font=('Segoe UI Semibold', 10))
    style.configure('Card.TLabel', background=PANEL)
    style.configure('CardMuted.TLabel', background=PANEL, foreground=MUTED)
    style.configure('Number.TLabel', background=PANEL, font=('Segoe UI Semibold', 25))
    style.configure('TButton', padding=(15, 10), background=LINE, foreground=TEXT, borderwidth=0, font=('Segoe UI', 10))
    style.map('TButton', background=[('active', '#37516e'), ('disabled', '#1b293c')], foreground=[('disabled', MUTED)])
    style.configure('Accent.TButton', background=ACCENT, foreground='#09271f', font=('Segoe UI Semibold', 10))
    style.map('Accent.TButton', background=[('active', '#a2f1d8'), ('disabled', LINE)])
    style.configure('TEntry', fieldbackground=SIDEBAR, foreground=TEXT, padding=10, bordercolor=LINE, insertcolor=TEXT, lightcolor=LINE, darkcolor=LINE, font=('Segoe UI', 10))
    style.configure('TCombobox', fieldbackground=SIDEBAR, background=LINE, foreground=TEXT, padding=8, arrowsize=14, font=('Segoe UI', 10))
    style.map('TCombobox', fieldbackground=[('readonly', SIDEBAR)], foreground=[('readonly', TEXT)], selectbackground=[('readonly', LINE)])
    style.configure('TCheckbutton', background=PANEL, foreground=TEXT, padding=6)
    style.map('TCheckbutton', background=[('active', PANEL)])
    style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=48, borderwidth=0, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, font=('Segoe UI', 10))
    style.configure('Treeview.Heading', background=SIDEBAR, foreground=MUTED, padding=12, font=('Segoe UI Semibold', 9), bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
    style.map('Treeview', background=[('selected', '#2a4a61')], foreground=[('selected', TEXT)])
    style.map('Treeview.Heading', background=[('active', LINE)])
    style.configure('Vertical.TScrollbar', background=LINE, troughcolor=SIDEBAR, bordercolor=PANEL, arrowcolor=MUTED, lightcolor=LINE, darkcolor=LINE)
    root.option_add('*TCombobox*Listbox.background', PANEL)
    root.option_add('*TCombobox*Listbox.foreground', TEXT)


def label(parent, text, size=10, color=TEXT, bg=PANEL, **kw):
    return tk.Label(parent, text=text, font=('Segoe UI', size), fg=color, bg=bg, **kw)


class Ring(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, width=120, height=120, bg=PANEL, highlightthickness=0)

    def draw(self, done, total):
        self.delete('all')
        self.create_oval(10, 10, 110, 110, outline=LINE, width=8)
        ratio = done / total if total else 0
        if ratio:
            self.create_arc(10, 10, 110, 110, start=90, extent=-359.9 * ratio, style='arc', outline=ACCENT, width=8)
        self.create_text(60, 53, text=f'{round(ratio * 100)}%', fill=TEXT, font=('Segoe UI Semibold', 22))
        self.create_text(60, 79, text='of today', fill=MUTED, font=('Segoe UI', 9))


def table(parent, columns):
    frame = ttk.Frame(parent)
    frame.pack(fill='both', expand=True)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show='headings', selectmode='browse', height=1)
    for key, title, width in columns:
        tree.heading(key, text=title, anchor='w')
        tree.column(key, width=width, minwidth=60, stretch=key == 'name', anchor='w')
    tree.grid(row=0, column=0, sticky='nsew')
    scroll = ttk.Scrollbar(frame, command=tree.yview)
    scroll.grid(row=0, column=1, sticky='ns')
    tree.configure(yscrollcommand=scroll.set)
    tree.tag_configure('done', foreground=ACCENT)
    tree.tag_configure('muted', foreground=MUTED)
    tree.tag_configure('overdue', foreground=RED)
    return tree
