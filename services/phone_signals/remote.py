"""Allowlisted native-phone capabilities, using the existing P0 execution fence."""
import sqlite3
from . import schema
from .store import PhoneStore
from services.remote.commands import no_args


def store(service):
    return PhoneStore(service.directory.parent / 'phone' / 'phone_events.db', clock=service.clock)


def receive(service, device, args):
    acknowledged, inserted = store(service).ingest(device['id'], args['events'], args['generation'])
    from services.presence.triage import store as triage_store
    from services.presence.phone import capabilities
    from services.mind.graph_sources import priority_packages
    from datetime import datetime
    caps = capabilities(service, device)
    try:
        triage_store(service.directory.parent / 'phone' / 'triage.db').ingest(
            [dict(row, device=device['id']) for row in inserted], datetime.fromtimestamp(service.clock()),
            vip=priority_packages(caps.get('vip', [])), urgent=caps.get('urgent', []))
    except (ValueError, OSError, sqlite3.Error):
        from core.logger import logger
        logger.debug('Private notification triage deferred; source events remain stored.')
    from services.event_bus import event_bus
    for row in inserted:
        event_bus.publish('phone.event', dict(type=row['type'], time=row['timestamp']), plugin_id='phone-signals')
    return dict(acknowledged=acknowledged, stored=len(inserted))


def heartbeat(service, device, args):
    generation = store(service).heartbeat(device['id'], args)
    from services.health.watchdog import watchdog
    watchdog.handset_contact(service.clock())
    return dict(generation=generation)


def status(service, device, args):
    return store(service).status(device['id'])


def forget(service, device, args):
    from services.mind import phone_patterns
    with phone_patterns.lock:
        generation = store(service).forget(device['id'])
        phone_patterns.forget(device['id'])
    from services.remote.phone_handoff import store as transport_store
    from services.remote.phone_files import PhoneFiles
    from services.automation.clipboard_history import clipboard_history
    PhoneFiles(service, transport_store(service)).forget(device['id'])
    transport_store(service).forget(device['id'])
    clipboard_history.forget_phone(device['id'])
    from services.presence.runtime import forget as forget_presence
    forget_presence(device['id'], service.directory.parent / 'phone' / 'triage.db')
    from services.mind import care, goals
    care.forget_phone(device['id'])
    goals.forget_phone(device['id'])
    with service.lock:
        pending = getattr(service, '_phone_link', None)
        if pending and pending['device'] == device['id']:
            service._phone_link = None
    return dict(forgotten=True, generation=generation)


def timeline(service, device, args):
    from datetime import datetime
    from services.activity.timeline import segments
    from services.activity.attention import where_is_attention
    now = datetime.now()
    return dict(day=now.date().isoformat(), segments=segments(now.replace(hour=0, minute=0, second=0, microsecond=0), now,
                path=service.directory.parent / 'phone' / 'phone_events.db'), attention=where_is_attention(now))


def register(registry):
    registry.register('timeline', timeline, risk='safe', validate=no_args)
    for name, handler, validator, risk in (
        ('phone_events', receive, schema.events, 'safe'), ('phone_heartbeat', heartbeat, schema.heartbeat, 'safe'),
        ('phone_status', status, no_args, 'safe'), ('phone_forget', forget, no_args, 'confirm'),
    ):
        registry.register(name, handler, risk=risk, validate=validator, scope='phone_data')


def router(service):
    from fastapi import APIRouter, Request
    from fastapi.responses import JSONResponse
    from services.remote.routes import refused
    routes = APIRouter(prefix='/phone', include_in_schema=False)

    async def handle(request, name):
        auth, audit = request.state.remote_auth, request.state.remote_audit
        try:
            entry = service.registry.get(name)
            audit.update(command=name, risk=entry.risk)
            result = await service.command(auth['device'], dict(command=name, args=auth['body']), auth['epoch'])
            audit['result'] = result['result']
            return JSONResponse(result['data'])
        except Exception:
            audit['result'] = 'refused'
            return refused()

    @routes.post('/events')
    async def events(request: Request):
        return await handle(request, 'phone_events')

    @routes.post('/heartbeat')
    async def beat(request: Request):
        return await handle(request, 'phone_heartbeat')

    @routes.get('/status')
    async def phone_status(request: Request):
        return await handle(request, 'phone_status')

    return routes
