from types import SimpleNamespace

import httpx
import pytest

from interfaces.tray import backend, tray as tray_module
from interfaces.tray.tray import FridayTray


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeIcon:
    def __init__(self, name, image, title, menu):
        self.icon, self.title, self.menu = image, title, menu
        self.notifications = []
        self.stopped = False

    def update_menu(self):
        pass

    def notify(self, message, title):
        self.notifications.append(message)

    def stop(self):
        self.stopped = True


class FakeApi:
    BackendError = backend.BackendError

    def __init__(self):
        self.settings = backend.Settings()
        self.online = True
        self.sent = []
        self.cleared = False
        self.clipboard = ["first & second", "hello"]
        self.stats = ["CPU  5%", "RAM  60%  (9.4 / 15.7 GB)"]
        self.files = {"enabled": True, "files": 1608, "readable": 900, "scanning": False, "progress": [0, 0]}
        self.fail_with = None
        self.voice_results = []  # replies (or errors) for successive voice() calls
        self.wake_results = []   # replies (or errors) for successive wake() calls; then "switched off"
        self.during_voice = None

    def is_online(self):
        return self.online

    def active_provider(self):
        return "openrouter"

    def chat(self, message):
        if self.fail_with:
            raise self.fail_with
        self.sent.append(message)
        return backend.ChatReply(f"did: {message}", False)

    def voice(self, after_speech=False, speak=None):
        self.sent.append(("voice", after_speech, self.settings.speak_replies, self.settings.provider))
        self.forced_speech = speak
        if self.during_voice:
            self.during_voice()
        if self.voice_results:
            outcome = self.voice_results.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return {"transcription": "what time is it", "response": "It's 3pm."}

    def stop_listening(self, discard=False):
        self.sent.append("stop listening" + (" (discard)" if discard else ""))

    def stop_conversation_input(self):
        pass

    def talk_on(self):
        return getattr(self, "talking", False)

    def set_talk(self, on):
        self.talking = on
        return on

    def wake(self, session):
        self.sent.append(("wake", session))
        outcome = self.wake_results.pop(0) if self.wake_results else backend.BackendError("stopped", 409)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def stop_wake(self, session):
        self.sent.append(("stop wake", session))

    def clear_history(self):
        self.cleared = True

    def clipboard_history(self):
        return list(self.clipboard)

    def file_search_status(self):
        return self.files

    def rescan_files(self):
        self.sent.append("rescan files")
        return "Re-scanning your files in the background."

    def clear_clipboard_history(self):
        self.clipboard = []

    def system_stats(self):
        if isinstance(self.stats, Exception):
            raise self.stats
        return list(self.stats)

    def runtime_status(self):
        import copy
        value = getattr(self, 'runtime', {
            'mode': {'name': 'normal', 'quiet': False},
            'spotify': {'configured': True, 'connected': False},
        })
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


@pytest.fixture
def api():
    return FakeApi()


@pytest.fixture
def events():
    return SimpleNamespace(shown=0, quit=0, confirm_answer=True, confirmed=[])


@pytest.fixture
def friday(monkeypatch, api, events):
    monkeypatch.setattr(tray_module.pystray, "Icon", FakeIcon)
    # Run background work inline so results are visible straight away.
    monkeypatch.setattr(tray_module, "_in_background", lambda fn, *args: fn(*args))

    def confirm(title, text):
        events.confirmed.append(title)
        return events.confirm_answer

    tray = FridayTray(
        show_command_bar=lambda: setattr(events, "shown", events.shown + 1),
        quit_app=lambda: setattr(events, "quit", events.quit + 1),
        confirm=confirm,
        api=api,
    )
    # notify() shows a PowerShell toast (not icon.notify); catch it so tests see it and no real toast pops up
    tray.transient = []  # which notifications disappear by themselves
    monkeypatch.setattr(tray_module, "show_toast", lambda title, text, transient=False: (
        tray.icon.notifications.append(text), tray.transient.append(transient)))
    tray.check_status()
    return tray


