# Automatic activity awareness

Open **Customize FRIDAY → Screen access** to add app permissions. Enter an
executable name (such as `chrome.exe`) or use **Choose app**. Check **Allow
reading** for Allowed; leave it unchecked for Blocked, then save. Existing
rules can be edited or deleted. Unlisted ordinary apps keep the allowed default.
Changes apply immediately without unpausing watching. Blocking stops new
captures and excludes that app's stored observations from conversation context;
it does not delete history. Protected content checks still apply to allowed apps.

Friday uses background observations in ordinary local conversations. You do not
need to ask a screen question first: successful checks automatically update her
private activity context. A normal follow-up can refer to a recent topic. She
uses dated observations rather than claiming to know your current intentions.

She keeps compact daily records of observed subjects and activities, alongside
the short observation cache. Repeated checks extend an exposure; they do not
each count as a new habit. A recurring activity needs at least a minute of
observed evidence on three separate days before it becomes tentative context.
Sustained reading, watching or writing also helps the existing busy gate avoid
unnecessary interruptions. Observations do not trigger a narration or check-in.

Friday can read the active app's accessible text and use a small local vision
model when that text does not explain the visible subject. It makes occasional
observations after the window settles, normally about every 30 seconds. This is
not a video recording or a claim to know your exact intentions.

The visible **Screen awareness · Pause** badge is required for any observation.
Click it to pause, or use the Screen button in Friday's control panel. Missing,
hidden or disconnected badges prevent observations. Idle and locked sessions
are skipped.

Controls:

- `start screen awareness` / `resume screen awareness`
- `pause screen awareness` / `stop watching my screen`
- `screen awareness status`
- `screen memory`
- `forget screen memory` — deletes summaries and pauses watching

Explicit screen reports remain available, but ordinary conversations receive
activity context automatically. Remote phone and Telegram requests cannot
enable watching or inspect screen memories.

Analysis uses local Ollama models. The vision dependency is
[`qwen3-vl:2b-instruct`](https://ollama.com/library/qwen3-vl:2b-instruct);
the regular text model is used first. There is no cloud fallback for background
observations or activity-informed conversation. Requested speech uses offline
TTS without an audio cache. Private conversation has a short in-memory thread
for follow-ups; it is not copied to shared conversation history or owner facts.
Pausing or forgetting revokes that context and drops replies still in flight.
Explicit memory and schedule commands keep their existing paths. Ordinary
private conversation stays in its temporary thread; it does not create owner facts.

Friday keeps at most 200 short, provisional interpretations and 512 daily
activity aggregates for seven days in the local cognition database. They remain separate from confirmed personal
facts and task completion. Screenshots and extracted app text are not saved or
added to general chat history. Clearing the activity log or forgetting matching
personal data also clears matching screen memories, daily learning and derived
patterns, and pauses watching.

Ordinary apps, including Terminal, Command Prompt, PowerShell and Python app
windows, are eligible for reading. Password managers, password fields,
banking/payment/login windows, private browsing and secret-related content
are excluded. These content checks also apply inside terminals. Browser pages
require a recognized browser-owned HTTP/HTTPS address field. Unknown URLs,
unsupported accessibility, large control trees or changing windows are blocked;
some apps will therefore remain unavailable. Pixel-only changes can still make
an interpretation outdated, so its timestamp matters. Model descriptions can
be wrong and do not establish your intent, understanding or progress.

Setup and verification artifacts are under `tasks/screen-*` and `tasks/passive-*`. The synthetic
native test uses an owned lecture window and a protected test field, saves no
captured images, removes its test summaries, and finishes paused. Activation
occurs only after the full test report and source hashes match.
