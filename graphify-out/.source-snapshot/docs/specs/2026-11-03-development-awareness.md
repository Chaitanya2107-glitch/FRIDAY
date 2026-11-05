# Development awareness

Owner request: FRIDAY should notice work on its own code while being upgraded.

## Acceptance

- A local background monitor checks fixed FRIDAY source roots every ten seconds.
  Content fingerprints detect edits, repeated saves, additions, deletions and
  reversions, independently of Git's dirty-file list.
- An initial snapshot establishes a baseline, not an invented upgrade event.
  An atomic local manifest and bounded history preserve changes across restarts.
- Separate recent disk activity, changes since monitor startup, and changes
  observed between sessions. Backend changes recommend a restart; Island source
  changes need rebuilding/relaunching. Neither is proof of loaded behavior or
  successful validation. Tests and documentation do not require a restart.
- Shared chat/voice/cognitive context contains cached counts and fixed component
  labels only. Source text, filenames, hashes and absolute paths stay out of
  online prompts. Detailed status is laptop-only and works without a model.
- Ignore private/runtime storage, environment files, dependencies, build outputs
  and links/junctions. Incomplete or failed scans retain the previous baseline
  and report uncertainty. Prompt assembly never scans the filesystem.
- Register the monitor with the existing API lifecycle and cancel it on shutdown.
  No automatic code execution, reload, restart or release follows an observation.

## Ownership and policy decision receipt

User authorization: reversible local implementation, tests and documentation for
the requested feature. Decision: allow these development actions. Codex is the
sole writer; runtime_research and context_research are read-only. Local policy
is legacy; no tracked collaboration harness or action capability adapter is
installed. Ruflo guidance/memory tools and its CLI are unavailable in this
session; repository decisions and existing implementation patterns were inspected.
No dependency installation, external messaging, commit, publish or owner-data
change is part of this implementation. Validation uses isolated test storage.

Implementation: reuse the standard library, settings_store.save, shared live
state, cognition introspection commands, mind routes and existing task cleanup.
Validate scan failure/recovery, restart history, exclusions, prompt privacy,
actual chat/voice routing, API status, cancellation and focused regressions.
Final evidence and source hashes: tasks/development-awareness/receipt.json.
