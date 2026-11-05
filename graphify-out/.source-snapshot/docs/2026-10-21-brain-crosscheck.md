# Brain roadmap cross-check — 2026-10-21

Verdict: useful first increments exist for phases 1–7, but they are not complete
or perfectly reliable. A passing unit suite does not prove that the local model
always chooses the right work, extracts a date, or retrieves the right object.

## Reproduced defects and fixes

1. **High: forgotten situation could reach a conversation provider.** Recall
   originals were revalidated, but the shared temporal situation had already been
   appended to the prompt. Forgetting during behavioral-state assembly removed
   database sources while leaving that copied appointment in the outbound prompt.
   Reproduced with a temporary store and captured provider payload. Fixed by
   deferring prompt assembly and fencing the entire brain context with the
   executive forget epoch and latest temporal revision. Changed/unavailable
   versions or disabled cognition discard that context before provider handoff.
   Revisions conservatively omit the snapshot; they are not silently persisted or
   treated as verified facts. Already handed-off requests cannot be recalled.

2. **Medium: attention/deadline checks did not cover cold model loading.** Gaming
   was checked before loading, so gaming begun during loading could be followed by
   recall inference. A timed-out reply also left all source encoding running.
   Reproduced with controlled load/batch transitions. Fixed by passing the reply's
   monotonic deadline into recall and checking attention/deadline before and after
   loading and between embedding batches. Partial vectors are discarded. A running
   native model load or individual batch cannot be forcibly interrupted; after it
   returns, no next batch starts when deferred. No persistent vector cache added.

Four initial audit regressions failed before the fixes
(`tasks/brain-crosscheck-red.log`). Final audit tests cover unchanged context,
forgetting, a new commitment revision, disabled cognition, failed version reads,
gaming during load, expired cold-load deadlines and gaming between batches.

## Accuracy and live model limits still open

The new 11-query diagnostic corpus was frozen before inference. Four positive
queries found 3 intended sources. Of 7 queries about different objects/events,
only 2 abstained: **5 returned off-target originals**. Examples include a bicycle
tyre report for a motorcycle query, a coat zipper report for hiking boots, a
postponed acoustics exam for chemistry, and passport storage for a driving licence.
Lexical-only mode made 3 of these errors; embeddings added 2. Exact original text
and historical qualifiers remain in the prompt, but downstream language must still
avoid asserting that an off-target original answers the current question.

This is a relevance defect, not evidence that wrong facts were written or actions
executed. No domain exception/synonym lists, threshold changes or model prompt
tuning were fitted to this audit. Address object/event identity before claiming
general no-match accuracy or prioritizing broader recall coverage.

Existing recall regressions reproduced: 11/13 positives and 5/5 negative
abstentions in v1; 3/6 positives and 6/6 negative abstentions in the paraphrase set.
All runs retained correction exclusion, forgetting and retention/restart controls.
CLI exit 1 for missed positives or off-target negatives remains failure evidence.
Artifacts: `tasks/brain-crosscheck-recall*.json`,
`tasks/brain-crosscheck-lexical-only.json`,
`tasks/brain-crosscheck-paraphrase-regression.json`,
`tasks/brain-crosscheck-lexical-regression.json` and corresponding logs. All four
evaluation artifacts' production hashes match the reviewed code.

Four fresh installed-Ollama consolidation controls used temporary stores and the
existing `qwen2.5:3b-instruct-q5_K_M`. The independent critic made 4/4 correct
relationship judgments; the full workflow met 3/4 expectations. One positive
workflow was rejected by its evidence checks, while a separate diagnostic critic
approved the supplied grouping. Both unrelated controls saved no groups; no owner
facts, commands or notifications were created. This is continuing false rejection
and work-quality variability, not universal reasoning reliability. Natural
nonresident readiness took 9.797 seconds. Artifact:
`tasks/brain-crosscheck-semantic.json` / `.log`; sources stayed unchanged.

The fresh real temporal trial returned unavailable and saved no initial commitment
after two invalid generations, including a date phrase copied from receipt
metadata rather than the quoted report. Consequently its correction branch did
not run. Validation safely refused persistence; this trial does **not** verify
reliable live date extraction/revision. Artifact:
`tasks/brain-crosscheck-temporal.log`. Retain this failed trial rather than retrying
until a passing example can be reported.

## Built scope and runtime checks

| Phase | Implemented scope | Cross-check / practical limit |
|---|---|---|
| 1 | Source-linked commitments, original-date anchoring, revisions and history | Runtime validators reject unsupported dates; fresh live trial abstained. |
| 2 | Evidence-based priorities, attention/quiet gates, bounded timing feedback | Software behavior, not emotion or independent knowledge of the owner. |
| 3 | Expected/read-back outcomes and cautious lessons for master audio and selected modes | Not verification of every action, physical sound or task completion. |
| 4 | Ranked gaps for blockers and undated commitments; optional questions | Not open-ended autonomous research; quiet still blocks questions. |
| 5 | Reviewed extractive threads with original provenance/corrections | Bounded retention; inferred labels never become owner facts. |
| 6 | Local generation, independent critique, guarded persistence and budgets | Real model still rejects useful work; cold startup and calibration remain limits. |
| 7 | Bounded lexical retrieval, conservative local embedding fallback for explicit recall | Background focus remains lexical; object/event confusion remains open. |

Read-only HTTP `/health` returned 200/online on port 8000. This proves service
reachability, not that its existing process has reloaded the audit fixes.
`tasks/brain-crosscheck-runtime.json` records the check. Restart FRIDAY to load
updated code when automatic reload is off.

The outcome probe read the real Windows audio adapter without changing it.
Synthetic mismatched readbacks remained failed despite successful driver flags;
two failures produced cautious diagnostic advice and changed the life-state focus.
Quiet allowed silent review, produced no autonomous question and made zero inquiry
model calls. The executive chose silence, so no useful conclusion was saved in
this trial. Artifact: `tasks/brain-crosscheck-outcomes.log`.

## Verification

Fresh full suite: **5,263 passed**, zero failures/errors/skips, in **522.39 seconds**;
one existing Starlette/httpx deprecation warning. Artifacts:
`tasks/brain-crosscheck-verification.log` / `.xml`. The eight new audit cases pass.
An earlier focused run passed 93 cases before the final context-version transaction
adjustment; use the final full suite as the authoritative result.

The real cached-embedding cold-load timing probe used a stub conversation provider
and temporary source store. It returned the reply in **3.485 seconds**, while cold
loading took **17.203 seconds** and the process finished in 18.688 seconds after
executor shutdown. **Zero embedding batches** started after the expired deadline.
This verifies the post-load deadline check; it does not promise total reply time
under two seconds or measure actual conversation generation latency. Artifacts:
`tasks/brain-crosscheck-reply-timing.json` / `.log`.

Eight changed Python files parsed; trailing whitespace checks passed. Existing
unrelated working-tree changes were preserved. No models/dependencies downloaded,
provider configuration changed, physical control actions performed or notifications
sent by these probes. Model-generated source content was synthetic only.
Physical control mutations and every external integration were not exercised live;
their automated tests and the read-only audio check define this audit's scope.

Follow-up implemented 2026-10-22: see `tasks/identity-date-review-notes.md` and the
latest roadmap entry. Conservative recall now abstains on all seven audit negatives,
with reduced positive coverage; a fresh set still has one off-target result. Unique
quoted dates can repair unsupported model fields, and dated postponements use their
new date in shared views. The repaired date regression passes, but a fresh correction
was safely rejected. Final follow-up suite: 5,278 passed; these limits remain open.
