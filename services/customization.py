"""Validated catalog editing in the backend; saving never executes a command."""
import copy
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from services import settings_store
from services.activity import projects
from services.automation import modes, routines, whatsapp

SECTIONS = {'contacts': whatsapp, 'routines': routines, 'projects': projects, 'modes': modes}


class Conflict(ValueError):
    pass


class StoreUnavailable(ValueError):
    pass


class Fields(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')


class Contact(Fields):
    number: str = Field(min_length=1, max_length=40)


class Routine(Fields):
    steps: list[str] = Field(min_length=1, max_length=100)


class Mode(Fields):
    steps: list[str] = Field(max_length=100)
    quiet: bool


class Project(Fields):
    path: str = Field(min_length=1, max_length=1000)
    repo: str = Field(default='', max_length=200)
    sites: list[str] = Field(default_factory=list, max_length=50)
    resume: list[str] = Field(default_factory=list, max_length=100)


MODELS = {'contacts': Contact, 'routines': Routine, 'modes': Mode, 'projects': Project}


def _read(section):
    module = SECTIONS[section]
    try:
        raw = module.path.read_bytes()
    except FileNotFoundError:
        raw = b''
        data = copy.deepcopy(modes.DEFAULT_MODES) if section == 'modes' else {}
    else:
        if len(raw) > 2_000_000:
            raise StoreUnavailable('This settings file is too large to edit safely.')
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            raise StoreUnavailable('The saved file is unreadable. Repair it before editing; it has been preserved.') from error
    if not isinstance(data, dict):
        raise StoreUnavailable('The saved file must contain named entries. It has been preserved.')
    try:
        for name, value in data.items():
            if not isinstance(name, str) or not name.strip() or name != name.strip().lower():
                raise ValueError('Invalid saved name')
            if section == 'contacts':
                if not isinstance(value, str) or not whatsapp.clean_number(value):
                    raise ValueError('Invalid contact')
            elif section == 'routines':
                if not isinstance(value, list) or any(not isinstance(step, str) for step in value):
                    raise ValueError('Invalid routine')
            elif section == 'modes':
                Mode.model_validate(value)
            else:
                # Preserve unrelated project metadata; only editable fields are exposed.
                if not isinstance(value, dict) or not isinstance(value.get('path'), str):
                    raise ValueError('Invalid project')
                Project.model_validate(_fields(section, value))
    except (ValueError, TypeError) as error:
        raise StoreUnavailable('An entry in the saved file is invalid. Repair it before editing; nothing was overwritten.') from error
    return data, hashlib.sha256(raw).hexdigest()


def _fields(section, value):
    if section == 'contacts':
        return {'number': '+' + whatsapp.clean_number(value)}
    if section == 'routines':
        return {'steps': list(value)}
    if section == 'projects':
        return {'path': value['path'], 'repo': value.get('repo') or '',
                'sites': value.get('sites', []), 'resume': value.get('resume', [])}
    return copy.deepcopy(value)


@settings_store.synchronized
def snapshot(section: str) -> dict:
    data, revision = _read(section)
    active = modes.active(strict=True) if section == 'modes' else None
    return {'revision': revision, 'items': [{'name': name, 'value': _fields(section, value)}
            for name, value in sorted(data.items())], 'active': active['name'] if active else None}


def _normalize(section, value):
    fields = MODELS[section].model_validate(value).model_dump()
    for key in ('steps', 'resume', 'sites'):
        if key in fields:
            if any(not text.strip() or len(text) > 1000 or '\x00' in text for text in fields[key]):
                raise ValueError('Use nonempty lines of at most 1000 characters.')
            fields[key] = [text.strip() for text in fields[key]]
    if section == 'contacts':
        # Do not silently strip arbitrary letters from a pasted phone number.
        if not re.fullmatch(r'[+\d\s()\-]+', fields['number']):
            raise ValueError('Enter a phone number with country code, for example +91 98765 43210.')
        number = whatsapp.clean_number(fields['number'])
        if not number:
            raise ValueError('Enter a valid phone number with 10 to 15 digits.')
        return number
    if section == 'routines':
        return fields['steps']
    if section == 'projects':
        folder = Path(fields['path']).expanduser()
        if not folder.is_absolute() or not folder.is_dir() or folder.is_symlink() or folder.is_junction():
            raise ValueError('Choose an existing absolute project folder, rather than a link.')
        fields['path'] = str(folder.resolve())
        repo = fields['repo'].strip()
        if repo and not re.fullmatch(r'[a-zA-Z0-9][\w.-]*/[a-zA-Z0-9][\w.-]*', repo):
            raise ValueError('Use owner/repository for the GitHub repo, or leave it blank.')
        fields['repo'] = repo or None
        for site in fields['sites']:
            url = urlsplit(site if '://' in site else 'https://' + site)
            url.port  # Validate numeric port/range without resolving or contacting the host.
            if (url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password
                    or re.search(r'\s', site)):
                raise ValueError('Project websites must be HTTP/HTTPS URLs without credentials.')
        if not fields['resume']:
            fields.pop('resume')
    return fields


@settings_store.synchronized
def change(section: str, *, original: str | None, name: str, value: dict | None, revision: str) -> dict:
    data, current = _read(section)
    if current != revision:
        raise Conflict('Settings changed elsewhere. Reload before saving; your draft has been kept.')
    if original is not None and original not in data:
        raise Conflict('That entry no longer exists. Reload the list before editing.')
    name = ' '.join(name.strip().lower().split())
    if section == 'contacts':
        name = whatsapp._name(name)
    elif section == 'routines':
        name = routines._clean_name(name)
    if not name or len(name) > 100 or any(ord(char) < 32 for char in name) or '/' in name or '\\' in name:
        raise ValueError('Use a name of 1 to 100 characters without slashes or control characters.')
    if section == 'modes' and not re.fullmatch(r'[a-z][\w -]{0,30}', name):
        raise ValueError('Mode names must start with a letter and use at most 31 letters, digits, spaces or hyphens.')
    if name != original and name in data:
        raise Conflict('That name is already in use. Choose a different name.')
    if section == 'modes':
        active = modes.active(strict=True)
        if active and active['name'] == original and (value is None or name != original):
            raise ValueError('End the active mode before deleting or renaming it.')
    if value is None:
        if original is None:
            raise ValueError('Select an entry to delete.')
        del data[original]
    else:
        updated = _normalize(section, value)
        if section == 'projects':
            updated = {**data.get(original, {}), **updated}
            if not value.get('resume'):
                updated.pop('resume', None)
        if original is not None and original != name:
            del data[original]
        data[name] = updated
    SECTIONS[section]._save(data)
    if section in {'contacts', 'projects'}:
        from services.automation import intent
        for scope, pending in list(intent._pending.items()):
            if pending.parsed.get('action') == ('send_whatsapp' if section == 'contacts' else 'resume_project'):
                intent._pending.pop(scope, None)
    result = snapshot(section)
    if section == 'projects':
        from services.activity.log import activity_log
        try:
            activity_log.resort()
        except Exception:
            result['warning'] = 'Project settings were saved, but activity totals could not be refreshed. Restart FRIDAY to refresh them.'
    result['selected'] = name if value is not None else None
    return result
