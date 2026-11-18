"""Read consented metadata from one handset; never combine different people's signals."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3


def observation(now, *, path=None, laptop_idle=None, classes=None, scene=None):
    from services.activity import timeline
    from services.activity.log import idle_seconds
    from services.proactive import timetable
    result = dict(fresh=False, laptop_idle=idle_seconds() if laptop_idle is None else laptop_idle,
                  class_window=False, scene=scene)
    if scene is None:
        from services.plugin_runtime import current_manager
        manager = current_manager()
        scenes = manager.get_service('scenes') if manager else None
        if scenes:
            result['scene'] = manager.invoke(scenes.api, scenes.status).get('active')
    classes = timetable.classes_for_date(now.date()) if classes is None else classes
    result['class_window'] = any(row['start'] <= now.strftime('%H:%M') < row['end'] for row in classes)
    path = Path(path or timeline.DEFAULT_PATH).absolute()
    if not path.is_file():
        return result
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        try:
            phones = db.execute('SELECT device,heartbeat,metadata FROM phones WHERE heartbeat>=? AND heartbeat<=? '
                                'ORDER BY heartbeat DESC,device', (now.timestamp() - 900, now.timestamp() + 60)).fetchall()
        except sqlite3.OperationalError:
            return result
        from services.remote import _service
        if _service is not None:
            phones = [row for row in phones if row['device'] in _service.pairing.devices
                      and 'phone_data' in _service.pairing.devices[row['device']].get('scopes', [])]
        if not phones:
            return result
        phone = phones[0]
        allowed = set(json.loads(phone['metadata'] or '{}').get('signals', []))
        if not allowed.intersection({'places', 'screen', 'battery', 'motion'}):
            return result
        rows = db.execute("SELECT id,timestamp,type,payload FROM phone_events WHERE device=? AND timestamp>=? AND timestamp<=? "
                          "AND type IN ('places','screen','battery','motion') ORDER BY timestamp,id",
                          (phone['device'], now.timestamp() - 2 * 86400, now.timestamp())).fetchall()
    latest = {r['type']: r for r in rows if r['type'] in allowed}
    result.update(fresh=True, device=phone['device'])
    for kind, row in latest.items():
        payload = json.loads(row['payload'])
        if kind == 'places':
            if payload['transition'] == 'entered':
                result['place'] = payload['place'].casefold()
            if row['timestamp'] >= now.timestamp() - 900:
                result['transition'] = dict(event='arrive' if payload['transition'] == 'entered' else 'leave',
                                            place=payload['place'].casefold(), id=row['id'], at=row['timestamp'], device=phone['device'])
        elif kind == 'battery':
            result['charging'] = payload['charging']
        elif kind == 'screen':
            result['screen'] = payload['state']
        elif kind == 'motion':
            result['motion'] = payload['activity']
    return result
