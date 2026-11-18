"""Apply the original popup's focus checks before screen/computer requests."""
import asyncio
import time


def requires_target(text):
    from interfaces.control_center.focus import requires_target as desktop_target
    if desktop_target(text):
        return True
    from services.computer.agent import is_computer_command
    from services.browser.commands import match_command, is_desktop_command
    from services.screen_watch.commands import is_query
    if is_query(text):
        return True
    if is_computer_command(text):
        return text.strip().lower() not in {'\\c', '\\c help', '\\c status', '\\c stop', '\\c no', '\\c cancel'}
    command = match_command(text)
    return bool(command and command.kind not in {'help', 'status', 'stop', 'report'}
                and (command.kind in {'desktop', 'yes'} or is_desktop_command(text)))


def check_target(target):
    import win32gui
    import win32process
    import psutil
    hwnd = win32gui.GetForegroundWindow()
    pid = win32process.GetWindowThreadProcessId(hwnd)[1] if hwnd else 0
    if (not target or hwnd != target['hwnd'] or pid != target['pid']
            or target['captured_at'] > time.time() + 1
            or psutil.Process(pid).create_time() > target['captured_at']):
        raise ValueError('Your active window changed. Return to your app and repeat the command.')


async def prepare_request(text, target):
    if requires_target(text):
        await asyncio.sleep(.2)
        await asyncio.to_thread(check_target, target)
