# Local review reliability: first increment

Answer: where did a review spend time, why did it stop, and can a smaller supported
contract complete useful local work without changing authority or resource limits?

First retain Ollama load, uncached prompt-processing and generation timings/counts,
completion reason and explicit incomplete status. Missing measurements remain unknown.
Preserve typed provider error causes so an attempt timeout is distinguishable from
network/provider failure. Never accept incomplete structured output as a valid review.

Record bounded private review diagnostics in the existing cognition event store:
phase/attempt, wall duration, scalar provider metrics, result/rejection category and
accepted work counts. No prompts, evidence, owner text, response text, raw errors or
source IDs. Existing clear/forget handling removes events. Diagnostics must not alter
decisions, create model calls, wake another loop or prevent an otherwise valid save.
Expose the latest trace through existing local brain diagnostics and read API.

Measure synthetic generation + independent critique + guarded save on the installed
model before optimizing. Then constrain cognitive schema to one work type and reduce
pure extractive-memory critique to its actual original sources. Preserve all source,
correction, date, uncertainty and independent boolean checks. General consequence
critique retains surrounding context needed to check contradictions. No answer cache.

Measured refinement: cold model readiness is separate from the at-most-25-second inference
window. Both share the existing 45-second executive lease; reserve one second for
acceptance/finalization and clamp inference to the remaining time. Startup has no owner
prompt or generated answer. Recheck source/attention/epoch after loading before inference.
Direct callers without a claimed deadline retain the original 25-second path.
Keep the existing per-attempt/startup allowance, claims,
leases, hourly/attention/gaming limits, models/providers and user settings. No downloads,
new dependency, forced unloading of a shared model or cloud fallback. Diagnostics show
unavailable honestly. A single successful trial is not general semantic reliability.

Tests: malformed/missing metrics, explicit truncation, timeout causes, phase errors,
retry/success, cancellation, privacy/forgetting, unchanged source/epoch checks, real
native schema, mixed-work rejection in schema and unrelated-source negative control.
Run a bounded synthetic installed-model comparison and record resident/cold uncertainty,
separate timings and failures. Freeze code before final focused/full verification.

Official contracts: https://docs.ollama.com/api/chat,
https://docs.ollama.com/api/usage and
https://docs.ollama.com/capabilities/structured-outputs.

Implementation notes and observed evidence (2026-10-21):

- Compact wire reports expand into the existing strictly validated internal report;
  the executive still owns source/attention/epoch/lease checks and atomic persistence.
- Pure memory review compares every cited subject before its boolean verdict. The
  boolean remains authoritative. Earlier false approvals/rejections are retained in
  diagnostic artifacts; no explanation is reinterpreted as approval.
- Final frozen probes a/b each saved three related-memory cases (including a second
  subject) and one dated commitment. In each run unrelated proposals failed both
  critiques, saved nothing, and ended unavailable/evidence_rejected; a separately
  proposed unrelated grouping was also rejected. That rejection is a safe stop,
  not a completed useful review. No owner fact, command or notification was created.
- Nonresident startup took 5.59/5.63 seconds in the first case; whole reviews took
  7.84/7.91 seconds. Resident useful cases took 2.50-3.36 seconds. These naturally
  observed loads did not force-unload any shared model. Empty-load responses omitted
  component metrics, which remain unknown; startup wall time is measured separately.
- Both probes verified frozen source hashes. Evidence:
  tasks/reliability-final-live-probe-a.json and -b.json. These are small synthetic
  controls on the installed model, not a guarantee across new subjects/hardware.
- Date recovery only fills an omitted phrase from a verified exact quote using
  supported calendar grammar. It does not infer intent; corrections/postponements
  and ambiguous/negated/multiple dates stay unresolved. Conflicting temporal repeats
  remain invalid; exact duplicates are collapsed before independent critique.
- A separate local HTTP setup microbenchmark motivated skipping certificate-store
  construction for plaintext loopback HTTP only. Do not infer an overall speedup
  from it or from earlier probes with different cache/residency/code states.

Verification: 5,197 full-suite tests and 355 focused checks passed; zero failures/errors/skips, one existing deprecation warning. Full run: 325.34 seconds. Sixteen affected Python files parsed; whitespace clean. Two frozen five-case installed-Ollama probes produced eight useful saves and two safe evidence rejections; both separately proposed unrelated groups were rejected. Useful reviews took 2.50-7.91 seconds; nonresident startup wall time was 5.59/5.63 seconds. No owner facts, commands or notifications were created. Evidence: tasks/reliability-final-verification.*, tasks/reliability-final-focused.*, reliability-final-live-probe-a.json/-b.json, reliability-source-validation.txt and reliability-review-notes.md. These small synthetic controls do not establish general model reliability; continue the saved phase 6 coverage work.

Further official contracts: https://docs.ollama.com/api/generate (empty prompt loading)
and https://docs.ollama.com/api/ps (resident models). Continue phase 6 with more unseen
semantic controls and observed cold starts before phase 7 relevance-based retrieval.

Source-grounding continuation (2026-10-21):

- Every memory citation needs an exact source-text quote and explicit source verdict;
  incomplete, duplicated, unknown or rejected citations block the whole report.
- Review source relatedness without the proposed title first, then separately review
  the original title. Canonical citation order removes input-order variation. All
  calls share existing review time/attempt/attention limits; no quota increase.
- Private diagnostics retain scalar memory-relatedness/label stages and up to six
  calls. Production diagnostics never retain the new critique quotes themselves.
- The first quote-only prototype still approved an unrelated pair. Blind review
  blocked the original bank regression, but a fresh frozen v3 control still approved
  unrelated artwork under a broad category. Source grounding is a strict structural
  safeguard, not proof of correct model semantics. Do not mark phase 6 cleared.
- Natural nonresident loads were observed without forcing unloads (5.562 seconds in
  the regression, 6.172 seconds in the final frozen v3 trial). Keep full failed-case
  evidence; do not substitute separate supplied-control success for workflow success.

Entity-relationship and retry-scope continuation (2026-10-21):

- The blind critic must name a grounded entity and source-specific meaning for each
  citation before classifying the relationship. A broad category, unrelatedness or
  uncertainty cannot authorize a group even with overall supported=true.
- An explicit relationship refusal ends the pass, including when another field is
  malformed. Invalid structural output can still use the existing correction attempt;
  positive results require every source/quote/entity check and label review.
- Validate the native work selector before its body and retain it across corrections.
  Repair the selected kind or choose silence, rather than turn a refused grouping into
  temporal work. Preserve legacy temporal/memory priority and all acceptance guards.
- Final fresh v5 met 8/8 workflows with zero unrelated saves; its supplied controls
  included one false rejection, so CLI exit 1 remains correct. Old v3 regression met
  8/8 workflows and 8/8 supplied controls, refusing the earlier seal failure. Both final
  trials used identical frozen production hashes. No claim of perfect semantic judgment.
- Source-grounding and this follow-up increment are implemented. Next is bounded
  relevance-based recall of original historical evidence; continue calibration of
  false rejections and initial work selection as documented follow-ups.
