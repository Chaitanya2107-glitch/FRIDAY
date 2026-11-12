"""Laptop-only prompts and QR display; never routed through models or notifications review."""
import ctypes
from ctypes import wintypes
import json
import os
import threading
import time


def protect(root):
    """Protect a top-level window before revealing pairing or consent data."""
    if os.name != 'nt':
        return False
    root.update_idletasks()
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    hwnd = user32.GetAncestor(root.winfo_id(), 2)
    return bool(hwnd and user32.SetWindowDisplayAffinity(hwnd, 0x11))


def confirm(question):
    if os.name != 'nt':
        return False
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.withdraw()
    root.title('FRIDAY Remote — owner approval')
    accepted = False
    def close(answer=False):
        nonlocal accepted
        accepted = answer
        root.destroy()
    tk.Label(root, text=question, wraplength=500, justify='left', padx=22, pady=20).pack()
    buttons = tk.Frame(root)
    buttons.pack(pady=(0, 18))
    tk.Button(buttons, text='Yes', width=12, command=lambda: close(True)).pack(side='left', padx=8)
    no = tk.Button(buttons, text='No', width=12, command=close)
    no.pack(side='left', padx=8)
    try:
        if not protect(root):
            root.destroy()
            notify('Remote consent could not open privately. No permission was granted.')
            return False
        root.protocol('WM_DELETE_WINDOW', close)
        root.bind('<Escape>', lambda event: close())
        root.after(120000, close)
        root.attributes('-topmost', True)
        root.deiconify()
        no.focus_set()
        root.mainloop()
        return accepted
    except Exception:
        try:
            root.destroy()
        except tk.TclError:
            pass
        return False


def copy_pairing(text):
    from services.automation import clipboard
    try:
        clipboard.set_text(text, private=True)
        return True
    except clipboard.ClipboardError:
        return False


def notify(message):
    def show():
        if os.name == 'nt':
            box = ctypes.windll.user32.MessageBoxW
            box.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
            box(None, message, 'FRIDAY Remote', (0x10 if 'FUNNEL' in message else 0x30) | 0x40000)
    threading.Thread(target=show, daemon=True, name='remote-notice').start()


def show_pairing(payload):
    def show():
        import tkinter as tk
        from PIL import ImageTk
        import qrcode
        try:
            root = tk.Tk()
        except tk.TclError:
            notify('The pairing window could not open.')
            return
        root.withdraw()
        root.title('FRIDAY Remote — pair your phone')
        root.attributes('-topmost', True)
        text = json.dumps(payload, separators=(',', ':'))
        code = qrcode.make(text).convert('RGB')
        code.thumbnail((600, 600))
        image = ImageTk.PhotoImage(code, master=root)
        tk.Label(root, image=image).pack(padx=16, pady=12)
        tk.Label(root, text=payload['url'] + '\n' + payload['laptop'] + '\n' + payload['fingerprint'], wraplength=600).pack(padx=16)
        countdown = tk.Label(root)
        countdown.pack(pady=8)

        def copy():
            if not copy_pairing(text):
                countdown.configure(text='Clipboard is busy. Try copying again.')
        tk.Button(root, text='Copy pairing JSON for the test script', command=copy).pack(pady=8)

        def tick():
            remaining = max(0, int(payload['expires'] - time.time()))
            countdown.configure(text=f'One use · expires in {remaining} seconds')
            if remaining:
                root.after(500, tick)
            else:
                root.destroy()
        try:
            if not protect(root):
                root.destroy()
                notify('The pairing QR could not be protected from screen capture and was not shown.')
                return
            root.deiconify()
            tick()
            root.mainloop()
        except Exception:
            try:
                root.destroy()
            except tk.TclError:
                pass
    threading.Thread(target=show, daemon=True, name='remote-pairing-qr').start()
