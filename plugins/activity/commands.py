"""Finite, whole-string activity questions; output is safe for local speech."""
import re

from services.automation.command_words import normalize_command

from .policy import CATEGORIES

PERIOD = r'today|yesterday|this week|(?:the )?last (?:7|seven) days'
PATTERNS = {
    'current': r"what am i (?:doing|working on)(?: right now)?|show my current activity|what(?:'s| is) my current (?:app|activity)",
    'summary': rf"activity summary(?: (?:for )?(?P<range>{PERIOD}))?|what did i do (?P<day>today|yesterday)|summari[sz]e my activity(?: (?:for )?(?P<period>{PERIOD}))?",
    'time': rf"(?:how much time (?:did i spend|have i spent) (?:on|in)|how long (?:did i spend|have i spent|was i|have i been) (?:on|in)) (?P<name>.+?) (?P<range>{PERIOD})",
    'pause': r'pause (?:activity )?tracking|stop tracking(?: my activity)?',
    'resume': r'resume (?:activity )?tracking|start tracking(?: my activity)?',
    'delete': r'delete my activity data|clear my activity data',
    'confirm': r'confirm (?:delete|deletion of) my activity data',
    'cancel': r'cancel (?:deleting|deletion of) my activity data',
    'categorise': r'categori[sz]e (?P<app>.+?) as (?P<category>[a-z]+)',
}


def duration(seconds):
    minutes = int(max(0, seconds) // 60)
    if minutes >= 60:
        hours, remainder = divmod(minutes, 60)
        return f'{hours} hour{"s" if hours != 1 else ""}' + (f' {remainder} minutes' if remainder else '')
    if minutes:
        return f'{minutes} minute{"s" if minutes != 1 else ""}'
    return f'{int(max(0, seconds))} seconds'


def result(text, *, ok=True, error=None, data=None):
    value = dict(ok=ok, text=text, speech=text, error=error)
    if data is not None:
        value['data'] = data
    return value


class Commands:
    def __init__(self, activity):
        self.activity = activity
        self.patterns = {key: re.compile(pattern, re.I) for key, pattern in PATTERNS.items()}

    def parse(self, text):
        text = normalize_command(text)
        return next(((key, match) for key, pattern in self.patterns.items() if (match := pattern.fullmatch(text))), (None, None))

    def matches(self, text):
        return self.parse(text)[0] is not None

    def run(self, text):
        kind, match = self.parse(text)
        if kind is None:
            return result('That is not an activity command.', ok=False, error='unknown_command')
        return self.execute(kind, match)

    def execute(self, kind, match):
        activity = self.activity
        if kind == 'current':
            data = activity.current()
            text = (f"You are using {data['app_name']} ({data['category']}) for {duration(data['seconds'])}." if data['state'] == 'active'
                    else 'Activity tracking is paused.' if data['state'] == 'paused'
                    else 'You are in a private window; its app is not recorded.' if data['state'] == 'private'
                    else 'You are idle, or no foreground app is available.')
            return result(text, data=data)
        if kind in {'summary', 'time'}:
            groups = match.groupdict()
            period = groups.get('range') or groups.get('day') or groups.get('period') or 'today'
            period = period.lower().removeprefix('the ').replace('seven', '7')
            if kind == 'time':
                data = activity.time_on(groups['name'], period)
                return result(f"You spent {duration(data['seconds'])} on {groups['name']} {period}.", data=data)
            data = activity.summary(period)
            apps = ', '.join(f"{row['app_name']} {duration(row['seconds'])}" for row in data['top_apps']) or 'none recorded'
            categories = ', '.join(f'{name} {duration(seconds)}' for name, seconds in sorted(data['categories'].items())) or 'none recorded'
            return result(f"Active {period}: {duration(data['active_seconds'])}. Top apps: {apps}. Categories: {categories}. "
                          f"Longest study/coding stretch: {duration(data['longest_focus_seconds'])}.", data=data)
        if kind in {'pause', 'resume'}:
            activity.pause(kind == 'pause')
            return result('Activity tracking is paused.' if activity.paused() else 'Activity tracking resumed.')
        if kind == 'delete':
            activity.confirm_until = activity.clock.monotonic() + 30
            return result('Delete all recorded activity sessions? Say "confirm delete my activity data" within 30 seconds to confirm.')
        if kind == 'cancel':
            activity.confirm_until = 0
            return result('Activity deletion cancelled.')
        if kind == 'confirm':
            with activity.lock:
                if not activity.confirm_until or activity.clock.monotonic() > activity.confirm_until:
                    return result('Ask "delete my activity data" first; confirmation lasts 30 seconds.', ok=False, error='confirmation_required')
                activity.store.delete_all()
                activity.session = activity.sample = None
                activity.rowid = None
                activity.idle = True
                activity.started = activity.clock.now().timestamp()
                activity.confirm_until = 0
                activity.nudges.reset()
                activity.nudges.last = -float('inf')
                activity._runtime()
                activity.generation += 1
                activity.api.manager.bus.forget(activity.api.plugin_id)
            return result('Your activity sessions were deleted.')
        if kind == 'categorise':
            category = match['category'].lower()
            if category not in CATEGORIES:
                return result('Choose: ' + ', '.join(sorted(CATEGORIES)) + '.', ok=False, error='invalid_category')
            activity.policy.categorise(match['app'], category)
            return result(f'{match["app"]} is now categorised as {category}.')
