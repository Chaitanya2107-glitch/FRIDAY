# Verified outcome learning: phase 3 first increment

Authorized on 2026-10-21 by the owner continuing the saved brain/life roadmap.

## Concrete paths

Instrument the actual shared drivers for absolute master-volume/mute changes and
the shared mode-start/end controllers. Do not instrument only the text router:
routines, buttons, automatic mode end and direct driver calls must use the same
verification path. Existing request/confirmation/channel checks remain authoritative.

Before mutation record a bounded expected target. After the driver accepts it,
record applied, then perform a fresh read of the master audio endpoint or strict
saved-mode state. Classify verified, failed or unknown. Matching a mode selector
does not verify all setup steps, optimization performance or source-task completion.
Audio readback verifies the current master settings, not audible sound delivery.

Preserve successful reply wording. Replace optimistic replies after mismatch or
unavailable readback with a clear failure/uncertainty result. Partial mode setup
errors must still report the actual selected mode. Never retry an external action
automatically to learn whether it worked.

## Persistence and learning

Use cognition SQLite for requested/applied/terminal receipts, original timestamps,
expected/observed whitelisted fields and driver status. Retain bounded history,
fence completion after forget/reset, and treat abandoned prior-runtime requests as
unknown without replay. Memory failure cannot bypass the actual local state check.

Expose historical receipts and bounded consecutive failure/unknown summaries to
local reasoning, life-state priorities, inquiry and notifications. A verified
success resets the relevant failure streak. Repeated failed verification changes
the reply and next proposal toward checking the actual controller/state, without
blocking an explicitly authorized retry or granting model tool authority.

Local brain status and a read-only outcome API explain the latest evidence and
scope. Keep private targets/source details out of generic public event text and
remote conversation. No raw commands, payloads, credentials or provider responses
are retained in the outcome ledger.

## Acceptance

Prove requested-before-driver ordering, independent readback, mismatches,
unavailable reads, partial mode setup, repeated failures, success recovery,
restart/interruption, idempotent completion, concurrent forget and disabled/broken
memory. Exercise real shared controllers with isolated state and native API
doubles. Run focused/full regressions and bounded live read-only/local-model
probes without changing owner audio, mode, apps or notifications.

Other integrations need their own observable contracts. This increment does not
claim a general OS/action verifier or infer task completion from workflow receipts.


## Delivery evidence

First increment implemented on 2026-10-21. Full regression: 5,084 passed;
focused regression: 385 passed. Two later partial-mode readback tests and the final
response clarification passed in a 121-case status/reasoning regression. No failures,
errors or skips; one existing warning. Fourteen affected Python files parsed.
Artifacts: tasks/outcome-learning-reviewed-verification.*,
tasks/outcome-learning-reviewed-focused.* and tasks/outcome-learning-delivery-focused.*.

The read-only native Windows audio getter succeeded. Actual installed Ollama review
received synthetic repeated mismatches and generated controller-inspection advice,
but independent critique withheld its overstated fix. No conclusion was saved; no
system actions, notifications or inquiry generations ran. This proves safe abstention,
not reliable autonomous diagnosis. Deterministic failure explanations and life focus
are separately exercised by real shared-controller tests. Evidence:
tasks/outcome-learning-scoped-live-probe.json; earlier attempts are diagnostics only.

Continue at phase 4 in docs/BRAIN_LIFE_ROADMAP.md. General integration verifiers and
local-model diagnostic calibration remain follow-ups.
