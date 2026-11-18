# Island desktop migration

Authorization: the owner requested complete migration from the taskbar to Island,
with all FRIDAY overlays hidden during gaming. Broader fixes follow owner review.

## Acceptance

- Island exposes every taskbar/tray control, clipboard restore/clear, file index
  search/status/rescan, saved routines, chat-memory clearing and learned guesses.
- Existing full native editors remain available directly; no legacy flyout or
  robot is required. The existing desktop controller retains backend ownership,
  microphone state machines, emergency shortcuts and screen-capture badge leases.
- Computer and screen requests restore/check the original application before
  capture or approval. Private proposals never enter public history/state.
- Gaming/fullscreen hides Island, HUD and the capture badge, suppresses Windows
  popups, prevents hover/replies/hotkeys from revealing overlays, and restores a
  passive resting surface afterward. Hiding the badge revokes screen capture.

## Ownership and policy decision

Decision: allow local implementation and focused validation within this checkout.
The root agent is the sole writer. Research agents are read-only. Preserve all
pre-existing changes. No commit, push, release, external messages or destructive
data operations are authorized by this development decision. Tests use fixtures;
clipboard clearing/history deletion are only explicit, confirmed user controls.

No repository session/lease harness was found. Ruflo MCP tools are unregistered;
offline CLI discovery found no cached CLI package. Local source-bound validation
and a receipt under tasks/island-migration record this work instead.

## Validation

Focused Python, TypeScript and Rust checks; browser/native checks where available.
Record exact changed-file hashes and limitations in the migration receipt.
