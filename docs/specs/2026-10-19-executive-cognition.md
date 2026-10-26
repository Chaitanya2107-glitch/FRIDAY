# Shared executive cognition: first milestone

Owner authorized implementation of the selected next upgrade on 2026-10-19. Direction:
`docs/2026-10-19-brain-assessment.md`. Preserve existing project code/settings and dependencies.

## Contract

- Persist bounded immutable situations in the existing cognition SQLite database. A situation contains
  source IDs/versions, original evidence, channel, local intention, current dated constraints and a
  small stable attention summary. Exclude notes, clipboard text, screenshots and filesystem paths from
  background review. Stored snapshots are evidence, never executable commands.
- Before the supported project-folder action, record a deterministic assessment and expected observable
  result. Revalidate source identity, source versions, cancellation and local channel immediately before
  the actual OS call. A blocker is context, not a reason to prevent opening useful project context.
- Record verified, blocked, cancelled and uncertain outcomes. Make execution receipts available to the
  existing reasoner without claiming source tasks completed or historical windows remain open.
- Reuse the existing watcher/reasoner. Persist queued review fingerprints, exclusive token leases,
  attempts and failure backoff. At most one review starts per 300 seconds and four per rolling hour,
  across workers/restarts. Unchanged completed evidence produces no new call. Changed evidence retires
  stale work. Optional review waits while gaming, busy, speaking/listening or waiting for an answer.
- Add `COGNITIVE_REVIEW_ENABLED=true` independent of `AI_ASSIST_ONLY`; respect the existing reasoning
  master switch and a durable local on/off control. Model calls require the `cognitive_review` purpose,
  reuse strict report/critique schemas and a total 25-second inference budget. Background review cannot
  extract new owner facts, apply inferred changes, execute tools or alter task progress. Proposals still
  use existing owner approvals and notification delivery review.
- Recheck all reviewed evidence and claim ownership before saving. Disabling/clearing/replacing a review
  invalidates in-flight results. Existing source fingerprints invalidate corrected/forgotten conclusions.
- `executive status`, `executive review on`, `executive review off`, `why did you decide that` are local
  typed/voice controls. Status reports policy/budget and factual decisions, not hidden model thoughts.
- Explicit history/workspace clearing and memory forgetting clear derived situations/decisions/reviews,
  invalidate active leases and preserve hourly attempt budgets. Retain at most 200 situations/reviews/
  decisions; attempts older than one day can be pruned. No automatic app launch from background review.

## Implementation order

1. Real SQLite tests and an ExecutiveControl service with immutable snapshots, assessments and outcomes.
2. Wire project preflight/result feedback and expose minimal historical execution evidence to reasoning.
3. Add durable review scheduling and purpose-scoped proposal-only reasoning with atomic acceptance guard.
4. Wire local controls/shared context, privacy lifecycle, watcher integration and usage documentation.
5. Focused then full regressions; bounded live probe, distinguishing provider reachability from model quality.

## Verification

`venv\Scripts\python.exe -B -m pytest tests/test_executive.py tests/test_project_execution.py tests/test_reasoning.py tests/test_ai_assistance.py -q`

Use temporary real files/SQLite and deterministic provider boundaries. Cover restart, independent workers,
hourly limits, failure/lease recovery, stale facts, disable/forget during inference, invalid model output,
privacy, source corrections, cancellation, blocked tasks, local-only commands, chat/voice and watcher.
Full gate: `venv\Scripts\python.exe -B -m pytest tests -q`.
Behavioral scope: project action assessments and shared background evidence review. General preflight
coverage for every older automation path and full temporal/episodic memory remain subsequent milestones.
