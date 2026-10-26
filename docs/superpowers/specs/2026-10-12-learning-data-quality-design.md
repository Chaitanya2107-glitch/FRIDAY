# Learning-data quality and weekly Telegram audit

Date: 2026-10-12
Status: Implemented and activated on 2026-10-12; 1740 tests passed.

## Intent and scope

The owner wants Friday to filter the data she learns from, organize that data into categories,
and deliver a weekly Telegram report showing category creation, collected records, appropriate
records, and examples eligible for ML training. This is the first milestone before the broader
task-aware brain upgrade.

The current trained model predicts the next app. The first release therefore catalogs the
existing learning sources, but admits only examples that satisfy the next-app model's contract
to that model. Useful facts, conversations, corrections, and reviewed lessons remain separate
learning sources; they are not automatically app-prediction examples or language-model training.

Defaults for review: automatic rule-based screening, local catalog and datasets, aggregate
Telegram reporting, existing counting fallback and model-promotion thresholds. No new model
framework, cloud dataset upload, or deletion of original data is required.

## Existing components to extend

- `services/activity/log.py`: source activity records already have IDs, timestamps, app,
  duration and category. `app_sequence()` currently drops most of these fields.
- `services/activity/categories.py`: existing activity categories and learned classifications.
- `services/mind/learner.py`: nightly next-app model, chronological test window, counting baseline.
- `services/mind/foresight.py`: prediction confirmations currently duplicated three times by
  `verified_rows()`; these express intention and need not match observed behavior.
- `services/memory/semantic.py` and `services/memory/episodes.py`: facts and conversation summaries.
- `services/mind/knowledge.py`, `thoughts.py`, `corrections.py`, and `reviews.py`: learned
  explanations, patterns, corrected commands and owner-reviewed examples.
- `services/telegram/summaries.py`: existing weekly recap, configured recipient, retry and
  persisted delivery markers. The default schedule is Sunday at 21:00, laptop local time.

## Accounting contract

Every catalog item has a stable source identity. Polling, restarting, reclassification and
retraining must not create additional collected records for an already cataloged source item.

| Metric | Definition and unit |
| --- | --- |
| Collected | Unique new source records first cataloged within the report window, excluding historical backfill. Unit: source record. |
| Historical backfill | Previously retained records inventoried during this rollout. Shown separately from newly collected records. |
| Appropriate | Collected records that pass their source-specific quality rules. This does not establish absolute factual truth. Unit: source record. |
| Excluded | Collected records unsuitable under a known policy, with a recorded reason. Originals remain in their existing source stores. |
| Quarantined | Collected records needing clarification, verification or repair. They cannot enter training while unresolved. |
| Pending screening | Collected records not processed yet; never silently treated as accepted. |
| Categories active | Distinct primary category buckets containing collected records in the window. |
| Categories created | Durable primary buckets first registered in the window, excluding the initial historical-backfill registry. |
| ML eligible | Unique derived next-app examples first becoming eligible within the report window. Also show the eligible dataset available at cutoff separately. Unit: transition example, not source record. |
| Used for training | Unique eligible example IDs included in actual fitting runs during the window. Weighted repetitions do not increase this count. |
| Evaluated | Unique example IDs used for validation/test during the window. An example can be evaluated in an earlier run and fitted in a later run; this count is not additive with the fitting count. |

The source-record funnel satisfies:

`collected = appropriate + excluded + quarantined + pending_screening`

ML examples are derived from source records and have their own counts. A valid memory can be
appropriate while contributing zero next-app examples. Rejected outcomes and negative feedback
can be useful learning records without supplying a positive multiclass prediction label.

## Catalog and categories

Keep source stores authoritative. Add a small local SQLite catalog referencing records, with:

- source name, stable source ID and source revision;
- source event time, first cataloged time, and historical-backfill flag;
- primary category, classification version and classification evidence;
- screening status, reason code and screening-policy version;
- applicable model contracts and derived example links;
- source removal/revocation state.

