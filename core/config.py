"""
core/config.py

Central configuration for F.R.I.D.A.Y.
Reads from .env file and environment variables.
This is the ONLY place settings should be defined.

To add a new setting:
  1. Add it here with a sensible default
  2. Add it to .env.example
  3. That's it — no other file should need changing
"""

import os
import re
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (the folder containing this project)
load_dotenv()

VALID_PROVIDERS = ("openrouter", "anthropic", "openai", "ollama")

# Added to every system prompt, even a custom SYSTEM_PROMPT from .env
REPLY_RULES = (
    "Your replies are shown as plain text and are often read aloud, so never use markdown, "
    "asterisks, bullet symbols or emoji. "
    "You cannot control the computer from a chat reply: FRIDAY's command system runs commands "
    "(apps, music, volume, reminders) before a message ever reaches you, so if you are being asked, "
    "the command was not recognised. Never claim or act out doing something you didn't do, such as "
    "playing, pausing or skipping music, opening apps or changing settings. Say plainly that you "
    "can't do that. If one of these real commands comes close, suggest it exactly as written: "
    "\"play music\", \"pause\", \"next song\", \"previous song\", \"what's playing\", "
    "\"play <song name>\", \"play my <name> playlist\", \"play my liked songs\", \"shuffle on\", "
    "\"repeat this song\", \"add <song> to the queue\", \"like this song\", \"connect Spotify\", "
    "\"open <app>\", \"volume up\", \"remind me in 10 minutes to <task>\". "
    "Never invent other commands."
)


def _safe_int(env_key: str, default: int) -> int:
    """
    Read an environment variable as an integer.
    If the value is missing or not a valid number, return the default.
    This prevents a crash at import time if someone types a bad value in .env.
    """
    raw = os.getenv(env_key, "").strip() or str(default)  # blank ("KEY=") = not set
    try:
        return int(raw)
    except ValueError:
        # Bad value in .env — fall back to default silently
        # The logger isn't available yet at this point, so we print as a one-time warning
        print(f"[CONFIG WARNING] {env_key}='{raw}' is not a valid integer — using default: {default}")
        return default


