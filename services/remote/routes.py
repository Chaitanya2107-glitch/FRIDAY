"""Path-scoped boundary on the existing ASGI bridge; local routes keep their original policy."""
import json

from fastapi import APIRouter, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from .commands import fields
from .pairing import device_input
from .security import Denied
from .tailscale import loopback

MAX_BODY = 16384
AUTH_HEADERS = ('host', 'tailscale-user-login', 'x-device-id', 'x-timestamp', 'x-nonce', 'x-signature')


def remote_path(path):
    return path == '/remote' or path.startswith('/remote/')


def refused():
    return JSONResponse({'detail': 'Not Found'}, status_code=404, headers={'Cache-Control': 'no-store'})


def source_ip(headers):
    import ipaddress
    value = headers.get('x-forwarded-for', '').split(',')[-1].strip()
    try:
        address = ipaddress.ip_address(value)
        if address in ipaddress.ip_network('100.64.0.0/10') or address in ipaddress.ip_network('fd7a:115c:a1e0::/48'):
            return str(address)
    except ValueError:
        pass
    return 'local'


class BridgeSecurity:
    def __init__(self, app, *, service, allowed_hosts):
        self.app, self.service = app, service
        self.local = TrustedHostMiddleware(app, allowed_hosts=allowed_hosts)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        if remote_path(scope['path']):
            return await self.remote(scope, receive, send)
        # Serve/Funnel must never escape their /remote target into the local API.
        if any(name.lower().replace(b'_', b'-').startswith((b'tailscale-', b'x-forwarded-', b'forwarded'))
               for name, _ in scope.get('headers', [])):
            return await refused()(scope, receive, send)
        return await self.local(scope, receive, send)

    async def remote(self, scope, receive, send):
        import asyncio
        from services.automation.intent import remote_request
        from .context import remote_origin
        service, token, origin_token = self.service, None, None
        audit = dict(device='unknown', command='unknown', risk='blocked', result='refused', source='local')
        state = scope.setdefault('state', {})
        state['remote_audit'] = audit
        try:
            request = Request(scope, receive)
            audit['source'] = source_ip(request.headers)
            if (not service.registered or not scope.get('client') or not loopback(scope['client'][0])
                    or not scope.get('server') or not loopback(scope['server'][0])):
                raise Denied('non_loopback')
            if (scope.get('query_string') or scope.get('raw_path', scope['path'].encode()) != scope['path'].encode('ascii')
                    or any(part in scope['path'] for part in ('%', '\\', '//', '/./', '/../'))):
                raise Denied('ambiguous_path')
            raw_headers = scope.get('headers', [])
            for name in (*AUTH_HEADERS, 'origin', 'content-length', 'content-type'):
                count = sum(key.lower() == name.encode() for key, _ in raw_headers)
                if count > 1 or name in AUTH_HEADERS and count != 1:
                    raise Denied('ambiguous_headers')
            if any(b'_' in key for key, _ in raw_headers):
                raise Denied('ambiguous_headers')
            epoch = service.epoch
            await asyncio.to_thread(service.check, epoch)
            host = request.headers['host'].lower()
            allowed = {service.magic_dns, service.magic_dns + ':443', 'localhost',
                       f'localhost:{service.port}', '127.0.0.1', f'127.0.0.1:{service.port}'}
            if host not in allowed or request.headers['tailscale-user-login'] != service.owner_login:
                raise Denied('identity_refused')
            origin = request.headers.get('origin')
            if origin is not None and origin != 'https://' + service.magic_dns:
                raise Denied('origin_refused')
            chunks, size = [], 0
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_BODY:
                        raise Denied('body_too_large')
                    chunks.append(chunk)
            raw = b''.join(chunks)
            try:
                body = json.loads(raw) if raw else {}
                if not isinstance(body, dict):
                    raise ValueError()
            except (ValueError, RecursionError):
                raise Denied('invalid_json') from None
            identity = request.headers['x-device-id']
            pair_start = scope['path'] in {'/remote/v1/pair/begin', '/remote/v1/pair'} and 'token' in body
            if pair_start:
                await asyncio.to_thread(service.pairing.check_token, body['token'])
                device = device_input(body)
                if identity != device['id']:
                    raise Denied('device_mismatch')
            else:
                try:
                    device = await asyncio.to_thread(service.pairing.get, identity)
                except Denied:
                    if scope['path'] not in {'/remote/v1/pair', '/remote/v1/pair/status'}:
                        raise
                    device = await asyncio.to_thread(service.pairing.pending_device, identity)
            audit['device'] = device['id']
            await asyncio.to_thread(service.proofs.verify, device, scope['method'], scope['path'], raw, request.headers)
            await asyncio.to_thread(service.audit.ready)
            service.check_epoch_pending(epoch)
            state['remote_auth'] = dict(device=device, body=body, epoch=epoch)
            token = remote_request.set(True)
            origin_token = remote_origin.set(True)
            audit['result'] = 'refused'

            async def guarded_send(message):
                if message['type'] == 'http.response.start':
                    try:
                        service.check_epoch_pending(epoch)
                    except Denied:
                        message['status'] = 404
                    if message['status'] >= 400:
                        message['status'] = 404
                        state['remote_failed'] = True
                        message['headers'] = [(b'content-type', b'application/json')]
                    message['headers'].extend([(b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff')])
                if message['type'] == 'http.response.body' and state.get('remote_failed'):
                    if message.get('more_body'):
                        return
                    message['body'] = b'{"detail":"Not Found"}'
                await send(message)
            delivered = False

            async def replay_body():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return dict(type='http.request', body=raw, more_body=False)
                return await receive()
            await self.app(scope, replay_body, guarded_send)
        except (Denied, UnicodeError, OSError, TimeoutError) as error:
            audit['result'] = str(error) if isinstance(error, Denied) else 'transport_error'
            await refused()(scope, receive, send)
        finally:
            if token is not None:
                remote_request.reset(token)
            if origin_token is not None:
                remote_origin.reset(origin_token)
            try:
                await asyncio.to_thread(service.audit.write, **audit)
            except OSError:
                service.trip()
                warning = 'Remote is OFF because its local audit log could not be written.'
                if service.warning != warning:
                    service.warning = warning
                    service.notify(warning)


def create_router(service):
    router = APIRouter(prefix='/remote/v1', include_in_schema=False)

    async def handle(request, operation):
        import asyncio
        auth, audit = request.state.remote_auth, request.state.remote_audit
        device, body, epoch = auth['device'], auth['body'], auth['epoch']
        try:
            if operation == 'commands':
                entry = service.registry.get(body.get('command'))
                audit.update(command=body['command'], risk=entry.risk)
                result = await service.command(device, body, epoch)
            elif operation == 'approve':
                audit.update(command='approval', risk='confirm')
                result = await service.approve(device, body, epoch)
                audit['command'] = result['command']
            elif operation == 'status':
                fields(body)
                audit.update(command='status', risk='safe')
                await asyncio.to_thread(service.pairing.get, device['id'])
                if 'safe' not in device['scopes']:
                    raise Denied('command_blocked')
                result = service.status()
            elif operation == 'pair_begin':
                fields(body, ('token', 'public_key', 'name'))
                audit.update(command='pair_begin', risk='confirm')
                row, options = await asyncio.to_thread(service.pairing.begin, body, service.magic_dns, passkey=True)
                result = dict(device_id=row['id'], **options)
            elif operation == 'pair':
                fields(body, optional=('token', 'public_key', 'name', 'registration'))
                audit.update(command='pair', risk='confirm')
                result = await service.pair(device, body, epoch)
            else:
                fields(body)
                audit.update(command='pair_status', risk='confirm')
                try:
                    await asyncio.to_thread(service.pairing.get, device['id'])
                    phase = 'paired'
                except Denied:
                    phase = (await asyncio.to_thread(service.pairing.pending_device, device['id']))['phase']
                fingerprint = await asyncio.to_thread(service.pairing.fingerprint)
                result = dict(state=phase, device_id=device['id'], fingerprint=fingerprint)
            if operation in {'pair', 'pair_begin', 'pair_status'}:
                result['proof'] = await asyncio.to_thread(service.pairing.proof, device['id'], result.get('state', 'registration'), request.headers['x-nonce'])
            audit['result'] = result.get('result', 'completed')
            if operation not in {'pair', 'pair_begin', 'pair_status'}:
                await asyncio.to_thread(service.pairing.seen, device['id'])
            return JSONResponse(result)
        except Denied as error:
            audit['result'] = str(error)
            return refused()
        except Exception:
            audit['result'] = 'handler_failed'
            return refused()  # No private provider/OS exception text in remote responses or logs.

    @router.get('/status')
    async def status(request: Request):
        return await handle(request, 'status')

    @router.post('/commands')
    async def command(request: Request):
        return await handle(request, 'commands')

    @router.post('/approve')
    async def approve(request: Request):
        return await handle(request, 'approve')

    @router.post('/pair/begin')
    async def pair_begin(request: Request):
        return await handle(request, 'pair_begin')

    @router.post('/pair')
    async def pair(request: Request):
        return await handle(request, 'pair')

    @router.get('/pair/status')
    async def pair_status(request: Request):
        return await handle(request, 'pair_status')

    return router


def local_router(service):
    router = APIRouter()

    @router.post('/api/v1/remote/off')
    async def remote_off(request: Request):
        import asyncio
        from services.automation.intent import remote_request
        if remote_request.get() or not request.client or not loopback(request.client.host):
            return refused()
        service.trip()
        return await asyncio.to_thread(service.disable)
    return router
