# Phase 7: bounded original-source recall

Replace the recent-100 overlap fallback with deterministic text relevance over the
existing 500 dialogue reports and at most 800 reviewed source snapshots. Rank original
text and paired questions, never generated summaries, inferred labels or model guesses.
This first increment is lexical retrieval, not embedding-based semantic search. It
adds no model call, model download, dependency, index, cache or watcher loop.

Return whole bounded canonical source records (text up to 1200, question up to 500),
original ID/channel/date and explicit historical/incomplete-excerpt meaning. No match
means no result. Cap selections at eight originals and 4000 encoded characters; use
existing outer prompt limits. Reviewed thread membership is provenance only and must
not drag unrelated members into context or make the inferred association a fact.

Read one consistent store snapshot. Exclude retained superseded source IDs, archived
correction links and any original containing a superseded commitment. Persist a
monotonic recall-withheld flag in the existing original-episode row when correcting,
so bounded temporal-history pruning cannot re-enable it. Backfill existing retained
links on migration. Do not pretend to reconstruct correction history already lost
before this increment. Forget removes originals/snapshots through existing clearing;
no recall cache or separate search database can restore them.

Keep Telegram reports separate from chat/voice; never expose local reviewed archives
to Telegram. Reuse source fingerprints, epochs, private-context filters and atomic
acceptance. Fail closed when source provenance cannot be read; unavailable is not a
reason to return arbitrary recent dialogue. Recheck source availability after async
conversation context assembly before handing it to the provider.

Use the owner query for dialogue. Reuse bounded task/goal focus for shared reasoning,
inquiry and notification context, retaining IDs so older originals can be cited and
rechecked by the existing executive. Historical recall grants no current state or
action permission. Current revisions and current owner messages take precedence.

Verify old raw sources, archived sources after ordinary retention and restart,
irrelevant-query abstention, ranking, paired answers, channel privacy, corrections
including partial multi-commitment messages, history pruning, forgetting and bounds.
Measure a frozen holdout with unseen queries including negatives and paraphrases.
Report missed paraphrases honestly; do not fit domain synonym lists to the holdout.

Implemented boundaries:

- Current-turn sources are excluded through both raw and archived paths.
- Older focused retrieval has a historical marker, excluded from temporal native
  source enums and the runtime temporal validator. Matching recent originals remain
  eligible for the preexisting commitment review path.
- If superseded revision history is pruned, the persisted original flag still blocks
  recall and prevents rearchiving that source without retained correction provenance.
- The frozen ranking evaluation found 10/13 positive queries at three results and
  abstained on all five negatives. Three paraphrases remain misses. Its exit 1 is
  authoritative evidence of imperfect coverage, not a reason to return unrelated data.

Paraphrase increment (2026-10-21):

- After lexical abstention, explicit recall can score the eligible originals with
  the existing file-search embedding model. Loading uses `local_files_only=True`;
  missing weights, busy embedding resources, gaming or inference failure abstain.
- Use the existing configured model and normalized vectors. Require cosine >=0.65
  and a lead >=0.05 over the next original; return at most one semantic original.
  These conservative thresholds were chosen before running the new frozen corpus.
  Neither reviewed labels nor generated summaries participate in scoring.
- Re-read eligible canonical sources after scoring and again before conversation
  provider handoff. Do not hold the cognition lock during inference. Vectors are
  request-local; no vector/text index persists, including after forgetting.
- Conversations wait at most two seconds for recall. A cancelled wait does not
  terminate a running embedding thread; that thread may finish loading/scoring,
  but writes no memories and cannot later insert results into the reply. Background
  focus queries explicitly remain lexical, avoiding a repeated model workload.
- New frozen corpus: `tasks/recall_paraphrase_holdout.json`. Real cached weights
  found 3/6 positives with 6/6 negative abstentions. Old regression improved to
  11/13 positives with 5/5 negative abstentions. Both evaluation commands retain
  exit 1 because missed positives remain failures. No threshold or synonym tuning
  followed these measurements. These small synthetic results are not relevance
  guarantees; this increment does not solve general paraphrase understanding.

Audit hardening (2026-10-21): whole conversation brain context, including shared
temporal/life state, is fenced against the executive forget epoch and newest
temporal revision before provider handoff. Changed/unavailable versions or disabled
cognition omit this snapshot. Recall receives the conversation's monotonic deadline;
the offline embedder checks it and gaming after loading and between batches, and
discards partial vectors. A native load or batch already in progress cannot be
forcibly terminated. The two-second recall wait is not a total response-time bound.
Broader diagnostic negatives exposed five off-target results out of seven; see
`docs/2026-10-21-brain-crosscheck.md`. The old negative scores are narrow regression
results, not proof of general no-match accuracy.
