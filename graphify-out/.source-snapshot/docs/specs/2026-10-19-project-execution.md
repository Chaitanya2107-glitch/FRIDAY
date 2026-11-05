# Verified project execution

Authorized by the owner's 2026-10-19 request to extend the existing execution engine first.

## Objective and capability order

1. `project-execution`: extend existing briefs with an explicit, verified desktop action.
2. `brain-assessment`: assess shared cognition, temporal memory, reasoning and background attention;
   choose the next increment from evidence after execution verification.

Reuse Python, SQLite, existing COM integration and pytest. No new dependencies or model-policy
changes are needed for project execution. Existing task plans and notes remain data.

## Contract

- `start project session for <saved project>` prepares a verified brief, opens the exact registered
  folder in Explorer, then checks that Explorer actually exposes that path.
- `project session status`, `resume project session`, `cancel project session` use durable local focus;
  explicit saved project names/IDs are also supported. Existing work-session brief commands retain meaning.
- Desktop phases run outside SQLite transactions, with durable exclusive claims and a finite lease.
  Check sources before acting and before accepting evidence. Never overwrite cancellation.
- An interrupted/expired action is reconciled by observing its result, never blindly replayed.
  Uncertain outcomes remain blocked; a new explicit session is needed to authorize another attempt.
- A completed session proves a brief and an observed folder window at completion time. Status distinguishes
  historical completion from current verification if the folder closes or artifact changes.
- Do not run arbitrary project resume strings, shell commands, type text, close existing apps,
  send messages, mark source tasks complete, or enable general model tool execution.

## Structure and style

Extend `services/mind/execution.py` and additive workspace storage; implement the project adapter in
`services/mind/project_execution.py`, using the existing ProjectSessionEngine and COM conventions.
Route named local commands through `execution_commands.py`. Keep errors/action results consistent:
`ActionResult(False, actionable_message, repeatable=False)`.

## Verification

`venv\Scripts\python.exe -B -m pytest tests/test_project_execution.py tests/test_execution.py tests/test_project_session.py -q`

Exercise real temporary files/SQLite, duplicate workers, source changes, cancellation during external
work, interruption after action, expired claims, missing/tampered briefs, scoped commands and chat/voice.
Stub only desktop effects in automated tests. Run the full suite before completion. A live temporary-folder
trial can establish Explorer behavior without accessing project contents or running saved commands.

## Boundaries

Preserve unrelated uncommitted work and all existing user settings. Additive storage only. No installs,
commits, deployment, private-file contents in logs, or background replay of uncertain desktop actions.
The later cognition assessment must distinguish implemented behavior from research proposals.
