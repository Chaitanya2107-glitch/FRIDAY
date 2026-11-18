# Island wiring audit — 2026-11-03

## Feature parity update — 2026-11-18

The Island's Features tab now reads the shared production capability catalog:
67 feature groups, their requirements, examples and allowlisted guides. Selecting
an example fills the bar for review; Enter uses the existing FRIDAY backend.
This includes care/coaching, presence and companion handoffs. The Plugins tab
also lists the actual installed manager inventory, status, registered examples
and existing enable/disable/reload controls alongside the native tracker widgets.

The audit found and corrected functional gaps beyond missing discovery:

- Natural `open …` commands use canonical FRIDAY routing, including `open phone
  link`. Explicit native app/project actions check the backend's pending requests
  first, preventing them from bypassing outstanding confirmations.
- Redacted clipboard and other private system replies retain private metadata in
  both typed and voice paths. Coaching, presence and phone handoff notices use
  the ephemeral private Island stream, with gaming suppression intact.
- Selected-text reading uses the original target-window verification.
- Indexed-file result buttons use connection-bound references and the existing
  canonical context/file-stamp checks for opening and revealing files.
- Ctrl+Alt+F now invokes Handy dictation in the Island. Paste-to-submit, manual
  typing cancellation, Escape/blur cancellation and gaming blocking remain
  separate from FRIDAY's built-in microphone controls. Handy must be installed.

The remaining cataloged families already reach canonical chat, shared tracker
stores or their full native editors: apps/device/input, reminders/deadlines/classes,
notes/reading/files, media/Spotify, routines/modes/watches, projects/activity,
brain/memory/training, browser/research/supervised desktop, secure local logins,
WhatsApp/Telegram and phone/remote controls. Pairing and consent retain their
protected native handoffs rather than displaying secrets in an ordinary webview.

Evidence is recorded separately in `tasks/island-parity/`. Source wiring and
simulated action coverage do not establish live microphone, Handy recording,
external account, physical phone or every game's readiness. No real message
sends, power actions, purchases or private owner-data operations were executed.

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

## Migration update — 2026-11-17

The Island now owns the desktop surface whenever its executable is installed.
The old start-with-FRIDAY opt-out no longer sends ordinary launches to the taskbar.
The controller still owns backend lifecycle, microphone state and emergency
shortcuts; its flyout, taskbar button and robot are not part of the Island flow.

- All tray controls have Island entry points, including proactive talk, complete
  microphone stop, Remote off, the Control Center/Guide, screen controls, Spotify,
  saved routines and separately confirmed saved-chat-memory deletion.
- Desktop tools provide private clipboard history/copy/clear, indexed-file
  status/search/rescan and system readings. The existing live system HUD remains.
  Closing the panel revokes clipboard references and removes its private DOM.
- Empty command bars retrieve learned suggestions and report selection/closure
  using server-owned offers. Phone drafts and private confirmations are excluded.
- Computer/screen requests settle and verify the original foreground HWND, PID
  and process creation time before capture or action. Private computer proposals
  offer per-step approval/cancel; public progress contains only lifecycle metadata.
- Private voice responses use a short-lived authenticated local display stream,
  outside conversation history and public runtime snapshots. They are delivered
  to currently connected local Island surfaces, rather than stored for reconnect.
- Native gaming/fullscreen/lock suppression hides both Island and HUD and blocks
  focus/reveal attempts. Known windowed games are recognized by executable/path
  offline; the backend adds its shared activity categorizer. After suppression,
  the resting/hover state returns passively. The capture badge withdraws and
  revokes capture; ordinary Windows popups defer while suppressed. Connected
  Island notifications use its own surface instead of a duplicate Windows toast.

Migration validation and exact source/build inputs are recorded in
`tasks/island-migration/`. This does not certify external accounts, cloud inference,
microphone hardware, or every possible unrecognized windowed game. Broader fixes
and feature removals are deferred to the owner's review after migration.

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
