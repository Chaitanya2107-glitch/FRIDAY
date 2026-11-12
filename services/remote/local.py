"""Explicit laptop management commands; pairing details never enter conversational memory."""
import asyncio
from datetime import datetime

from services.automation.results import ActionResult
from .security import Denied


def fence_if_off(text):
    from services.automation.intent import remote_request
    from services.automation.command_words import normalize_command
    if remote_request.get() or not isinstance(text, str) or normalize_command(text).casefold() not in {'remote off', 'disable remote'}:
        return
    from . import _service
    if _service is not None:
        _service.trip()


async def try_command(text):
    from services.automation.intent import remote_request
    if remote_request.get():
        return None
    from services.automation.command_words import normalize_command
    clean = normalize_command(text)
    command = clean.casefold()
    known = {'enable remote', 'disable remote', 'remote off', 'remote status', 'pair my phone',
             'list paired devices', 'show remote activity'}
    if command not in known and not command.startswith('revoke '):
        return None
    from . import current, desktop
    service = current()
    try:
        if command in {'disable remote', 'remote off'}:
            service.trip()
            value = await asyncio.to_thread(service.disable)
            message = 'Remote is OFF.' + ('' if value['serve_reset'] else ' Serve reset failed; remote routes are disabled.')
        elif command == 'enable remote':
            epoch = service.epoch
            token = service.kill_token
            state = await asyncio.to_thread(service.live)
            if not await asyncio.to_thread(service.confirm,
                    f'Enable remote access over Tailscale?\n\nOwner: {state.owner_login}\nTailnet: {state.tailnet}\n'
                    f'Laptop: {state.magic_dns}\n\nOnly locally approved, signed devices may use remote commands.'):
                return ActionResult(False, 'Remote remains OFF.', repeatable=False)
            await asyncio.to_thread(service.enable, confirmed=True, expected_epoch=epoch, expected_token=token)
            message = 'Remote enabled. Say pair my phone to show a one-time QR.'
        elif command == 'pair my phone':
            payload = await asyncio.to_thread(service.issue_pairing)
            desktop.show_pairing(payload)
            message = 'Opening a one-time pairing QR on the laptop. It expires in 120 seconds.'
        elif command == 'list paired devices':
            devices = await asyncio.to_thread(service.pairing.list)
            message = '\n'.join(f'{d["name"]} ({d["id"]})' for d in devices) or 'No paired devices.'
        elif command.startswith('revoke '):
            name = clean[7:].strip()
            if text.strip().casefold().startswith('revoke '):
                literal = text.strip()[7:].strip()
                devices = await asyncio.to_thread(service.pairing.list)
                if any(row['name'].casefold() == literal.casefold() or row['id'] == literal for row in devices):
                    name = literal
            await asyncio.to_thread(service.revoke, name)
            message = 'Device revoked. Its requests are refused immediately.'
        elif command == 'show remote activity':
            rows = await asyncio.to_thread(service.audit.recent)
            message = '\n'.join(f'{datetime.fromtimestamp(r["time"]):%d %b %H:%M:%S} {r["device"]} '
                                f'{r["command"]} [{r["risk"]}] {r["result"]} {r["source_ip"]}' for r in rows) or 'No remote activity.'
        else:
            try:
                state = await asyncio.to_thread(service.live)
                connection = f'Tailscale: {state.magic_dns}; Serve: {"on" if state.serving else "off"}.'
            except Denied:
                connection = 'Tailscale is unavailable or unsafe.'
            value = service.status()
            message = f'Remote {"ON" if value["enabled"] else "OFF"}; {value["devices"]} paired devices. {connection}'
            if value['warning']:
                message += '\n' + value['warning']
        return ActionResult(True, message, memory_message='Remote management handled privately.', repeatable=False)
    except (Denied, OSError, ValueError):
        return ActionResult(False, service.warning or 'Remote request refused. Check Tailscale is installed and logged in, '
                            'Funnel is off, and the bridge is bound to loopback. If Funnel is on, say disable remote to clear Serve.',
                            memory_message='Remote management handled privately.', repeatable=False)