An item's source revision can trigger reassessment without increasing the collected count.
The catalog stores audit metadata rather than a second copy of private conversation or file content.
Source removal or revoked approval must invalidate associated eligible examples.

Primary learning families cover activity observations, command outcomes/corrections, prediction
and habit feedback, semantic facts/plans, conversation records/summaries, learned knowledge and
thought patterns, and owner-reviewed lessons. Operational credentials and access tokens are
outside the learning catalog.

Reuse activity-purpose labels such as coding, study, communication, entertainment and project
work where already supported. A primary bucket can be `activity/coding` or `prediction_feedback`.
Optional topic/project tags do not inflate primary-category totals. Unknown classification is
an explicit bucket; a missing purpose category alone does not invalidate an otherwise usable
next-app label. Do not invent categories merely to make the weekly creation count grow.

Enumerate retained source coverage during initial backfill. Sources with only cumulative state
or previously pruned records must report their limits; past individual observations cannot be
reconstructed honestly from aggregate counters. Freeze report classifications at their cutoff.

## Screening and next-app eligibility

Use deterministic, versioned checks rather than an AI model declaring its own data correct.

Source screening checks stable identity, required fields, parsable time, invalid/future time,
valid durations where applicable, duplicate source identity, reliable classification evidence,
and source-specific approval or sensitivity rules. Uncertain facts remain identified as inferred;
owner corrections take precedence over unsupported guesses.

Build examples from ordered raw app-session records, retaining IDs, duration and boundaries.
Never filter a rejected session out and then invent a direct transition across it. For the
sequence A, rejected B, C, neither A-to-C nor its prior-app context may be synthesized.

The initial next-app sample contract is:

- source and destination are valid, distinct observed app identities;
- both sessions are appropriate, with stable IDs and valid chronological timing;
- features contain only information available at the prediction snapshot (`feature_at`);
- use the source session's first known timestamp uniformly for train/evaluation/deployment app-switch
  features, never a later destination or retrospectively recorded confirmation timestamp; forecast
  confirmations may supply weights but do not change historical feature time;
- the target is the actual subsequent observed app, with a separate `label_at`;
- system-window, idle, invalid-record and restart boundaries reset continuity/context;
- proposed default settled-session threshold: 5 seconds for each session;
- proposed default maximum unobserved gap between source end and destination start: 60 seconds;
- short or interrupted sessions remain cataloged, but affected transitions are ineligible;
- no raw window titles, file contents, conversation text or credentials enter this dataset.

The two timing defaults are policy parameters requiring owner review. A minimum-duration rule
must not silently bridge over quick intermediate app visits.

User confirmation of a forecast is stored as feedback. It becomes supporting evidence for an
app-transition example only if linked to the observed matching outcome. A negative answer alone
does not name the actual next app. Stable example IDs connect observations and feedback; explicit
sample weights can express stronger evidence without creating duplicate examples or higher counts.

Distinguish user-initiated actions from autonomous Friday actions. Add causal metadata for new
automated app opens and affected observations. Exclude autonomous transitions from natural-user
behavior training. Historical records without origin evidence remain marked unknown; do not claim
they are verified human choices. Existing snapshots and future-origin tracking must disclose this
coverage limit in reports and dataset manifests. Conservative default: unknown-origin historical
observations can be appropriate records, but are ineligible for natural-user training until their
origin is reviewed or attributable. Counting remains available while newly tracked, eligible
observations accumulate; the report must explain this temporary eligibility shortfall.

## Training integration and evaluation

The catalog must govern the learner's real input, not merely provide a decorative report.
Every training run consumes a versioned dataset snapshot and records its policy version,
source/example IDs, cutoff, train/evaluation counts, weights and resulting metrics.

Apply one feature/filter/weight recipe to evaluation and deployment. Feedback and features
must have been available before each chronological cutoff. Do not inject later confirmations
into an earlier training fold. Keep evaluation outcomes independent of owner forecast confirmations.

