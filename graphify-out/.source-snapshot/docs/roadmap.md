# roadmap.md
# F.R.I.D.A.Y — Development Roadmap

Philosophy: slow, deliberate, sustainable.
One solid layer at a time. Nothing ships broken.

**Deferred wiring/debugging audit (2026-10-15):** saved at
[`wiring-audit-2026-10-15.md`](wiring-audit-2026-10-15.md). Nine open findings cover
capability policy, confirmation ownership, reminder delivery, keyboard execution,
file-result isolation, mode cleanup, combined speech and CLI input limits. Includes
reproductions and remaining live trials. Owner requested fixing these later; no fixes applied.

**Assistant upgrade direction (2026-10-15):** the owner-approved eight-part roadmap is saved in
[`assistant-roadmap.md`](assistant-roadmap.md), with capability dependencies, flagship experiences and
evaluation priorities. Work starts with persistent execution. The first implemented workflow prepares
verified local task handoffs with durable checkpoints; arbitrary tool-plan execution remains future work.

Shared cognition milestone (2026-10-12): one bounded local event record connects replies, notifications,
actions, Telegram sends, speech status, activity categories and proactive questions/reactions. The existing
brain and shared AI prompt read the same facts/live state; direct recall commands expose recorded evidence.
This implements continuity and event awareness. Human consciousness isn't a software acceptance claim;
longer-range planning and interpreting unseen application state remain separate work.

Telegram milestone (2026-10-12): FRIDAY knows its integrated bot through the shared system prompt.
Laptop chat/voice can send files and on-demand reports to the configured recipient; scheduled reports
run daily at 07:00, nightly at 21:00 and Sunday at 21:00, with persisted delivery markers and retries.
Live bot/recipient connectivity was verified. Reports require the laptop and FRIDAY to be running.

Computer agent milestone (2026-10-11): the first supervised desktop loop is implemented.
`\c <task>` in the command bar proposes one action; `\c yes` approves that step and gets a fresh
vision check. Click/double-click, scroll, Unicode text and keys are supported. Context is temporary;
each step requires approval, expires after 120 seconds, and is checked against window/control focus
and visible changes. Tasks have a 20-step limit. Still pending: a live user trial, unattended execution,
voice entry, drag/drop, and semantic UI targeting beyond screenshot coordinates.

---

## Phase Overview

| Phase | Theme | Duration | Goal |
|---|---|---|---|
| Phase 1 | Foundation | 2 weeks | Working chat with memory |
| Phase 2 | Voice + Search | 3 weeks | Speak to it, it searches |
| Phase 3 | System Control + Plugins | 4 weeks | Controls your laptop |
| Phase 4 | Intelligence + Polish | ongoing | Feels like a real assistant |

---

## Phase 1 — Foundation
**Goal:** User types a message → F.R.I.D.A.Y responds → memory saves → history works.

### Week 1 — Build
| Day | Goal | Tasks |
|---|---|---|
| Day 1 | Project structure | Folders, config, base provider, requirements |
| Day 2 | First provider | Anthropic provider working. Test with Swagger UI |
| Day 3 | Memory | SQLite memory working. History loads in next request |
| Day 4 | API wired up | Full flow: message → AI → save → response |
| Day 5 | Test everything | Manual end-to-end test. Fix anything broken |

### Week 2 — Stabilise
| Day | Goal | Tasks |
|---|---|---|
| Day 1 | Error handling | Catch and handle all failure modes gracefully |
| Day 2 | Logging | Add basic file logging (requests, errors, token usage) |
| Day 3 | Second provider | Add OpenAI provider. Test provider switching |
| Day 4 | Ollama provider | Test with a local model |
| Day 5 | Docs + cleanup | Update all docs. Review code quality. Tag v0.1.0 |

**Phase 1 exit criteria:**
- [ ] POST /api/v1/chat works with all 3 providers
- [ ] Conversation history persists across restarts
- [ ] Config validation catches missing keys at startup
- [ ] No hardcoded values anywhere
- [ ] All docs updated

---

## Phase 2 — Voice + Search
**Goal:** Speak to F.R.I.D.A.Y. It speaks back. It can look things up.

