"""Bounded remote-safe SSE projections; every connection retains P0 fencing."""
import asyncio
import json
import time

from fastapi.responses import StreamingResponse

from .commands import fields
from .security import Denied

TOPICS = {
    'mood.changed': ('mood', 'expires_at', 'sticky'),
    'schedule.class_soon': ('subject', 'faculty', 'starts_at', 'room', 'minutes', 'date'),
    'schedule.due_soon': ('title', 'item_id', 'kind', 'due_at', 'hours', 'subject'),
    'focus.started': ('minutes', 'remaining_s'),
    'focus.paused': ('remaining_s',), 'focus.done': ('minutes',),
    'friday.notice': ('title', 'text'),
}


def frame(topic, payload):
    return f'event: {topic}\ndata: {json.dumps(payload, ensure_ascii=False, allow_nan=False)}\n\n'


async def authorize(service, auth, name):
    entry = service.registry.get(name)
    device = await asyncio.to_thread(service.pairing.get, auth['device']['id'])
    if entry.risk != 'safe' or entry.risk not in device['scopes']:
        raise Denied('command_blocked')
    await asyncio.to_thread(service.check, auth['epoch'], auth['device'])


def event_response(service, request):
    auth = request.state.remote_auth

    async def stream():
        from services.plugin_runtime import current_manager
        from services.friday_island_server import events as notices
        from .panel import plugin_state
        manager = current_manager()
        pending = asyncio.Queue(maxsize=40)
        loop = asyncio.get_running_loop()
        subscription = None
        notice_cursor = notices.snapshot()['last']

        def enqueue(event):
            if pending.full():
                pending.get_nowait()
            pending.put_nowait(event)

        def receive(event):
            if event['topic'] in TOPICS:
                try:
                    loop.call_soon_threadsafe(enqueue, event)
                except RuntimeError:
                    pass

        try:
            if manager:
                subscription = manager.bus.subscribe('*', receive, plugin_id='remote-pwa', allow_remote=True)
            # Short connections bound gate revalidation and refresh using new signed requests.
            until = time.monotonic() + 25
            while time.monotonic() < until and not await request.is_disconnected():
                await authorize(service, auth, 'events')
                yield ': connected\n\n'
                try:
                    event = await asyncio.wait_for(pending.get(), 2)
                    await authorize(service, auth, 'events')
                    payload = {key: value for key, value in event['payload'].items()
                               if key in TOPICS[event['topic']] and isinstance(value, (str, int, float, bool, type(None)))}
                    yield frame(event['topic'], payload)
                except TimeoutError:
                    try:
                        focus = await asyncio.to_thread(plugin_state, 'focus', 'status')
                    except Exception:
                        focus = None
                    service.check_epoch(auth['epoch'], auth['device'])
                    yield frame('focus.tick', {key: value for key, value in (focus or {}).items()
                                             if key in {'state', 'running', 'remaining_s', 'end_at'}})
                updates = notices.snapshot(notice_cursor)
                notice_cursor = updates['last']
                for row in updates['events']:
                    # Only public non-transient notifications; never display chat/question events.
                    if row['kind'] == 'notification' and not row.get('transient'):
                        await authorize(service, auth, 'events')
                        yield frame('friday.notice', {key: row[key] for key in ('title', 'text')})
        except (Denied, OSError):
            return
        finally:
            if subscription:
                await asyncio.to_thread(manager.bus.unsubscribe, subscription)

    return StreamingResponse(stream(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})


def chat_response(service, request):
    auth = request.state.remote_auth
    fields(auth['body'], ('command', 'args'))
    if auth['body']['command'] != 'ask':
        raise Denied('command_blocked')
    entry = service.registry.get('ask')
    if entry.risk != 'safe':
        raise Denied('command_blocked')
    entry.validate(auth['body']['args'])

    async def stream():
        task = asyncio.create_task(service.command(auth['device'], auth['body'], auth['epoch']))
        try:
            # The existing failover pipeline returns a complete answer, not provider tokens.
            while not task.done():
                await authorize(service, auth, 'ask')
                yield ': thinking\n\n'
                await asyncio.wait({task}, timeout=1)
            result = await task
            await authorize(service, auth, 'ask')
            if result['result'] != 'completed':
                raise Denied('conversation_refused')
            yield frame('reply', {'text': result['data']['text']})
            yield frame('done', {})
        except (Denied, OSError):
            yield frame('refused', {})
        except Exception:
            yield frame('refused', {})
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(stream(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})
