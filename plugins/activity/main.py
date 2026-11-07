"""FRIDAY activity plugin: entirely local metadata, never screen/window contents."""
from pathlib import Path

from .commands import Commands, PATTERNS, result
from .policy import Policy
from .provider import WindowsForegroundProvider
from .tracker import Activity

_activity = None


def register(api, *, provider=None, clock=None):
    global _activity
    policy = Policy(api, Path(__file__).parent)
    activity = Activity(api, policy, provider or WindowsForegroundProvider(policy), clock)
    _activity = activity
    commands = activity.commands = Commands(activity)
    for kind, pattern in PATTERNS.items():
        api.on_command(pattern, lambda match, kind=kind: commands.execute(kind, match),
                       help=f'Local activity: {kind}.', examples=[])
    api.provide('activity', activity)
    api.subscribe('scene.*', activity.scene)
    def summary(request):
        try:
            return activity.summary(request.get('query', {}).get('range', 'today'))
        except ValueError:
            return result('Use today, yesterday, this week or last 7 days.', ok=False, error='invalid_range')
    api.add_route('GET', 'summary', summary)

    def worker(stop):
        while not stop.wait(policy.number('poll_seconds', .25, 3600)):
            try:
                api._call(activity.poll)
            except Exception:
                pass  # The host logs/counts failures and cancels after its circuit limit.
    api.run_background(worker)


def unload():
    if _activity:
        _activity.close()
