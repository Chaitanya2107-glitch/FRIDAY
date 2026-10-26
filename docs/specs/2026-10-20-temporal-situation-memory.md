# Temporal situation memory: first brain/life increment

## Scope

Extend the existing cognitive report with bounded temporal interpretations of
local owner episodes. Each interpretation quotes its actual source, identifies
the commitment, retains the source's original time and includes status, date
bounds, uncertainty and an optional explicit correction target. Local validation
and the existing separate critique must succeed before a single transaction
saves the report. No new inference worker or tool permission is introduced.

Store revisions in the cognition SQLite database. Keep historical rows and expose
only non-superseded revisions as current interpretations. A past due date does
not prove completion. An undated postponement is unresolved, not tomorrow.
Remote episodes cannot change the laptop situation. User forget/reset clears
both interpretations and history and invalidates in-flight reviews.

## Integration

Add source-linked temporal evidence to the executive. A shared situation snapshot
categorizes active interpretations as past, current, upcoming, unresolved or
closed and includes live canonical runtime state. Life feeling reports consume
this snapshot; conversation, notifications and inquiry receive the same temporal
interpretations without automatically scheduling, cancelling or modifying tasks,
reminders, deadlines or classes.

## Checks

Use synthetic episodes and isolated SQLite for anchored dates, corrections,
postponement without a new date, uncertainty, completion, historical provenance,
idempotency, concurrency, stale sources, remote isolation, forgetting and malformed
reports. Exercise the real executive generation/critique/save path with provider
doubles. Run focused and full pytest regressions and a bounded synthetic local
provider probe where available. Never use real owner data for the probe.
