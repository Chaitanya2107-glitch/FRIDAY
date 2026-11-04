# FRIDAY command and integration audit

The advertised Island slash catalog contains 53 commands. Each expansion is checked
against the actual Island bridge and its backend routing in
`tests/test_island_slash_commands.py`; OS actions and external providers are replaced
with test doubles. Browser checks exercise the command bar and authenticated transport.
These checks establish routing and behavior under controlled conditions; they do not
prove that every installed app, device or external account is available.

Normal commands remain supported too, including `next song`, `copy hello to
clipboard`, `browser cancel`, `what classes do I have today`, `open college
schedules` and `brain status`. The broader command checks cover natural phrases
and the shared chat/voice command router.

| Commands | Handler / prerequisite |
| --- | --- |
| `/help`, `/status`, `/history`, `/settings`, `/projects`, `/plugins` | Island views and command palette; conversation history needs the backend |
| `/open`, `/proj` | Native installed-app / project lookup; `/open` retains the backend folder/URL fallback |
| `/resume` | A saved FRIDAY backend project |
| `/next`, `/schedule`, `/college` | College plugin, saved timetable and native College editor |
| `/habit`, `/todo` | Shared tracker; empty arguments list items |
| `/note`, `/notes`, `/remind`, `/reminders`, `/due` | Notes, reminders and saved deadlines; reminders need a valid time and task |
| `/find`, `/open-file`, `/ask-files` | File index; opening needs recent search results; questions need indexed passages and an answering provider |
| `/browser`, `/research` | Existing supervised automation; empty `/browser` shows help; research needs its configured browser/network/providers |
| `/copy`, `/type`, `/press` | Clipboard and typing handlers; typing needs the original desktop window; existing confirmations remain |
| `/battery`, `/cpu`, `/ram`, `/time`, `/date` | Local system information and clock |
| `/volume`, `/brightness`, `/mute`, `/unmute` | Local device adapters; hardware support still applies |
| `/play`, `/pause`, `/next-song`, `/previous-song` | Media adapters; playback requires an available player/account |
| `/briefing`, `/memory`, `/remember`, `/routines`, `/modes`, `/brain` | Existing briefing, memory, configuration and cognition services |
| `/screen`, `/phone` | Screen-awareness and phone status; phone functionality requires its configured connection |
| `/lock`, `/sleep`, `/shutdown`, `/restart`, `/cancel` | Existing power controls and confirmation flow |

Fixed during this audit:

- `/copy` now uses recognized clipboard grammar. Explicit writes own their text
  before transforms, history commands or multi-command parsing can reinterpret it.
- `/next-song` reaches media control instead of being intercepted by the College
  plugin's `next` command. Bare `/next` still means the next class.
- `/open` checks the native app catalog before falling back to the literal backend opener.
- `/browser cancel` matches the ordinary browser stop control.
- `/computer-status` and `/computer-stop` were removed from the advertised slash
  catalog because the default assistant mode disables that feature. Standalone
  suggestions no longer advertise unimplemented `focus` and `note` handlers.
- Slash suggestions and manual execution check whether the full backend, standalone
  plugins or only offline native actions are available.
- Malformed Telegram shutdown delays and arguments to power shortcuts are rejected.
- College requests and bootstrap use the configured API host/port. The CLI loads the
  same configuration. Tray, CLI and notification requests bypass system proxies.
- Backend shutdown cancels background workers and closes the local model runtime
  even if browser cleanup fails.

Local validation evidence and source hashes are retained under
`tasks/friday-integration/`. The existing unfinished development-awareness and Mochi
changes were preserved. No commit, push or external publication was performed.

## Validation result

- 854 focused backend checks, 1,425 command regression checks, 67 follow-up checks
  and 43 native editor/control-panel checks passed. These groups overlap.
- All 53 slash-catalog cases passed; 17 frontend tests and 11 Rust tests passed.
  One Rust test that reads the installed-app catalog remains explicitly ignored.
- Both real Chromium/bridge scenarios passed. The native release build succeeded;
  the normal FRIDAY app and controller were relaunched with the rebuilt executable.
- Seven live API routes and the authenticated WebSocket/runtime/controller checks
  passed after activation. No command was sent through the live owner session.
- The initial full run had 6,150 passes, two timeout-related failures and 13 native
  checks disabled by their interactive-desktop flag. Both failed modules passed
  follow-up checks. The rebind test now allows Windows socket cleanup time, and
  the terminal-attention test uses a deterministic notification context. The
  native checks were exercised separately with the desktop flag enabled. The
  entire full suite was not rerun after those test adjustments.

External providers/accounts and real power, keyboard, media and device actions
were not exhaustively exercised. Their routing and confirmations were tested
using isolated stores and test doubles.
