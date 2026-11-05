"""Expose the real project catalog; add launch profiles without replacing records."""
from pathlib import Path


def catalog(config):
    from services import customization
    data = customization.snapshot('projects')
    items = data['items']
    matched = set()
    for item in items:
        profile = next((row for row in config.projects if Path(row.path).resolve() == Path(item['value']['path']).resolve()), None)
        if profile:
            item['native_id'] = profile.id
            matched.add(profile.id)
    for profile in config.projects:
        if profile.id not in matched:
            conflict = any(item['name'].casefold() == profile.name.casefold() for item in data['items'])
            items.append({'name': profile.name, 'value': {'path': profile.path}, 'native_id': profile.id,
                          'native_only': True, 'conflict': conflict})
    return {'revision': data['revision'], 'items': items,
            'profiles': [{'name': row.name, 'path': row.path} for row in config.projects]}


def import_profiles(config):
    from services import customization
    from services.mind.cognition import cognition
    from .runtime import local_turn
    added, conflicts = [], []
    with local_turn(), cognition.operation('feature_request', 'island', 'Register Island project folders') as operation:
        for row in config.projects:
            snapshot = customization.snapshot('projects')
            same = next((item for item in snapshot['items'] if item['name'].casefold() == row.name.casefold()), None)
            if same:
                if Path(same['value']['path']).resolve() != Path(row.path).resolve():
                    conflicts.append(row.name)
                continue
            try:
                customization.change('projects', original=None, name=row.name,
                    value={'path': row.path, 'repo': '', 'sites': [], 'resume': []}, revision=snapshot['revision'])
                added.append(row.name)
            except (ValueError, OSError):
                conflicts.append(row.name)
        operation.finish('completed' if not conflicts else 'partial')
    return {**catalog(config), 'added': added, 'conflicts': conflicts}
