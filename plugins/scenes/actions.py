"""Built-in reversible actions and validation; hardware is injected for tests."""
from pathlib import Path
import re
from urllib.parse import urlsplit

from .desktop import PLANS
from .registry import Action, Skipped

PASSIVE_FILES = {'.txt', '.md', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.csv',
                 '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.mp3', '.wav', '.flac',
                 '.mp4', '.mkv', '.avi', '.json', '.log', '.ics', '.m3u', '.m3u8', '.pls'}


def fields(params, required, optional=()):
    if not isinstance(params, dict) or set(params) - set(required) - set(optional) or set(required) - set(params):
        raise ValueError('Use only these action fields: ' + ', '.join([*required, *optional]))


def text(value, max_length=160):
    if not isinstance(value, str) or not value.strip() or len(value) > max_length or any(ord(c) < 32 for c in value):
        raise ValueError('Use nonempty text without control characters.')


def app_params(p):
    fields(p, ['name'])
    text(p['name'])
    if not re.fullmatch(r'[\w .()+-]+', p['name']) or p['name'].strip().lower() in {'all', 'everything', 'explorer', 'file explorer'}:
        raise ValueError('Name one app explicitly; wildcards, command arguments and the desktop are forbidden.')
    if re.search(r'\b(?:cmd|powershell|pwsh|wscript|cscript|mshta|shutdown|rundll32|regsvr32)\b', p['name'], re.I):
        raise ValueError('Scene app actions cannot launch command/script hosts or power tools.')


def percent_params(p):
    fields(p, ['percent'])
    if type(p['percent']) is not int or not 0 <= p['percent'] <= 100:
        raise ValueError('percent must be an integer from 0 to 100.')


def bool_params(p):
    fields(p, ['on'])
    if type(p['on']) is not bool:
        raise ValueError('on must be true or false.')


def safe_url(url):
    text(url, 2048)
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError('Use an http/https URL without credentials; executable protocols are forbidden.')


def safe_path(value):
    text(value, 4096)
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or value.startswith(('\\\\', '//', '\\?')):
        raise ValueError('Use an absolute local document/folder path without traversal.')
    resolved = path.resolve()
    if (str(resolved).startswith(('\\\\', '//', '\\?')) or not resolved.exists()
            or (not resolved.is_dir() and resolved.suffix.lower() not in PASSIVE_FILES)):
        raise ValueError('Use an existing absolute local folder or document/media file; scripts, executables and shortcuts are forbidden.')
    return resolved