### Week 3 — Voice Input
| Day | Goal | Tasks |
|---|---|---|
| Day 1 | Research | Evaluate Whisper vs alternatives. Choose approach |
| Day 2 | STT service | Build `services/voice/stt.py` using Whisper |
| Day 3 | Voice endpoint | POST /api/v1/voice endpoint accepting audio |
| Day 4 | Test + refine | Test with real voice. Tune for accuracy |
| Day 5 | Docs | Update architecture.md and AI_HANDOFF.md |

### Week 4 — Voice Output
| Day | Goal | Tasks |
|---|---|---|
| Day 1 | Research | Evaluate ElevenLabs vs pyttsx3 (offline). Choose both |
| Day 2 | TTS service | Build `services/voice/tts.py` with ElevenLabs + offline fallback |
| Day 3 | Wire together | Full voice loop: speak → STT → AI → TTS → hear response |
| Day 4 | Test + refine | Test full voice conversation |
| Day 5 | Docs | Update all docs |

### Week 5 — Web Search
| Day | Goal | Tasks |
|---|---|---|
| Day 1 | Research | Evaluate DuckDuckGo vs SerpAPI |
| Day 2 | Search service | Build `services/search/web_search.py` |
| Day 3 | Integrate | AI uses search results to answer questions |
| Day 4 | Test | Test with real research questions |
| Day 5 | Phase 2 review | Tag v0.2.0. Update docs. Plan Phase 3 |

**Phase 2 exit criteria:**
- [ ] Full voice conversation works end-to-end
- [ ] Offline TTS fallback works without internet
- [ ] Web search integrated into responses
- [ ] No regressions from Phase 1

---

## Phase 3 — System Control + Plugins
**Goal:** F.R.I.D.A.Y controls the laptop. Plugin system introduced.

### Week 6-7 — Event Bus + Orchestrator
*This is the most architecturally significant phase. Take your time.*
- Design and build the event bus (in-process pub/sub)
- Build the orchestrator that routes user intent to the right service
- Refactor chat route to go through orchestrator

### Week 8 — System Automation
- Build `services/automation/system_control.py`
- Commands: open app, open file, open URL, run terminal command
- Safety: require confirmation before destructive actions

### Week 9 — Plugin System
- Build `core/plugin_manager/`
- Plugin manifest format (JSON or YAML)
- Load plugins from `/plugins/` directory
- First plugin: a simple clock/calendar plugin

### Week 10 — Phase 3 Review
- Integration testing across all services
- Security review (what should plugins be allowed to do?)
- Tag v0.3.0

---

## Phase 4 — Intelligence + Polish
**Goal:** Feels like a real assistant. Knows you. Thinks ahead.

- Semantic memory (ChromaDB alongside SQLite)
- Memory summarisation (compress old conversations)
- Wake word detection ("Hey Friday")
- Desktop UI (Electron or Tauri floating widget)
- Personality customisation
- Vision (understand screenshots)
- Proactive suggestions

*Phase 4 has no fixed timeline. It evolves continuously.*

---

## Backlog — Candidate Features (not yet scheduled)

Captured for future prioritisation. Nothing here is committed to a phase yet —
pull items up into a phase deliberately, don't build off this list directly.

### Quick wins (small, self-contained, fits existing patterns)
- ~~**Web search**~~ — DONE 2026-09-14. `services/search/web_search.py` (ddgs).
  Triggers: `\s <query>`, "look up …", "search the web for …", "web search …".
  Results go into the system prompt; chat replies cite [1], [2], voice replies don't.
- ~~**More system_control verbs**~~ — DONE 2026-09-14. Close app (graceful, no
  force-kill; refuses Explorer), volume set/up/down/mute (pycaw), brightness
  (WMI, built-in screens only), clipboard read/write (clipboard reads aren't
  saved to chat memory), screenshots to Pictures/Screenshots.
  Note: the older `/api/v1/system` endpoint has its own parser and doesn't
  know these verbs — chat, voice and the popup all use `intent.py` instead.
- ~~**Destructive-action confirmation**~~ — DONE 2026-09-14. Verified it was
  never implemented. Now `organise_folder` asks "Organise Downloads? This moves
  N files…" and only runs on an explicit yes as the very next message (chat,
  voice, popup); "no" or any other message cancels, and it expires after 2
  minutes. The legacy `/api/v1/system` endpoint now refuses to organise.
  `close_app` is intentionally not gated (it closes gracefully, apps still
  prompt to save).
