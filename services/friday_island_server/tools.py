"""Private, on-demand Island tools over the existing desktop services."""
import asyncio
import secrets


class DesktopTools:
    def __init__(self):
        self.clipboards = {}
        self.predictions = {}
        self.private_pending = set()
        self.files = {}

    async def request(self, owner, action, item='', value=''):
        from interfaces.api.routes import clipboard, files
        if action == 'features':
            from dataclasses import asdict
            from interfaces.control_center.catalog import CAPABILITIES
            return {'items': [asdict(capability) for capability in CAPABILITIES]}
        if action == 'guide':
            from interfaces.control_center.catalog import read_guide
            return {'text': await asyncio.to_thread(read_guide, value)}
        if action == 'plugins':
            from services.plugin_runtime import current_manager
            manager = current_manager()
            rows = await asyncio.to_thread(manager.list_plugins) if manager else []
            return {'items': [{key: row[key] for key in ('id', 'name', 'description', 'enabled', 'status', 'commands')}
                              for row in rows]}
        if action == 'read':
            from services.automation import routines, system_stats
            history, status, stats, names = await asyncio.gather(clipboard.get_clipboard_history(),
                files.file_search_status(), asyncio.to_thread(system_stats.menu_lines),
                asyncio.to_thread(routines.load), return_exceptions=True)
            warnings = [label + ' unavailable. Retry after checking its settings.' for label, result in
                        [('Clipboard history', history), ('File index', status), ('System stats', stats), ('Routines', names)]
                        if isinstance(result, Exception)]
            history = [] if isinstance(history, Exception) else history.items[:20]
            entries = {secrets.token_hex(12): text for text in history}
            self.clipboards[owner] = entries
            return {'clipboard': [{'id': key, 'text': text} for key, text in entries.items()],
                    'files': None if isinstance(status, Exception) else status,
                    'stats': [] if isinstance(stats, Exception) else stats,
                    'routines': [] if isinstance(names, Exception) else list(names), 'warnings': warnings}
        if action == 'clipboard_copy':
            from services.automation.clipboard import set_text
            text = self.clipboards.get(owner, {}).get(item)
            if text is None:
                raise ValueError('Clipboard entry expired. Refresh the tools.')
            await asyncio.to_thread(set_text, text)
            return {'ok': True, 'text': 'Copied back to the clipboard.'}
        if action == 'clipboard_clear':
            result = await clipboard.clear_clipboard_history()
            self.clipboards.clear()
            return {'ok': True, 'text': result['message']}
        if action == 'files_rescan':
            result = await files.rescan_files()
            return {'ok': True, 'text': result['message']}
        if action == 'files_search' and value.strip():
            from services.files import assistant
            self.files.pop(owner, None)
            try:
                hits, search_id = await asyncio.to_thread(assistant.search_results, value.strip())
            except assistant.AutomationError as error:
                return {'ok': False, 'text': str(error)}
            entries = {}
            results = []
            for index, hit in enumerate(hits[:100], 1):
                key = secrets.token_hex(12)
                entries[key] = (index, search_id)
                results.append({'id': key, 'name': hit.name, 'path': hit.path})
            self.files[owner] = entries
            return {'results': results}
        if action in {'files_open', 'files_reveal'}:
            from services.files import assistant
            entry = self.files.get(owner, {}).get(item)
            if entry is None:
                return {'ok': False, 'text': 'File entry expired. Search again.'}
            index, search_id = entry
            handler = assistant.open_result if action == 'files_open' else assistant.reveal_result
            try:
                return {'ok': True, 'text': await asyncio.to_thread(handler, index, search_id=search_id)}
            except assistant.AutomationError as error:
                return {'ok': False, 'text': str(error)}
        if action == 'close':
            self.clipboards.pop(owner, None)
            self.files.pop(owner, None)
            return {'ok': True}
        raise ValueError('Unknown Island tool')

    async def suggestions(self, owner):
        from interfaces.api.routes.system import bar_suggestions
        items = self.predictions.get(owner)
        if items is None:
            items = (await bar_suggestions())['suggestions'][:6]
        self.predictions[owner] = items
        return [{'text': text, 'detail': 'Suggested for you', 'fill': True} for text in items]

    async def outcome(self, owner, sent=None):
        from interfaces.api.routes.system import BarOutcome, bar_outcome
        offered = self.predictions.pop(owner, [])
        if offered:
            from services.phone.commands import match_command
            if owner in self.private_pending or sent and match_command(sent):
                sent = None
            await bar_outcome(BarOutcome(offered=offered, sent=sent))

    def disconnect(self, owner):
        self.files.pop(owner, None)
        self.clipboards.pop(owner, None)
        self.predictions.pop(owner, None)
        self.private_pending.discard(owner)
