import logging
import functools

import pytest

from core.config import config
from core.logger import logger
from services.learning import origin as learning_origin
from services.learning.catalog import catalog as learning_catalog
from interfaces.api import app as api_app
from services.activity import habits, insights, limits, predict, projects
from services.activity.log import activity_log
from services.automation import app_finder, command_cache, intent, logins, modes, personality, routines, whatsapp
from services.files import filing, installers
from services.files.index import file_index
from services.memory import notes, reading_list
from services.activity import categories
from services.mind import (brain, corrections, evening, foresight, humour, knowledge, learner, life, reflection, talk,
                           wonder)
from services.mind.cognition import cognition
from services.mind.reviews import reviews
from services.mind import notifications as brain_notifications
from services.mind import reminder_review
from services.memory import episodes
from services.memory.semantic import semantic_memory
from services.network.status import network
from services.proactive import watcher as proactive_watcher
from services.spotify import auth as spotify_auth
from services.telegram import bot as telegram_bot, client as telegram
from services.telegram import summaries as telegram_summaries
from services.telegram import commands as telegram_commands
from services.files import assistant as file_assistant
from services.voice import tts as tts_module, wake
from services.computer import agent as computer_module, desktop as computer_desktop
from services.browser import service as automation_service, research as research_service
from services.browser.worker import ProcessRuntime
from services.watch import asked as watches


async def _no_download(self):
    pass


# Tests never write to the real logs/friday.log (their made-up errors looked like FRIDAY's own)
for handler in [h for h in logger.handlers if isinstance(h, logging.FileHandler)]:
    logger.removeHandler(handler)
    handler.close()