- ~~**Reminders / scheduled tasks**~~ — DONE 2026-09-14. `services/reminders/`
  (no new dependencies). "remind me at 5pm to X" / "in 20 minutes" / "tomorrow
  at 9am", plus "list reminders", "cancel reminder 2", "clear reminders".
  Stored in memory/friday.db (survive restarts); a background loop in the API
  delivers them as a Windows notification + spoken aloud, and reminders missed
  while FRIDAY was off are delivered late on next start.
- ~~**Intent-classifier model routing**~~ — DONE 2026-09-14. The AI fallback
  in `intent.py` now uses a cheap model per provider (`INTENT_DEFAULT_MODELS`
  in config.py: Llama 3.1 8B on OpenRouter, Claude Haiku, GPT-4o-mini; Ollama
  keeps its local model), or `INTENT_PROVIDER` + `INTENT_MODEL` from .env.
  If the cheap model errors or returns bad JSON it retries once on the chat
  model. Providers accept a model override via `get_provider(name, model=...)`.
- ~~**Clipboard history manager**~~ — DONE 2026-09-14. The backend watches the
  clipboard and keeps the last 20 text items in memory only (never on disk or in
  chat memory; items apps mark private, e.g. password managers, are skipped).
  Tray: "Clipboard history" submenu (click to copy back, clear). Chat/voice:
  "clipboard history", "copy clipboard item 3", "clear clipboard history".
  Device-command matching moved to `services/automation/device_commands.py`.
- ~~**Provider auto-failover**~~ — DONE 2026-09-14. `providers/failover.py`: chat
  and voice replies retry on fallback providers when the chosen one fails.
  `FALLBACK_PROVIDERS` in .env: blank = every other provider with an API key,
  then Ollama; a comma-separated order; or "none". Replies report which
  provider actually answered. (The intent classifier keeps its own fallback.)
- **Markdown/code rendering** — BLOCKED: the desktop/web UIs were removed
  (2026-09-14) and the tray/command bar show plain text. Revisit with the new UI.
- ~~**System stats**~~ — DONE 2026-09-17. `services/automation/system_stats.py`:
  "how's my system?", "battery", "cpu usage", "how hot is my gpu", "what's using
  my ram", "why is my laptop so slow" (chat, voice, tray "System stats" submenu).
  psutil + nvidia-smi + one NtQuerySystemInformation call for per-app memory/CPU.
- **Conversation export/import** — dump SQLite history to a portable file and
  restore it, useful before wiping `memory/friday.db` or migrating machines.

### Medium lift (roadmap already names some of these)
- ~~**Semantic memory**~~ — done 2026-09-24 as learned facts in SQLite + local
  embeddings (no ChromaDB). Still open: searching past *conversations* by meaning
  ("what did I say about X weeks ago").
- **Memory summarisation** — compress old conversations so context doesn't
  grow unbounded.
- ~~**Wake word ("Hey Friday")**~~ — DONE 2026-09-24, on demand (the user didn't want
  always-on): tray toggle / Ctrl+Alt+H, auto-off after 30 min. Uses the existing VAD + Whisper
  instead of openWakeWord/Porcupine, so "Hey Friday, <command>" works in one breath.
- **Plugin system** — `plugins/` and `core/plugin_manager/` are still empty
  stubs from the Phase 3 plan; minimal manifest + loader, first plugin a
  clock/calendar.
- ~~**Local file RAG**~~ — DONE 2026-09-21. `services/files/`: Documents,
  Desktop and Downloads (or `FILE_SEARCH_FOLDERS`) indexed in the background;
  "find my …" lists files, "what does my … say" answers from excerpts. Not
  built: OCR for images/scanned PDFs, watching folders live (rescans every 30 min).
- **Usage/cost dashboard** — track token spend per provider across sessions,
  surfaced in the desktop settings panel.
- ~~**Native tool-calling for intent detection**~~ — DONE 2026-09-17. The AI
  fallback in `intent.py` sends the actions as tools
  (`services/automation/command_tools.py`) on all four providers. One message
  can trigger several actions. Still a separate cheap call before chat — merging
  it into the chat call itself is not done.
