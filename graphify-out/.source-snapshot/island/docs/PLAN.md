# FRIDAY Island v1

## Inspected source and authority

The host is Python 3.12.8, FastAPI/uvicorn, with Tk desktop interfaces.
`main.py` runs `interfaces.api.app:create_app`; College Schedules is under
`services/college` and `interfaces/college`. Reuse
`services.proactive.timetable.next_class_occurrence`, without changing its source.
Use the existing **tool-free** `services.mind.language.answer` for conversation;
the chat automation router is deliberately outside this surface's authority.

Root is the only writer. Read-only inspection/review agents share the checkout.
The registered tool list has no Ruflo guidance/memory tools. Local Ruflo policy
is legacy with no live collaboration harness/action capability. User authorization
covers additive local development, builds, tests and isolated commits, not release.
Preserve all pre-existing tracked/untracked work. Do not change existing startup.

## Layout and milestones

1. `services/friday_island_server/`, `tests/island/`: config, WebSocket, command
   engine, plugin registry and protocol/security tests.
2. `island/src-tauri/`: native Windows window, focus policy, primary-monitor
   geometry, regions, global hotkeys, configured launches and icon extraction.
3. `island/src/`: TypeScript state machine, shared palette, SVG character,
   reconnecting client and token-based CSS; user-editable pins/projects/settings.
4. `island/docs/`, `island/README.md`: protocol, setup, plugin authoring and
   evidence with exact source hashes. Run all focused suites and production build.

## Protocol and config

Protocol v1 is JSON `{v,type,id,...}` over authenticated WebSocket on
`127.0.0.1:17321`. The first frame is a token handshake; requests include raw
commands/suggestions and plugin queries; responses contain text or typed actions
referencing configured IDs. Origin/peer checks, size limits and rate limits apply.
Do not log frames or tokens. The UI makes only loopback connections; FRIDAY's
existing tool-free language handler retains its configured provider behavior.

The single `%APPDATA%/FRIDAY/island/config.json` is validated by Python and Rust.
Use an interoperable file lock, atomic replacement and revision checks; preserve
corrupt bytes. Rust owns settings writes, Python initializes only if missing or
damaged. No command can supply an executable, argument, URL or path at runtime.

## Validation and handoff

Each milestone leaves runnable checks. Test authentication failures, malformed
frames, recovery, fuzzy ambiguity, corrupt config and configured-action boundaries.
Test Rust config/launch policy and frontend state transitions. Compile and package
on Windows. Manually assess focus retention, corner click-through, hotkeys,
high-DPI/monitor changes, acrylic fallback and reduced motion; distinguish automated
evidence from visual/manual checks. Commits contain only the new feature paths.
