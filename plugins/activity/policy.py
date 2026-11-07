"""Only canonical process/site labels cross the native sampling boundary."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import threading

CATEGORIES = {'study', 'coding', 'entertainment', 'social', 'games', 'communication', 'system', 'other'}
DEFAULTS = {
    'poll_seconds': 2, 'idle_seconds': 120, 'site_labels': True, 'retention_days': 90,
    'paused': False, 'pause_in_private_scene': True,
    'excluded_processes': ['1password.exe', 'bitwarden.exe', 'keepass.exe', 'keepassxc.exe', 'dashlane.exe',
                           'nordpass.exe', 'enpass.exe', 'keeper.exe', 'lastpass.exe', 'roboform.exe',
                           'banking.exe', 'bank.exe', 'yono.exe', 'icicibank.exe', 'sbiyono.exe'],
    'excluded_title_fragments': ['InPrivate', 'Incognito', 'Private Browsing', 'Online Banking',
                                 'Internet Banking', 'NetBanking', 'HDFC Bank', 'ICICI Bank', 'Chase Online'],
    'nudge_rules': {'entertainment': 120, 'games': 120}, 'nudge_cooldown_minutes': 60,
    'category_overrides': {},
}


@dataclass(frozen=True)
class Sample:
    process: str | None = None
    app_name: str | None = None
    category: str = 'other'
    idle_seconds: float = 0
    fullscreen: bool = False
    private: bool = False


class Policy:
    def __init__(self, api, folder: Path):
        self.api, self.folder = api, folder
        self.lock = threading.RLock()
        self.maps = {'categories': {'processes': {}, 'sites': {}, 'names': {}}, 'sites': {'browsers': [], 'sites': {}}}
        cached = api.settings.get('activity.maps', {})
        for name in self.maps:
            try:
                if name in cached:
                    self._validate_map(name, cached[name])
                    self.maps[name] = cached[name]
            except (ValueError, TypeError):
                pass
        self.stamps = {}
        existing = api.settings.get('activity', {})
        if not isinstance(existing, dict):
            raise ValueError('activity settings must be a JSON object')
        self.values = {**DEFAULTS, **existing}
        if self.values != existing:
            api.settings.set('activity', self.values)
        self.reload()

    def reload(self):
        with self.lock:
            raw = self.api.settings.get('activity', {})
            if isinstance(raw, dict):
                self.values = {**DEFAULTS, **raw}
            for name in self.maps:
                path = self.folder / f'{name}.json'
                try:
                    stamp = (path.stat().st_mtime_ns, path.stat().st_size)
                    if self.stamps.get(name) == stamp:
                        continue
                    value = json.loads(path.read_text(encoding='utf-8'))
                    self._validate_map(name, value)
                except (OSError, ValueError, TypeError):
                    self.api.log.warning('Invalid activity configuration: %s.json; keeping safe defaults/last valid map', name)
                    continue
                self.maps[name], self.stamps[name] = value, stamp
                if cached := self.api.settings.get('activity.maps', {}):
                    if cached.get(name) == value:
                        continue
                self.api.settings.set('activity.maps', self.maps)

    @staticmethod
    def _validate_map(name, value):
        if not isinstance(value, dict):
            raise ValueError('Map must be a JSON object')
        def label(text):
            return isinstance(text, str) and 0 < len(text) <= 128 and all(ord(char) >= 32 for char in text)
        if name == 'categories':
            for key in ['processes', 'sites', 'names']:
                if not isinstance(value.get(key, {}), dict):
                    raise ValueError('Invalid map')
                if any(not label(k) or not label(v) for k, v in value.get(key, {}).items()):
                    raise ValueError('Map names/values must be bounded strings')
            if any(category not in CATEGORIES for key in ['processes', 'sites'] for category in value.get(key, {}).values()):
                raise ValueError('Unknown category')
        elif (not isinstance(value.get('browsers'), list) or any(not label(p) for p in value['browsers'])
              or not isinstance(value.get('sites'), dict)
              or any(not label(k) or not isinstance(items, list) or any(not label(s) for s in items)
                     for k, items in value['sites'].items())):
            raise ValueError('Invalid site labels')

    def number(self, key, minimum=.1, maximum=1_000_000):
        value = self.values.get(key, DEFAULTS[key])
        return float(value) if type(value) in {int, float} and minimum <= value <= maximum else float(DEFAULTS[key])

    def update(self, key, value):
        with self.lock:
            current = self.api.settings.get('activity', {})
            current[key] = value
            self.api.settings.set('activity', current)
            self.values = {**DEFAULTS, **current}

    def categorise(self, name, category):
        if category not in CATEGORIES or not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise ValueError('Choose an app/site and a supported category.')
        overrides = dict(self.values.get('category_overrides', {}))
        overrides[name.strip().casefold()] = category
        self.update('category_overrides', overrides)

    def sanitize(self, process: str, title: str, idle_seconds=0, fullscreen=False) -> Sample:
        process = process.lower()
        if process in {'logonui.exe', 'lockapp.exe'}:
            return Sample(idle_seconds=idle_seconds)
        excluded = self.values.get('excluded_processes', DEFAULTS['excluded_processes'])
        fragments = self.values.get('excluded_title_fragments', DEFAULTS['excluded_title_fragments'])
        # The mandatory private markers cannot be removed by editing preferences.
        private = (process in {str(p).lower() for p in excluded}
                   or any(str(part).casefold() in title.casefold() for part in [*fragments, 'InPrivate', 'Incognito', 'Private Browsing']))
        if private:
            return Sample(category='private', idle_seconds=idle_seconds, fullscreen=fullscreen, private=True)
        categories = self.maps['categories']
        label = categories.get('names', {}).get(process, process.removesuffix('.exe').replace('_', ' ').title())
        is_site = False
        if self.values.get('site_labels') and process in self.maps['sites'].get('browsers', []):
            for site, hints in self.maps['sites']['sites'].items():
                if any(re.search(r'(?<![\w])' + re.escape(hint) + r'(?![\w])', title, re.I) for hint in hints):
                    label, is_site = site, True
                    break
        overrides = self.values.get('category_overrides', {})
        category = (overrides.get(label.casefold()) or overrides.get(process)
                    or overrides.get(process.removesuffix('.exe'))
                    or (categories.get('sites', {}).get(label) if is_site else None)
                    or categories.get('processes', {}).get(process, 'other'))
        return Sample(process, label, category if category in CATEGORIES else 'other', idle_seconds, fullscreen)