def find(menu, prefix):
    for entry in menu.items:
        if entry.text.startswith(prefix):
            return entry
    raise AssertionError(f"no menu item starting with {prefix!r}")


def click(tray, entry):
    entry(tray.icon)


def test_stop_microphone_cancels_all_modes_and_quit_waits_for_cancellation(friday, api, events):
    friday.wake_on = friday.listening = friday.in_conversation = api.settings.conversation = True
    friday._wake_session = "active-mic"
    friday.quit()
    assert not friday.wake_on and not friday.in_conversation and not api.settings.conversation
    assert friday._stop_requested and friday._typed_done.is_set()
    assert api.sent[-2:] == [("stop wake", "active-mic"), "stop listening (discard)"]
    assert events.quit == 1 and friday.icon.stopped


def test_stopped_wake_session_cannot_dispatch_a_late_result(friday, api, monkeypatch):
    friday.wake_on, friday._wake_session = True, "late-wake"

    def late_result(session):
        friday.pause_microphone(wait=True)
        return {"transcription": "late", "response": "must not be shown"}

    monkeypatch.setattr(api, "wake", late_result)
    friday._wake_loop("late-wake")
    assert friday._stop_requested and not friday.wake_on
    assert friday.icon.notifications == []


def submenu(tray, name):
    return find(tray.icon.menu, name).submenu


def test_mode_and_spotify_follow_live_backend_status(friday, api):
    api.runtime = {'mode': {'name': 'gaming', 'quiet': True},
                   'spotify': {'configured': True, 'connected': True}}
    friday.check_status()
    assert find(friday.icon.menu, 'Mode: Gaming')
    assert 'Gaming' in friday.icon.title
    quick = submenu(friday, 'Quick actions')
    assert find(quick, 'Spotify: Connected')
    assert not any(item.text.startswith('Connect Spotify') for item in quick.items)
    click(friday, find(quick, 'Disconnect Spotify'))
    assert api.sent[-1] == 'disconnect spotify'


def test_runtime_status_failure_clears_mode_and_spotify_claims(friday, api):
    api.runtime = backend.BackendError('status unavailable')
    friday.check_status()
    assert 'unavailable' in find(friday.icon.menu, 'Mode:').text.lower()
    quick = submenu(friday, 'Quick actions')
    assert find(quick, 'Spotify: Status unavailable')
    assert not any(item.text.startswith('Connect Spotify') for item in quick.items)


def test_quick_action_refreshes_state_immediately(friday, api):
    api.runtime = {'mode': {'name': 'work', 'quiet': True},
                   'spotify': {'configured': True, 'connected': True}}
    friday.run_command('start work mode')
    assert find(friday.icon.menu, 'Mode: Work')


def test_offline_never_displays_old_mode_or_spotify_connection(friday, api):
    api.online = False
    friday.check_status()
    assert 'unavailable' in find(friday.icon.menu, 'Mode:').text.lower()
    assert find(submenu(friday, 'Quick actions'), 'Spotify: Status unavailable')


# ── Status ────────────────────────────────────────────────────────────────────

def test_shows_online_with_provider(friday):
    status = friday.icon.menu.items[0]
    assert status.text == "●  FRIDAY is online — openrouter"
    assert status.enabled is False
    assert friday.icon.title == "F.R.I.D.A.Y — online | Mode: Normal"


def test_offline_disables_everything_that_needs_the_backend(friday, api):
    api.online = False
    friday.check_status()

    assert friday.icon.menu.items[0].text == "○  FRIDAY is offline"
    assert friday.icon.title == "F.R.I.D.A.Y — offline"
    assert not find(submenu(friday, "Talk to FRIDAY"), "Start listening").enabled
    assert not find(submenu(friday, "Quick actions"), "Take a screenshot").enabled
    assert not find(friday.icon.menu, "Clipboard history").enabled
    assert not find(friday.icon.menu, "Clear chat memory").enabled
    assert find(friday.icon.menu, "Open command bar").enabled
    assert find(friday.icon.menu, "Quit FRIDAY").enabled


