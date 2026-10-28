# Screen awareness

Owner authorization: build the discussed text-first, vision-fallback screen
awareness for the personal assistant. Root owns all writes; helpers are read-only.

Acceptance:
- A visible, non-activating pause badge is required before capture; loss of the
  badge/heartbeat, pause, shutdown, idle or private windows prevents capture.
- Read only the active window through a killable UIA worker. Never read password
  values. Use HWND capture, never a monitor fallback. No screenshots/text on disk.
- Use the installed local text model first; a local vision model handles screens
  without sufficient accessible text. Verify actual capabilities and reject
  cloud-backed models/endpoints. No cloud fallback, tools or actions.
- Poll foreground changes, settle briefly, and analyze at most one frame at a
  time, normally every 30 seconds. Discard changed/cancelled/forgotten results.
- Keep bounded, seven-day provisional summaries separately from owner facts.
  Offer private local inspection/history and forgetting. No raw screen data in
  chat history, generic prompts, Telegram, training or logs.
- Keep the original robot appearance. Add badge, panel/tray controls and sanitized
  runtime status. Queries report when a screen interpretation was made and its
  uncertainty; they do not establish intent, understanding or task completion.

Validation: deterministic privacy/cancellation/provider/storage/API tests,
existing routing/UI regressions, synthetic local text/image model probes and
native badge/capture checks on an owned test window. Bind results to source
hashes; no commits, publishing or unrelated model/voice changes.
