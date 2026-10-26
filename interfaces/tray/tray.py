"""
interfaces/tray/tray.py

FRIDAY's system tray icon — the main way to control FRIDAY. The dot shows the
backend's state (green online, red offline, amber listening, blue while it
listens for "Hey Friday", purple in conversation mode) and the menu
exposes every feature: command bar, voice, quick actions, system stats,
clipboard history, file search, provider, memory, quit.
"""

import threading
import time
import uuid

import pystray
from PIL import Image, ImageDraw

from core.logger import logger
from interfaces.tray import backend
from services.automation import clipboard, keyboard, routines
from services.automation.system_control import AutomationError
from services.reminders.service import show_toast
from services.voice.conversation import match_conversation

POLL_SECONDS = 5
NOTIFY_LIMIT = 250  # Windows cuts notification text off around 256 characters
CLIPBOARD_MENU_ITEMS = 10
MENU_LABEL_CHARS = 45
VOICE_HOTKEY = "Ctrl+Alt+Space"
WAKE_HOTKEY = "Ctrl+Alt+H"
CONVERSATION_HOTKEY = "Ctrl+Alt+C"
CONVERSATION_SILENCES = 2  # this many listens in a row with nothing said end a conversation
TYPING_KEEPS_TALKING = 10  # seconds: a key pressed this recently means the Boss is typing, not silent
TYPED_REPLY_WAIT = 120     # seconds to wait for a typed message's reply before listening again
PROVIDERS = ("openrouter", "anthropic", "openai", "ollama")
QUICK_ACTIONS = (
    ("What's on my screen?", "what's on my screen?"),
    ("Take a screenshot", "take a screenshot"),
    ("Volume up", "turn the volume up"),
    ("Volume down", "turn the volume down"),
    ("Mute", "mute"),
    ("Unmute", "unmute"),
    ("Read my clipboard", "read my clipboard"),
    ("List reminders", "list reminders"),
)
DOT_COLORS = {
    "online": (0, 220, 140, 255),
    "offline": (220, 60, 60, 255),
    "listening": (255, 180, 0, 255),
    "wake": (60, 140, 255, 255),  # the mic is open for "Hey Friday"
    "conversation": (170, 90, 255, 255),  # conversation mode: she listens again after every reply
}


def make_icon(status: str) -> Image.Image:
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([4, 4, size - 4, size - 4], outline=(0, 255, 180, 255), width=5)
    draw.ellipse([20, 20, size - 20, size - 20], fill=DOT_COLORS[status])
    return image


def _one_line(text: str, limit: int) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[:limit - 1] + "…"


def _menu_label(text: str) -> str:
    # Windows menus treat "&" as a keyboard-shortcut marker; "&&" shows a literal "&".
    return _one_line(text, MENU_LABEL_CHARS).replace("&", "&&")


def files_status_text(status: dict) -> str:
    if not status.get("enabled", True):
        return "File search is off"
    if status.get("scanning"):
        done, total = status.get("progress") or (0, 0)
        return f"Indexing… {done}/{total} files read" if total else "Indexing… looking for files"
    return f"{status.get('files', 0):,} files indexed, {status.get('readable', 0):,} with text"


QUICK_REPLY_CHARS = 120  # a command's reply this short ("Opening Chrome.") is a confirmation, not an answer


def is_quick_command(is_command: bool, reply: str) -> bool:
    """A command's short confirmation: its notification disappears by itself. AI answers and long replies stay."""
    return is_command and len(reply) <= QUICK_REPLY_CHARS and "\n" not in reply.strip()


def _in_background(fn, *args):
    # Menu callbacks run on the tray's own thread — slow requests must not freeze the menu.
    threading.Thread(target=fn, args=args, daemon=True).start()


