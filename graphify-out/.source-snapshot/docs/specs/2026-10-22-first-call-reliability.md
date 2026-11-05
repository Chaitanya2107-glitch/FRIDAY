# First-call local review reliability

Owner authorization: “lets go and build it”, continuing the proposed local-model
first-call reliability improvement. This task does not implement general topic
tracking. Root is the sole writer; two read-only reviewers inspect provider
timing and reasoning contracts. Existing unrelated work stays intact.

## Baseline and scope

`tasks/firstcall-baseline-live.json` freezes two rounds of the existing ten
synthetic cases before production edits. The first robotics and voice requests
time out; all warm cases pass. Existing diagnostics distinguish slow cold
readiness from an additional resident first-generation stall. They do not prove
a GPU, CPU or queueing cause. Preserve failed controls and exact source hashes.

The smallest candidate is a temporal-only prompt for a fully scoped, verified
conversation-date correction. Use it only when the entire reviewed evidence is
the linked answers and their exact current targets. Any other evidence keeps
the general reasoning context, including possible contradictory reports.
Remove optional activity/planning context and duplicate proposal serialization
only in this narrow model request. Retain every original evidence object,
question, answer, receipt date, target and origin. Validation/save still receive
the full original bounded snapshot. Keep the independent temporal critic's
instructions, schema and boolean coverage/refusal rules.

Separate server readiness, resident lookup and prompt-free model load wall
timings using existing requests. Missing context metadata cannot establish
known compatible residency. Diagnostics remain scalar/private and do not
create another worker, infer facts or trigger generation.

## Acceptance and safety envelope

- Compare exact source-bound cold/first-call and warm controls against baseline.
  Record successful saves and safe refusals separately, with per-phase timings.
- Preserve 45-second executive ownership, the at-most-25-second inference window,
  existing attempt/startup allowance, one repair attempt, five-minute spacing and
  four review starts per hour. No ceiling or setting increases.
- Keep the configured local model, context limit, provider policy, gaming and
  attention protection; no downloads, cloud thinking, new packages or warmup loop.
- Retain exact sources/quotes/date anchoring, independent critique, cancellation,
  disable/forget fencing and atomic persistence. Silence is not a saved update.
- Generic reasoning, summaries, inquiry links and extra evidence keep their
  existing contracts. Only explicit owner date answers qualify for compaction.
- Measure diagnostics and prompt/schema sizes; do not manufacture success by
  widening timeouts, retrying unboundedly or stopping a shared Ollama process.
- Use synthetic temporary stores and owned-process cleanup for live controls.
  No owner facts/settings, external actions or notifications are changed.

Run focused regression, refusal/privacy/race controls, installed-model comparison
and full regression. Bind final claims to source/build inputs and disclose
remaining availability limits. No commit, push, release or deployment is authorized.

## Measured outcome and remaining boundary

The scoped candidate retains the existing safety envelope and reduces prompt
size and warm review time in the frozen comparison. It does not resolve the
cold first-inference timeout. A contemporaneous owned-server trace reaches an
empty inference slot and fast sampler initialization before the delay; it shows
no queue or reload, but cannot separate first prefill, GPU/kernel initialization,
graph preparation or decoding. There is no evidence-backed further provider
change within the preserved constraints. Keep the failed controls and pending
answers; do not report cold reliability as achieved. Details and final regression
receipt: `tasks/firstcall-review-notes.md`, `tasks/firstcall-verification-summary.json`.
