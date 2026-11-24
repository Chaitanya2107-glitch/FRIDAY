"""Evidence-backed local suggestions. Owner-confirmed routines remain estimates."""
from datetime import datetime, timedelta
from pathlib import Path


def candidates(now, presence, *, classes=(), deadlines=(), commute=None, study=None, planned=False, prepare=None):
    if presence.get('confidence', 0) < .6 or presence['state'] in {'asleep', 'winding_down', 'in_class'}:
        return []
    result = []
    home = presence['state'] == 'at_home' or presence.get('place') == 'home' and presence['state'] == 'at_desk'
    if home and commute and commute.get('confirmed'):
        for row in classes:
            start = datetime.fromisoformat(row.get('date', now.date().isoformat()) + 'T' + row['start'])
            leave = start - timedelta(seconds=commute['seconds'])
            minutes = round((leave - now).total_seconds() / 60)
            if 5 <= minutes <= 15:
                result.append(dict(key='commute:' + start.isoformat(), text=f'As of {now:%H:%M}, leave in about {minutes} minutes for your {row["start"]} class. '
                    f'Reason: {commute["samples"]} observed trips suggest about {round(commute["seconds"] / 60)} minutes of travel; you confirmed this routine.'))
                break
    if home and not planned:
        for row in deadlines:
            if not row.get('done') and datetime.fromisoformat(row['due']).date() == (now + timedelta(days=1)).date():
                name = row.get('what', row.get('title', 'A recorded task'))
                item = dict(key='deadline:' + str(row.get('id', name)) + ':' + now.date().isoformat(),
                            text=f'{name} is due tomorrow. Reason: you appear to be at home and no timed plan is recorded for now.')
                if prepare and (preparation := prepare(row)):
                    item['preparation'] = preparation
                    item['text'] += ' ' + preparation
                result.append(item)
                break
    if study and study.get('confirmed') and abs(now.hour * 60 + now.minute - study['minute']) <= 10:
        result.append(dict(key='study:' + now.date().isoformat(), text='This is around a study time you previously accepted. '
                           'Reason: the existing learned routine falls within ten minutes of now; it may not fit today.'))
    return result


def prepare_work(row):
    import sqlite3
    from services.mind.graph import graph, normalized
    from services.mind.graph_sources import project_rows, refresh, work_node, work_projects

    if not graph.path.is_file():
        return ''
    try:
        view = refresh()
        item = work_node(view, row.get('id'), row.get('what', ''))
        if not item:
            return ''
        for project, _ in work_projects(view, item):
            matching = [p for p in project_rows() if normalized(p['name']) == normalized(project['name'])
                        and not p.get('conflict')]
            if len(matching) == 1 and Path(matching[0]['value']['path']).is_dir():
                return f"Your {project['name']} project folder is ready when you need it."
        courses = view.neighbors(item['id'], ('due_for',), kinds=('course',))
        if len(courses) == 1:
            return f"To prepare notes, say “make a revision pack for {courses[0][0]['name']}”."
    except (OSError, sqlite3.Error, ValueError, KeyError):
        pass
    return ''


def observed_candidates(now, presence):
    from services.proactive import timetable
    from services.college import work
    from services.activity import timeline, habits
    from services.activity.log import activity_log
    from services.activity.categories import categorize
    from services.mind.phone_patterns import commute_estimate
    events = timeline.phone_events((now - timedelta(days=30)).timestamp(), now.timestamp(), presence.get('device'))
    commute = commute_estimate(events, now, device=presence.get('device'))
    classes = timetable.classes_for_date(now.date())
    planned = any(row['start'] <= now.strftime('%H:%M') < row['end'] for row in classes)
    study = None
    state = habits.load_state().get('habits', {})
    for habit in habits.due_now(activity_log, now):
        if habit.minute is not None and state.get(habit.key, {}).get('accepted', 0) > 0 and any(
                thing.startswith('app:') and categorize('app', thing[4:]) == 'study' for thing in habit.things):
            study = dict(minute=habit.minute, confirmed=True)
            break
    return candidates(now, presence, classes=classes, deadlines=work.snapshot()['items'], commute=commute,
                      study=study, planned=planned, prepare=prepare_work)
