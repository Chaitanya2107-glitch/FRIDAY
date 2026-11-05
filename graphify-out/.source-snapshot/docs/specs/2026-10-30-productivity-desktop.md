# Habit tracker and to-do desktop

Authorized by the owner's request on 2026-10-30. Local, reversible implementation;
no publishing, commits, paid calls or changes to existing personal records.
Root is the only writer. A read-only researcher inspected integration points.
The Ruflo MCP tools are absent; cached CLI memory search reported no database.
CLI swarm initialization was rejected with policy-ledger-anchor-missing; no
coordination-dependent actions proceeded and the ledger was not modified.
Repository policy is legacy mode with no configured rules; the local development
request permits this implementation. This record is a development receipt, not
a production authorization or distributed fencing capability.

Acceptance: a polished resizable Tkinter app has Today, Habits and To-do views;
manual habits support selected weekdays, daily check-ins, history, scheduled-day
streaks, editing, archiving and atomic CSV/bulk import. Existing FRIDAY tasks are
visible, editable and completable without bypassing plan/evidence requirements.
Changes survive restart and appear through FRIDAY commands. No backend or model
is required for desktop data access. All disk I/O runs outside Tk's event loop.
Errors retain drafts; stale edits are rejected. No sample habits enter real data.

Architecture: services/productivity reuses Workspace/Cognition SQLite and adds
manual habits/check-ins and task metadata. The existing learned habit engine
remains separate. A dedicated command handler supports explicit tracker commands;
tray and python module launchers open the native app. Root owns all edits.

Validation: isolated persistence/import/streak/command tests, real withdrawn Tk
event-loop checks, existing workspace/habit/router/tray regression tests, and a
synthetic visual preview. Record final results and source hashes in tasks/.
