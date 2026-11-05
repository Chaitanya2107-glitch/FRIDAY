# Island wiring audit — 2026-11-03

Scope: trace the running integrated transport, Island presentation, canonical
FRIDAY chat/automation routes, native editor handoffs and live college data.
Source wiring establishes reachability; it does not establish that every external
account or device is currently available.

## Corrected in this update

- A typed request previously switched through an empty clock capsule. Auto-hide
  and expiring background replies could hide it during the request. An untimed
  pending capsule now transitions directly into the result; background results
  wait behind it, and automatic hiding is suppressed while busy.
- `/` opens the supported local command catalog, including installed plugin
  commands. Selection fills the bar; Enter runs the existing local command flow.
  Telegram-only bypass and key-control authority are not added to Island.
- Public display/history fetch is bounded to three exchanges, without deleting
  saved chat memory. Reminder cards are bounded separately.
- The live college provider already read the real saved timetable. Island exposed
  only its warning window and refreshed the compatibility transport hourly due
  to a tick/seconds mismatch. Current/next status now uses the native college
  projection, checks changes every five seconds, and updates open widgets.
- Numbered/pronoun file-result opens and result-folder reveals now take the
  canonical file route before native app matching.
- Supervised computer replies now carry the private flag, keeping proposal and
  screen-derived text out of the Island's public conversation history.

## Still needs direct Island integration

| Area | Remaining work | Evidence |
| --- | --- | --- |
| Personalized empty-bar suggestions | Connect prediction retrieval and outcome/learning feedback to Island's empty command bar. Current suggestions use command templates, plugins and native apps. | `interfaces/popup/app.py` `_load_guesses`; `/predict/bar`, `/predict/bar/outcome`; `island/src/main.ts` |
| Full supervised desktop tasks | Port the original popup's target-focus settling/checks and its proposal/approval/status presentation. Island's runtime progress currently covers browser/research, not the computer-agent proposal lifecycle. Private responses are fixed, but this remains partial integration. | `interfaces/popup/computer.py`; `services/friday_island_server/runtime.py`; `services/computer/agent.py` |
| Dedicated clipboard/file/system panels | Wire the clipboard history/picker, indexed-file results/status/rescan, and detailed CPU/RAM views into Island panels. Related natural commands still reach FRIDAY, and existing tray/native screens remain available. | `interfaces/tray/tray.py`; `interfaces/taskbar/panel.py`; `interfaces/api/routes/clipboard.py`, `files.py`, `system.py` |

## Existing connections

The integrated bridge uses canonical local chat with its confirmations, providers
and memory. Notes, reminders, deadlines, college commands, routines/modes, phone
commands, Telegram requests, Spotify commands, browser/research and typing are
reachable through their existing command paths. Voice/wake/conversation controls,
task stops, notifications, projects and native editors use the shared desktop
controller. College/productivity/customization screens are real native editor
handoffs. Per-user launch/start/stop/quit ownership remains shared.

Microphone hardware capture, cloud inference, external message sending and live
Spotify/phone/Telegram readiness were not exercised for this audit. These are
unverified live dependencies, rather than evidence of missing source wiring.

Verification receipts: `tasks/island-polish/receipt.json`. Earlier capsule and
integration checks remain in their own immutable source snapshots.
