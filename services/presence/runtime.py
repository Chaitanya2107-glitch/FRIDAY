"""Watcher integration: inference first, then bounded reviewed proposals and policy refresh."""
import asyncio
from datetime import datetime
import threading

from . import delivery, engine, phone, triage

lock = threading.RLock()
_last_arrival = None
_greeted = set()
_policy_at = 0
_policy_context = None
_subscriptions = []
_policy_worker = None
_policy_stop = None
_policy_wake = threading.Event()


def _watch_policy_changes():
    if _subscriptions:
        return
    from services.event_bus import event_bus
    def changed(event):
        # Event payloads grant no authority. Re-read the actual local timer/scene.
        if event['topic'] in {'focus.started', 'focus.done', 'focus.stopped', 'focus.paused', 'focus.resumed', 'scene.started', 'scene.ended'}:
            _policy_wake.set()
    for topic in ('focus.*', 'scene.*'):
        _subscriptions.append(event_bus.subscribe(topic, changed, plugin_id='presence-policy', allow_remote=True))


def _start_policy_worker(service):
    global _policy_worker, _policy_stop
    if _policy_worker is not None and _policy_worker.is_alive():
        return
    stopped, epoch = threading.Event(), service.epoch
    _policy_stop = stopped
    def work():
        while not stopped.is_set():
            changed = _policy_wake.wait(5)
            _policy_wake.clear()
            if stopped.is_set() or service.epoch != epoch or service.stopped.is_set():
                return
            try:
                now = datetime.now()
                context = situation(now)
                triage.store().context(context, now)
                refresh_policy(now, context, force=changed)
            except (ValueError, OSError):
                pass
    _policy_worker = threading.Thread(target=work, name='presence-policy', daemon=True)
    _policy_worker.start()


def reset_ephemeral():
    global _last_arrival, _policy_at, _policy_context
    from services.event_bus import event_bus
    if _policy_stop:
        _policy_stop.set(); _policy_wake.set()
    if _policy_worker and _policy_worker.is_alive():
        _policy_worker.join(timeout=1)
    for subscription in _subscriptions:
        event_bus.unsubscribe(subscription)
    _subscriptions.clear()
    _last_arrival, _policy_at, _policy_context = None, 0, None
    _greeted.clear()


def situation(now=None, presence=None):
    now = now or datetime.now()
    presence = presence or engine.current(now)
    from services.plugin_runtime import current_manager
    manager = current_manager()
    scene, focus = None, False
    if manager:
        scenes = manager.get_service('scenes')
        timer = manager.get_service('focus')
        if scenes:
            scene = manager.invoke(scenes.api, scenes.status).get('active')
        if timer:
            focus = manager.invoke(timer.api, timer.status).get('running', False)
    if scene == 'sleep' or presence['state'] == 'asleep':
        return 'sleep'
    if scene in {'study', 'exam'} or focus:
        return 'study'
    return 'class' if scene == 'class' or presence['state'] == 'in_class' and presence.get('in_class', True) else 'free'


def refresh_policy(now, context, *, force=False):
    with lock:
        _refresh_policy(now, context, force=force)


def _refresh_policy(now, context, *, force=False):
    global _policy_at, _policy_context
    if not force and context == _policy_context and now.timestamp() - _policy_at < 45:
        return
    try:
        service, device, _ = phone._device()
        caps = phone.capabilities(service, device)
        if 'notification_snooze' not in caps:
            return
        _watch_policy_changes()
        _start_policy_worker(service)
        from services.mind.graph_sources import priority_packages
        vip, urgent = priority_packages(caps.get('vip', [])), caps.get('urgent', [])
        blocked = triage.store().blocked(device['id'], context, now, vip=vip, urgent=urgent) if context in triage.BUSY else []
        until = now.timestamp() + 90
        if context == 'study':
            from services.plugin_runtime import current_manager
            manager = current_manager()
            focus = manager.get_service('focus') if manager else None
            if focus:
                state = manager.invoke(focus.api, focus.status)
                if state.get('running') and state.get('remaining_s', 0) > 0:
                    until = min(until, now.timestamp() + state['remaining_s'])
        phone.send('triage_policy', dict(situation=context, until=until,
                   vip=vip, urgent=urgent, blocked=blocked, snooze=caps.get('notification_snooze') is True), ttl=90)
        _policy_at, _policy_context = now.timestamp(), context
    except (ValueError, OSError):
        pass


