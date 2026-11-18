"""Local-only outgoing handoff and explicit incoming-link decisions."""
import json
from pathlib import Path
import threading

from .commands import text_args
from .security import Denied
from .transport_store import TransportStore


def store(service):
    with service.lock:
        if not hasattr(service, '_transport'):
            service._transport = TransportStore(service.directory.parent / 'phone' / 'transport.db', service.clock)
        return service._transport


def settings(service):
    try:
        value = json.loads((service.directory / 'companion.json').read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        raise Denied('companion_settings_invalid') from None


def native_devices(service):
    return [device for device in service.pairing.devices.values() if 'phone_data' in device.get('scopes', [])]


def selected(service):
    devices = native_devices(service)
    choice = settings(service).get('device')
    if choice:
        return next((d for d in devices if d['id'] == choice), None)
    return devices[0] if len(devices) == 1 else None


def send(service, kind, payload, ttl=900):
    from services.automation.intent import remote_request
    if remote_request.get():
        raise Denied('local_only')
    device = selected(service)
    if device is None:
        raise Denied('choose_native_phone')
    with service.effects:
        service.check(service.epoch, device)
        return store(service).put(device['id'], kind, payload, ttl)


def info(service, device, args):
    from services.phone_signals.remote import store as events_store
    phones = []
    source = events_store(service)
    for row in native_devices(service):
        state = source.status(row['id'])
        metadata = state.get('metadata') or {}
        place = None
        with source.connect() as db:
            latest = db.execute("SELECT payload,timestamp FROM phone_events WHERE device=? AND type='places' "
                                'ORDER BY timestamp DESC LIMIT 1', (row['id'],)).fetchone()
            if latest:
                payload = json.loads(latest['payload'])
                place = dict(place=payload['place'], transition=payload['transition'], time=latest['timestamp'])
        phones.append(dict(device=row['id'], name=row['name'], last_seen=state.get('last_heartbeat'),
                           last_place=place, battery=metadata.get('battery'), connected=store(service).reachable(row['id'])))
    choice = selected(service)
    return dict(phones=phones, selected=choice['id'] if choice else None)


def receive(service, device, args):
    from services.automation.clipboard_history import clipboard_history
    from plugins.smart_clipboard.detectors import url
    text = text_args('text', 4000)(args)['text']
    clipboard_history.record(text, source='phone', device=device['id'])
    if url(text):
        # Receipt is deliberately inert. Only a fresh local owner decision can open it.
        with service.lock:
            service._phone_link = dict(url=text, device=device['id'], expires=service.clock() + 900)
        service.notify('Phone link received. Open this link now? Say "open phone link" at the laptop, or "discard phone link".')
        return dict(text='Link received. Waiting for a laptop Open decision.', waiting=True)
    return dict(text='Added to clipboard history.', source='phone')


def ring_laptop(service, device, args):
    from services.activity.log import foreground_app, idle_seconds
    app, idle = foreground_app(), round(idle_seconds())
    from services.reminders.service import show_toast
    show_toast('Find my laptop', 'Your phone requested this sound.', mirror_telegram=False, urgency='critical',
               cognition_text='Find my laptop requested.')
    def sound():
        try:
            import winsound
            for _ in range(5):
                if not service.enabled.is_set() or service.stopped.is_set():
                    break
                winsound.Beep(1600, 700)
        except (RuntimeError, ImportError):
            pass
    threading.Thread(target=sound, name='find-laptop', daemon=True).start()
    return dict(text='Laptop ring requested.', app=app, idle_seconds=idle)


def auto_clipboard(text):
    """Called with an already-read smart-clipboard snapshot; never reads the clipboard."""
    from . import _service
    from plugins.smart_clipboard.privacy import sensitive_text
    service = _service
    if not service or not service.enabled.is_set() or service.stopped.is_set():
        return
    try:
        if settings(service).get('auto_clipboard') is True and not sensitive_text(text) and len(text) <= 4000:
            send(service, 'text', dict(text=text, source='clipboard'))
    except (Denied, OSError):
        pass


def current_url():
    """One owner-triggered address-bar read, without copying page text or the clipboard."""
    from services.activity.log import foreground_ids, foreground_app
    from plugins.smart_clipboard.detectors import url
    from plugins.smart_clipboard.privacy import sensitive_text
    if (foreground_app() or '').lower().removesuffix('.exe') not in {'chrome', 'msedge', 'firefox', 'brave', 'vivaldi', 'opera'}:
        raise Denied('foreground_browser_required')
    hwnd, pid = foreground_ids()
    from pywinauto import Desktop
    root = Desktop(backend='uia').window(handle=hwnd).wrapper_object()
    candidates = []
    for control in root.descendants(control_type='Edit')[:80]:
        item = control.element_info
        if item.element.CurrentIsPassword or not item.visible:
            continue
        if str(item.automation_id).lower() not in {'addresseditbox', 'urlbar-input', 'omnibox'} and str(item.name).lower() not in {
                'address and search bar', 'search or enter address', 'address bar', 'location'}:
            continue
        text = str(control.get_value() or '')
        if '://' not in text:
            text = 'https://' + text
        if url(text) and not sensitive_text(text):
            candidates.append(text)
    if foreground_ids() != (hwnd, pid) or len(set(candidates)) != 1:
        raise Denied('browser_url_unavailable')
    return candidates[0]