class FridayTray:
    def __init__(self, show_command_bar, quit_app, confirm, api=backend, typist=keyboard.run_steps,
                 ask_in_bar=lambda text: None, ask_done=lambda: None, stop_backend=None):
        """
        show_command_bar / quit_app: thread-safe callables from the command bar.
        ask_in_bar(text) / ask_done(): show FRIDAY's own question in the bar (without taking focus) / take it away.
        confirm(title, text) -> bool: asks the user a yes/no question.
        typist(steps): types a voice reply's text/keys into the focused app.
        """
        self._typist = typist
        self._show_command_bar = show_command_bar
        self._ask_in_bar, self._ask_done = ask_in_bar, ask_done
        self.talk_on = False  # "Let FRIDAY talk on her own" (services/mind/talk.py)
        self.body = None  # FRIDAY's desktop body (interfaces/body/), set by app.py
        self._asking = False  # listening for the answer to her own question
        self._quit_app = quit_app
        self._stop_backend = stop_backend
        self._confirm = confirm
        self._api = api
        self.online = False
        self.listening = False
        self._stop_requested = False  # the user pressed stop during the current listen
        self.wake_on = False  # listening for "Hey Friday" — always off at start
        self.in_conversation = False  # conversation mode (services/voice/conversation.py)
        self._typed_turn = False  # conversation mode: the Boss typed instead of talking — wait for that reply
        self._typed_done = threading.Event()
        self._wake_session = ""  # a new id each time it's switched on
        self.default_provider: str | None = None
        self.clipboard_items: list[str] = []
        self.stats_lines: list[str] = []
        self.files_line = ""
        self.runtime_status: dict | None = None
        self._stopping = threading.Event()
        self.icon = pystray.Icon(
            "friday", make_icon("offline"), "F.R.I.D.A.Y — offline", menu=self._build_menu()
        )

    @property
    def status(self) -> str:
        if not self.online:
            return "offline"
        if self.in_conversation:
            return "conversation"
        return "listening" if self.listening else "wake" if self.wake_on else "online"

    def status_text(self) -> str:
        if self.status == "offline":
            return "○  FRIDAY is offline"
        if self.status == "conversation":
            return f"◉  In conversation{' — listening' if self.listening else ''}  ({CONVERSATION_HOTKEY} to end)"
        if self.status == "listening":
            return f"◉  Listening…  ({VOICE_HOTKEY} to stop)"
        if self.status == "wake":
            return f'◉  Listening for "Hey Friday"  ({WAKE_HOTKEY} to stop)'
        provider = self._api.settings.provider or self.default_provider
        return f"●  FRIDAY is online — {provider}" if provider else "●  FRIDAY is online"

    def mode_text(self) -> str:
        name = ((self.runtime_status or {}).get('mode') or {}).get('name') if self.online else None
        return f"Mode: {name.title()}" if name else "Mode: Status unavailable"

    def _quick_action_items(self):
        Item = pystray.MenuItem
        for label, command in QUICK_ACTIONS:
            yield Item(label, self._command_action(command), enabled=lambda item: self.online)
        yield pystray.Menu.SEPARATOR
        spotify = (self.runtime_status or {}).get('spotify') or {}
        if not self.online or spotify.get('connected') is None:
            yield Item('Spotify: Status unavailable', None, enabled=False)
        elif spotify['connected']:
            yield Item('Spotify: Connected', None, enabled=False)
            yield Item('Now playing on Spotify', self._command_action("what's playing"))
            yield Item('Disconnect Spotify', self._command_action('disconnect spotify'))
        elif not spotify.get('configured'):
            yield Item('Spotify: Not configured', None, enabled=False)
        else:
            yield Item('Spotify: Not connected', None, enabled=False)
            yield Item('Connect Spotify', self._command_action('connect spotify'))

    def _build_menu(self) -> pystray.Menu:
        Item, Menu = pystray.MenuItem, pystray.Menu
        online = lambda item: self.online

        return Menu(
            Item(lambda item: self.status_text(), None, enabled=False),
            Item(lambda item: self.mode_text(), None, enabled=False),
            Menu.SEPARATOR,
            Item("Open command bar   Ctrl+Shift+F", self._show_command_bar, default=True),
            Item("Show FRIDAY's body", self.toggle_body, checked=lambda item: bool(self.body and self.body.visible),
                 visible=lambda item: self.body is not None),
            Item("Talk to FRIDAY", Menu(
                Item(lambda item: f"{'Stop' if self.listening else 'Start'} listening   {VOICE_HOTKEY}",
                     self.toggle_listening, enabled=online),
                Item(f"Conversation mode   {CONVERSATION_HOTKEY}", self.toggle_conversation,
                     checked=lambda item: self.in_conversation, enabled=online),
                Item(f'Listen for "Hey Friday"   {WAKE_HOTKEY}', self.toggle_wake,
                     checked=lambda item: self.wake_on, enabled=online),
                Item("Speak a command with Handy   Ctrl+Alt+F", None, enabled=False),  # hint: it's a hotkey only
                Item("Let FRIDAY talk on her own", self.toggle_talk,
                     checked=lambda item: self.talk_on, enabled=online),
                Menu.SEPARATOR,
                Item("Speak voice replies aloud", self.toggle_speak_replies,
                     checked=lambda item: self._api.settings.speak_replies),
                Item("Speak typed replies aloud", self.toggle_speak_typed,
                     checked=lambda item: self._api.settings.speak_typed),
            )),
            Item("Quick actions", Menu(self._quick_action_items)),
            Item("Routines", Menu(self._routine_menu_items), enabled=online),
            Item("Customize FRIDAY…", self.open_customization),
            Item("System stats", Menu(self._stats_menu_items), enabled=online),
            Item("Clipboard history", Menu(self._clipboard_menu_items), enabled=online),
            Item("File search", Menu(
                Item(lambda item: self.files_line or "Reading…", None, enabled=False),
                Menu.SEPARATOR,
                Item("Re-scan my files now", self._rescan_files),
            ), enabled=online),
            Item("AI provider", Menu(
                Item(lambda item: f"Default ({self.default_provider})" if self.default_provider else "Default",
                     self._provider_action(None),
                     checked=lambda item: self._api.settings.provider is None, radio=True),
                *(Item(name, self._provider_action(name),
                       checked=lambda item, name=name: self._api.settings.provider == name, radio=True)
                  for name in PROVIDERS),
            )),
            Menu.SEPARATOR,
            Item("Clear chat memory…", self.clear_memory, enabled=online),
            Item("Stop FRIDAY" if self._stop_backend else "Quit FRIDAY", self.stop_friday),
            Item("Exit taskbar widget", self.quit, visible=lambda item: self._stop_backend is not None),
        )

    def open_customization(self):
        from interfaces.settings.launcher import launch
        _in_background(launch)

    def _stats_menu_items(self):
        Item = pystray.MenuItem
        for line in self.stats_lines or ["Reading…"]:
            yield Item(line, None, enabled=False)
        yield pystray.Menu.SEPARATOR
        yield Item("How's my system?", self._command_action("how's my system?"))

    def _routine_menu_items(self):
        Item = pystray.MenuItem
        try:
            names = list(routines.load())  # read on every open: new routines show up straight away
        except AutomationError:
            names = []
        if not names:
            yield Item('None yet — say "create a routine called …"', None, enabled=False)
        for name in names:
            yield Item(_menu_label(name), self._command_action(f"run {name}"))

    def _clipboard_menu_items(self):
        Item = pystray.MenuItem
        if not self.clipboard_items:
            yield Item("Nothing copied yet", None, enabled=False)
            return
        for text in self.clipboard_items[:CLIPBOARD_MENU_ITEMS]:
            yield Item(_menu_label(text), self._restore_clipboard_action(text))
        yield pystray.Menu.SEPARATOR
        yield Item("Clear clipboard history", self.clear_clipboard_history)

    # ── Actions ───────────────────────────────────────────────────────────────

    def toggle_listening(self) -> None:
        """
        Voice hotkey and menu item: start listening (FRIDAY stops talking first),
        or — while listening — stop early.
        """
        if not self.online:
            self.notify("FRIDAY is offline — use Start FRIDAY in its taskbar controls.")
            return
        if self.listening:
            self._stop_requested = True
            _in_background(self._stop_listening_now)
            return
        self._stop_requested = False
        self._set_listening(True)
        _in_background(self.listen)

    def listen(self) -> None:
        try:
            self._handle_voice(self._api.voice())
        except self._api.BackendError as e:
            if not self._stop_requested:  # an error caused by the user's own stop isn't news
                self.notify(f"Voice didn't work: {e}")
        finally:
            self._set_listening(False)

    def _show_voice(self, result: dict, transient: bool = False) -> None:
        self.notify(f"You: {result['transcription']}\nFRIDAY: {result['response']}",
                    transient=transient or is_quick_command(result.get("action") == "system", result["response"]))
        if result.get("keyboard"):
            self._type(result["keyboard"])

    def pause_microphone(self, wait: bool = False) -> None:
        """End the current listen and both continuous microphone modes."""
        session, was_wake = self._wake_session, self.wake_on
        self.wake_on = self.in_conversation = self._api.settings.conversation = False
        self._stop_requested = True
        self._typed_done.set()
        self.refresh()

        def stop():
            if was_wake:
                self._stop_wake_now(session)
            try:
                self._api.stop_listening(discard=True)
            except self._api.BackendError as error:
                if self.online:
                    self.notify(str(error))
        if wait:
            stop()
        else:
            _in_background(stop)

    def _handle_voice(self, result: dict) -> None:
        """Show and type a voice reply; if FRIDAY asked a yes/no question, listen for the answer."""
        while True:
            self._show_voice(result)
            if result.get("conversation") == "start":
                self.start_conversation()  # "let's talk": the conversation loop takes over the mic
                return
            if not result.get("awaiting_reply") or self._stop_requested:
                return
            # Listen for the answer once FRIDAY is done asking.
            result = self._api.voice(after_speech=True)

    # ── Conversation mode ─────────────────────────────────────────────────────

    def toggle_conversation(self) -> None:
        """Tray checkbox and Ctrl+Alt+C: start a back-and-forth, or end it."""
        if self.in_conversation:
            self.in_conversation = False
            self._typed_done.set()  # don't leave the loop waiting for a typed reply
            if self.listening:
                self._stop_requested = True
                _in_background(self._api.stop_listening, True)
            self.refresh()
            return
        self.start_conversation()

    def start_conversation(self) -> None:
        if self.in_conversation:
            return
        if not self.online:
            self.notify("FRIDAY is offline — use Start FRIDAY in its taskbar controls.")
            return
        self.in_conversation = self._api.settings.conversation = True
        self.refresh()
        _in_background(self._conversation)

    def _conversation(self) -> None:
        """Listen, reply, listen again — until "bye", Ctrl+Alt+C, or CONVERSATION_SILENCES silences in a row."""
        silences = 0
        try:
            while self.in_conversation:
                if self._typed_turn:  # a typed message: listen again once its (spoken) reply is out
                    self._typed_done.wait(TYPED_REPLY_WAIT)
                    self._typed_turn, silences = False, 0
                    continue
                self._stop_requested = False
                self._set_listening(True)
                try:
                    # after_speech: she finishes her reply (or "I'm all ears") before the mic opens
                    result = self._api.voice(after_speech=True, speak=True)
                except self._api.BackendError as e:
                    if self._typed_turn:
                        continue
                    if not self.in_conversation or self._stop_requested:
                        return
                    if e.status == 422:  # nothing said
                        if self._typing_recently():
                            silences = 0  # typing, not silent
                            continue
                        silences += 1
                        if silences >= CONVERSATION_SILENCES:
                            self.notify("Conversation ended — you went quiet.", transient=True)
                            return
                        continue
                    self.notify(f"Conversation ended: {e}")
                    return
                finally:
                    self._set_listening(False)
                silences = 0
                self._show_voice(result, transient=True)
                if result.get("conversation") == "end":
                    return
        finally:
            self.in_conversation = self._api.settings.conversation = False
            self.refresh()

    def _typing_recently(self) -> bool:
        last = self.body.last_key_at if self.body else 0.0
        return bool(last) and time.monotonic() - last < TYPING_KEEPS_TALKING

    def typed_reply_done(self) -> None:
        self._typed_done.set()

    def toggle_wake(self) -> None:
        """Tray checkbox and Ctrl+Alt+H: start or stop listening for "Hey Friday"."""
        if self.wake_on:
            self.wake_on = False
            self.refresh()
            _in_background(self._stop_wake_now, self._wake_session)
            return
        if not self.online:
            self.notify("FRIDAY is offline — use Start FRIDAY in its taskbar controls.")
            return
        self.wake_on = True
        self._wake_session = uuid.uuid4().hex
        self.refresh()
        _in_background(self._wake_loop, self._wake_session)

    def _wake_loop(self, session: str) -> None:
        try:
            while self.wake_on and self._wake_session == session:
                try:
                    result = self._api.wake(session)
                except self._api.BackendError as e:
                    if e.status == 408:
                        self.notify('Stopped listening for "Hey Friday" — nobody said it for a while.')
                    elif self.wake_on and e.status != 409:  # 409 = switched off meanwhile
                        self.notify(f'"Hey Friday" stopped: {e}')
                    return
                if not self.wake_on or self._wake_session != session:
                    return
                self._stop_requested = False
                try:
                    self._handle_voice(result)
                except self._api.BackendError as e:
                    self.notify(f"Voice didn't work: {e}")  # keep listening for the next "Hey Friday"
        finally:
            if self._wake_session == session:  # not if it's already been switched on again
                self.wake_on = False
                self.refresh()

    def toggle_body(self) -> None:
        if self.body:
            self.body.visible = not self.body.visible  # the menu tick flips at once; the body saves it
            self.body.set_visible(self.body.visible)

    def toggle_talk(self) -> None:
        """Tray checkbox: FRIDAY's free will on/off."""
        def switch(on: bool) -> None:
            try:
                self.talk_on = self._api.set_talk(on)
            except self._api.BackendError as e:
                self.notify(str(e))
            self.refresh()
        _in_background(switch, not self.talk_on)

    def _ask_loop(self) -> None:
        """Waits for FRIDAY to ask something on her own: then the bar shows it and the mic opens."""
        while not self._stopping.is_set():
            if not self.online:
                self._stopping.wait(POLL_SECONDS)
                continue
            try:
                question = self._api.next_ask()
            except self._api.BackendError:
                self._stopping.wait(POLL_SECONDS)
                continue
            if question:
                self._answer(question)

    def _answer(self, question: str) -> None:
        self._ask_in_bar(question)
        if self.listening or self.wake_on or self.in_conversation:  # the mic is taken: the bar is enough
            return
        self._asking, self._stop_requested = True, False
        self._set_listening(True)
        try:
            self._handle_voice(self._api.voice(after_speech=True))
        except self._api.BackendError:
            pass  # nothing said, or the answer was typed instead — both are fine
        finally:
            self._asking = False
            self._set_listening(False)
            self._ask_done()

    def bar_submitted(self, text: str = "") -> None:
        """The command bar sent something: if it answers her question, close the mic (and drop what it heard).
        Typing "let's talk" starts conversation mode."""
        if self.in_conversation and text:
            if match_conversation(text) == "end":
                self.toggle_conversation()
                return
            # typing counts as a turn: close the mic (dropping what it heard) until the reply has been said
            self._typed_done.clear()
            self._typed_turn = True
            if self.listening:
                _in_background(self._api.stop_listening, True)
            return
        if match_conversation(text) == "start":
            self.start_conversation()
        if self._asking and self.listening:
            self._stop_requested = True
            _in_background(self._api.stop_listening, True)

    def _stop_wake_now(self, session: str) -> None:
        try:
            self._api.stop_wake(session)
        except self._api.BackendError as e:
            self.notify(str(e))

    def _type(self, steps) -> None:
        # The hotkey never takes focus away, so the user's app is still in front
        try:
            self._typist(steps)
        except keyboard.KeyboardError as e:
            self.notify(str(e))

    def _stop_listening_now(self) -> None:
        try:
            self._api.stop_listening()
        except self._api.BackendError as e:
            self.notify(str(e))

    def toggle_speak_typed(self) -> None:
        self._api.settings.speak_typed = not self._api.settings.speak_typed
        self.refresh()

    def toggle_speak_replies(self) -> None:
        self._api.settings.speak_replies = not self._api.settings.speak_replies
        self.refresh()

    def _command_action(self, command: str):
        return lambda: _in_background(self.run_command, command)

    def run_command(self, command: str) -> None:
        try:
            self.notify(self._api.chat(command).text)
        except self._api.BackendError as e:
            self.notify(str(e))
        finally:
            self._refresh_runtime_status()

    def _refresh_runtime_status(self) -> None:
        try:
            status = self._api.runtime_status() if self.online else None
        except self._api.BackendError:
            status = None
        if status != self.runtime_status:
            self.runtime_status = status
            self.refresh()

    def _restore_clipboard_action(self, text: str):
        return lambda: self.restore_clipboard_item(text)

    def restore_clipboard_item(self, text: str) -> None:
        try:
            clipboard.set_text(text)
        except clipboard.ClipboardError:
            self.notify("Couldn't copy that — another app is using the clipboard.")
            return
        self.notify(f"Copied back to the clipboard: {_one_line(text, 60)}")

    def clear_clipboard_history(self) -> None:
        _in_background(self._clear_clipboard_history_now)

    def _clear_clipboard_history_now(self) -> None:
        try:
            self._api.clear_clipboard_history()
        except self._api.BackendError as e:
            self.notify(str(e))
            return
        self.clipboard_items = []
        self.refresh()
        self.notify("Clipboard history cleared.")

    def _rescan_files(self) -> None:
        _in_background(self._rescan_files_now)

    def _rescan_files_now(self) -> None:
        try:
            self.notify(self._api.rescan_files())
        except self._api.BackendError as e:
            self.notify(str(e))

    def _provider_action(self, name: str | None):
        def choose():
            self._api.settings.provider = name
            self.refresh()
        return choose

    def clear_memory(self) -> None:
        if not self._confirm(
            "Clear chat memory?",
            "This permanently deletes FRIDAY's conversation history.\nReminders and saved facts are kept.",
        ):
            return
        _in_background(self._clear_memory_now)

    def _clear_memory_now(self) -> None:
        try:
            self._api.clear_history()
            self.notify("Chat memory cleared.")
        except self._api.BackendError as e:
            self.notify(str(e))

    def stop_friday(self) -> None:
        if self._stop_backend:
            self._stop_backend()
        else:
            self.quit()

    def quit(self) -> None:
        self._stopping.set()
        if self.online and (self.wake_on or self.listening or self.in_conversation or self._asking):
            self.pause_microphone(wait=True)
        self.icon.stop()
        self._quit_app()

    # ── State + display ───────────────────────────────────────────────────────

    def _set_listening(self, listening: bool) -> None:
        self.listening = listening
        self.refresh()

    def refresh(self) -> None:
        self.icon.icon = make_icon(self.status)
        title = f"F.R.I.D.A.Y — {self.status}"
        self.icon.title = _one_line(f"{title} | {self.mode_text()}" if self.online else title, 127)
        self.icon.update_menu()

    def notify(self, text: str, transient: bool = False) -> None:
        """transient: a quick command's confirmation ("Opening Chrome.") — it disappears by itself."""
        if len(text) > NOTIFY_LIMIT:
            text = text[:NOTIFY_LIMIT - 1] + "…"
        # PowerShell toast, not icon.notify: pystray's balloon is silently dropped on Win11
        show_toast("F.R.I.D.A.Y", text, transient=transient)

    def check_status(self) -> None:
        online = self._api.is_online()
        provider = self.default_provider if online else None
        items = self.clipboard_items if online else []
        stats = self.stats_lines if online else []
        files_line = self.files_line if online else ""
        if online:
            try:
                runtime = self._api.runtime_status()
            except self._api.BackendError:
                runtime = None
            if provider is None:
                try:
                    provider = self._api.active_provider()
                except self._api.BackendError:
                    pass  # only used for a menu label — the next poll tries again
            try:
                items = self._api.clipboard_history()
            except self._api.BackendError:
                pass  # keep showing the last list — the next poll tries again
            try:
                stats = self._api.system_stats()
            except self._api.BackendError:
                pass  # same: keep the last numbers
            try:
                files_line = files_status_text(self._api.file_search_status())
            except self._api.BackendError:
                pass
            try:
                talk_on = self._api.talk_on()
                if talk_on != self.talk_on:
                    self.talk_on = talk_on  # switched by voice ("you can talk freely")
                    self.refresh()
            except self._api.BackendError:
                pass

        else:
            runtime = None
        state = (online, provider, items, stats, files_line, runtime)
        if state != (self.online, self.default_provider, self.clipboard_items, self.stats_lines, self.files_line, self.runtime_status):
            if online != self.online:
                logger.info(f"FRIDAY backend is {'online' if online else 'offline'}")
            self.online, self.default_provider, self.clipboard_items, self.stats_lines, self.files_line, self.runtime_status = state
            self.refresh()

    def run(self, show_icon: bool = True) -> None:
        """Blocks until Quit. Status polling runs in pystray's setup thread."""
        def setup(icon):
            icon.visible = show_icon
            threading.Thread(target=self._ask_loop, name="friday-asks", daemon=True).start()
            while not self._stopping.is_set():
                self.check_status()
                self._stopping.wait(POLL_SECONDS)

        self.icon.run(setup=setup)