# ── Voice ─────────────────────────────────────────────────────────────────────

def test_voice_toggle_listens_and_shows_the_reply(friday, api):
    seen = []
    api.during_voice = lambda: seen.append((friday.status, friday.icon.menu.items[0].text))

    click(friday, find(submenu(friday, "Talk to FRIDAY"), "Start listening"))

    assert seen == [("listening", "◉  Listening…  (Ctrl+Alt+Space to stop)")]
    assert api.sent == [("voice", False, True, None)]
    assert friday.icon.notifications == ["You: what time is it\nFRIDAY: It's 3pm."]
    assert friday.status == "online"


def test_pressing_the_voice_toggle_again_stops_listening(friday, api):
    def press_again_while_listening():
        assert find(submenu(friday, "Talk to FRIDAY"), "Stop listening")
        friday.toggle_listening()
    api.during_voice = press_again_while_listening

    friday.toggle_listening()

    assert api.sent == [("voice", False, True, None), "stop listening"]


def test_listens_for_the_answer_when_friday_asks_a_question(friday, api):
    api.voice_results = [
        {"transcription": "organise downloads", "response": "Organise Downloads? Reply yes or no.", "awaiting_reply": True},
        {"transcription": "yes", "response": "Organised 4 files in Downloads.", "awaiting_reply": False},
    ]

    friday.toggle_listening()

    assert api.sent == [("voice", False, True, None), ("voice", True, True, None)]
    assert friday.icon.notifications == [
        "You: organise downloads\nFRIDAY: Organise Downloads? Reply yes or no.",
        "You: yes\nFRIDAY: Organised 4 files in Downloads.",
    ]
    assert friday.status == "online"


def test_pressing_the_hotkey_during_a_question_cancels_quietly(friday, api):
    api.voice_results = [
        {"transcription": "organise downloads", "response": "Organise Downloads? Reply yes or no.", "awaiting_reply": True},
        backend.BackendError("Stopped listening."),
    ]
    api.during_voice = lambda: len(api.sent) == 2 and friday.toggle_listening()

    friday.toggle_listening()

    assert api.sent[-1] == "stop listening"
    assert friday.icon.notifications == ["You: organise downloads\nFRIDAY: Organise Downloads? Reply yes or no."]
    assert friday.status == "online"


def test_voice_errors_are_shown(friday, api):
    api.voice_results = [backend.BackendError("No speech detected. Please try again.")]
    friday.toggle_listening()
    assert friday.icon.notifications == ["Voice didn't work: No speech detected. Please try again."]


def test_voice_hotkey_while_offline_explains_instead_of_listening(friday, api):
    api.online = False
    friday.check_status()

    friday.toggle_listening()

    assert api.sent == []
    assert friday.icon.notifications == ["FRIDAY is offline — use Start FRIDAY in its taskbar controls."]


def test_speak_replies_toggle_changes_voice_requests(friday, api):
    talk = submenu(friday, "Talk to FRIDAY")
    toggle = find(talk, "Speak voice replies aloud")
    assert toggle.checked is True

    click(friday, toggle)
    click(friday, find(talk, "Start listening"))

    assert toggle.checked is False
    assert api.sent == [("voice", False, False, None)]


# ── Clipboard history ─────────────────────────────────────────────────────────

def test_clipboard_history_lists_recent_copies(friday):
    labels = [entry.text for entry in submenu(friday, "Clipboard history").items]
    assert labels[:2] == ["first && second", "hello"]  # "&&" shows as "&" in Windows menus
    assert labels[-1] == "Clear clipboard history"


def test_clicking_an_entry_copies_it_back(friday, monkeypatch):
    written = []
    monkeypatch.setattr(tray_module.clipboard, "set_text", written.append)

    click(friday, find(submenu(friday, "Clipboard history"), "hello"))

    assert written == ["hello"]
    assert friday.icon.notifications == ["Copied back to the clipboard: hello"]


