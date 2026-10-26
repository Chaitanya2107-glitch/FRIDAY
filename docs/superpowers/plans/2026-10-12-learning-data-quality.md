# Learning Data Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Automatically screen and categorize Friday's retained learning data, gate next-app training on valid observed examples, and send a weekly Telegram audit with honest counts.

**Architecture:** Local source adapters feed a SQLite metadata catalog. A boundary-preserving dataset builder creates next-app samples for the learner; immutable report snapshots and training-run manifests supply the existing Telegram scheduler.

**Tech Stack:** Python, SQLite, existing scikit-learn pipeline, existing Telegram Bot API sender, pytest.

**Spec:** `docs/superpowers/specs/2026-10-12-learning-data-quality-design.md`

## Global Constraints

- No raw learning payloads are duplicated in the catalog or sent in the aggregate report.
- Unique source IDs and sample IDs, not processing passes or weights, determine counts.
- Minimum settled session 5 seconds; maximum unobserved gap 60 seconds.
- Unknown-origin historical activity and autonomous Friday activity cannot train the natural-user predictor.
- Preserve counting fallback, 300 earlier/100 held-out examples, at least two target classes, and a 0.02 top-3 improvement with no top-1 degradation.
- Source facts/conversations remain separate from next-app training; preserve reviewed-example export controls.
- Sunday 21:00 default schedule uses the existing configuration; retry frozen report snapshots and catch up missed tracked periods.
- User explicitly approved the design and instructed implementation on 2026-10-12; execute in this session.

## Review Focus

- Missing, malformed, locked or partly scanned source stores must not erase previous eligibility or silently imply complete coverage.
- Rejected intermediate sessions and restarts must break transitions instead of fabricating app choices.
- Reclassification, source removal and repeated feedback weighting must not inflate audit totals or leave stale samples.
- Forecast confirmations must not become observed labels or leak across evaluation cutoffs.
- Weekly retries/restarts must preserve the same report counts and avoid synthesizing reports before tracking started.

### Task 1: Shared contracts, catalog and source adapters

**Files:** Create `services/learning/contracts.py`, `catalog.py`, `sources.py`, `service.py`, `__init__.py`; tests `test_learning_catalog.py`, `test_learning_sources.py`.

**Interfaces:** `LearningRecord`, `Session`, `PredictionFeedback`, `TrainingExample`, `SourceScan`; singleton `catalog`; `catalog.ingest(records, now, complete_sources, coverage)`, `catalog.replace_examples(examples, now, fingerprint)`, `catalog.record_training_run(run)`, `catalog.report(start, end, freeze_key=None)`; `service.refresh(log=None, now=None)`.

- [x] Write failing fixtures for idempotent ingest, backfill, unknown categories, source revision/removal, malformed/private records and metadata-only retention.
- [x] Implement SQLite catalog and source adapters with read-only source access, stable identities and source coverage diagnostics.
- [x] Verify exact funnel totals, per-category totals, source deletion handling and immutable snapshots.

### Task 2: Dataset builder and actual learner gating

**Files:** Create `services/learning/dataset.py`; modify `services/mind/learner.py`; tests `test_learning_dataset.py`, `test_learning_learner.py`.

**Interfaces:** `dataset.build_examples(sessions, feedback, now, min_seconds=5, max_gap_seconds=60)` returns `Dataset`; examples expose `row`, source IDs, outcome time, feedback timing and weight.

- [x] Write failing fixtures for A/rejected-B/C, idle gaps, short sessions, future timestamps, unknown/automatic origins and mismatched confirmations.
- [x] Implement observed-transition construction with stable IDs and weights without repeated rows.
- [x] Integrate snapshot-based chronological train/test splitting and uniform feature/weight recipes.
- [x] Record skipped/completed fitting runs and publish only the evaluated candidate; test fallback, insufficient labels and promotion gates.

### Task 3: Origin tracking and runtime refresh

**Files:** Modify `services/activity/log.py`, `services/automation/intent.py`, `services/mind/foresight.py`, `services/activity/habits.py`, `services/proactive/watcher.py`, `core/config.py`, `.env.example`, `tests/conftest.py`; tests `test_learning_origin.py`, runtime integration tests.

- [x] Add reversible schema columns and instrument user-requested versus autonomous opens; initialize a per-runtime boundary for new observations.
- [x] Persist feedback availability time without asserting forecast fulfillment.
- [x] Add validated config switches and a local periodic catalog refresh; isolate all new storage in tests.
- [x] Verify new sessions gain attributable provenance, historical sessions remain unknown, automated switches are excluded, and ordinary commands still work.

### Task 4: Weekly and on-demand reporting

**Files:** Create `services/learning/reports.py`; modify `services/telegram/summaries.py`, `commands.py`, `capabilities.py`; tests `test_learning_reports.py`, `test_learning_telegram.py`.

- [x] Write failing tests for exact counters, reason totals, inferred/observed separation, training/evaluation units and omission of source content.
- [x] Append the learning section to weekly recap; expose `learning report`, `training data status`, and Telegram delivery of the learning report.
- [x] Persist frozen snapshots and tracked weekly catch-up; verify retries send identical counts and startup does not fabricate older reports.

### Task 5: Review, documentation and activation

**Files:** Update `docs/FEATURES.md`, implementation status in spec/plan; focused and full test suite.

- [x] Review data contracts and actual catalog-to-training call path against the approved spec.
- [x] Run focused learning/Telegram/brain tests followed by `venv\Scripts\python.exe -m pytest tests -q`.
- [x] Backfill retained local sources, inspect an aggregate report and verify reconciliation without uploading raw data.
- [x] Reload the running backend, verify current commands and configured weekly schedule, and report real initial eligibility/coverage limits.
- [x] Commit only task-owned files where doing so would not include the user's existing uncommitted code.

## Verification and activation evidence

- Independent model/data review resolved short-session bridges, unstable transition identities,
  future-informed features, cutoff-crossing evaluation and misleading source-failure skips.
- Full suite: **1740 passed**, one existing FastAPI/httpx deprecation warning.
- Initial inventory: **40610 records / 27 categories**; 39923 accepted, 455 excluded,
  232 quarantined, 0 pending. These are initial historical inventory totals, not weekly growth.
- Initial next-app eligibility: **0**; historical activity origins are unknown. Training recorded
  an explicit insufficient-data skip and counting remains available. Existing model artifacts were
  copied locally to `memory/mind/before_learning_quality` before retirement.
- Initial local aggregate report: `memory/learning_initial_audit.txt`. New records and migration
  revisions after backend startup continue to change the live inventory without inflating backfill.
- Backend reloaded with tracking enabled; live `/health` reports online. Both `learning report`
  and `training data status` returned local system-action audits through `/api/v1/chat`.
- Telegram configuration verified ready, Sunday 21:00 local time. No live test report or file was sent.
- Task-only learning modules/tests/spec/plan are saved separately; pre-existing uncommitted
  integration files and the user's staged `.env` deletion remain intact.