class Config:
    """
    Single config object. Import the singleton `config` below, not this class.
    All settings have safe defaults so the app doesn't crash on missing values.
    """

    # ── Provider settings ────────────────────────────────────────────────────
    # Which AI provider to use by default: "openrouter" | "anthropic" | "openai" | "ollama"
    # DEFAULT is openrouter — one key gives access to 200+ models
    ACTIVE_PROVIDER: str = os.getenv("ACTIVE_PROVIDER", "openrouter")
    # Local execution; models understand language and provide conversational replies.
    AI_ASSIST_ONLY: bool = os.getenv("AI_ASSIST_ONLY", "true").lower() == "true"
    AI_LANGUAGE_ENABLED: bool = os.getenv("AI_LANGUAGE_ENABLED", "true").lower() == "true"
    # Explicit owner-started tasks; generated inputs always require step approval.
    BROWSER_AUTOMATION_ENABLED: bool = os.getenv("BROWSER_AUTOMATION_ENABLED", "true").lower() == "true"
    AI_WORDING_ENABLED: bool = os.getenv("AI_WORDING_ENABLED", "true").lower() == "true"
    AI_KNOWLEDGE_ENABLED: bool = os.getenv("AI_KNOWLEDGE_ENABLED", "true").lower() == "true"
    # Notification review is purpose-scoped; it cannot generate general replies or tools.
    NOTIFICATION_REVIEW_ENABLED: bool = os.getenv("NOTIFICATION_REVIEW_ENABLED", "true").lower() == "true"
    NOTIFICATION_REVIEW_TIMEOUT_SECONDS: int = _safe_int("NOTIFICATION_REVIEW_TIMEOUT_SECONDS", 20)
    NOTIFICATION_REVIEW_RETRY_SECONDS: int = _safe_int("NOTIFICATION_REVIEW_RETRY_SECONDS", 60)
    AI_WORDING_TIMEOUT_SECONDS: int = _safe_int("AI_WORDING_TIMEOUT_SECONDS", 8)
    OLLAMA_AUTO_START: bool = os.getenv("OLLAMA_AUTO_START", "true").lower() == "true"
    OLLAMA_IDLE_SECONDS: int = _safe_int("OLLAMA_IDLE_SECONDS", 300)
    OLLAMA_START_TIMEOUT_SECONDS: int = _safe_int("OLLAMA_START_TIMEOUT_SECONDS", 10)
    EVENING_QUESTION_LIMIT: int = _safe_int("EVENING_QUESTION_LIMIT", 8)
    LEARNING_SESSION_QUESTIONS: int = _safe_int("LEARNING_SESSION_QUESTIONS", 20)
    QUESTION_RETRY_HOURS: int = _safe_int("QUESTION_RETRY_HOURS", 24)

    # ── OpenRouter (RECOMMENDED — one key, all models) ───────────────────────
    # Get your free key at: https://openrouter.ai
    # Browse models at:     https://openrouter.ai/models
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    # Default model — change this to any model on OpenRouter
    # Examples:
    #   "anthropic/claude-sonnet-4-5"         ← Claude Sonnet (smart, balanced)
    #   "anthropic/claude-haiku-4-5"           ← Claude Haiku (fast, cheap)
    #   "openai/gpt-4o"                        ← GPT-4o
    #   "openai/gpt-4o-mini"                   ← GPT-4o mini (cheap)
    #   "meta-llama/llama-3.1-8b-instruct"    ← Llama 3.1 (free tier)
    #   "google/gemini-flash-1.5"             ← Gemini Flash (fast + cheap)
    #   "mistralai/mistral-7b-instruct"       ← Mistral 7B (free tier)
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "anthropic/claude-haiku-4-5")
    # Tried in order when a model is busy/rate-limited (comma-separated). Mix companies:
    # free models are rate-limited per upstream provider, so one busy provider can't take them all down.
    OPENROUTER_BACKUP_MODELS: list[str] = [
        m.strip() for m in os.getenv("OPENROUTER_BACKUP_MODELS", "").split(",") if m.strip()
    ]

    # ── Direct provider keys (optional — only needed if not using OpenRouter) ─
    ANTHROPIC_API_KEY: str  = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str    = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # ── Ollama (local models — no API key needed) ────────────────────────────
    # Requires Ollama installed and running: https://ollama.com
    # Pull a model first: ollama pull qwen2.5:3b-instruct-q5_K_M
    # Default: qwen2.5 3B (fast on a laptop, supports tool calling). It's also the
    # offline model — used whenever the APIs fail or there's no internet.
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str    = os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct-q5_K_M")

    # ── Semantic memory (services/memory/semantic.py) ────────────────────────
    # When true, a cheap AI model pulls lasting facts ("I'm vegetarian") out of
    # your chat messages in the background. "remember that …" works either way.
    SEMANTIC_MEMORY_LEARN: bool = os.getenv("SEMANTIC_MEMORY_LEARN", "true").lower() == "true"

    # ── Activity log (services/activity/log.py) ──────────────────────────────
    # Records which app is in the foreground and every command FRIDAY runs,
    # locally, as data for learning your habits. App names only.
    ACTIVITY_LOG_ENABLED: bool = os.getenv("ACTIVITY_LOG_ENABLED", "true").lower() == "true"

    # ── Morning briefing and nudges (services/proactive/) ────────────────────
    # The briefing plays the first time you're at the laptop each day after
    # BRIEFING_AFTER_HOUR. WEATHER_CITY blank = no weather (Open-Meteo, no key).
    # Nudges (low battery, hot GPU, long app stretches, low disk) are silent notifications.
    BRIEFING_ENABLED: bool = os.getenv("BRIEFING_ENABLED", "true").lower() == "true"
    BRIEFING_AFTER_HOUR: int = _safe_int("BRIEFING_AFTER_HOUR", 6)
    WEATHER_CITY: str = os.getenv("WEATHER_CITY", "").strip()
    # Telegram summaries use the laptop's local time, every day; blank hour = off.
    TELEGRAM_BRIEFING_HOUR: str = os.getenv("TELEGRAM_BRIEFING_HOUR", "7").strip()
    TELEGRAM_NIGHTLY_HOUR: str = os.getenv("TELEGRAM_NIGHTLY_HOUR", "21").strip()
    TELEGRAM_WEEKLY_HOUR: str = os.getenv("TELEGRAM_WEEKLY_HOUR", "21").strip()
    TELEGRAM_WEEKLY_DAY: int = _safe_int("TELEGRAM_WEEKLY_DAY", 6)  # Monday=0, Sunday=6
    # The campus Wi-Fi's login page host (services/network/campus.py); blank = never sign in automatically
    CAMPUS_WIFI_PORTAL: str = os.getenv("CAMPUS_WIFI_PORTAL", "captiveportal.reva.edu.in").strip()
    NUDGES_ENABLED: bool = os.getenv("NUDGES_ENABLED", "true").lower() == "true"
    LONG_APP_HOURS: int = _safe_int("LONG_APP_HOURS", 3)

    # ── Telegram bot (services/telegram/) ────────────────────────────────────
    # Blank token = off. Only TELEGRAM_USER_ID is answered. Notifications also go
    # to Telegram once you've been idle for TELEGRAM_AWAY_MINUTES.
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_USER_ID: int = _safe_int("TELEGRAM_USER_ID", 0)
    TELEGRAM_AWAY_MINUTES: int = _safe_int("TELEGRAM_AWAY_MINUTES", 10)

    # ── "It's done" alerts (services/watch/) ─────────────────────────────────
    # Claude Code replies and terminal commands are reported once they took
    # DONE_MIN_MINUTES; heavy CPU/GPU work once it ran HEAVY_WORK_MINUTES;
    # "tell me when <url> changes" checks the page every WEB_WATCH_MINUTES.
    DONE_MIN_MINUTES: int = _safe_int("DONE_MIN_MINUTES", 2)
    HEAVY_WORK_MINUTES: int = _safe_int("HEAVY_WORK_MINUTES", 10)
    WEB_WATCH_MINUTES: int = _safe_int("WEB_WATCH_MINUTES", 10)

    # ── Quick chat on the local model ────────────────────────────────────────
    # Short, simple messages ("how are you", "capital of Australia") try the local
    # Ollama model first (~0.5 s), then the usual providers; anything needing more
    # thought (code, explanations, answers from files/web) keeps the main model.
    # See providers/failover.py:is_quick_chat.
    QUICK_CHAT_LOCAL: bool = os.getenv("QUICK_CHAT_LOCAL", "true").lower() == "true"
    REASONING_ENABLED: bool = os.getenv("REASONING_ENABLED", "true").lower() == "true"
    # Scoped evidence review/proposals, also permitted in assist-only mode.
    COGNITIVE_REVIEW_ENABLED: bool = os.getenv("COGNITIVE_REVIEW_ENABLED", "true").lower() == "true"

    # ── Command detection (intent classifier) ────────────────────────────────
    # When a message looks like a command but no local rule matches, an AI
    # decides which system tools (if any) to call, using native tool calling.
    # That's a small task, so it runs on a cheap, fast model that handles tools
    # well, instead of the chat model.
    #   Both blank → the chat provider, using its cheap default below
    #   Both set   → exactly that provider + model (e.g. ollama + gemma3:4b)
    INTENT_PROVIDER: str = os.getenv("INTENT_PROVIDER", "")
    INTENT_MODEL: str    = os.getenv("INTENT_MODEL", "")
    INTENT_DEFAULT_MODELS: dict[str, str] = {
        "openrouter": "openai/gpt-4o-mini",  # small Llama models are unreliable with tools
        "anthropic":  "claude-haiku-4-5",
        "openai":     "gpt-4o-mini",
        # No ollama entry: local models are already free, so it keeps OLLAMA_MODEL
    }

    # ── Screen questions (vision) ────────────────────────────────────────────
    # "What's on my screen?" sends a screenshot to a model that can read images.
    # Many chat models can't (e.g. Llama 3.1 8B), so these use their own model.
    #   Both blank → the chat provider, using its vision default below
    #   Both set   → exactly that provider + model
    VISION_PROVIDER: str = os.getenv("VISION_PROVIDER", "")
    VISION_MODEL: str    = os.getenv("VISION_MODEL", "")
    # Separate image-capable backups; ordinary chat backups may not see images.
    # Blank means only the selected OpenRouter vision model is tried.
    OPENROUTER_VISION_BACKUP_MODELS: list[str] = [
        m.strip() for m in os.getenv("OPENROUTER_VISION_BACKUP_MODELS", "").split(",") if m.strip()
    ]
    VISION_DEFAULT_MODELS: dict[str, str] = {
        "openrouter": "openai/gpt-4o-mini",
        "anthropic":  "claude-haiku-4-5",
        "openai":     "gpt-4o-mini",
        # No ollama entry: it uses OLLAMA_MODEL, which must be a vision model (e.g. gemma3:4b)
    }

    def vision_model_for(self, provider: str) -> str | None:
        """The model screen questions use on this provider (None = its .env model)."""
        if self.VISION_MODEL and provider == self.VISION_PROVIDER:
            return self.VISION_MODEL
        return self.VISION_DEFAULT_MODELS.get(provider)

    # ── Provider failover ────────────────────────────────────────────────────
    # If the chat provider fails (outage, rate limit, bad key, Ollama not running),
    # FRIDAY retries on these providers, in order.
    #   Blank  → every other provider that's set up (has an API key), then Ollama
    #   "none" → never fall back — e.g. so a paid provider is never used silently
    #   List   → exactly these, e.g. "anthropic, ollama"
    FALLBACK_PROVIDERS: str = os.getenv("FALLBACK_PROVIDERS", "")

    # ── Spotify (optional, needs Premium) ────────────────────────────────────
    # The Client ID of your own app at developer.spotify.com/dashboard. With it,
    # "connect Spotify" logs in once and FRIDAY can really play songs, playlists
    # and liked songs, shuffle, repeat, queue and like songs. Without it, music
    # commands still control whatever player is open.
    SPOTIFY_CLIENT_ID: str = os.getenv("SPOTIFY_CLIENT_ID", "").strip()

    @property
    def SPOTIFY_REDIRECT_URI(self) -> str:
        # Spotify only accepts plain http for an explicit loopback IP (never "localhost")
        return f"http://127.0.0.1:{self.API_PORT}/api/v1/spotify/callback"

    # ── File search ──────────────────────────────────────────────────────────
    # FRIDAY indexes these folders in the background: every file by name, and
    # the text inside documents, PDFs, Office files and code. Then "find my
    # resume" finds files and "what do my notes say about X" answers from them.
    # Semicolon-separated. Blank = Documents, Desktop and Downloads.
    FILE_SEARCH_FOLDERS: str = os.getenv("FILE_SEARCH_FOLDERS", "")
    FILE_SEARCH_ENABLED: bool = os.getenv("FILE_SEARCH_ENABLED", "true").lower() == "true"
    # Runs locally (on the GPU if there is one); downloaded once from Hugging Face
    FILE_SEARCH_EMBED_MODEL: str = os.getenv("FILE_SEARCH_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    FILE_SEARCH_RESCAN_MINUTES: int = _safe_int("FILE_SEARCH_RESCAN_MINUTES", 30)

    def file_search_folders(self) -> list[Path]:
        if self.FILE_SEARCH_FOLDERS.strip():
            return [Path(os.path.expandvars(p.strip())).expanduser()
                    for p in self.FILE_SEARCH_FOLDERS.split(";") if p.strip()]
        home = Path.home()
        return [home / "Documents", home / "Desktop", home / "Downloads"]

    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "small")

    # ── "Hey Friday" (services/voice/wake.py) ────────────────────────────────
    # Only listened for while switched on (tray menu or Ctrl+Alt+H). A phrase has
    # to start what you say; whatever follows is the command. Switches itself off
    # after WAKE_AUTO_OFF_MINUTES without hearing one.
    WAKE_PHRASES: str = os.getenv("WAKE_PHRASES", "hey friday,hi friday,ok friday,okay friday,hello friday,k friday,hay friday")  # "k"/"hay": how Parakeet sometimes hears a quick "hey"
    WAKE_AUTO_OFF_MINUTES: int = _safe_int("WAKE_AUTO_OFF_MINUTES", 30)

    def wake_phrases(self) -> list[str]:
        return [p.strip().lower() for p in self.WAKE_PHRASES.split(",") if p.strip()]
    EDGE_TTS_VOICE: str = os.getenv("EDGE_TTS_VOICE", "en-US-AriaNeural")  # quick to start (the Irish voice lagged 4–7 s)
    # Used instead when a reply is written in Hindi (Devanagari script)
    EDGE_TTS_HINDI_VOICE: str = os.getenv("EDGE_TTS_HINDI_VOICE", "hi-IN-SwaraNeural")
    # Evening notification listing saved projects with uncommitted git changes (hour, 0-23; blank = off)
    GIT_REMINDER_HOUR: str = os.getenv("GIT_REMINDER_HOUR", "21")
    # Your section, when a timetable covers several (e.g. II-A): only its classes are read
    TIMETABLE_SECTION: str = os.getenv("TIMETABLE_SECTION", "")
    # Hour the daily journal (Documents\FRIDAY Journal) is written, with a notification (blank = off)
    JOURNAL_HOUR: str = os.getenv("JOURNAL_HOUR", "22")
    # First day of this semester (YYYY-MM-DD) for "semester wrap-up"; blank = since FRIDAY started logging
    SEMESTER_START: str = os.getenv("SEMESTER_START", "").strip()
    # Offline voice (Piper, runs on the CPU). Downloaded once into memory/piper/ while online.
    # Voices: https://huggingface.co/rhasspy/piper-voices (e.g. en_US-amy-medium, en_US-ryan-high)
    PIPER_VOICE: str = os.getenv("PIPER_VOICE", "en_US-hfc_female-medium")

    # ── Memory settings ──────────────────────────────────────────────────────
    MEMORY_DB_PATH: str       = os.getenv("MEMORY_DB_PATH", "memory/friday.db")
    # Safe int — won't crash if someone types a bad value in .env
    MAX_HISTORY_MESSAGES: int = _safe_int("MAX_HISTORY_MESSAGES", 10)
    COGNITION_ENABLED: bool = os.getenv("COGNITION_ENABLED", "true").lower() == "true"
    COGNITION_MAX_EVENTS: int = _safe_int("COGNITION_MAX_EVENTS", 500)
    COGNITION_EVENT_CHARS: int = _safe_int("COGNITION_EVENT_CHARS", 16000)
    COGNITION_PROMPT_CHARS: int = _safe_int("COGNITION_PROMPT_CHARS", 3200)
    LEARNING_DATA_ENABLED: bool = os.getenv("LEARNING_DATA_ENABLED", "true").lower() == "true"
    LEARNING_MIN_SESSION_SECONDS: int = _safe_int("LEARNING_MIN_SESSION_SECONDS", 5)
    LEARNING_MAX_GAP_SECONDS: int = _safe_int("LEARNING_MAX_GAP_SECONDS", 60)
    LEARNING_AUTOMATION_WINDOW_SECONDS: int = _safe_int("LEARNING_AUTOMATION_WINDOW_SECONDS", 60)

    # ── API / server settings ────────────────────────────────────────────────
    API_HOST: str  = os.getenv("API_HOST", "127.0.0.1")
    # Safe int — won't crash if someone types a bad value in .env
    API_PORT: int  = _safe_int("API_PORT", 8000)
    DEBUG: bool    = os.getenv("DEBUG", "true").lower() == "true"
    # Auto-restart the server when code changes (defaults to DEBUG). launch_friday.vbs
    # turns it off: the reloader runs the server in a child process that can outlive
    # a shutdown and keep answering on the port with old code.
    API_RELOAD: bool = os.getenv("API_RELOAD", os.getenv("DEBUG", "true")).lower() == "true"

    # ── Paths ────────────────────────────────────────────────────────────────
    ROOT_DIR:   Path = Path(__file__).parent.parent
    MEMORY_DIR: Path = ROOT_DIR / "memory"
    LOGS_DIR:   Path = ROOT_DIR / "logs"

    # ── System prompt ────────────────────────────────────────────────────────
    # Centralised here so it's easy to change without hunting through code
    @property
    def SYSTEM_PROMPT(self) -> str:
        from datetime import datetime
        now = datetime.now().astimezone()  # read on every request, so the time is always current
        today = f"{now:%A, %B %d, %Y}, and the local time is {now:%I:%M %p} ({now.tzname()})"
        from services.automation import personality  # sarcastic unless "be serious" (imported late: no cycle)

        from services.mind import humour, reflection  # FRIDAY's learned notes and sense of humour
        from services.proactive import timetable
        from services.telegram import capabilities as telegram_capabilities
        from services.mind import cognition_context, training
        from services.mind import reasoning
        from services.memory import schedule

        base = os.getenv("SYSTEM_PROMPT") or (personality.PERSONA if personality.is_on() else personality.PLAIN)
        extras = [personality.now_line(), humour.dial() if personality.is_on() else "", reflection.prompt_section(),
                  timetable.prompt_line(now.replace(tzinfo=None)), telegram_capabilities.prompt_section(),
                  cognition_context.prompt_section(), training.prompt_section(), schedule.prompt_section(now), reasoning.prompt_section(now)]
        return (f"{base}\n{REPLY_RULES}\nToday's date is {today}. This comes from the user's own clock, so you do "
                "know the current date and time: use it, and never say you can't access a clock."
                + "".join(f"\n{extra}" for extra in extras if extra))

    def provider_is_configured(self, name: str) -> bool:
        """Has what it needs to be tried: an API key, or for Ollama a URL and model."""
        return bool({
            "openrouter": self.OPENROUTER_API_KEY,
            "anthropic":  self.ANTHROPIC_API_KEY,
            "openai":     self.OPENAI_API_KEY,
            "ollama":     self.OLLAMA_BASE_URL and self.OLLAMA_MODEL,
        }.get(name))

    def fallback_providers(self) -> list[str]:
        """Providers to retry on, in order, when the chat provider fails."""
        setting = self.FALLBACK_PROVIDERS.strip().lower()
        if setting == "none":
            return []
        if setting:
            return [name.strip() for name in setting.split(",") if name.strip()]
        return [name for name in VALID_PROVIDERS if self.provider_is_configured(name)]

    def validate(self) -> list[str]:
        """
        Check that required settings are present and valid.
        Returns a list of error strings. Empty list = all good.
        Call this at startup before doing anything else.
        """
        errors = []

        # ── Provider key checks ──────────────────────────────────────────────
        if not self.AI_ASSIST_ONLY and self.ACTIVE_PROVIDER == "openrouter" and not self.OPENROUTER_API_KEY:
            errors.append("OPENROUTER_API_KEY is missing — get your free key at openrouter.ai")

        if not self.AI_ASSIST_ONLY and self.ACTIVE_PROVIDER == "anthropic" and not self.ANTHROPIC_API_KEY:
            errors.append("ANTHROPIC_API_KEY is missing — add it to your .env file")

        if not self.AI_ASSIST_ONLY and self.ACTIVE_PROVIDER == "openai" and not self.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY is missing — add it to your .env file")

        # ── Ollama checks ────────────────────────────────────────────────────
        # Ollama doesn't need an API key, but the base URL must be set
        if not self.AI_ASSIST_ONLY and self.ACTIVE_PROVIDER == "ollama":
            if not self.OLLAMA_BASE_URL:
                errors.append(
                    "OLLAMA_BASE_URL is missing — add it to .env (default: http://localhost:11434)"
                )
            if not self.OLLAMA_MODEL:
                errors.append(
                    "OLLAMA_MODEL is missing — add it to .env (example: qwen2.5:3b-instruct-q5_K_M)"
                )

        # ── Provider name check ──────────────────────────────────────────────
        if self.ACTIVE_PROVIDER not in VALID_PROVIDERS:
            errors.append(
                f"ACTIVE_PROVIDER='{self.ACTIVE_PROVIDER}' is not valid. "
                "Use: openrouter | anthropic | openai | ollama"
            )

        # ── Command detection checks ─────────────────────────────────────────
        if self.INTENT_PROVIDER and self.INTENT_PROVIDER not in VALID_PROVIDERS:
            errors.append(
                f"INTENT_PROVIDER='{self.INTENT_PROVIDER}' is not valid. "
                "Use: openrouter | anthropic | openai | ollama — or leave it blank"
            )
        if self.INTENT_MODEL and not self.INTENT_PROVIDER:
            errors.append(
                "INTENT_MODEL is set but INTENT_PROVIDER isn't — set both, or leave both blank"
            )
        if not self.AI_ASSIST_ONLY and self.INTENT_PROVIDER in ("openrouter", "anthropic", "openai") and not self.provider_is_configured(self.INTENT_PROVIDER):
            errors.append(
                f"INTENT_PROVIDER={self.INTENT_PROVIDER} needs its API key in .env — "
                "add it, or leave INTENT_PROVIDER blank"
            )

        # ── Screen question checks ───────────────────────────────────────────
        if self.VISION_PROVIDER and self.VISION_PROVIDER not in VALID_PROVIDERS:
            errors.append(
                f"VISION_PROVIDER='{self.VISION_PROVIDER}' is not valid. "
                "Use: openrouter | anthropic | openai | ollama — or leave it blank"
            )
        if self.VISION_MODEL and not self.VISION_PROVIDER:
            errors.append(
                "VISION_MODEL is set but VISION_PROVIDER isn't — set both, or leave both blank"
            )
        if not self.AI_ASSIST_ONLY and self.VISION_PROVIDER in ("openrouter", "anthropic", "openai") and not self.provider_is_configured(self.VISION_PROVIDER):
            errors.append(
                f"VISION_PROVIDER={self.VISION_PROVIDER} needs its API key in .env — "
                "add it, or leave VISION_PROVIDER blank"
            )

        # ── Failover checks ──────────────────────────────────────────────────
        if self.FALLBACK_PROVIDERS.strip().lower() not in ("", "none"):
            for name in self.fallback_providers():
                if name not in VALID_PROVIDERS:
                    errors.append(
                        f"FALLBACK_PROVIDERS has '{name}', which isn't a provider. "
                        "Use: openrouter | anthropic | openai | ollama — or 'none'"
                    )
                elif not self.AI_ASSIST_ONLY and not self.provider_is_configured(name):
                    errors.append(
                        f"FALLBACK_PROVIDERS lists {name}, but it isn't set up in .env — "
                        "add its API key or remove it from the list"
                    )

        # ── Value range checks ───────────────────────────────────────────────
        if self.MAX_HISTORY_MESSAGES < 1:
            errors.append("MAX_HISTORY_MESSAGES must be at least 1")
        for setting, minimum in (("COGNITION_MAX_EVENTS", 1), ("COGNITION_EVENT_CHARS", 1),
                                 ("COGNITION_PROMPT_CHARS", 600), ("LEARNING_MIN_SESSION_SECONDS", 1),
                                 ("LEARNING_MAX_GAP_SECONDS", 1), ("LEARNING_AUTOMATION_WINDOW_SECONDS", 1)):
            if getattr(self, setting) < minimum:
                errors.append(f"{setting} must be at least {minimum}")

        if self.FILE_SEARCH_RESCAN_MINUTES < 1:
            errors.append("FILE_SEARCH_RESCAN_MINUTES must be at least 1")
        if not 0 <= self.BRIEFING_AFTER_HOUR <= 23:
            errors.append("BRIEFING_AFTER_HOUR must be an hour from 0 to 23")
        if not self.wake_phrases():
            errors.append("WAKE_PHRASES needs at least one phrase, like \"hey friday\"")
        if self.WAKE_AUTO_OFF_MINUTES < 1:
            errors.append("WAKE_AUTO_OFF_MINUTES must be at least 1")
        if self.LONG_APP_HOURS < 1:
            errors.append("LONG_APP_HOURS must be at least 1")

        if not (1 <= self.API_PORT <= 65535):
            errors.append(f"API_PORT={self.API_PORT} is not a valid port number (must be 1–65535)")

        return errors

    def ensure_dirs(self):
        """Create required runtime directories if they don't exist yet."""
        self.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self.LOGS_DIR.mkdir(parents=True, exist_ok=True)


# ── Singleton ────────────────────────────────────────────────────────────────
# Import this everywhere. Never instantiate Config() yourself.
config = Config()