def test_clear_clipboard_history(friday, api):
    click(friday, find(submenu(friday, "Clipboard history"), "Clear clipboard history"))

    assert api.clipboard == []
    assert [entry.text for entry in submenu(friday, "Clipboard history").items] == ["Nothing copied yet"]


def test_new_copies_appear_after_the_next_poll(friday, api):
    api.clipboard = ["just copied"]
    friday.check_status()
    assert find(submenu(friday, "Clipboard history"), "just copied")


# ── System stats ──────────────────────────────────────────────────────────────

def test_system_stats_show_the_latest_numbers(friday, api):
    labels = [entry.text for entry in submenu(friday, "System stats").items]
    assert labels[:2] == ["CPU  5%", "RAM  60%  (9.4 / 15.7 GB)"]
    assert labels[-1] == "How's my system?"
    assert not find(submenu(friday, "System stats"), "CPU").enabled

    api.stats = ["CPU  70%"]
    friday.check_status()
    assert find(submenu(friday, "System stats"), "CPU  70%")


def test_system_stats_keep_the_last_numbers_when_a_poll_fails(friday, api):
    api.stats = backend.BackendError("timed out")
    friday.check_status()
    assert find(submenu(friday, "System stats"), "CPU  5%")


def test_how_is_my_system_asks_friday(friday, api):
    click(friday, find(submenu(friday, "System stats"), "How's my system?"))
    assert api.sent == ["how's my system?"]
    assert friday.icon.notifications == ["did: how's my system?"]


# ── Other menu items ──────────────────────────────────────────────────────────

def test_choosing_a_provider(friday, api):
    providers = submenu(friday, "AI provider")
    assert find(providers, "Default (openrouter)").checked

    click(friday, find(providers, "ollama"))
    assert api.settings.provider == "ollama"
    assert find(providers, "ollama").checked and not find(providers, "Default").checked
    assert friday.icon.menu.items[0].text == "●  FRIDAY is online — ollama"

    click(friday, find(providers, "Default"))
    assert api.settings.provider is None


def test_quick_action_runs_command_and_shows_result(friday, api):
    click(friday, find(submenu(friday, "Quick actions"), "Take a screenshot"))
    assert api.sent == ["take a screenshot"]
    assert friday.icon.notifications == ["did: take a screenshot"]


def test_backend_errors_are_shown_as_notifications(friday, api):
    api.fail_with = backend.BackendError("FRIDAY isn't running.")
    click(friday, find(submenu(friday, "Quick actions"), "List reminders"))
    assert friday.icon.notifications == ["FRIDAY isn't running."]


@pytest.mark.parametrize("answer", [True, False])
def test_clear_memory_asks_first(friday, api, events, answer):
    events.confirm_answer = answer
    click(friday, find(friday.icon.menu, "Clear chat memory"))
    assert events.confirmed == ["Clear chat memory?"]
    assert api.cleared is answer


def test_open_command_bar(friday, events):
    click(friday, find(friday.icon.menu, "Open command bar"))
    assert events.shown == 1


def test_quit_stops_icon_and_command_bar(friday, events):
    click(friday, find(friday.icon.menu, "Quit FRIDAY"))
    assert friday.icon.stopped and events.quit == 1


def test_long_notifications_are_trimmed(friday):
    friday.notify("x" * 1000)
    assert len(friday.icon.notifications[0]) == tray_module.NOTIFY_LIMIT


# ── Backend client ────────────────────────────────────────────────────────────

def _response(status, payload):
    return httpx.Response(status, json=payload, request=httpx.Request("POST", "http://friday"))


def test_chat_sends_the_chosen_provider(monkeypatch):
    sent = {}

    def request(method, url, timeout, **kwargs):
        sent.update(method=method, url=url, body=kwargs["json"])
        return _response(200, {"response": "hi"})
    monkeypatch.setattr(backend.httpx, "request", request)
    monkeypatch.setattr(backend.settings, "provider", "ollama")

    assert backend.chat("hello") == backend.ChatReply("hi", False)
    assert sent["url"].endswith("/api/v1/chat")
    assert sent["body"] == {"message": "hello", "provider": "ollama", "speak": False}


