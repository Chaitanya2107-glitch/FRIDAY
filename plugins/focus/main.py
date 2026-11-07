"""Managed, offline focus and Pomodoro timers."""
from .commands import PATTERNS, result
from .timer import Focus

_focus = None


def register(api):
    global _focus
    focus = _focus = Focus(api)
    api.provide('focus', focus)
    for pattern in PATTERNS.values():
        api.on_command(pattern, lambda match: focus.handle_command(match.string),
                       help='Start, pause, resume or inspect an offline focus timer.',
                       examples=['focus 25', 'pomodoro', 'pause focus', 'focus stats today'])
    api.add_route('GET', 'status', lambda request: focus.status())
    def stats(request):
        try:
            return focus.stats(request.get('query', {}).get('range', 'today'))
        except ValueError:
            return result('Use today or this week.', ok=False, error='invalid_range')
    api.add_route('GET', 'stats', stats)
    api.every(1, focus.tick)


def unload():
    if _focus:
        _focus.close()
