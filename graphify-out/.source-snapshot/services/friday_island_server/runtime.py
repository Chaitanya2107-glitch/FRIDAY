"""Authenticated Island requests reuse the full FRIDAY runtime and its policies."""
from contextlib import contextmanager
import asyncio
import secrets
import time


@contextmanager
def local_turn():
    from services.automation.intent import remote_request, telegram_owner, skip_confirmation
    from services.screen_watch.commands import local_request
    tokens = [(var, var.set(value)) for var, value in
              [(remote_request, False), (telegram_owner, False),
               (skip_confirmation, False), (local_request, True)]]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


class FridayRuntime:
    def __init__(self):
        self.command_lock = asyncio.Lock()
        self.keyboards = {}
        self.epoch = secrets.token_hex(12)

    def pending(self):
        from services.automation.intent import is_awaiting_confirmation
        with local_turn():
            return is_awaiting_confirmation()

    async def command(self, text, owner, target=None):
        from interfaces.api.routes import chat
        from services.friday_island_server.desktop_link import desktop
        async with self.command_lock:
            with local_turn():
                state = desktop.snapshot()
                command_id = None
                try:
                    if state.get('connected'):
                        command_id = desktop.enqueue('typed', text)
                        deadline = time.monotonic() + 3
                        while not desktop.acknowledged(command_id):
                            if time.monotonic() >= deadline:
                                raise ValueError('Desktop did not confirm readiness. The assistant command was not run.')
                            await asyncio.sleep(.025)
                        state = desktop.snapshot()
                    if state.get('listening'):
                        from interfaces.api.routes.voice import stop_listening
                        await stop_listening(discard=True)
                    result = await chat.chat(chat.ChatRequest(message=text,
                        provider=state.get('provider'),
                        speak=bool(state.get('speak_typed') or state.get('conversation'))))
                finally:
                    if command_id:
                        desktop.cancel_pending(command_id)
                    try:
                        if command_id and desktop.snapshot().get('connected'):
                            desktop.enqueue('typed_done')
                    except ValueError:
                        pass  # Completion signalling must not mask an already executed command.
                data = result.model_dump()
                steps = data.pop('keyboard', [])
                data.update(text=result.response, ok=result.action_success is not False)
                if steps:
                    data['private'] = True  # Typing requests must not enter the Island transcript.
                    if not target or not target.get('hwnd') or not target.get('pid'):
                        data.update(ok=False, text='Typing requires the original desktop window. Summon Island with a hotkey and try again.')
                    else:
                        token = secrets.token_hex(24)
                        self.keyboards = {key: value for key, value in self.keyboards.items() if value['expires'] > time.monotonic()}
                        if len(self.keyboards) >= 16:
                            raise ValueError('Too many pending typing results')
                        self.keyboards[token] = dict(owner=owner, target=target, steps=steps, expires=time.monotonic() + 30)
                        data['keyboard_token'] = token
                return data

    async def apply_keyboard(self, token, owner):
        item = self.keyboards.get(token)
        if not item or item['owner'] is not owner:
            raise ValueError('Typing result expired or belongs to another connection')
        self.keyboards.pop(token)
        if item['expires'] < time.monotonic():
            raise ValueError('Typing result expired; repeat the command')
        from services.automation import keyboard
        await asyncio.to_thread(self._type, item, keyboard.run_steps)
        return {'ok': True, 'text': 'Typed into your original window.'}

    @staticmethod
    def _type(item, run):
        import win32gui
        import win32process
        import psutil
        target = item['target']
        hwnd = win32gui.GetForegroundWindow()
        pid = win32process.GetWindowThreadProcessId(hwnd)[1] if hwnd else 0
        if hwnd != target['hwnd'] or pid != target['pid'] or psutil.Process(pid).create_time() > item['target']['captured_at']:
            raise ValueError('Your active window changed. No text was typed.')
        run(item['steps'])

    def disconnect(self, owner):
        self.keyboards = {key: item for key, item in self.keyboards.items() if item['owner'] is not owner}

    async def action(self, action, value=''):
        from .desktop_link import desktop
        from services.mind.cognition import cognition
        with local_turn(), cognition.operation('feature_request', 'island', 'Local Island control') as operation:
            if action == 'speech_stop':
                from services.voice.tts import tts
                tts.stop()
            elif action == 'voice_stop':
                from interfaces.api.routes.voice import stop_listening
                await stop_listening(discard=False)
            elif action == 'automation_stop':
                from services.browser.service import automation
                from services.computer.agent import computer_agent
                from services.automation.intent import cancel_pending_confirmation
                from core.config import config
                await automation.handle('browser stop', config.ACTIVE_PROVIDER)
                computer_agent.cancel()
                cancel_pending_confirmation()
            elif action == 'history_clear':
                from interfaces.api.routes.chat import clear_history
                async with self.command_lock:
                    await clear_history()
            elif action == 'provider':
                if value not in {'', 'openrouter', 'anthropic', 'openai', 'ollama'}:
                    raise ValueError('Unknown provider')
                desktop.enqueue(action, value)
            elif action == 'notification':
                from urllib.parse import urlsplit, parse_qs
                from services.proactive.buttons import respond
                url = urlsplit(value)
                query = parse_qs(url.query)
                if url.scheme != 'friday' or set(query) != {'token', 'answer'}:
                    raise ValueError('Invalid notification action')
                reply = await asyncio.to_thread(respond, query['token'][0], query['answer'][0])
                operation.finish('completed')
                return {'ok': True, 'text': reply}
            else:
                desktop.enqueue(action, value)
            operation.finish('completed')
        return {'ok': True, 'text': 'Requested. Live status shows the resulting state.'}

    async def snapshot(self, since=None):
        from interfaces.api.routes import body, chat, system
        from .desktop_link import desktop
        from .events import snapshot
        from core.config import config
        from services import body_state
        with local_turn():
            automation = await chat.automation_status()
            automation['response'] = automation.get('response', '')[:12000]
            return {'backend': True, 'epoch': self.epoch,
                    'body': await body.body(since=body_state.last_id()), 'system': (await asyncio.to_thread(system.get_runtime_status)).model_dump(),
                    'desktop': desktop.snapshot(), 'automation': automation,
                    'provider': config.ACTIVE_PROVIDER, **snapshot(since)}

    async def history(self):
        from interfaces.api.routes.chat import get_history
        with local_turn():
            items = await get_history(limit=6)
            return {'items': [{'role': row['role'], 'content': row['content'][:1800]} for row in items]}