def install(registry, desktop):
    api = registry.api
    def register(name, do, undo=lambda token: None, preview=None, validate=None, prepare=None, cleanup=False):
        registry.register(name, Action(do, undo, preview or (lambda p: name.replace('_', ' ')),
                                       validate or (lambda p: None), prepare, cleanup))
    def effect(fn, p):
        fn(p)
        return None
    register('open_app', lambda p: effect(lambda v: desktop.open_app(v['name']), p),
             preview=lambda p: 'Open ' + p['name'] + ' (already-open apps are kept).', validate=app_params)
    register('close_app', lambda p: effect(lambda v: desktop.close_app(v['name']), p),
             preview=lambda p: 'Ask ' + p['name'] + ' to close; save prompts remain visible. Closed documents cannot be restored.', validate=app_params)
    register('minimize_app', lambda p: desktop.minimize(p['name']), desktop.restore_windows,
             lambda p: 'Minimize ' + p['name'] + '; restore its previous window placement on exit.', app_params,
             lambda p: desktop.window_snapshot(p['name']))
    def volume(p):
        previous = desktop.audio_snapshot()
        desktop.set_volume(p['percent'])
        return previous
    def mute(p):
        previous = desktop.audio_snapshot()
        desktop.mute(p['on'])
        return previous
    register('set_volume', volume, desktop.restore_audio,
             lambda p: f'Set volume to {p["percent"]}%; restore its exact level and mute state on exit.', percent_params,
             lambda p: desktop.audio_snapshot())
    register('mute', mute, desktop.restore_audio, lambda p: ('Mute' if p['on'] else 'Unmute') + ' sound; restore audio on exit.',
             bool_params, lambda p: desktop.audio_snapshot())
    def brightness(p):
        previous = desktop.brightness_snapshot()
        desktop.set_brightness(p['percent'])
        return previous
    register('set_brightness', brightness, desktop.restore_brightness,
             lambda p: f'Set the built-in display to {p["percent"]}% brightness; restore it on exit.', percent_params,
             lambda p: desktop.brightness_snapshot())
    def power_params(p):
        fields(p, ['plan'])
        if p['plan'] not in PLANS:
            raise ValueError('Use balanced, high_performance or power_saver.')
    def power(p):
        previous = desktop.power_plan()
        desktop.set_power_plan(p['plan'])
        return previous
    register('set_power_plan', power, desktop.set_power_plan,
             lambda p: 'Use the ' + p['plan'].replace('_', ' ') + ' power plan; restore the previous GUID on exit.', power_params,
             lambda p: desktop.power_plan())
    def quiet_snapshot(p):
        from services import quiet_mode
        return dict(owner=registry.owner, on=quiet_mode.owner_enabled(registry.owner))
    def quiet(p):
        from services import quiet_mode
        previous = quiet_snapshot(p)
        quiet_mode.set_owner(registry.owner, p['on'])
        return previous
    def restore_quiet(token):
        from services import quiet_mode
        if token['owner'] != registry.owner:
            raise ValueError('Quiet owner does not match this scene.')
        quiet_mode.set_owner(token['owner'], token['on'])
    register('quiet_mode', quiet, restore_quiet,
             lambda p: ('Suppress' if p['on'] else 'Allow') + ' ordinary FRIDAY notices/cards; critical timer/recovery notices still appear.',
             bool_params, quiet_snapshot, True)
    def focus_params(p):
        fields(p, ['minutes'])
        if type(p['minutes']) not in {int, float} or not 0 < p['minutes'] <= 1440:
            raise ValueError('Focus minutes must be positive, at most 1440.')
    def focus(p):
        service = api.get_service('focus')
        if service is None:
            raise Skipped('Focus plugin is unavailable; no timer was started.')
        value = service.start(p['minutes'], label='Scene focus', owner=registry.owner)
        if not value['ok']:
            raise Skipped(value['text'])
        return {'owner': registry.owner}
    def prepare_focus(p):
        service = api.get_service('focus')
        if service is None:
            raise Skipped('Focus plugin is unavailable; no timer was started.')
        if service.status().get('active'):
            raise Skipped('An existing focus timer was kept; the scene did not replace it.')
        return {'owner': registry.owner}
    def undo_focus(token):
        if not isinstance(token, dict) or token.get('owner') != registry.owner:
            raise ValueError('Focus owner does not match this scene.')
        service = api.get_service('focus')
        if service is None:
            raise Skipped('Enable the focus plugin to stop the scene-owned timer.')
        service.stop(owner=token['owner'])
    register('start_focus', focus, undo_focus, lambda p: f'Start a {p["minutes"]}-minute focus timer if none is already running.',
             focus_params, prepare_focus)
    def threshold_params(p):
        fields(p, ['category', 'minutes'])
        focus_params({'minutes': p['minutes']})
        if p['category'] not in {'study', 'coding', 'entertainment', 'social', 'games', 'communication', 'system', 'other'}:
            raise ValueError('Use a supported activity category.')
    def threshold(p):
        service = api.get_service('activity')
        if service is None:
            raise Skipped('Activity plugin is unavailable; its nudge threshold was left alone.')
        service.set_threshold_override(p['category'], p['minutes'], registry.owner)
        return {'owner': registry.owner}
    def undo_threshold(token):
        if not isinstance(token, dict) or token.get('owner') != registry.owner:
            raise ValueError('Activity threshold owner does not match this scene.')
        if service := api.get_service('activity'):
            service.clear_overrides(token['owner'])
    def prepare_threshold(p):
        if api.get_service('activity') is None:
            raise Skipped('Activity plugin is unavailable; its nudge threshold was left alone.')
        return {'owner': registry.owner}
    register('set_activity_threshold', threshold, undo_threshold,
             lambda p: f'Ask activity for a {p["minutes"]}-minute {p["category"]} limit while this scene is active (if installed).',
             threshold_params, prepare_threshold, True)
    def mood_params(p):
        fields(p, ['mood'])
        if not isinstance(p['mood'], str) or not re.fullmatch(r'[a-z_]{1,32}', p['mood']):
            raise ValueError('Use a named mood.')
    def mood(p):
        previous = {'mood': 'idle'}
        events = api.manager.bus.recent('mood.changed')
        if events:
            previous['mood'] = events[-1]['payload'].get('mood', 'idle')
        api.set_mood(p['mood'], 120, priority=4)
        return previous
    register('set_mood', mood, lambda token: api.set_mood(token['mood'], 5, priority=4),
             lambda p: 'Show a ' + p['mood'] + ' mood while the scene is active.', mood_params,
             lambda p: {'mood': 'idle'}, True)
    def url_params(p):
        fields(p, ['url'])
        safe_url(p['url'])
    register('open_url', lambda p: effect(lambda v: desktop.open_url(v['url']), p),
             preview=lambda p: 'Open ' + p['url'] + ' in your browser; nothing is fetched by FRIDAY.', validate=url_params)
    def path_params(p):
        fields(p, ['path'])
        safe_path(p['path'])
    register('open_path', lambda p: effect(lambda v: desktop.open_path(safe_path(v['path'])), p),
             preview=lambda p: 'Open local document/folder ' + p['path'] + '.', validate=path_params)
    def say_params(p):
        fields(p, ['text'])
        text(p['text'], 2000)
    def say(p):
        line = p['text']
        if line == '{tomorrow_summary}':
            service = api.get_service('briefings')
            method = getattr(service, 'tomorrow_summary', None)
            if not callable(method):
                raise Skipped('No offline briefings.tomorrow_summary() service is available.')
            line = method()
            if isinstance(line, dict):
                line = line.get('text', '')
            if not isinstance(line, str) or not line:
                raise Skipped('Tomorrow\'s briefing is empty.')
        api.speak(line)
        return None
    register('say', say, preview=lambda p: ('Read tomorrow\'s summary if the offline briefings service exists.'
             if p['text'] == '{tomorrow_summary}' else 'Say: ' + p['text']), validate=say_params)
    def music_params(p):
        fields(p, ['playlist_or_url'])
        text(p['playlist_or_url'], 2048)
        value = p['playlist_or_url']
        if value.startswith(('http:', 'https:')):
            safe_url(value)
        elif ':' in value and not Path(value).is_absolute():
            raise ValueError('Use a playlist name, local playlist or http/https URL.')
    def music(p):
        value = p['playlist_or_url']
        if value == '{study_music}':
            value = api.settings.get('study_music', '')
            if not value:
                raise Skipped('Optional study music is not configured.')
            music_params({'playlist_or_url': value})
        if value.startswith(('http:', 'https:')):
            desktop.open_url(value)
        elif Path(value).is_absolute():
            desktop.open_path(safe_path(value))
        else:
            desktop.play_music(value)
            if value not in {'music', 'resume'}:
                raise Skipped('Opened the local Spotify client search; choose a cached/offline playlist to play it.')
        return None
    register('play_music', music, preview=lambda p: ('Optionally open your configured study playlist.' if p['playlist_or_url'] == '{study_music}'
             else 'Open/resume music: ' + p['playlist_or_url'] + '. Named Spotify results need you to select playback.'), validate=music_params)
    from .safe_commands import SceneCommands
    commands = SceneCommands(api, registry)
    register('run_command', commands.run, commands.undo, commands.preview, commands.validate, commands.prepare)
    registry.get('run_command').closes = commands.closes