def test_chat_reply_says_when_friday_is_waiting_for_an_answer(monkeypatch):
    payload = {"response": "Organise Downloads? Reply yes or no.", "awaiting_reply": True}
    monkeypatch.setattr(backend.httpx, "request", lambda *a, **k: _response(200, payload))
    assert backend.chat("organise downloads").awaiting_reply is True


def test_voice_waits_long_enough_for_a_full_listen(monkeypatch):
    sent = {}

    def request(method, url, timeout, **kwargs):
        sent.update(url=url, timeout=timeout, body=kwargs["json"])
        return _response(200, {"transcription": "hi", "response": "hello"})
    monkeypatch.setattr(backend.httpx, "request", request)

    backend.voice(after_speech=True)

    assert sent["url"].endswith("/api/v1/voice")
    assert sent["timeout"] > backend.MAX_LISTEN_SECONDS
    assert sent["body"] == {"speak": True, "provider": None, "after_speech": True}


def test_backend_error_message_is_passed_through(monkeypatch):
    monkeypatch.setattr(backend.httpx, "request", lambda *a, **k: _response(502, {"message": "Web search failed"}))
    with pytest.raises(backend.BackendError, match="Web search failed"):
        backend.chat("\\s anything")


def test_unreachable_backend_gives_a_friendly_error(monkeypatch):
    def refuse(*args, **kwargs):
        raise httpx.ConnectError("connection refused")
    monkeypatch.setattr(backend.httpx, "request", refuse)
    monkeypatch.setattr(backend.httpx, "get", refuse)

    with pytest.raises(backend.BackendError, match="isn't running"):
        backend.chat("hi")
    assert backend.is_online() is False


def test_file_search_status_and_rescan(friday, api):
    labels = [entry.text for entry in submenu(friday, "File search").items]
    assert labels[0] == "1,608 files indexed, 900 with text"

    api.files = {"enabled": True, "files": 10, "readable": 2, "scanning": True, "progress": [3, 40]}
    friday.check_status()
    assert find(submenu(friday, "File search"), "Indexing… 3/40 files read")

    click(friday, find(submenu(friday, "File search"), "Re-scan my files now"))
    assert api.sent == ["rescan files"]
    assert friday.icon.notifications == ["Re-scanning your files in the background."]


# ── "Hey Friday" ──────────────────────────────────────────────────────────────

def wake_item(tray):
    return find(submenu(tray, "Talk to FRIDAY"), 'Listen for "Hey Friday"')


def test_hey_friday_is_off_until_switched_on(friday):
    assert friday.wake_on is False
    assert wake_item(friday).checked is False


def test_switching_hey_friday_on_handles_each_wake_until_it_is_switched_off(friday, api):
    seen = []
    api.wake_results = [
        {"transcription": "work mode", "response": "Work mode: done."},
        {"transcription": "mute", "response": "Muted."},
    ]
    real_wake = api.wake
    api.wake = lambda session: seen.append((friday.status, friday.icon.menu.items[0].text)) or real_wake(session)

    click(friday, wake_item(friday))

    session = api.sent[0][1]
    assert api.sent == [("wake", session)] * 3  # two wakes, then the backend said it was switched off
    assert friday.icon.notifications == ["You: work mode\nFRIDAY: Work mode: done.", "You: mute\nFRIDAY: Muted."]
    assert seen[0] == ("wake", '◉  Listening for "Hey Friday"  (Ctrl+Alt+H to stop)')
    assert friday.status == "online" and friday.wake_on is False


def test_switching_it_off_tells_the_backend(friday, api):
    friday.wake_on, friday._wake_session = True, "s1"
    friday.toggle_wake()
    assert api.sent == [("stop wake", "s1")]
    assert friday.wake_on is False


