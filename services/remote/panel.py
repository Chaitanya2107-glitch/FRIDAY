"""Read-only, explicit phone projections of existing local sources."""
from datetime import datetime, timedelta


def plugin_state(name, path):
    from services.plugin_runtime import current_manager
    manager = current_manager()
    if manager is None:
        return None
    return manager.route(name, path, {})


def schedule(service, device, args):
    from services.college import overview, work
    now = datetime.now()
    return dict(today=overview.class_status(now)['today'],
                tomorrow=overview.class_status(now + timedelta(days=1))['today'],
                assignments=work.snapshot('deadlines')['items'], exams=work.snapshot('exams')['items'])


def status(service, device, args):
    import psutil
    from services.college import overview
    from services.activity import log
    now = datetime.now()
    result = dict(service.status(), reachable=True, sampled_at=service.clock(), errors={})

    def read(key, fn):
        try:
            result[key] = fn()
        except Exception:
            result[key] = None
            result['errors'][key] = 'unavailable'

    def battery():
        power = psutil.sensors_battery()
        return dict(percent=power.percent, plugged=power.power_plugged) if power else None

    read('battery', battery)
    def current_app():
        from services.plugin_runtime import current_manager
        manager = current_manager()
        activity = manager.get_service('activity') if manager else None
        if activity:
            state = manager.invoke(activity.api, activity.current)
            return state.get('app_name') if state.get('state') == 'active' else None
        return log.foreground_app()

    read('current_app', current_app)  # Application identity only, never window titles.
    read('scene', lambda: plugin_state('scenes', 'status'))
    read('focus', lambda: plugin_state('focus', 'status'))
    read('mood', lambda: plugin_state('mood', 'state'))
    read('next_class', lambda: overview.class_status(now)['next_class'])
    read('due_today', lambda: [r for r in overview.overview(now)['due_soon']
                              if r['due'][:10] == now.date().isoformat()])
    return result


def activity(service, device, args):
    return dict(entries=service.audit.recent())


def this_device(service, device, args):
    row = service.pairing.get(device['id'])
    return {key: row[key] for key in ('id', 'name', 'created', 'last_seen')}


def revoke_self(service, device, args):
    # Removal fences this device immediately without invalidating its success response.
    service.pairing.revoke(device['id'])
    service.approvals.clear()
    service.proofs.forget(device['id'])
    return dict(revoked=True)


def events(service, device, args):
    return {}  # The signed stream uses this capability's risk/scope and validator.
