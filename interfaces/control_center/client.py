"""Local API requests; desktop toggles use the existing authenticated controller."""
import json
import time
import uuid

from interfaces.tray import backend

Error = backend.BackendError


class Client:
    def request(self, method, path, *, timeout=8, **kwargs):
        return backend._request(method, path, timeout=timeout, trust_env=False, **kwargs)

    def chat(self, message: str, provider=None, speak=False) -> dict:
        if not message.strip() or len(message) > 4000 or '\x00' in message:
            raise Error('Enter a message of 1–4000 characters without null bytes.')
        from services.voice.conversation import match_conversation
        conversation = match_conversation(message)
        if conversation:
            state = self.desktop_state()
            if not state.get('connected'):
                raise Error('Start FRIDAY desktop to use conversation mode.')
            if bool(state.get('conversation')) != (conversation == 'start'):
                self.control('conversation')
            return {'response': 'Conversation mode requested. Live status shows the resulting state.',
                    'awaiting_reply': False}
        try:
            state = self.desktop_state()
        except Error:
            state = {}  # Plain REST chat also supports a backend without the desktop bridge.
        if state.get('connected') and any(state.get(key) for key in ('listening', 'conversation', 'wake')):
            raise Error('Voice input is active. Turn off listening, Hey Friday and conversation in Tools & controls before sending typed chat here, or use the existing command bar (Ctrl+Shift+F).')
        return self.request('POST', '/api/v1/chat', timeout=120,
                            json={'message': message, 'provider': provider, 'speak': speak})

    def history(self):
        return self.request('GET', '/api/v1/history', params={'limit': 30})

    def clear_history(self):
        return self.request('DELETE', '/api/v1/history')

    def snapshot(self):
        try:
            health = self.request('GET', '/health', timeout=2)
            if not isinstance(health, dict) or health.get('service') != 'F.R.I.D.A.Y':
                raise Error('Another service answered at FRIDAY’s configured address.')
        except Error as error:
            return {'online': False, 'error': str(error)}
        state = {'online': True, 'health': health, 'errors': {}}
        for key, path in (('providers', '/providers'), ('system', '/system/status'),
                          ('stats', '/system/stats'), ('files', '/files/status'),
                          ('automation', '/automation/status')):
            try:
                state[key] = self.request('GET', '/api/v1' + path, timeout=2)
            except Error as error:
                state['errors'][key] = str(error)
        try:
            state['desktop'] = self.desktop_state()
        except Error as error:
            state['errors']['desktop'] = str(error)
        return state

    @staticmethod
    def _connection():
        # Read the token without creating, migrating or repairing owner settings.
        from services.friday_island_server.config import config_path, IslandConfig
        path = config_path()
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise Error('Start FRIDAY desktop to enable its voice and lifecycle controls.')
        return IslandConfig.model_validate_json(path.read_text(encoding='utf-8-sig')).connection

    def _desktop(self, action=None, value=''):
        try:
            from websockets.sync.client import connect
            connection = self._connection()
            # A native client of the same token-authenticated loopback bridge.
            with connect(f'ws://127.0.0.1:{connection.port}', origin='tauri://localhost',
                         open_timeout=2, close_timeout=1, max_size=1024 * 1024,
                         proxy=None) as socket:
                socket.send(json.dumps({'v': 1, 'type': 'handshake', 'id': 'hello', 'token': connection.token}))
                reply = json.loads(socket.recv(timeout=3))
                if reply.get('type') != 'handshake' or not reply.get('ok'):
                    raise Error('FRIDAY desktop authentication failed. Start FRIDAY and refresh.')
                request_id = uuid.uuid4().hex
                if action:
                    socket.send(json.dumps({'v': 1, 'type': 'runtime_action', 'id': request_id,
                                            'action': action, 'value': value}))
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    reply = json.loads(socket.recv(timeout=max(.01, deadline - time.monotonic())))
                    if action and reply.get('id') == request_id:
                        if reply.get('type') == 'error' or reply.get('ok') is False:
                            raise Error(reply.get('text') or 'Desktop control was refused.')
                        return reply
                    if not action and reply.get('type') == 'runtime_state':
                        return reply.get('desktop', {})
                raise Error('Desktop did not answer. Refresh status before trying again.')
        except Error:
            raise
        except Exception as error:
            raise Error('Desktop controls are unavailable. Start FRIDAY desktop and refresh.') from error

    def desktop_state(self):
        return self._desktop()

    def control(self, action, value=''):
        if action not in {'listen', 'wake', 'conversation', 'speech', 'speak_typed', 'body',
                          'controls', 'start', 'stop', 'restart', 'speech_stop', 'voice_stop',
                          'automation_stop'}:
            raise Error('Unknown desktop control.')
        return self._desktop(action, value)