@pytest.fixture(autouse=True)
def isolated_caches(tmp_path, tmp_path_factory, monkeypatch):
    """Tests never read or write the real command and speech caches."""
    from services.files import embed
    @functools.wraps(embed.encode_local)
    def no_recall_model(texts, **kwargs):
        raise RuntimeError('Tests use explicit embedding doubles')
    monkeypatch.setattr(embed, 'encode_local', no_recall_model)
    monkeypatch.setattr(config, "MEMORY_DB_PATH", str(tmp_path / "chat.db"))
    monkeypatch.setattr(intent, "_pending", {})
    # Existing model-feature tests exercise the explicit legacy mode. Assistance tests opt in.
    monkeypatch.setattr(config, "AI_ASSIST_ONLY", False)
    monkeypatch.setattr(config, "AI_LANGUAGE_ENABLED", False)  # language tests opt in explicitly
    # Provider payload tests simulate a reachable server. Lifecycle tests use their own runtime.
    from providers.ollama.runtime import runtime
    async def simulated_ollama(base_url):
        pass
    monkeypatch.setattr(runtime, "ensure_running", simulated_ollama)
    async def simulated_model_readiness():
        return {'was_resident': True}
    monkeypatch.setattr(runtime, 'prepare_model', simulated_model_readiness)
    monkeypatch.setattr(config, "REASONING_ENABLED", False)  # reasoning tests opt in with deterministic providers
    monkeypatch.setattr(config, "COGNITIVE_REVIEW_ENABLED", False)  # executive tests opt in with deterministic providers
    async def approve_test_candidates(candidates, now, observations):
        return [brain_notifications.Choice(id=str(i), send=True, reason="Isolated test decision")
                for i in range(len(candidates))]
    monkeypatch.setattr(brain_notifications, "_reason", approve_test_candidates)
    async def approve_test_reminder(reminder, now):
        return reminder_review.Review("send", "Isolated test decision", allow_speech=True,
                                      fingerprint="isolated-test")
    async def recheck_test_reminder(reminder, decision, now):
        return decision
    monkeypatch.setattr(reminder_review, "review", approve_test_reminder)
    monkeypatch.setattr(reminder_review, "recheck", recheck_test_reminder)
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path / "memory-root")
    monkeypatch.setattr(learning_catalog, "path", tmp_path / "learning.db")
    monkeypatch.setattr(config, "LEARNING_DATA_ENABLED", False)
    learning_origin.reset()
    monkeypatch.setattr(activity_log, "origin", "unknown")
    monkeypatch.setattr(activity_log, "_observed_runtime", False)
    monkeypatch.setattr(cognition, "path", tmp_path / "mind" / "cognition.db")
    monkeypatch.setattr(reviews, "path", tmp_path / "training" / "reviews.db")
    monkeypatch.setattr(computer_module.computer_agent, "session", None)
    monkeypatch.setattr(computer_module.computer_agent, "_busy", False)
    monkeypatch.setattr(computer_module.computer_agent, "_generation", 0)
    monkeypatch.setattr(computer_desktop, "capture", lambda *a: pytest.fail("a test tried to capture the real desktop"))
    monkeypatch.setattr(computer_desktop, "execute", lambda *a: pytest.fail("a test tried to control the real desktop"))
    monkeypatch.setattr(automation_service.automation, "job", None)
    monkeypatch.setattr(automation_service.automation, "task", None)
    monkeypatch.setattr(ProcessRuntime, "_start", lambda *a: pytest.fail("a test tried to start a real automation worker"))
    monkeypatch.setattr(research_service, "_search", lambda *a: pytest.fail("research tests require explicit search doubles"))
    monkeypatch.setattr(command_cache, "db_path", str(tmp_path / "command_cache.db"))
    monkeypatch.setattr(command_cache, "SEMANTIC", False)  # never loads the real embedding model
    monkeypatch.setattr(tts_module, "CACHE_DIR", tmp_path / "tts_cache")  # speech objects made in tests
    monkeypatch.setattr(tts_module.tts, "cache_dir", tmp_path / "tts_cache")  # the shared one
    # ...nor the real Piper voice: it's never downloaded (prewarm) or found (so never spoken) in tests
    monkeypatch.setattr(tts_module, "PIPER_DIR", tmp_path / "piper")
    monkeypatch.setattr(tts_module.TextToSpeech, "ensure_piper_voice", _no_download)
    # ...nor the real Spotify login: Spotify starts out disconnected in every test
    monkeypatch.setattr(spotify_auth, "TOKEN_PATH", tmp_path / "spotify_token.json")
    # ...nor the real file index: it starts empty
    monkeypatch.setattr(file_index, "db_path", tmp_path / "file_index.db")
    monkeypatch.setattr(file_index, "_ready", False)
    monkeypatch.setattr(file_index, "_vectors", None)
    # ...nor the real long-term memory: it starts empty and doesn't learn
    monkeypatch.setattr(semantic_memory, "db_path", str(tmp_path / "memory.db"))
    monkeypatch.setattr(semantic_memory, "_cache", None)
    monkeypatch.setattr(config, "SEMANTIC_MEMORY_LEARN", False)
    monkeypatch.setattr(episodes, "path", tmp_path / "episodes.json")
    # ...nor quick chat on the local model, unless a test turns it on
    monkeypatch.setattr(config, "QUICK_CHAT_LOCAL", False)
    # ...nor the real activity log
    monkeypatch.setattr(activity_log, "db_path", str(tmp_path / "activity.db"))
    monkeypatch.setattr(activity_log, "last_app", None)
    monkeypatch.setattr(activity_log, "app", None)
    # ...nor the real logins, nor Windows Credential Manager (an in-memory stand-in), nor real key presses
    monkeypatch.setattr(logins, "path", tmp_path / "logins.json")
    secrets_store = {}
    monkeypatch.setattr(logins, "save_secret", lambda name, user, pw: secrets_store.__setitem__(name, (user, pw)))
    monkeypatch.setattr(logins, "read_secret", lambda name: secrets_store.get(name))
    monkeypatch.setattr(logins, "delete_secret", lambda name: secrets_store.pop(name, None))
    monkeypatch.setattr(logins, "_login_window", lambda *a: pytest.fail("a test tried to open the login window"))
    monkeypatch.setattr(logins.keyboard, "type_secret", lambda text: pytest.fail("a test tried to type a secret"))
    # ...nor the real routines or modes
    monkeypatch.setattr(routines, "path", tmp_path / "routines.json")
    monkeypatch.setattr(modes, "path", tmp_path / "modes.json")
    monkeypatch.setattr(modes, "state_path", tmp_path / "mode_state.json")
    # ...nor the real briefing/nudge state, nor the registry (friday:// for notification buttons)
    monkeypatch.setattr(proactive_watcher, "state_path", tmp_path / "proactive.json")
    monkeypatch.setattr(proactive_watcher.buttons, "register_protocol", lambda: None)
    monkeypatch.setattr(api_app, "register_file_menu", lambda: None)
    monkeypatch.setattr(proactive_watcher.buttons, "_offers", {})
    # ...nor whether the real PC is gaming / fullscreen: not busy unless a test says so
    monkeypatch.setattr(proactive_watcher, "is_busy", lambda: False)
    # A test's behavioral policy must not depend on the developer's real keyboard/absence.
    # Tests of typing/away states override this canonical adapter explicitly.
    monkeypatch.setattr('services.activity.log.idle_seconds', lambda: 10)
    monkeypatch.setattr(proactive_watcher, "_held", [])
    # ...nor the real journal folder (Documents\FRIDAY Journal)
    monkeypatch.setattr(proactive_watcher.journal, "JOURNAL_DIR", tmp_path / "journal")
    # ...nor the real timetable
    monkeypatch.setattr(proactive_watcher.timetable, "path", tmp_path / "timetable.json")
    monkeypatch.setattr(proactive_watcher.timetable, "_warned", set())
    monkeypatch.setattr(proactive_watcher.timetable, "subjects_path", tmp_path / "subjects.json")
    monkeypatch.setattr(proactive_watcher.deadlines, "path", tmp_path / "deadlines.json")
    monkeypatch.setattr(proactive_watcher.attendance, "path", tmp_path / "attendance.json")
    monkeypatch.setattr(proactive_watcher.college, "path", tmp_path / "college.json")
    monkeypatch.setattr(proactive_watcher.college, "_offered", set())
    # ...nor the real Everything: no installed app is found unless a test says so
    monkeypatch.setattr(app_finder, "_everything", lambda args: [])
    # ...nor real windows: no app has a window open, and nothing real is ever closed
    monkeypatch.setattr(app_finder, "app_windows", lambda is_app: [])
    monkeypatch.setattr(app_finder, "close_windows", lambda hwnds: pytest.fail("a test tried to close real windows"))
    monkeypatch.setattr(app_finder, "minimize_windows", lambda hwnds: pytest.fail("a test tried to minimize real windows"))
    monkeypatch.setattr(app_finder, "bring_to_front", lambda hwnd: pytest.fail("a test tried to focus a real window"))
    # ...nor the real connection: online unless a test says otherwise
    monkeypatch.setattr(network, "online", True)
    monkeypatch.setattr(network, "reason", None)
    # ...nor the real projects
    monkeypatch.setattr(projects, "path", tmp_path / "projects.json")
    monkeypatch.setattr(projects, "_cache", None)
    # ...nor the real contacts, and nothing is ever sent
    monkeypatch.setattr(whatsapp, "path", tmp_path / "contacts.json")
    monkeypatch.setattr(whatsapp.os, "startfile", lambda target: pytest.fail(f"a test tried to open {target}"))
    # ...nor the real Telegram bot: nothing is ever sent, and remote control isn't locked
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", 0)
    monkeypatch.setattr(telegram, "state_path", tmp_path / "telegram.json")
    monkeypatch.setattr(telegram_commands, "_pending_files", {})
    monkeypatch.setattr(telegram, "call", lambda method, **kw: pytest.fail(f"a test called Telegram's {method}"))
    monkeypatch.setattr(telegram_bot, "RECEIVED_DIR", tmp_path / "received")
    monkeypatch.setattr(telegram_bot, "_reveal", lambda path: None)
    monkeypatch.setattr(telegram_summaries, "state_path", tmp_path / "telegram_summaries.json")
    monkeypatch.setattr(telegram_summaries, "_retry_after", {})
    monkeypatch.setattr(telegram_summaries, "_delivered", {})
    monkeypatch.setattr(telegram_summaries, "_busy", False)
    monkeypatch.setattr(file_assistant, "last_results", file_assistant._LastResults())
    # ...nor FRIDAY's jokes (random quips would change exact replies): serious unless a test turns sarcasm on
    serious = tmp_path_factory.mktemp("personality") / "personality.json"  # not in tmp_path: some tests need it empty
    serious.write_text('{"off": true}')
    monkeypatch.setattr(personality, "path", serious)
    monkeypatch.setattr(personality, "_toasted", set())
    # ...nor the real habit state or training examples, and nothing is learned from a previous test
    monkeypatch.setattr(habits, "state_path", tmp_path / "habits.json")
    monkeypatch.setattr(habits, "examples_path", tmp_path / "habit_examples.jsonl")
    monkeypatch.setattr(habits, "_cache", {})
    monkeypatch.setattr(predict, "bar_log_path", tmp_path / "bar_predictions.jsonl")
    monkeypatch.setattr(insights, "commands_path", tmp_path / "command_examples.jsonl")
    # ...nor the real notes or watches, and no webpage is ever loaded
    monkeypatch.setattr(notes, "path", tmp_path / "notes.json")
    monkeypatch.setattr(notes, "diary_path", tmp_path / "diary.json")
    monkeypatch.setattr(reading_list, "path", tmp_path / "reading_list.json")
    monkeypatch.setattr(reading_list, "last_page", lambda: pytest.fail("a test read the real browser history"))
    # ...nor the real speech speed or wake log
    monkeypatch.setattr(tts_module, "SPEED_PATH", tmp_path / "voice.json")
    monkeypatch.setattr(tts_module.tts, "rate", 0)
    monkeypatch.setattr(wake, "LOG_PATH", tmp_path / "wake_log.jsonl")
    # ...nor FRIDAY's real learned humour or profile
    monkeypatch.setattr(humour, "path", tmp_path / "mind" / "humour.json")
    monkeypatch.setattr(reflection, "path", tmp_path / "mind" / "profile.json")
    monkeypatch.setattr(reflection, "messages_on", lambda day: [])  # never the Boss's real chat (it went to a real model)
    monkeypatch.setattr(corrections, "path", tmp_path / "mind" / "corrections.json")
    monkeypatch.setattr(corrections, "_last", {})
    monkeypatch.setattr(talk, "path", tmp_path / "mind" / "talk.json")
    monkeypatch.setattr(wonder, "path", tmp_path / "mind" / "wonder.json")
    monkeypatch.setattr(talk, "_was_away", False)
    monkeypatch.setattr(talk, "_back_until", 0.0)
    monkeypatch.setattr(talk, "_asks", None)
    monkeypatch.setattr(talk, "_launch_pending", False)  # tests that want the launch question set it
    monkeypatch.setattr(talk, "mic_in_use", lambda: False)
    # ...nor her real brain: she starts out knowing nothing, noticing nothing, feeling nothing
    monkeypatch.setattr(knowledge, "db_path", str(tmp_path / "mind" / "brain.db"))
    monkeypatch.setattr(categories, "LEARNED", {"app": {}, "title": {}})
    monkeypatch.setattr(life, "path", tmp_path / "mind" / "life.json")
    monkeypatch.setattr(life, "diary_path", tmp_path / "mind" / "diary.jsonl")
    monkeypatch.setattr(brain, "_cur", None)
    monkeypatch.setattr(brain, "_switches", brain._switches.__class__(maxlen=60))
    monkeypatch.setattr(brain, "_away_since", None)
    monkeypatch.setattr(brain, "_next_lookup", None)
    monkeypatch.setattr(evening, "path", tmp_path / "mind" / "evening.json")
    monkeypatch.setattr(evening, "answers_path", tmp_path / "mind" / "evening.jsonl")
    monkeypatch.setattr(foresight, "_counts", None)
    monkeypatch.setattr(foresight, "_pending", None)
    monkeypatch.setattr(foresight, "_act", lambda *a: pytest.fail("a test let FRIDAY open an app by herself"))
    monkeypatch.setattr(learner, "shadow_path", tmp_path / "mind" / "next_app_shadow.pkl")
    monkeypatch.setattr(brain, "_started", True)  # tests that want the first-run catch-up call brain.start()
    monkeypatch.setattr(learner, "model_path", tmp_path / "mind" / "next_app.pkl")
    monkeypatch.setattr(learner, "scores_path", tmp_path / "mind" / "learner.json")
    # ...nor the real app limits or Downloads
    monkeypatch.setattr(limits, "path", tmp_path / "app_limits.json")
    monkeypatch.setattr(limits, "_told", set())
    monkeypatch.setattr(installers, "DOWNLOADS", tmp_path / "Downloads")
    monkeypatch.setattr(installers, "_recycle", lambda files: pytest.fail("a test tried to use the real Recycle Bin"))
    monkeypatch.setattr(filing, "COLLEGE_DIR", tmp_path / "College")
    monkeypatch.setattr(watches, "path", tmp_path / "watches.json")
    monkeypatch.setattr(watches, "_programs", {})
    monkeypatch.setattr(watches, "_logs", {})
    monkeypatch.setattr(watches, "_battery", None)
    monkeypatch.setattr(watches, "_next_web_check", 0.0)
    monkeypatch.setattr(watches, "fingerprint", lambda url: pytest.fail(f"a test tried to load {url}"))
