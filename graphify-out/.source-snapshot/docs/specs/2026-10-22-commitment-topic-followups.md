# Current commitment topics in laptop chat and voice

Owner request: "build the nnext one", clarified as "Broader chat/voice follow-ups
that remember the current topic". This first increment remembers one explicitly
selected saved commitment. Root is the sole writer; two read-only reviewers cover
routing and temporal/source boundaries. Existing unrelated edits remain intact.

## Behavior and scope

"When is my robotics exam?" reads its unique current saved interpretation and
establishes a local topic. "When is it again?", "How many days left?" and
"What was the previous date?" then use that same exact saved revision. "What
about my maths exam?" explicitly selects another unique saved commitment.
Successful, independently reviewed date clarifications can also establish the
newly committed target. Generated replies and unresolved reports never seed it.

Reuse the existing SQLite reference-context table, token and 15-minute expiry.
Store only the target ID, full target fingerprint and cognition forget epoch.
Named matching checks all current subjects, so a display bound cannot hide
ambiguity. Ambiguity asks for a complete named question; it does not select by
recency or retain a new autonomous question/choice queue. Unknown named subjects
without a matching saved commitment retain the existing normal conversation path.
Unbound pronoun questions ask for a saved name without using a model.

Before each answer, require the unchanged token, expiry, forget epoch and exact
current temporal row in one transaction. Follow the exact supersedes link for
the previous date, including reverse linkage and subject identity; pruned history
is unavailable. Count from today's local calendar only for one definite planned
date. Date ranges, undated/uncertain, cancelled and completed reports produce no
countdown. A past date does not prove completion. Always describe a saved owner
report; a pending correction is not an accepted update.

Foreground topic mutations also require the latest recorded local chat/voice
request to match the current turn. An older save may still commit its authorized
date but cannot replace a newer selected topic; stale query/cleanup work also
cannot bind or clear over it. Missing/pruned request records abstain. Telegram
and background events do not replace local request ordering.

Chat and voice share the local topic. Telegram cannot read, select, cancel or
retire it. Unrelated local turns, a new date clarification, explicit cancellation,
automation's early route, history clear, forgetting and workspace clear retire
or invalidate it. Reopening an expired topic requires an explicit named lookup.
Clearing a topic does not cancel its commitment. References grant no permission
to open, finish, move, remind or execute anything.

## Implementation and validation

- Reuse `reference_context` and `Workspace(store)`; no new table/model/dependency.
- Integrate through the existing `conversation_context.observe/try_handle`
  before search, model interpretation, humour learning or proactive answers.
- Successful dialogue status can bind its already verified exact revision;
  optional topic storage failure must not invalidate a committed date receipt.
- Clear only this reference kind during cognition forgetting, preserving existing
  workspace task/focus behavior. Return noncacheable replies with generic safe
  memory labels; do not promote generated readback into owner facts.
- Cover named/pronoun/switch, chat/voice, ambiguity, ordinal refusal, source changes,
  expiry/restart, cancel/forget/disable, midnight, uncertain/range/closed/past,
  direct history lineage, old source retention and model/search bypass.
- Run focused and full regression and an isolated no-model end-to-end probe.
  Bind results to exact source hashes. No owner data/configuration changes,
  model downloads, budget increases, commit, deployment or release.

Broader arbitrary subject tracking, unreviewed-report pronouns, recommendations
and action pronouns remain outside this bounded increment. Cold first-inference
timeouts from the preceding task remain unresolved and are not changed here.
