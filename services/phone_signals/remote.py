"""Allowlisted native-phone capabilities, using the existing P0 execution fence."""
from . import schema
from .store import PhoneStore
from services.remote.commands import no_args


def store(service):
    return PhoneStore(service.directory.parent / 'phone' / 'phone_events.db', clock=service.clock)


def receive(service, device, args):
    acknowledged, inserted = store(service).ingest(device['id'], args['events'], args['generation'])
    from services.event_bus import event_bus
    for row in inserted:
        event_bus.publish('phone.event', dict(type=row['type'], time=row['timestamp']), plugin_id='phone-signals')
    return dict(acknowledged=acknowledged, stored=len(inserted))


def heartbeat(service, device, args):
    return dict(generation=store(service).heartbeat(device['id'], args))


def status(service, device, args):
    return store(service).status(device['id'])


def forget(service, device, args):
    return dict(forgotten=True, generation=store(service).forget(device['id']))


def register(registry):
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