def test_auto_off_is_announced(friday, api):
    api.wake_results = [backend.BackendError("nobody said it", 408)]
    friday.toggle_wake()
    assert friday.icon.notifications == ['Stopped listening for "Hey Friday" — nobody said it for a while.']
    assert friday.wake_on is False


def test_a_failed_command_keeps_listening(friday, api):
    api.wake_results = [{"transcription": "yes?", "response": "Organise it?", "awaiting_reply": True}]
    api.voice_results = [backend.BackendError("mic unplugged")]
    friday.toggle_wake()
    assert api.sent[-1][0] == "wake"  # asked for the next "Hey Friday" after the error
    assert "Voice didn't work: mic unplugged" in friday.icon.notifications


def test_hey_friday_needs_friday_running(friday, api):
    api.online = False
    friday.check_status()
    friday.toggle_wake()
    assert friday.wake_on is False and api.sent == []
    assert friday.icon.notifications == ["FRIDAY is offline — use Start FRIDAY in its taskbar controls."]


def test_routines_menu_runs_a_saved_routine(friday, api):
    from services.automation import routines
    assert [e.text for e in submenu(friday, "Routines").items] == ['None yet — say "create a routine called …"']
    routines._save({"work mode": ["open chrome"]})
    click(friday, find(submenu(friday, "Routines"), "work mode"))
    assert api.sent[-1] == "run work mode"


# ── FRIDAY talking on her own ─────────────────────────────────────────────────

def test_talk_checkbox_switches_free_will(friday, api):
    item = find(find(friday.icon.menu, "Talk to FRIDAY").submenu, "Let FRIDAY talk")
    item(friday.icon)
    assert api.talking and friday.talk_on
    api.talking = False  # switched off by voice
    friday.check_status()
    assert not friday.talk_on


def test_her_question_opens_the_bar_and_the_mic(friday, api):
    shown, done = [], []
    friday._ask_in_bar, friday._ask_done = shown.append, lambda: done.append(True)
    api.voice_results = [{"transcription": "working on catjang", "response": "Nice."}]
    friday._answer("What are you building, Boss?")
    assert shown == ["What are you building, Boss?"] and done == [True]
    assert ("voice", True, api.settings.speak_replies, api.settings.provider) in api.sent  # after she finishes
    assert not friday.listening


def test_typing_the_answer_closes_the_mic_and_drops_the_audio(friday, api):
    def type_instead():
        friday.bar_submitted()
        raise backend.BackendError("Stopped listening.", 409)
    api.during_voice = type_instead
    friday._answer("How's the assignment going?")
    assert "stop listening (discard)" in api.sent
    assert not any("Voice didn't work" in n for n in friday.icon.notifications)  # no error toast


# ── Notifications: a command's confirmation disappears, answers stay ──────────

def test_quick_command_notifications_disappear_answers_stay(friday, api):
    api.voice_results = [
        {"transcription": "open chrome", "response": "Opening Chrome.", "action": "system"},
        {"transcription": "why is the sky blue", "response": "Rayleigh scattering, Boss.", "action": "chat"},
        {"transcription": "how good are your predictions", "response": "x" * 300, "action": "system"},
    ]
    for _ in range(3):
        friday.listen()
    assert friday.transient == [True, False, False]


def test_is_quick_command():
    from interfaces.tray.tray import is_quick_command
    assert is_quick_command(True, "Opening Chrome.")
    assert not is_quick_command(False, "Opening Chrome.")        # an AI answer, however short
    assert not is_quick_command(True, "Line one\nLine two")      # a multi-line result


# ── Conversation mode ─────────────────────────────────────────────────────────

def said(text, response="Mm.", conversation=None):
    return {"transcription": text, "response": response, "conversation": conversation}


