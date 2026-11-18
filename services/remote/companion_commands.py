"""Private literal companion commands, evaluated before any model or KDE fallback."""
import asyncio
from pathlib import Path
import re

from services.automation.results import ActionResult
from .security import Denied
from . import phone_handoff

PRIVATE = 'Companion command handled locally.'
PATTERNS = (
    r'ring (?:my |the )?phone', r'companion (?:status|phones)', r'(?:open|discard) phone link',
    r'send (?:this|this url|clipboard|this clipboard item) to (?:my )?phone',
    r'send (?:note|file) .+ to (?:my )?phone', r'use companion phone .+',
    r'(?:enable|disable) (?:phone approvals|phone clipboard sync|phone file indexing)',
)


def matches(text):
    return any(re.fullmatch(pattern, text.strip(), re.I | re.S) for pattern in PATTERNS)


def run(message, service):
    from services.automation.intent import remote_request
    from .phone_files import PhoneFiles
    text = message.strip()
    lower = text.lower()
    if remote_request.get():
        raise Denied('local_only')
    if lower == 'companion phones' or lower == 'companion status':
        info = phone_handoff.info(service, {}, {})
        lines = []
        for row in info['phones']:
            battery = row['battery'] or {}
            place = row['last_place'] or {}
            lines.append(f'{row["name"]} ({row["device"]}): {"connected" if row["connected"] else "unreachable"}; '
                         f'battery {battery.get("level", "unknown")}; last seen {row["last_seen"] or "unknown"}; '
                         f'last reported place {place.get("place", "unknown")} at {place.get("time", "unknown")}.')
        return '\n'.join(lines) or 'No native companion paired. Pair it in the Android app first.'
    if match := re.fullmatch(r'use companion phone (.+)', text, re.I):
        choices = [d for d in phone_handoff.native_devices(service) if match[1] in (d['id'], d['name'])]
        if len(choices) != 1:
            return 'Use the exact device name or ID shown by companion phones.'
        options = phone_handoff.settings(service)
        options['device'] = choices[0]['id']
        from services.settings_store import save
        save(service.directory / 'companion.json', options)
        return 'Companion selected.'
    if match := re.fullmatch(r'(enable|disable) (phone approvals|phone clipboard sync|phone file indexing)', text, re.I):
        option = {'phone approvals': 'phone_approvals', 'phone clipboard sync': 'auto_clipboard',
                  'phone file indexing': 'index_received_files'}[match[2].lower()]
        on = match[1].lower() == 'enable'
        if not service.confirm(f'{match[1].capitalize()} {match[2]}?\n'
                               'Phone clipboard sync skips private and secret-looking items. '
                               'File indexing permits received documents in local semantic search.'):
            return 'Cancelled.'
        from .phone_approvals import guard
        if not guard(dict(action='change_companion_settings', setting=option, value=on)):
            return 'Phone approval declined. Settings unchanged.'
        options = phone_handoff.settings(service)
        options[option] = on
        from services.settings_store import save
        save(service.directory / 'companion.json', options)
        if option == 'index_received_files':
            folder = PhoneFiles(service, phone_handoff.store(service)).quarantine()
            if on:
                (folder / '.nosearch').unlink(missing_ok=True)
                from services.plugin_runtime import current_manager
                manager = current_manager()
                search = manager.get_service('semantic_search') if manager else None
                if search and hasattr(search, 'api'):
                    roots = search.api.settings.get('indexed_roots', [])
                    search.api.settings.set('indexed_roots', list(dict.fromkeys([*roots, str(folder)])))
        service.audit.write(device='owner', command='companion_setting', risk='confirm', result='enabled' if on else 'disabled')
        return match[2].capitalize() + (' enabled.' if on else ' disabled.')
    if lower in {'open phone link', 'discard phone link'}:
        with service.lock:
            pending = getattr(service, '_phone_link', None)
            service._phone_link = None
        if not pending or pending['expires'] <= service.clock():
            return 'No current phone link is waiting.'
        if lower == 'discard phone link':
            return 'Phone link discarded.'
        from plugins.smart_clipboard.detectors import url
        if not url(pending['url']) or not service.confirm('Open this link now?\n' + pending['url']):
            return 'Link left closed.'
        import webbrowser
        webbrowser.open(pending['url'])
        return 'Link open requested.'
    device = phone_handoff.selected(service)
    if not device:
        return 'Pair a native phone, then use companion phones to select it.'
    if re.fullmatch(r'ring (?:my |the )?phone', text, re.I):
        phone_handoff.send(service, 'ring', dict(duration=30), ttl=60)
        report = run('companion status', service)
        return 'Ring requested for 30 seconds. The phone must be connected.\n' + report
    if match := re.fullmatch(r'send file (.+) to (?:my )?phone', text, re.I | re.S):
        service.check(service.epoch, device)
        PhoneFiles(service, phone_handoff.store(service)).send(device['id'], Path(match[1].strip().strip('"')))
        return 'File waiting for the phone. Tap its notification to download it.'
    if match := re.fullmatch(r'send note (.+) to (?:my )?phone', text, re.I | re.S):
        content = match[1]
    elif lower in {'send this url to my phone', 'send this url to phone'}:
        content = phone_handoff.current_url()
    elif lower in {'send this to my phone', 'send this to phone'}:
        try:
            content = phone_handoff.current_url()
        except (Denied, ImportError):
            from services.automation import clipboard
            from plugins.smart_clipboard.windows import DEFAULT_BLOCKLIST
            snapshot = clipboard.read_snapshot(DEFAULT_BLOCKLIST)
            if snapshot.sensitive or not snapshot.text:
                raise Denied('private_clipboard')
            content = snapshot.text
    else:
        from services.automation import clipboard
        from plugins.smart_clipboard.windows import DEFAULT_BLOCKLIST
        snapshot = clipboard.read_snapshot(DEFAULT_BLOCKLIST)
        if snapshot.sensitive or not snapshot.text:
            raise Denied('private_clipboard')
        content = snapshot.text
    if not 1 <= len(content) <= 4000:
        raise Denied('invalid_text')
    from plugins.smart_clipboard.detectors import url
    kind = 'link' if url(content) else 'text'
    phone_handoff.send(service, kind, dict(text=content))
    return 'Waiting for the phone. Open it from the phone notification.'


async def try_command(message):
    if not matches(message):
        return None
    from . import current
    service = current()
    # Native ring owns its phrase only when a native phone exists; KDE stays available.
    if re.fullmatch(r'ring (?:my |the )?phone', message.strip(), re.I) and not phone_handoff.native_devices(service):
        return None
    from services.automation.intent import cancel_pending_confirmation
    cancel_pending_confirmation()
    try:
        result = await asyncio.to_thread(run, message, service)
        return ActionResult(True, result, PRIVATE, False)
    except (Denied, OSError, ValueError, ImportError):
        return ActionResult(False, 'Companion request refused. Check remote access, phone selection and the requested item.', PRIVATE, False)
