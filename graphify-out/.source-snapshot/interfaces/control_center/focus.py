"""Explicit target handoff with HWND, process and foreground revalidation."""
import os
import re

from interfaces.control_center.client import Error


def requires_target(text: str) -> bool:
    from services.automation.command_words import normalize_command, rephrase_command
    from services.browser.commands import is_desktop_command, match_command
    from services.vision.screen import extract_screen_question
    from services.voice.voice_commands import match_voice_command
    normal = normalize_command(rephrase_command(text))
    voice = match_voice_command(normal)
    browser = match_command(normal)
    computer = re.match(r'^\\c(?:\s+(.*))?$', normal)
    computer_input = computer and (computer[1] or '').casefold() not in {'', 'help', 'status', 'stop', 'no', 'cancel'}
    return bool(extract_screen_question(text) or (voice and voice['action'] == 'read_aloud')
                or computer_input or (browser and is_desktop_command(normal) and browser.kind in {'desktop', 'yes'})
                or normal == 'add this to my reading list')


def capture():
    if os.name != 'nt':
        raise Error('Target-app commands require Windows. Use ordinary chat or the local guides here.')
    import ctypes
    from ctypes import wintypes
    import psutil
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    hwnd = user.GetForegroundWindow()
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not hwnd or not pid.value or pid.value == os.getpid():
        raise Error('Choose another application during the countdown, then try again.')
    try:
        created = psutil.Process(pid.value).create_time()
    except psutil.Error as error:
        raise Error('The selected app is no longer available.') from error
    return hwnd, pid.value, created


def verify(target):
    if capture() != target:
        raise Error('The active window changed. No keyboard input was sent. Choose the target again.')


def apply(target, steps):
    from services.automation import keyboard
    submitted = 0
    try:
        for step in steps:
            verify(target)
            keyboard.run_steps([step])
            submitted += 1
    except (Error, keyboard.KeyboardError) as error:
        raise Error(f'Input stopped after {submitted} submitted steps. The current step may be incomplete. Check the destination before retrying.') from error
    return 'Input submitted to your selected app.'
