"""Local status reports and model-free, owner-budgeted recovery notices."""

import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil

from core.config import config
from core.logger import logger
from services import settings_store
from services.automation.command_words import normalize_command
from services.automation.results import ActionResult
from services.health.watchdog import LABELS, watchdog

_TITLE = 'F.R.I.D.A.Y'
_CLOCK = re.compile(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]')
_BACKUP_SUFFIXES = {'.zip', '.7z', '.bak', '.sqlite', '.db'}


def _path():
    return config.MEMORY_DIR / 'health.json'


def _read():
    path = _path()
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Invalid health settings. The file was preserved.')
    return value


def _scheduled_time(value):
    value = value.get('report_time', os.getenv('FRIDAY_STATUS_REPORT_TIME', ''))
    return value if isinstance(value, str) and _CLOCK.fullmatch(value) else ''


def report_time():
    try:
        return _scheduled_time(_read())
    except (OSError, ValueError):
        return ''


@settings_store.synchronized
def set_report_time(value):
    if not isinstance(value, str) or value and not _CLOCK.fullmatch(value):
        raise ValueError('Choose a 24-hour time such as 19:30, or turn off the daily status report.')
    settings_store.save(_path(), _read() | {'report_time': value})
    return value


def _backup(root):
    directory = root / 'backups'
    if not directory.is_dir() or directory.is_symlink() or not directory.resolve().is_relative_to(root):
        return None
    latest = None
    for file in directory.iterdir():
        if file.suffix.lower() in _BACKUP_SUFFIXES and not file.is_symlink() and file.is_file():
            stamp = file.stat().st_mtime
            latest = stamp if latest is None else max(stamp, latest)
    return datetime.fromtimestamp(latest).strftime('%Y-%m-%d %H:%M') if latest is not None else None


def _folder_bytes(root):
    total = 0
    for folder, dirs, files in os.walk(root):
        base = Path(folder)
        dirs[:] = [name for name in dirs if (base / name).resolve() == base / name]
        for name in files:
            file = base / name
            try:
                if not file.is_symlink() and file.is_file():
                    total += file.stat().st_size
            except FileNotFoundError:
                pass  # A cache entry can disappear while it is read.
    return total


def build():
    from providers.failover import model_state

    rows = watchdog.snapshot()
    ran = [LABELS[name] for name, row in rows.items() if row['last_heartbeat'] is not None]
    failures = [f"{LABELS[name]} ({row['failures']}, {row['state']})"
                for name, row in rows.items() if row['failures']]
    model = model_state()
    root = config.MEMORY_DIR.resolve()
    try:
        disk = shutil.disk_usage(root if root.is_dir() else config.ROOT_DIR)
        disk_text = f'{disk.used / 2**30:.1f} GiB used of {disk.total / 2**30:.1f} GiB'
    except OSError:
        disk_text = 'unavailable'
    try:
        memory_text = f'{_folder_bytes(root) / 2**20:.1f} MiB'
    except OSError:
        memory_text = 'unavailable'
    try:
        backup = _backup(root)
        backup_text = backup or 'no recorded backup'
    except OSError:
        backup_text = 'unavailable'
    lines = [
        'Status report.',
        'Ran this session: ' + (', '.join(ran) or 'waiting for subsystem heartbeats') + '.',
        'Failures this session: ' + (', '.join(failures) or 'none recorded') + '.',
        ('Model: on (' + model['status'].replace('_', ' ') + ').') if model['enabled'] else 'Model: off.',
        f'Disk: {disk_text}. Memory folder: {memory_text}. Last backup: {backup_text}.',
    ]
    contact = rows['phone']['handset_heartbeat']
    if contact is not None:
        when = datetime.fromtimestamp(contact).strftime('%Y-%m-%d %H:%M')
        lines.append(f'Last paired handset contact this session: {when}.')
    return '\n'.join(lines)


async def handle(message, *, remote=False):
    text = normalize_command(message).casefold()
    match = re.fullmatch(r'(?:set )?daily status report (?:for|at) (.+)', text)
    disable = text == 'turn off daily status report'
    if text != 'status report' and match is None and not disable:
        return None
    if remote:
        return ActionResult(False, 'Status reports are available at the laptop.', repeatable=False)
    if text == 'status report':
        return ActionResult(True, await asyncio.to_thread(build), repeatable=False)
    try:
        value = await asyncio.to_thread(set_report_time, match[1] if match else '')
    except (OSError, ValueError) as error:
        text = str(error) if isinstance(error, ValueError) else 'I could not save the status report time.'
        return ActionResult(False, text, repeatable=False)
    return ActionResult(True, f"I'll give you a status report daily at {value}." if value else 'Daily status reports are off.',
                        repeatable=False)


def _send(text, now):
    from services.mind import talk, training
    from services.proactive.watcher import is_busy, nudges_active

    if not nudges_active(now.timestamp()) or is_busy() or talk.mic_in_use():
        return False
    if not training.allows_nudge(_TITLE, text, now=now.timestamp()):
        return False
    return training.show_toast(_TITLE, text, mirror_telegram=False, cognition_public=False,
                               cognition_text='Local FRIDAY health notice.') is True


@settings_store.synchronized
def _finish_daily(day):
    settings_store.save(_path(), _read() | {'last_report_day': day})


async def tick(now=None):
    now = now or datetime.now()
    if pending := watchdog.pending():
        name, serial, text = pending
        if await asyncio.to_thread(_send, text, now):
            watchdog.delivered(name, serial)
            return
    settings = await asyncio.to_thread(_read)
    scheduled = _scheduled_time(settings)
    day = now.date().isoformat()
    if scheduled and now.strftime('%H:%M') >= scheduled and settings.get('last_report_day') != day:
        text = await asyncio.to_thread(build)
        if await asyncio.to_thread(_send, text, now):
            await asyncio.to_thread(_finish_daily, day)


async def run():
    while True:
        try:
            await tick()
        except (OSError, TypeError, ValueError) as error:
            logger.debug('Health report deferred (%s)', type(error).__name__)
        await asyncio.sleep(30)
