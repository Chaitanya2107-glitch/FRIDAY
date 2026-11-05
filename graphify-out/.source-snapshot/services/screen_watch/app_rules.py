"""Owner app permissions, shared by capture workers and the customization editor."""
import json
import re

from core.config import config
from services import settings_store


def app_name(value):
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        raise ValueError('Use an app executable name without control characters.')
    value = ' '.join(value.strip().casefold().split())
    if value.endswith('.exe.exe'):
        raise ValueError('Use one executable name, for example chrome.exe.')
    value = value.removesuffix('.exe')
    aliases = {'terminal': 'windowsterminal', 'windows terminal': 'windowsterminal',
               'command prompt': 'cmd', 'powershell 7': 'pwsh', 'vs code': 'code'}
    value = aliases.get(value, value)
    if not value or len(value) > 100 or re.search(r'[<>:"/\\|?*]', value) or value.endswith('.'):
        raise ValueError('Use an app executable name, for example chrome.exe or powershell.exe.')
    return value


class AppRules:
    @property
    def path(self):
        return config.MEMORY_DIR / 'screen_apps.json'

    @settings_store.synchronized
    def _save(self, data):
        from services.screen_watch.service import watch
        # Revoke old generations before publishing; the caller holds settings_store.lock.
        watch.rules_changed()
        settings_store.save(self.path, data)

    @settings_store.synchronized
    def allowed(self, app):
        try:
            if self.path.stat().st_size > 2_000_000:
                return False
            data = json.loads(self.path.read_bytes())
            if not isinstance(data, dict) or any(
                    not isinstance(name, str) or app_name(name) != name or not isinstance(rule, dict)
                    or set(rule) != {'allowed'} or type(rule['allowed']) is not bool
                    for name, rule in data.items()):
                return False
            return data.get(app_name(app), {'allowed': True})['allowed']
        except FileNotFoundError:
            return True
        except (OSError, ValueError, TypeError):
            return False


rules = AppRules()