- ~~**Typing and writing**~~ — DONE 2026-09-21. `services/automation/keyboard.py`,
  `typing_commands.py`, `writer.py`: dictation ("type …"), AI writing ("write …"),
  key presses ("press ctrl+s", "select all"). The backend returns keyboard steps;
  the command bar/tray type them into the app that has focus. Not built: mouse control,
  editing text already on screen, app-specific automation.
- ~~**Music controls**~~ — DONE 2026-09-17. `services/automation/media_control.py`:
  play/pause/next/previous/what's playing via Windows media sessions (winrt),
  "play music", "play <song>" (Spotify search). Not built: shuffle, playlists,
  playing a specific song directly (would need the Spotify Web API).
- ~~**Full Spotify control**~~ — DONE 2026-09-21. `services/spotify/` (Web API,
  PKCE login, Premium only): "play <song>" really plays it; artists, albums, your
  playlists, liked songs; shuffle, repeat, queue, like/unlike. Pause/skip/what's
  playing still go through media_control. Not built: creating/editing playlists
  (Spotify removed playlist creation for dev-mode apps in Feb 2026), podcasts,
  choosing which device plays.
- ~~**Bigger local command vocabulary**~~ — DONE 2026-09-17.
  `services/automation/command_words.py` holds every command word; most
  phrasings ("can you open the browser please", "a bit quieter", "go to github")
  now run without an AI call.
- ~~**Routines**~~ — DONE 2026-09-24. `services/automation/routines.py`: "start work mode"
  runs saved command sentences in order (`memory/routines.json`, editable by hand).
  Only on request — no schedules; the habit engine should suggest them instead.
  Not built: pauses between steps, tray submenu.
- **Named conversation threads** — let memory hold separate contexts (e.g.
  "work" vs "personal") instead of one continuous history.
- **Image input in chat** — let the user paste/attach an image in text mode
  for the AI to analyze, using existing multimodal provider support
  (distinct from the "vision on live screenshots" backlog item below).

### Bigger lift / longer horizon
- ~~**Vision**~~ — DONE 2026-09-17 (on demand). `services/vision/screen.py`:
  "what's on my screen?", "explain the error on my screen", `\v <question>`.
  Captures the monitor under the mouse and asks a vision model
  (`VISION_PROVIDER`/`VISION_MODEL`). Real-time/continuous watching is not built.
- **Proactive suggestions** — PARTLY DONE 2026-09-24: morning briefing and nudges
  (`services/proactive/`). Still open: suggestions learned from habits (the habit engine).
- **Personality customisation** — configurable tone/persona in config instead
  of hardcoded prompts.
- **Focus / do-not-disturb mode** — OS-level integration to mute
  notifications during voice sessions or a declared "focus" state.
- ~~**Voice barge-in**~~ — DONE: Ctrl+Alt+Space stops speech (2026-09-14), and with
  "Hey Friday" switched on, "Hey Friday, …" over FRIDAY interrupts it (2026-09-24).
  Interrupting with plain speech (no wake phrase) would need echo cancellation / headphones.
- **Bilingual speech recognition** — STT is English-only (`language="en"`);
  FRIDAY speaks Hindi but can't transcribe it yet.
- **Speaker recognition** — only act on the owner's voice, ignoring other
  voices picked up by the mic (matters more once wake-word/always-listening
  ships).
- **Encrypted local secrets vault** — replace the plaintext `.env` API keys
  with an OS-keychain-backed store (Windows Credential Manager), reducing
  what's exposed if the machine or repo is compromised.

---

## What We Are Deliberately NOT Building

To avoid scope creep, these are explicitly out of scope:

- Multi-user support
- Cloud hosting or deployment
- Mobile app
- Custom model training
- Paid tier / subscriptions
- Anything requiring a server outside the laptop

---

## Dependency Order

Some things must exist before others can be built:

```
config → providers → memory → API routes → (Phase 1 complete)
                                         ↓
                              voice STT → voice TTS → (Phase 2 voice)
                                         ↓
                              search service → (Phase 2 search)
                                         ↓
                              event bus → orchestrator → automation → (Phase 3)
                                         ↓
                              plugin manager → plugins → (Phase 3)
                                         ↓
                              semantic memory → desktop UI → (Phase 4)
```

Never skip a layer. Each one is the foundation for the next.
