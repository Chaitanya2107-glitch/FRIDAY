"""All new routes retain the P0 gate and have explicit allowlisted capabilities."""
import asyncio
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .commands import fields, no_args, text_args
from .security import Denied, key_id
from .transport_store import QUEUABLE, expiry, identifier
from . import phone_approvals, phone_files, phone_handoff


def queue_args(args):
    fields(args, ('id', 'created', 'expires_at', 'command'), ('args',))
    identifier(args['id'])
    if not isinstance(args['command'], str) or args['command'] not in QUEUABLE or not isinstance(args.get('args', {}), dict):
        raise Denied('queue_risk_refused')
    return dict(args)


def ack_args(args):
    fields(args, ('ids',))
    if not isinstance(args['ids'], list) or not 1 <= len(args['ids']) <= 10:
        raise Denied('invalid_ack')
    for identity in args['ids']:
        identifier(identity)
    return dict(args)


def dedicated(service, device, args):
    raise Denied('dedicated_route_required')


def inbox(service, device, args):
    from services.mind import care_safeguard
    messages = phone_handoff.store(service).inbox(device['id'])
    if care_safeguard.active(service.clock()):
        messages = [row for row in messages if not (row['type'] in {'notice', 'text'} and
                    row['payload'].get('kind') in care_safeguard.AUTOMATIC_NOTICE_KINDS)]
    return dict(messages=messages)


def ack(service, device, args):
    return phone_handoff.store(service).ack(device['id'], args['ids'])


def files(service):
    return phone_files.PhoneFiles(service, phone_handoff.store(service))


def register(registry):
    registry.register('queue', dedicated, risk='safe', validate=queue_args)
    registry.register('ring_laptop', phone_handoff.ring_laptop, risk='safe', validate=no_args)
    registry.register('phone_info', phone_handoff.info, risk='safe', validate=no_args)
    for name, handler, validator in (
        ('phone_inbox', inbox, no_args), ('phone_ack', ack, ack_args),
        ('phone_handoff', phone_handoff.receive, text_args('text', 4000)),
        ('phone_file_begin', lambda s, d, a: files(s).begin(d['id'], a), phone_files.begin_args),
        ('phone_file_chunk', lambda s, d, a: files(s).chunk(d['id'], a), phone_files.chunk_args),
        ('phone_file_finish', lambda s, d, a: files(s).finish(d['id'], a), phone_files.finish_args),
        ('phone_file_read', lambda s, d, a: files(s).read(d['id'], a), phone_files.read_args),
        ('phone_approval_enroll', dedicated, phone_approvals.key_args),
        ('phone_approval_key', phone_approvals.key_status, no_args),
        ('phone_approval_result', phone_approvals.resolve, phone_approvals.result_args),
    ):
        registry.register(name, handler, risk='safe', validate=validator, scope='phone_data')


async def queued(service, device, body, epoch):
    body = queue_args(body)
    entry = service.registry.get(body['command'])
    if entry.risk != 'safe':
        raise Denied('queue_risk_refused')
    await asyncio.to_thread(service.authorize_entry, device, entry)
    expiry(body['created'], body['expires_at'], service.clock())
    args = await asyncio.to_thread(entry.validate, body.get('args', {}))
    await asyncio.to_thread(service.check, epoch, device)
    data = phone_handoff.store(service)
    old = await asyncio.to_thread(data.claim, device['id'], body)
    if old is not None:
        return old
    # Persist running before the effect. A crash can lose an action, never repeat it.
    result = await asyncio.to_thread(service.run_effect, device, body['command'], args, epoch,
                                     expires_at=body['expires_at'])
    succeeded = not isinstance(result, dict) or result.get('ok', True) is not False
    answer = dict(result='completed' if succeeded else 'refused', data=result)
    await asyncio.to_thread(data.finish, device['id'], body['id'], answer)
    return answer


