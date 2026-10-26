"""
interfaces/popup/win32.py

The Win32 plumbing the command bar (app.py) is built on: DLLs, structures, function
signatures and message constants, via ctypes (no GUI toolkit).
"""

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ── Pointer-sized types ───────────────────────────────────────────────────────
# ctypes.wintypes' WPARAM/LPARAM have been inconsistent across Python builds;
# defining these ourselves guarantees they're pointer-sized on 64-bit Windows,
# which matters here since HWNDs and window-proc addresses get passed through
# them directly.
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


# ── Function prototypes ───────────────────────────────────────────────────────
# Explicit argtypes/restype everywhere a HANDLE/pointer crosses the boundary —
# ctypes defaults to c_int, which truncates 64-bit pointers and HWNDs.
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM

user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetFocus.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.IsWindow.argtypes = [wintypes.HWND]
user32.SetFocus.restype = wintypes.HWND

user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.SendMessageW.restype = LRESULT
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.PostMessageW.restype = wintypes.BOOL

user32.PostQuitMessage.argtypes = [ctypes.c_int]

user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]

user32.GetSystemMetrics.argtypes = [ctypes.c_int]

user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]

user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
user32.SetWindowLongPtrW.restype = ctypes.c_void_p
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_void_p

user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.CallWindowProcW.restype = LRESULT

user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]

user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = wintypes.HANDLE

gdi32.CreateFontW.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.LPCWSTR,
]
gdi32.CreateFontW.restype = wintypes.HANDLE

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

# ── Constants ──────────────────────────────────────────────────────────────
WS_POPUP, WS_BORDER, WS_CHILD, WS_VISIBLE = 0x80000000, 0x00800000, 0x40000000, 0x10000000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x00000008, 0x00000080
ES_AUTOHSCROLL = 0x0080
SW_SHOW, SW_HIDE = 5, 0
WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004+
GWLP_WNDPROC = -4
WM_DESTROY, WM_CLOSE, WM_HOTKEY, WM_ACTIVATE, WM_TIMER, WM_KEYDOWN = 0x0002, 0x0010, 0x0312, 0x0006, 0x0113, 0x0100
WM_SETFONT, WM_CHAR = 0x0030, 0x0102
WM_APP_SHOW = 0x8000 + 1  # WM_APP + 1: sent by other threads (the tray) to show the bar
WM_APP_HINT = 0x8000 + 2  # the guesses arrived (from a worker thread)
WM_APP_ASK = 0x8000 + 3  # FRIDAY asked something on her own: show it without taking focus
WM_APP_ASK_DONE = 0x8000 + 4  # her question was answered (by voice) or expired
SW_SHOWNOACTIVATE = 4
VK_TAB = 0x09
SS_ENDELLIPSIS = 0x4000
EM_SETSEL, EM_SETREADONLY = 0x00B1, 0x00CF
WA_INACTIVE = 0
VK_RETURN, VK_ESCAPE, VK_SPACE = 0x0D, 0x1B, 0x20
VK_CONTROL, VK_LCONTROL, VK_RCONTROL = 0x11, 0xA2, 0xA3
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x4000
HOTKEY_ID, VOICE_HOTKEY_ID, WAKE_HOTKEY_ID, HANDY_HOTKEY_ID = 1, 4, 5, 6
CONVERSATION_HOTKEY_ID = 9
POLL_TIMER_ID, RESULT_TIMER_ID, HANDY_TIMER_ID, ASK_TIMER_ID = 2, 3, 7, 8
WM_COMMAND, EN_CHANGE = 0x0111, 0x0300
IDC_ARROW = 32512
COLOR_WINDOW = 5
