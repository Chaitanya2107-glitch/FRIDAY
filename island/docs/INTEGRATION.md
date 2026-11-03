# FRIDAY desktop integration

Run `launch_friday.vbs` from FRIDAY's root. The existing desktop lifecycle owns
the full backend and Island. A standalone Island launch uses that same lifecycle.
Repeated launches reuse the existing session. The Island is the primary surface;
the original robot and full native control panel remain accessible.

Use top-edge hover or `Ctrl+Shift+F`. The FRIDAY tab contains the conversation,
voice controls, provider selection, browser/research progress, task cancellation
and entry points for FRIDAY's full native editors. `next`, habits and todos keep
their existing Island shortcuts. Other assistant text uses the ordinary FRIDAY
conversation, memory and command flow, including confirmations.

Type `/` in the command bar to browse the scrollable command catalog. Selecting
an entry fills the bar; Enter executes it through its existing FRIDAY route.
Visible history is limited to the last three exchanges; saved backend memory
is preserved. A pending command keeps the capsule visible as “Working…” until
its result replaces the pending text, including in auto-hide/hover modes.

The college widget and resting capsule show real current/next-class status.
Schedule changes are checked every five seconds, separately from the 15-minute
pre-class reminder. A class in progress is shown as “Now”; “Next” means the next
future start. Source wiring and remaining gaps: [wiring audit](../../docs/island-wiring-audit.md).

Command replies and reminders appear directly in the capsule with Mochi sliding
to its left edge. Brief acknowledgements last five seconds. Detailed replies,
reminders, errors and work results last 30 seconds; hovering or focusing the text
pauses that timer. Use the acknowledge button to dismiss early. Questions that
need an answer stay until answered or dismissed. Long replies scroll within the
capsule; public conversation history remains in the FRIDAY tab. Incoming notices
wait while a command or editor is open, and queued reminders appear one at a time.

`Ctrl+Shift+S` toggles persistent Sneak mode. Only the command bar can appear
until Sneak is toggled off, including after commands, notifications or a restart.
Esc or switching apps dismisses the bar; `Ctrl+Shift+F` summons it again. Hover
does not reveal the Island. Replies appear inside the bar and clear on dismissal.

Stop FRIDAY keeps Island available. Start FRIDAY uses a native control path while
the backend is offline. Quit closes the managed session. A manually started API
keeps its independent ownership. Backend-folder edits apply on a full Quit and
relaunch; port edits rebind the transport and token rotation revokes old sessions.

Project folders are registered additively. Existing records and native ordered
launch actions are preserved. Conflicting folders are labeled for review rather
than overwritten. Full editors provide detailed schedules, tracker history and
customization. Native apps, pins, clock, battery and media also work offline.

Private turns and proposed typing stay out of the Island transcript. Private
display clears on close, tab changes and disconnect. A typing token is expiring,
connection-bound and one-use; foreground window/process identity is checked
before typing. Leaving an expanded Island clears its old typing target.

The existing desktop controller owns microphone modes and proactive questions.
Typed turns wait for its readiness acknowledgement. Delayed requests expire;
failure cleanup releases conversation input. Voice reply-state events update
pending replies without copying private content. Transient notifications retain
their transient delivery path. The trusted screen-awareness badge stays separate
and visible even while Island is hidden.

Verification is recorded in `tasks/island-integration/receipt.json`, with per-scope
logs, source hashes, an immutable source ZIP and the executable digest. Checks
cover Python regression, TypeScript, Rust, Chromium, owned native windows, live
integrated startup and duplicate activation. Microphone capture and external
message sends are excluded from live verification.

The persistent Sneak toggle and capsule reply updates have separate verification
receipts and source snapshots in `tasks/island-sneak/receipt.json` and
`tasks/island-replies/receipt.json`.

Protocol details: [PROTOCOL.md](PROTOCOL.md). Implementation contract:
[integration specification](../../docs/specs/2026-11-02-island-integration.md).