Preserve the existing minimum-data gates: 300 earlier examples, 100 test examples, and at least
two trainable target classes. Preserve the counting fallback and current promotion criteria:
top-3 improves by at least 0.02 without degrading top-1. Publish the candidate actually evaluated;
do not silently replace it with an all-data/extra-confirmation refit and attribute the earlier score
to that different artifact. If filtering leaves insufficient data, report the skipped run reason.

The report must distinguish data eligibility, actual training, evaluation performance and model
promotion. Passing screening does not guarantee model accuracy improved. Reviewed text examples
keep their existing approval/exportable controls; no automatic language-model fine-tuning is added.

## Weekly Telegram report

Append a compact learning-quality section to the existing weekly recap. Use the configured
Telegram recipient and weekly schedule. Learning accounting uses consecutive scheduled cutoffs
with half-open windows `[previous cutoff, current cutoff)`, clamped to the tracking start. At the
default Sunday 21:00 delivery this includes the previous Sunday evening; no interval is dropped
between reports. The existing activity recap retains its calendar-week period. Label both periods
explicitly in laptop local time. Late-arriving data after the frozen cutoff appears in a subsequent report.

Include:

1. period, tracking start, source coverage and initial-backfill count when relevant;
2. categories active, categories newly created and per-primary-category record counts;
3. collected, appropriate, excluded, quarantined and pending-screening record counts;
4. top exclusion/quarantine reasons with counts;
5. eligible next-app examples, examples actually fitted/evaluated, latest dataset/policy version;
6. latest measured model/baseline performance, promotion or skipped-training result;
7. unresolved source/label/origin coverage limits.

Send aggregate labels/counts and fixed reason descriptions, not raw messages, titles, personal
facts or file paths. Freeze a report snapshot and reference it on delivery retries; do not
recalculate changing totals for the same report period. Successful delivery persists its marker.
Reuse the existing five-minute retry policy and sender without overriding the configured schedule.
Represent failures honestly; network-ambiguous delivery cannot be promised exactly once.

Provide on-demand commands: `learning report`, `training data status`, and
`send me my learning report through telegram`. They use the same report builder and definitions.
When Friday is not running at the configured time, deliver the missed unsent period after startup
without mixing it with the new period. Keep delivery counts separate from data counters.

## Acceptance criteria

- Repeated ingestion/restart/reclassification leaves unique collected counts unchanged.
- Every supported retained learning item has a primary category or explicit unknown classification.
- Source-record funnel totals reconcile; historical backfill and updates are separate.
- Uncertain/malformed records have reason codes and cannot enter training while quarantined.
- Rejecting B in A/B/C does not fabricate an A/C transition or stale prior-app context.
- A confirmation without an observed next app remains feedback, not ground-truth training data.
- Threefold evidence weighting still counts one unique example in the report.
- Facts/conversation records are not admitted to the current next-app model.
- Autonomous app openings are marked and excluded from natural-behavior examples when provenance exists.
- Future feedback cannot cross chronological training cutoffs; training/evaluation use the same recipe.
- Source deletion or revoked review approval removes affected eligibility from future snapshots.
- Inadequate datasets leave counting operational and explain why training was skipped.
- Report retries use identical frozen counts and do not count processing attempts as collected data.
- Weekly cutoff, late ingestion, restart catch-up, per-category totals and sender failures are tested.
- Raw private content and credentials do not appear in the aggregate Telegram report.

## Delivery slices after approval

1. Source contracts, catalog/backfill and honest category/quality counts.
2. Boundary-preserving next-app builder, outcome links, origin tracking and learner integration.
3. Frozen weekly/on-demand report integration and persisted training-run accounting.

Use temporary SQLite/JSON fixtures and mocked Telegram sends for tests. Replay representative
activity locally to compare the filtered baseline with the existing dataset before promotion.
Introduce a reversible configuration switch for the filtered learner; retain the existing fallback
and original source data throughout rollout. Changing the selected predictor or the broader brain
workspace remains separate work after this first milestone is verified.
