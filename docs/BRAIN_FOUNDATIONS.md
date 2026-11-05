# Brain health and source-backed working memory

This increment improves the existing cognition pipeline and memory context. It
does not add automatic computer actions or change attention/inference budgets.
Restart FRIDAY once to load these source changes; saving source does not update
an already-running Python process.

## Inspect the brain

Type or say `brain health`, `brain status`, or `working memory status`.

- `brain health` reports actual attention-task liveness, the last attention gate
  or executive wait reason, and the most recent local review diagnostics.
- `brain status` retains the existing inquiry, life, commitment, consolidation
  and review report and adds the health summary.
- `working memory status` shows explicitly selected tasks/goals, an exact valid
  saved commitment topic, and up to three original owner reports with dates.
  A recent report alone is historical evidence; it does not establish a current
  topic, observed activity, completed work or permission to act.

The microphone/call, typing, gaming, quiet, active-request and inference-budget
gates remain authoritative. A waiting brain can be behaving correctly. Health
now distinguishes those waits from an unavailable check or a failed startup.
The current live baseline reported a call/microphone gate. That observation
does not establish the cause of every older missing review.

Local read APIs:

```text
GET /api/v1/mind/health
GET /api/v1/mind/working-memory
```

These two detailed endpoints require the existing local-client check. Local
commands use the shared chat/voice router and never call an LLM for inspection.
Authenticated owner Telegram inspection uses only its own report scope for
working memory; it does not consume the laptop's selected tasks or commitments.

## What changed

The attention loop owns a real asyncio task. Startup, including retirement of
legacy interview queues, is inside its protected lifecycle. A startup failure
can no longer leave an open-loop flag claiming that the task is running.
Cancellation clears live globals and records a stopped state. Duplicate loop
starts do not create a second worker.

Each loop check records bounded metadata about its state and reasons. Executive
claim waits distinguish the existing minimum gap, hourly limit, active review,
retry backoff and lack of new pending work. None of these diagnostic reads spends
a review attempt or changes a gate.

Review diagnostics have a separate durable latest record and bounded history;
ordinary activity observations cannot evict the latest review. Only allowlisted
states, counts, timings and model-call metrics are persisted. Source text, model
answers, prompts, paths, exception messages and credentials are excluded.
Existing forget operations clear this derived state and increment the existing
epoch, preventing a late trace from restoring forgotten diagnostics. A prior
process's running receipt is historical/interrupted rather than a live task.

Working memory is a view over existing stores, with no new topic model or owner
fact store. It reads selected work and original reports under one SQLite snapshot.
Commitment versions, topic tokens/expiry, source corrections and the forget epoch
enter its version signature. Related local chat and voice context may be shared;
Telegram reports remain in their own scope. Current credentials are redacted even
if an older source predates the credential setting.

The conversational language layer receives selected working context as data with
explicit uncertainty labels. It rechecks source versions before handoff and after
generation; a changed or forgotten source causes the prepared answer to be withheld
with a request to repeat the question. An already-submitted provider request cannot
be recalled from that provider. Ordinary conversations with no selected working
context retain their existing recall path. Source changes do not authorize any
action, overwrite a commitment or complete a task.

## Verification and remaining work

Two baseline defects were reproduced before implementation: false task liveness
after a startup failure, and review diagnostics lost after event retention.
Focused checks cover actual loop progress/cancellation, gate and budget reasons,
bounded/allowlisted receipts, restart/forget fencing, source edits, changed plans,
corrected/expired commitments, channel privacy and real chat/voice inspection.

Source-bound evidence and the baseline/candidate comparison are saved under
`tasks/brain-foundations/receipt.json` by its local verification script. Tests use
isolated storage and provider doubles. They establish implementation behavior;
they do not establish reliable real-model cognition or explain the whole historical
October-to-November review gap.

Next priorities remain broader conversation topic resolution, measured improvement
of paraphrase recall, deterministic numeric reasoning with the computation engine,
and more useful consolidation/life/curiosity behavior. The existing conservative
semantic checks and independent critique were preserved.
