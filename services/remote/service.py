"""Remote enable latch, owner identity, pairing and fenced command dispatch."""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
import threading
import time

from core.logger import logger
from services.settings_store import save
from . import desktop
from .approval import Approvals, registration_complete
from .audit import Audit
from .commands import build_registry, fields
from .pairing import Pairing
from .security import Denied, RequestProofs
from .tailscale import Tailscale, loopback


class RemoteService:
    def __init__(self, directory: Path, port: int, *, tailscale=None, clock=time.time,
                 confirm=desktop.confirm, notify=desktop.notify, bound_addresses=None):
        self.directory, self.port, self.clock = Path(directory).absolute(), port, clock
        self.tailscale = tailscale or Tailscale()
        self.confirm, self.notify = confirm, notify
        self.bound_addresses = bound_addresses or self.listening_addresses
        self.source_stamp = self.source_state()
        self.pairing, self.audit = Pairing(self.directory, clock), Audit(self.directory, clock=clock)
        self.proofs, self.approvals = RequestProofs(notify, clock), Approvals(clock)
        self.registry = build_registry()
        self.lock, self.effects, self.cli_lock = threading.RLock(), threading.RLock(), threading.RLock()
        self.enabled = threading.Event()  # Never persisted: every restart/update requires owner enable.
        self.stopped = threading.Event()
        self.stopped.set()
        self.kill_token = object()
        self.epoch, self.registered, self.last_command = 0, False, None
        self.owner_login, self.magic_dns, self.warning = '', '', ''
        self._funnel_warned = False
        self.pair_tasks = set()
        try:
            path = self.directory / 'setup.json'
            if path.exists():
                setup = json.loads(path.read_text(encoding='utf-8'))
                self.owner_login = setup['owner_login']
                self.magic_dns = setup['magic_dns']
                if not all(isinstance(v, str) and 1 <= len(v) <= 254 for v in (self.owner_login, self.magic_dns)):
                    raise ValueError()
        except (ValueError, KeyError, OSError, TypeError):
            self.warning = 'Remote setup is unreadable; saved files were preserved.'

    def register(self, host):
        self.registered = loopback(host)
        if not self.registered:
            self.warning = 'Remote routes refused: the bridge bind is not loopback.'
            logger.warning('\033[31m%s\033[0m', self.warning)
        return self.registered

    @staticmethod
    def source_state():
        root = Path(__file__).resolve().parents[2]
        paths = [root / 'main.py', root / 'requirements.txt']
        for folder in ('core', 'services', 'interfaces', 'providers', 'plugins'):
            paths.extend((root / folder).rglob('*.py'))
        for folder in ('island/remote', 'island/remote-dist'):
            paths.extend(path for path in (root / folder).rglob('*') if path.is_file())
        return tuple(sorted((str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in paths if path.is_file()))

    def listening_addresses(self):
        import psutil
        try:
            return [connection.laddr.ip for connection in psutil.Process().net_connections(kind='tcp')
                    if connection.status == psutil.CONN_LISTEN and connection.laddr.port == self.port]
        except (psutil.Error, OSError):
            raise Denied('bind_unverified') from None

    def verify_bind(self):
        addresses = self.bound_addresses()
        if not addresses:
            raise Denied('bind_unverified')
        if any(not loopback(address) for address in addresses):
            self.fence_off()
            self.registered = False
            self.warning = 'Remote routes refused: an actual bridge listener is not loopback.'
            logger.warning('\033[31m%s\033[0m', self.warning)
            raise Denied('non_loopback')
        if self.source_state() != self.source_stamp:
            self.fence_off()
            self.warning = 'Remote is OFF after a source update. Restart FRIDAY, then enable remote locally.'
            raise Denied('source_updated')

    def status(self):
        return dict(enabled=self.enabled.is_set() and not self.stopped.is_set(), devices=len(self.pairing.devices),
                    last_command=self.last_command, warning=self.warning,
                    warning_level='red' if self.warning else '', registered=self.registered)

    def live(self):
        state = self.tailscale.status()
        if state.funnel is True:
            self.fence_off()
            with self.lock:
                self.warning = 'FUNNEL IS ON. Remote requests are blocked. Use disable remote to clear Serve configuration.'
                if not self._funnel_warned:
                    self._funnel_warned = True
                    logger.warning('\033[31m%s\033[0m', self.warning)
                    self.notify(self.warning)
            raise Denied('funnel_on')
        if not state.installed or not state.logged_in or state.funnel is not False:
            raise Denied('tailscale_unavailable')
        return state

    def enable(self, *, confirmed=False, expected_epoch=None, expected_token=None):
        if not confirmed or not self.registered or self.pairing.error or self.warning.startswith('Remote setup is unreadable'):
            raise Denied('local_enable_required')
        self.verify_bind()
        token = self.kill_token if expected_token is None else expected_token
        with self.lock:
            if token is not self.kill_token or expected_epoch is not None and expected_epoch != self.epoch:
                raise Denied('remote_off')
            self.epoch += 1
            epoch = self.epoch
            self.enabled.clear()
            self.stopped.clear()
        with self.cli_lock:
            self.check_epoch_pending_enable(epoch, token)
            state = self.live()
            if not state.owner_login or not state.magic_dns:
                raise Denied('owner_identity_unavailable')
            self.tailscale.enable(self.port)
            final = self.live()
            if (final.owner_login, final.magic_dns) != (state.owner_login, state.magic_dns) or not final.serving:
                raise Denied('serve_unverified')
            with self.lock:
                self.check_epoch_pending_enable(epoch, token)
                save(self.directory / 'setup.json', dict(owner_login=final.owner_login, magic_dns=final.magic_dns))
                self.owner_login, self.magic_dns = final.owner_login, final.magic_dns
                self.pairing.cancel()
                self.approvals.clear()
                self.warning, self._funnel_warned = '', False
                self.audit.write(device='owner', command='enable_remote', risk='confirm', result='enabled')
                self.enabled.set()
        return self.status()

    def check_epoch_pending_enable(self, epoch, token):
        if epoch != self.epoch or self.stopped.is_set() or token is not self.kill_token:
            raise Denied('remote_off')

    def trip(self):
        self.kill_token = object()  # Invalidate owner enables queued before the immediate off signal.
        self.stopped.set()
        self.enabled.clear()

    def fence_off(self):
        self.trip()
        with self.lock:
            self.stopped.set()
            self.enabled.clear()
            self.epoch += 1
            self.pairing.cancel()
            self.approvals.clear()

    def disable(self):
        self.fence_off()
        reset = True
        try:
            with self.cli_lock:
                self.tailscale.reset()
        except Denied:
            reset = False
        finally:
            self.fence_off()
        try:
            self.audit.write(device='owner', command='remote_off', risk='safe', result='disabled' if reset else 'reset_failed')
        finally:
            self.notify('Remote is OFF.' + ('' if reset else ' Serve reset failed; the routes are still disabled.'))
        return dict(enabled=False, serve_reset=reset)

    def check(self, epoch, device=None):
        if not self.registered or not self.enabled.is_set() or self.stopped.is_set() or epoch != self.epoch:
            raise Denied('remote_off')
        self.verify_bind()
        if device is not None:
            self.pairing.get(device['id'])  # Revocation is checked again immediately before submission.
        state = self.live()
        if not state.serving or (state.owner_login, state.magic_dns) != (self.owner_login, self.magic_dns):
            raise Denied('tailnet_changed')
        if not self.enabled.is_set() or self.stopped.is_set() or epoch != self.epoch:
            raise Denied('remote_off')
        if device is not None:
            self.check_epoch(epoch, device)
        return state

    async def monitor(self):
        while True:
            try:
                await asyncio.to_thread(self.verify_bind)
                await asyncio.to_thread(self.live)
            except Denied:
                pass
            await asyncio.sleep(5)

    def issue_pairing(self):
        self.check(self.epoch)
        return self.pairing.issue('https://' + self.magic_dns)

    def revoke(self, name):
        with self.lock:
            self.epoch += 1
            self.approvals.clear()
            identity = self.pairing.revoke(name)
            self.proofs.forget(identity)
        self.audit.write(device='owner', command='revoke_device', risk='confirm', result='revoked')
        return identity

    def run_effect(self, device, command, args, epoch, binding=None, expires_at=None):
        with self.effects:
            self.check(epoch, device)
            entry = self.registry.get(command)
            self.authorize_entry(device, entry)
            from .handlers import approval_binding, effect_lock
            with effect_lock(command):
                if binding is not None and approval_binding(command, args) != binding:
                    raise Denied('approval_target_changed')
                actual_args = dict(args, _approved_target=binding['target']) if command == 'open_app' else args
                self.check_epoch(epoch, device)
                if expires_at is not None and self.clock() >= expires_at:
                    raise Denied('approval_expired')
                result = entry.handler(self, device, actual_args)
            if not self.enabled.is_set() or self.stopped.is_set() or self.epoch != epoch:
                raise Denied('remote_off')
            return result

    async def command(self, device, body, epoch):
        fields(body, ('command',), ('args',))
        entry = self.registry.get(body['command'])
        await asyncio.to_thread(self.authorize_entry, device, entry)
        args = await asyncio.to_thread(entry.validate, body.get('args', {}))
        await asyncio.to_thread(self.check, epoch, device)
        if entry.risk == 'confirm':
            binding = await asyncio.to_thread(self.prepare_binding, body['command'], args)
            self.check_epoch(epoch, device)
            challenge = await asyncio.to_thread(self.approvals.create, self.magic_dns, device, body['command'], args, epoch, binding)
            self.check_epoch(epoch, device)
            return dict(result='approval_required', **challenge)
        if inspect.iscoroutinefunction(entry.handler):
            result = await entry.handler(self, device, args)
            self.check_epoch(epoch, device)
        else:
            result = await asyncio.to_thread(self.run_effect, device, body['command'], args, epoch)
        succeeded = not isinstance(result, dict) or result.get('ok', True) is not False
        if succeeded:
            self.last_command = body['command']
        return dict(result='completed' if succeeded else 'refused', data=result)

    def authorize_entry(self, device, entry):
        current = self.pairing.get(device['id'])
        if entry.risk == 'blocked' or entry.risk not in current['scopes'] or entry.scope and entry.scope not in current['scopes']:
            raise Denied('command_blocked')

    @staticmethod
    def prepare_binding(command, args):
        from .handlers import approval_binding, effect_lock
        with effect_lock(command):
            return approval_binding(command, args)

    def check_epoch(self, epoch, device):
        if not self.enabled.is_set() or self.stopped.is_set() or self.epoch != epoch:
            raise Denied('remote_off')
        # A note writer may hold the JSON guard; never invert Pairing -> JSON lock order.
        if self.pairing.error or device['id'] not in self.pairing.devices:
            raise Denied('device_unknown')

    async def approve(self, device, body, epoch):
        fields(body, ('challenge', 'approval'))
        if not isinstance(body['challenge'], str) or not isinstance(body['approval'], dict):
            raise Denied('invalid_approval')
        await asyncio.to_thread(self.check, epoch, device)
        row, counter = await asyncio.to_thread(self.approvals.consume, body['challenge'], device, body['approval'], epoch, self.pairing)
        entry = self.registry.get(row['command'])
        if entry.risk != 'confirm':
            raise Denied('command_blocked')
        args = await asyncio.to_thread(entry.validate, row['args'])
        await asyncio.to_thread(self.pairing.seen, device['id'], counter)
        result = await asyncio.to_thread(self.run_effect, device, row['command'], args, epoch, row['binding'], row['expires'])
        succeeded = not isinstance(result, dict) or result.get('ok', True) is not False
        if succeeded:
            self.last_command = row['command']
        return dict(result='completed' if succeeded else 'refused', command=row['command'], data=result)

    def prepare_pair(self, candidate, body):
        if 'token' in body:
            candidate, _ = self.pairing.begin(body, self.magic_dns)
        with self.pairing.lock:
            row = self.pairing.pending_device(candidate['id'])
            if row['phase'] != 'ready':
                raise Denied('pairing_used')
            self.pairing.pending[candidate['id']]['phase'] = 'awaiting_laptop'
        approval = None
        if row['registration_state'] is not None:
            approval = registration_complete(self.magic_dns, row['registration_state'], body.get('registration'))
        return row, approval

    def finish_pair(self, row, approval, epoch, accepted):
        with self.lock:
            self.check_epoch_pending(epoch)
            if accepted:
                self.pairing.activate(row['id'], approval, expected_pairing=row['pairing_id'])
            else:
                self.pairing.discard_pending(row['id'], row['pairing_id'])
        self.audit.write(device=row['id'], command='pair_decision', risk='confirm', result='paired' if accepted else 'rejected')

    async def pair(self, candidate, body, epoch):
        row, approval = await asyncio.to_thread(self.prepare_pair, candidate, body)
        self.check_epoch_pending(epoch)

        async def ask():
            try:
                sharing = '\nAlso permit sending explicitly enabled phone signals (phone_data).' if 'phone_data' in row['scopes'] else ''
                accepted = await asyncio.to_thread(self.confirm, f'Pair {row["name"]}?\n\nAllow this phone to use remote commands?{sharing} Yes / No')
                await asyncio.to_thread(self.check, epoch)
                await asyncio.to_thread(self.finish_pair, row, approval, epoch, accepted)
            except (Denied, OSError):
                await asyncio.to_thread(self.pairing.discard_pending, row['id'], row['pairing_id'])
        task = asyncio.create_task(ask())
        self.pair_tasks.add(task)
        task.add_done_callback(self.pair_tasks.discard)
        fingerprint = await asyncio.to_thread(self.pairing.fingerprint)
        self.check_epoch_pending(epoch)
        return dict(state='awaiting_laptop', device_id=row['id'], fingerprint=fingerprint)

    def check_epoch_pending(self, epoch):
        if not self.enabled.is_set() or self.stopped.is_set() or epoch != self.epoch:
            raise Denied('remote_off')
