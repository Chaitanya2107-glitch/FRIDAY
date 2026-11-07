# Smart clipboard

Build the Windows plugin using Phase 0's managed timers, services, cards and
actions. Poll sequence numbers every 400 ms. Read flags and owner before text
under one clipboard lock; skip password managers and private/own copies. Keep
one item and its result in RAM. Cards/command replies contain at most an
80-character preview; action payloads contain opaque, expiring item tokens.
No contents in logs, custom events, routes, persistent state or model calls.
Explicit Open/Search actions may open the default browser; nothing opens
automatically. Local path detection must not probe remote drives.

Use an extensible detector registry. Reuse the existing bounded computation
worker and safe SymPy AST, add a stdlib arithmetic fallback and small unit
table. Optional dictionary/chemistry packages never trigger installation or
downloads. Suppress proactive cards during idle, game/sleep or fullscreen;
commands/hotkey bypass confidence only. Add capsule chips, TTL and a validated
color swatch without focusing the Island or persisting plugin cards.

Acceptance: at least 60 classifier examples, fake native clipboard/hotkey
tests, every action, missing-package paths, privacy and stale-action tests,
rate/activity gating, own-write suppression, extension registration and host
reload/disable. Run plugin/event/clipboard/router regressions and Island checks.

Policy decision receipt: allow the user's reversible local source/test/docs
changes and isolated validation. Root is the only writer; clipboard_privacy_review
is read-only. The inspected policy is legacy, with no tracked collaboration
harness or action-capability adapter. Ruflo tools are unregistered and offline
CLI discovery found no cached package; no package install is needed. No owner
clipboard access, hotkey registration, backend restart, commit, push or release
is part of validation. Finish with source hashes and focused test evidence in
tasks/smart-clipboard. This receipt is development evidence, not release authority.