async def tick(now=None):
    global _last_arrival
    now = now or datetime.now()
    snapshot = await asyncio.to_thread(engine.current, now)
    context = await asyncio.to_thread(situation, now, snapshot)
    data = triage.store()
    await asyncio.to_thread(data.context, context, now)
    await asyncio.to_thread(data.decay, now)
    await asyncio.to_thread(refresh_policy, now, context)
    for alert in await asyncio.to_thread(data.alerts, now):
        if context == 'sleep' and not alert['urgent']:
            continue
        text = f'Priority {triage.bucket(alert["category"])} notification from {alert["package"]}. Reason: a call, alarm or an app on your VIP/urgent list.'
        if await delivery.submit(text, 'notification_vip', now, urgent=True, key=alert['device'] + ':' + alert['id']):
            await asyncio.to_thread(data.alerted, alert['device'], alert['id'])
    from services.plugin_runtime import current_manager
    manager = current_manager()
    scenes = manager.get_service('scenes') if manager else None
    if scenes and hasattr(scenes, 'presence'):
        scenes.api._active()
        scenes.presence.read_current = engine.current
        if hasattr(scenes.presence, 'retry_phone_restores'):
            await asyncio.to_thread(scenes.presence.retry_phone_restores)
        await asyncio.to_thread(scenes.presence.tick, now, snapshot)
        await scenes.presence.drain(now)
    edge = snapshot.get('transition')
    key = (snapshot.get('device'), edge.get('id')) if edge else None
    # First observation is a baseline, never an invented arrival after restart.
    if _last_arrival is None:
        _last_arrival = key or ('baseline',)
    elif key and key != _last_arrival:
        _last_arrival = key
        if edge['event'] == 'arrive' and edge['place'] in {'home', 'college'} and context == 'free' and snapshot['confidence'] >= .6:
            if key not in _greeted:
                _greeted.add(key)
                if len(_greeted) > 256:
                    _greeted.clear(); _greeted.add(key)
                text = 'Welcome home.' if edge['place'] == 'home' else 'You appear to have reached college. Welcome back.'
                if await delivery.submit(text, 'presence_greeting', now, key='arrival:' + ':'.join(key)):
                    from services.event_bus import event_bus
                    event_bus.publish('mood.set', dict(mood='happy', duration_s=5, priority=0, message='Welcome back'), plugin_id='presence')
    if context == 'free':
        for digest in await asyncio.to_thread(data.digests, now):
            counts = ', '.join(f'{number} {category}' for category, number in sorted(digest['counts'].items()))
            text = f'While you were focused: {digest["total"]} notifications — {counts}. Reason: the focus or class window ended.'
            if await delivery.submit(text, 'notification_digest', now, key='digest:' + str(digest['id'])):
                await asyncio.to_thread(data.delivered, digest['id'])
        from .anticipation import observed_candidates
        try:
            candidates = await asyncio.to_thread(observed_candidates, now, snapshot)
        except (ValueError, OSError):
            candidates = []
        for candidate in candidates:
            if candidate.get('preparation'):
                await delivery.submit(candidate['text'], 'presence_anticipation', now, key=candidate['key'], local_only=True)
            else:
                await delivery.submit(candidate['text'], 'presence_anticipation', now, key=candidate['key'])


def forget(device, path=None):
    global _last_arrival, _policy_at, _policy_context
    engine.engine.reset(device)
    triage.store(path).forget(device)
    from services.plugin_runtime import current_manager
    manager = current_manager()
    scenes = manager.get_service('scenes') if manager else None
    if scenes and hasattr(scenes, 'presence') and hasattr(scenes.presence, 'forget'):
        manager.invoke(scenes.api, scenes.presence.forget, device)
    with lock:
        _last_arrival, _policy_at, _policy_context = None, 0, None
        _greeted.clear()
