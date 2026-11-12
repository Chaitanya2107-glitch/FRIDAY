"""Fixed Tailscale CLI operations. Never enables Funnel or changes the API bind."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .security import Denied


def loopback(host: str) -> bool:
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def funnel_enabled(value) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'AllowFunnel':
                if not isinstance(child, dict) or any(type(v) is not bool for v in child.values()):
                    raise Denied('funnel_unknown')
                if any(child.values()):
                    return True
            elif funnel_enabled(child):
                return True
    elif isinstance(value, list):
        return any(funnel_enabled(child) for child in value)
    return False


@dataclass(frozen=True)
class Status:
    installed: bool = False
    logged_in: bool = False
    tailnet: str = ''
    magic_dns: str = ''
    owner_login: str = ''
    serving: bool = False
    funnel: bool | None = None


class Tailscale:
    def __init__(self, executable=None, runner=subprocess.run):
        default = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Tailscale/tailscale.exe'
        self.executable = executable or shutil.which('tailscale') or (str(default) if default.is_file() else None)
        self.runner = runner
        self.expected_proxy = None

    def run(self, *args):
        if not self.executable:
            raise Denied('tailscale_missing')
        try:
            value = self.runner([self.executable, *args], capture_output=True, text=True, encoding='utf-8',
                                timeout=10, shell=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if value.returncode != 0 or len(value.stdout) > 2 * 1024 * 1024:
                raise Denied('tailscale_unavailable')
            # Windows Tailscale writes successful --help output to stderr.
            return value.stdout + ('\n' + getattr(value, 'stderr', '') if args == ('serve', '--help') else '')
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            raise Denied('tailscale_unavailable') from None

    def json(self, *args):
        try:
            value = json.loads(self.run(*args))
        except Denied:
            raise
        except ValueError:
            raise Denied('tailscale_unknown') from None
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise Denied('tailscale_unknown')
        return value

    def status(self):
        if not self.executable:
            return Status()
        state = self.json('status', '--json')
        serve = self.json('serve', 'status', '--json')
        funnel = self.json('funnel', 'status', '--json')  # Read-only; no Funnel mutation exists here.
        for value in (serve, funnel):
            if set(value) - {'TCP', 'Web', 'Services', 'AllowFunnel', 'Foreground'}:
                raise Denied('funnel_unknown')
            if any(not isinstance(child, dict) for child in value.values()):
                raise Denied('funnel_unknown')
        if any(not isinstance(state.get(key) or {}, dict) for key in ('Self', 'User', 'CurrentTailnet')):
            raise Denied('tailscale_unknown')
        own = state.get('Self') or {}
        user = (state.get('User') or {}).get(str(own.get('UserID')), {})
        if not isinstance(user, dict):
            raise Denied('tailscale_unknown')
        dns = str(own.get('DNSName', '')).rstrip('.').lower()
        if dns and not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+', dns):
            raise Denied('tailscale_unknown')
        serving = bool(serve.get('Web') or serve.get('Services') or serve.get('Foreground'))
        if self.expected_proxy:
            try:
                serving = serve.get('Web', {}).get(dns + ':443', {}).get('Handlers', {}).get('/', {}).get('Proxy') == self.expected_proxy
            except AttributeError:
                raise Denied('tailscale_unknown') from None
        return Status(True, state.get('BackendState') == 'Running' and not own.get('Expired', False),
                      (state.get('CurrentTailnet') or {}).get('Name', ''), dns, user.get('LoginName', ''),
                      serving,
                      funnel_enabled(serve) or funnel_enabled(funnel))

    def enable(self, port):
        if type(port) is not int or not 1 <= port <= 65535:
            raise Denied('invalid_port')
        help_text = self.run('serve', '--help')
        if any(flag not in help_text for flag in ('--bg', '--https', '--set-path')):
            raise Denied('unsupported_tailscale_cli')
        self.run('serve', '--bg', '--https=443', '--set-path=/', f'http://127.0.0.1:{port}/remote')
        self.expected_proxy = f'http://127.0.0.1:{port}/remote'

    def reset(self):
        self.run('serve', 'reset')