def test_conversation_listens_again_after_every_reply_until_bye(friday, api):
    api.voice_results = [said("how was your day"), said("tell me a joke"), said("bye", "Talk later, Boss.", "end")]
    friday.toggle_conversation()
    assert [m for m in api.sent if m[0] == "voice"] == [("voice", True, True, None)] * 3  # waits for her to finish
    assert api.forced_speech is True  # replies are spoken even if spoken replies are off
    assert len(friday.icon.notifications) == 3
    assert not friday.in_conversation and friday.status == "online"


def test_two_silences_in_a_row_end_the_conversation(friday, api):
    quiet = lambda: backend.BackendError("No speech detected. Please try again.", 422)
    api.voice_results = [quiet(), said("hmm, what's next"), quiet(), quiet()]
    friday.toggle_conversation()
    assert len([m for m in api.sent if m[0] == "voice"]) == 4  # one silence alone doesn't end it
    assert friday.icon.notifications[-1] == "Conversation ended — you went quiet."
    assert not friday.in_conversation


def test_saying_lets_talk_starts_a_conversation(friday, api):
    api.voice_results = [said("let's talk", "I'm all ears, Boss.", "start"), said("that's all", "Talk later, Boss.", "end")]
    friday.toggle_listening()
    assert len([m for m in api.sent if m[0] == "voice"]) == 2
    assert not friday.in_conversation


def test_typing_lets_talk_in_the_bar_starts_a_conversation(friday, api):
    api.voice_results = [said("bye", "Talk later, Boss.", "end")]
    friday.bar_submitted("let's talk")
    assert ("voice", True, True, None) in api.sent


def test_conversation_hotkey_again_ends_it(friday, api):
    api.voice_results = [backend.BackendError("Stopped listening.", 409)]
    api.during_voice = lambda: friday.toggle_conversation()
    friday.toggle_conversation()
    assert "stop listening (discard)" in api.sent and not friday.in_conversation
    assert friday.icon.notifications == []


def test_speak_typed_replies_toggle(friday, api):
    toggle = find(submenu(friday, "Talk to FRIDAY"), "Speak typed replies aloud")
    assert toggle.checked is False
    click(friday, toggle)
    assert api.settings.speak_typed is True


def test_typing_while_in_conversation_is_not_silence(friday, api):
    friday.body = SimpleNamespace(last_key_at=tray_module.time.monotonic())  # a key was just pressed
    quiet = lambda: backend.BackendError("No speech detected. Please try again.", 422)
    api.voice_results = [quiet(), quiet(), quiet(), said("bye", "Talk later, Boss.", "end")]
    friday.toggle_conversation()
    assert "Conversation ended — you went quiet." not in friday.icon.notifications
    assert len([m for m in api.sent if m[0] == "voice"]) == 4


def test_a_typed_message_is_a_turn_of_the_conversation(friday, api):
    def type_instead():
        if not api.settings.speak_typed and api.settings.conversation and len(api.sent) == 1:
            friday.bar_submitted("what's the capital of peru")  # the mic closes, dropping what it heard
            friday.typed_reply_done()                           # the bar got its (spoken) reply
    api.during_voice = type_instead
    api.voice_results = [backend.BackendError("Stopped listening.", 409), said("bye", "Talk later, Boss.", "end")]
    friday.toggle_conversation()
    assert "stop listening (discard)" in api.sent
    assert len([m for m in api.sent if m[0] == "voice"]) == 2  # listened again after the typed turn
    assert not friday.in_conversation and not api.settings.conversation


def test_typing_bye_ends_the_conversation(friday, api):
    api.during_voice = lambda: friday.bar_submitted("bye")
    api.voice_results = [backend.BackendError("Stopped listening.", 409)]
    friday.toggle_conversation()
    assert not friday.in_conversation


def test_typed_messages_are_spoken_during_a_conversation(monkeypatch):
    sent = {}

    def request(method, url, timeout, **kwargs):
        sent.update(body=kwargs["json"])
        return _response(200, {"response": "hi"})
    monkeypatch.setattr(backend.httpx, "request", request)
    monkeypatch.setattr(backend.settings, "conversation", True)
    backend.chat("hello")
    assert sent["body"]["speak"] is True
