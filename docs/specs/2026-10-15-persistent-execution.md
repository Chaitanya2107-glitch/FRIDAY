# Persistent execution: first local workflow

Owner authorized saving the assistant roadmap and starting implementation on 2026-10-15.

## Objective and assumptions

Ship one complete, locally executed workflow: prepare a handoff for an existing saved workspace task.
Reuse SQLite, notes, task storage and the shared chat/voice command route. Keep current AI policy.
No additional dependency, cloud call, arbitrary shell invocation or unsupervised desktop input is needed.
Task steps written by the owner remain descriptive; creating a handoff does not complete that task.

## Commands and contract

- Primary usage is name-based: `prepare a handoff for my FRIDAY project`, `prepare a handoff for my current task`,
  `check the latest handoff`, `resume the handoff`, and `cancel the handoff`.
- Task/goal controls also accept names, `current` and explicit `latest` selectors. Persist selected targets
  separately for laptop and Telegram. Ambiguous names require a more specific repeated request before action.
- Numeric commands below remain available for compatibility; users do not need to remember IDs.

- `prepare task handoff 1`: create and run an execution for saved task 1; return its execution ID and verified path.
- `execution status 1`: show durable checkpoint, status and current artifact verification.
- `resume execution 1`: retry the failed/interrupted checkpoint without replaying completed reads.
- `cancel execution 1`: prevent further checkpoints; retain any already published artifact.

All commands operate only at the laptop. A complete job requires a verified artifact, not a successful
attempt to write. Missing/tampered artifacts must not be reported as currently verified. The handoff is a
dated snapshot. Task edits before publication block stale execution and require a newly prepared handoff.
Task handoffs contain task details, owner-reported evidence and related saved notes labelled by source/date.
Matching notes are selected by keywords, not asserted to be semantically exhaustive or the latest project file.
Diary entries and general file contents are excluded from this first workflow.

## Storage and phases

Add a dedicated execution table to the existing workspace database. Store snapshot data, cursor, state,
evidence, creation/update times and artifact hash. Keep it outside bounded cognition event history.
Phases: capture task snapshot; collect related notes; publish and verify deterministic Markdown.
Each short local phase and its checkpoint run under one SQLite write transaction, serializing concurrent
runners. Do not put network, model or long-running desktop operations inside these transactions.
Publication uses an atomic no-overwrite operation. A matching artifact is safe to recognize after an
interruption; different existing bytes are a conflict. Resume uses the original saved inputs.
Explicit workspace clearing removes execution records; previously generated files remain.

## Project structure and style

- `services/mind/execution.py`: narrow execution engine, local adapters, durable records and artifact verification.
- `services/mind/execution_commands.py`: full-message matching and transport-safe replies.
- `services/automation/intent.py`: dispatch commands through the existing asynchronous router/threadpool.
- `tests/test_execution.py`: isolated real SQLite/file tests and chat/voice integration.

Follow existing snake_case Python, parameterized SQLite and `ActionResult` replies. Report factual statuses;
keep private note content out of command replies, public events and logs. Errors cannot imply completion.

## Verification

Focused: `venv\Scripts\python.exe -m pytest tests/test_execution.py tests/test_workspace.py -q`
Regression: `venv\Scripts\python.exe -m pytest -q --tb=short`

Prove persisted checkpoints survive a new engine instance, concurrent runs do not duplicate side effects,
cancelled/blocked jobs do not advance, stale tasks are rejected, note failures are visible, local/cloud
policy is preserved, artifacts are verified and conflicting existing files are not overwritten.