def router(service):
    from .routes import refused
    routes = APIRouter(include_in_schema=False)

    async def authorize(request, name):
        auth = request.state.remote_auth
        entry = service.registry.get(name)
        if entry.risk != 'safe':
            raise Denied('command_blocked')
        request.state.remote_audit.update(command=name, risk=entry.risk)
        await asyncio.to_thread(service.authorize_entry, auth['device'], entry)
        args = await asyncio.to_thread(entry.validate, auth['body'])
        await asyncio.to_thread(service.check, auth['epoch'], auth['device'])
        return auth, args

    async def handle(request, name):
        try:
            auth, args = await authorize(request, name)
            value = await service.command(auth['device'], dict(command=name, args=args), auth['epoch'])
            request.state.remote_audit['result'] = value['result']
            return JSONResponse(value['data'])
        except Exception:
            return refused()

    @routes.post('/queue')
    async def queue(request: Request):
        try:
            auth, args = await authorize(request, 'queue')
            value = await queued(service, auth['device'], args, auth['epoch'])
            request.state.remote_audit.update(command=args['command'], result=value['result'])
            return JSONResponse(value)
        except Exception:
            return refused()

    @routes.get('/phone/inbox')
    async def poll(request: Request):
        try:
            auth, _ = await authorize(request, 'phone_inbox')
            deadline, checked = time.monotonic() + 30, time.monotonic()
            while True:
                service.check_epoch(auth['epoch'], auth['device'])
                await asyncio.to_thread(service.authorize_entry, auth['device'], service.registry.get('phone_inbox'))
                if time.monotonic() - checked >= 5:
                    await asyncio.to_thread(service.check, auth['epoch'], auth['device'])
                    checked = time.monotonic()
                messages = (await asyncio.to_thread(inbox, service, auth['device'], {}))['messages']
                if messages or time.monotonic() >= deadline:
                    service.check_epoch(auth['epoch'], auth['device'])
                    request.state.remote_audit['result'] = 'polled'
                    return JSONResponse(dict(messages=messages))
                if await request.is_disconnected():
                    return refused()
                await asyncio.sleep(.5)
        except Exception:
            return refused()

    @routes.post('/phone/approval/enroll')
    async def enroll(request: Request):
        try:
            auth, args = await authorize(request, 'phone_approval_enroll')
            device, epoch = auth['device'], auth['epoch']
            public = args['public_key']
            fingerprint = key_id(public)
            async def consent():
                try:
                    accepted = await asyncio.to_thread(service.confirm,
                        f'Allow {device["name"]} to approve laptop actions with its biometric key?\n'
                        f'Key fingerprint: {fingerprint}\nThe phone approval setting remains off until you enable it locally.')
                    await asyncio.to_thread(service.check, epoch, device)
                    def finish():
                        with service.effects:
                            service.check(epoch, device)
                            service.authorize_entry(device, service.registry.get('phone_approval_enroll'))
                            if accepted:
                                with phone_handoff.store(service).db() as db:
                                    db.execute('UPDATE phone_approvals SET consumed=1 WHERE device=?', (device['id'],))
                                    db.execute("DELETE FROM outbox WHERE device=? AND type='approval'", (device['id'],))
                                    db.execute('INSERT OR REPLACE INTO approval_keys VALUES (?,?)', (device['id'], public))
                            service.audit.write(device=device['id'], command='phone_approval_enroll',
                                                risk='confirm', result='accepted' if accepted else 'denied')
                    await asyncio.to_thread(finish)
                except (Denied, OSError):
                    pass
            task = asyncio.create_task(consent())
            service.pair_tasks.add(task); task.add_done_callback(service.pair_tasks.discard)
            request.state.remote_audit['result'] = 'awaiting_laptop'
            return JSONResponse(dict(state='awaiting_laptop', key_id=fingerprint))
        except Exception:
            return refused()

    @routes.get('/phone/info')
    async def info(request: Request):
        return await handle(request, 'phone_info')

    @routes.post('/phone/ack')
    async def acknowledge(request: Request):
        return await handle(request, 'phone_ack')

    @routes.post('/phone/handoff')
    async def handoff(request: Request):
        return await handle(request, 'phone_handoff')

    @routes.get('/phone/approval/key')
    async def approval_key(request: Request):
        return await handle(request, 'phone_approval_key')

    @routes.post('/phone/approval/result')
    async def approval_result(request: Request):
        return await handle(request, 'phone_approval_result')

    @routes.post('/phone/file/begin')
    async def begin(request: Request):
        return await handle(request, 'phone_file_begin')

    @routes.post('/phone/file/chunk')
    async def chunk(request: Request):
        return await handle(request, 'phone_file_chunk')

    @routes.post('/phone/file/finish')
    async def finish(request: Request):
        return await handle(request, 'phone_file_finish')

    @routes.post('/phone/file/read')
    async def read(request: Request):
        return await handle(request, 'phone_file_read')

    return routes
