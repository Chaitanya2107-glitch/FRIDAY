# FRIDAY cognition assessment and selected next upgrade

Assessed 2026-10-19 after implementing and verifying the project-execution workflow. This document
is the requested brainstorming/selection result. Proposed cognitive behavior below is not shipped
by the execution change. Planning, code review and source-driven research informed the assessment.

Implementation follow-up: the owner subsequently authorized the first executive milestone. It now
implements versioned situations, project preflight/outcome feedback and durable, scoped background
review. See `specs/2026-10-19-executive-cognition.md` and the current FEATURES entry. The baseline gaps
below describe the assessment before that implementation; broader memory/execution upgrades remain future.

## Decision

Build a **shared executive cognition loop** next, backed by versioned evidence. It should keep track
of what matters, check intent and relevant facts before consequential actions, observe results and
reconsider its plans when circumstances change. Reuse the existing cognition, reasoning, memory,
notification and execution services rather than introduce another independent brain framework.

The useful goal is human-inspired capabilities: attention, recall, uncertainty, planning, inhibition,
verification and learning. There is no basis to claim that this reproduces a human brain or consciousness.
Progress should be measured by behavior on real assistant tasks.

## What already exists, and the gaps

| Layer | Existing repository evidence | Most consequential gap |
|---|---|---|
| Perception and attention | `services/mind/brain.py`, activity sensors, `services/proactive/watcher.py` | Observations and goal priorities do not form one persistent current situation used by every action path. |
| Working memory | `cognition.py`, `workspace.py`, `cognition_context.py`, scoped reference context | Events/goals/short references exist, but there is no unified active intention, expected result and pending verification. |
| Personal memory | `services/memory/semantic.py`, schedule/deadline/class records, reasoning facts | Several stores model source/time differently; semantic replacement deletes older rows, while deadlines retain correction history. |
| Reasoning | `reasoning.py`, `reasoning_store.py`, `reasoning_effects.py` | Evidence citations, schema validation and critique already exist. The effective assist-only policy disables general reasoning, and most successful local commands bypass it. |
| Background thought | `reasoning.review()`, `brain.think()`, reflection, task follow-ups | The model review uses a five-minute gate and process-local evidence signature. There is no unified durable review queue/budget across restart. |
| Action control | `intent.py`, `actions.py`, supervised desktop agent and execution engine | Individual guards/confirmations exist, but a common pre-action evidence/precondition contract does not cover every tool path. |
| Outcome learning | Cognition events, prediction/review records, new verified project execution | Execution checkpoint evidence is not yet a first-class, queryable episode feeding shared deliberation. |

Effective flags were checked without reading or printing credentials: `AI_ASSIST_ONLY=true`,
`REASONING_ENABLED=true`, `COGNITION_ENABLED=true`, `NOTIFICATION_REVIEW_ENABLED=true`.
`reasoning.analyze()` returns disabled under assist-only; a reasoning flag alone does not enable it.
Notification review has its own permitted purpose and remains available.

The new project execution provides a useful foundation: five durable steps, source checks, an observed
Explorer folder and recovery without blind resubmission. It is a concrete workflow, not arbitrary planning.
The existing routine keyboard ordering/client execution and mode-cleanup findings remain open in
`wiring-audit-2026-10-15.md`; those paths must not become autonomous merely because deliberation exists.

## Ranked upgrades

| Priority | Upgrade | Why this order |
|---|---|---|
| 1 | Shared executive cognition with a minimal versioned evidence registry | Connects existing capabilities and prevents reasoning/action/memory from disagreeing about current state. |
| 2 | General temporal personal memory | Preserve who said what, when it was true, corrections and conflicts across all stores, extending the existing deadline/class patterns. |
| 3 | Episodic recall and consolidation | Retrieve relevant past conversations and verified outcomes across days; retain source episodes behind any summary. |
| 4 | Outcome-based procedural learning | Learn reusable procedures only from verified executions and owner-reviewed corrections. |
| 5 | Broader planning and application adapters | Add independently observable tool steps after executive checks and evidence updates work. |

A larger model, a knowledge graph or more frequent prompts alone does not resolve the current wiring
and state-consistency gaps. Evaluate model choice later against the same workflows and actual hardware.

## What “think on its own at all times” should mean

While FRIDAY and the laptop are running, maintain a lightweight event-driven attention loop. New
owner messages/corrections, meaningful activity changes, due commitments, blockers and execution
results can make a situation worth reviewing. A persistent timer catches missed/due work after sleep
or restart. Unchanged evidence should not cause another model call.

Use two speeds:

- **Fast pre-action check:** resolve the intended target and channel; check current facts, source
  versions, permissions, confirmations, cancellation and an observable success condition. Obvious local
  commands should remain responsive and work offline. This is required control logic, not an LLM vote.
- **Deliberate review:** when a goal conflict, correction, ambiguous intent or blocked task needs
  interpretation, retrieve relevant dated evidence and run the existing structured reasoning/critique.
  The output can propose, ask, wait or abstain. An inference is not a fact or an execution permission.

Store a concise decision record: cited evidence, allowed action scope, expected outcome, confidence
as an estimate and unresolved questions. Do not manufacture a stream of private thoughts or treat a
model-generated rationale as proof. Follow every action with its adapter's observation.

This gives continuous readiness with selective computation. A tight loop producing repeated model
thoughts would add resource use without establishing better cognition. No operation runs while the
machine is asleep or FRIDAY is stopped; missed work must be reconciled on startup.

## First implementation milestone for the selected upgrade

Start with the new project-session workflow and existing proactive task help:

1. Add an immutable bounded situation snapshot: active owner goal/task, selected project, current dated
   constraints, relevant source IDs/versions, recent verified outcomes, pending question and channel.
2. Add a pre-action assessment for the project adapter: proceed, ask, defer or refuse with a factual
   reason and explicit observable result. Recheck versions immediately before the actual side effect.
3. Feed the execution's verified/blocked/cancelled result back into the same situation. A completed brief
   never completes an assignment; an open folder never proves the owner worked on it.
4. Persist review requests with evidence fingerprints, a single-worker lease, expiry and failure backoff.
   Start with at most one background review per five minutes and four per hour. These are proposed
   budgets to measure, not settings enabled by this change. Defer optional work while gaming/busy.
5. Permit bounded structured review through an independent `cognitive_review` purpose. Keep general
   model tool calling and unrelated assist-only restrictions intact. The owner has requested cognitive
   review; make its behavior/status and disable control visible rather than silently changing the global mode.
6. Reuse existing reasoning schemas, critique, notification delivery review and execution claims. Start
   in proposal mode for autonomous planning; existing explicit commands keep their current authority.

Example: a project session encounters an owner-recorded blocker. FRIDAY retrieves the current blocker,
checks what action could actually help, prepares the verified context and offers that next step at a
suitable time. If the owner says the blocker changed, old suggestions become stale. It never infers
completion from app usage or repeats the same suggestion after rejection without new evidence.

## Memory changes after that milestone

Adopt one shared evidence envelope without immediately migrating every database: identity, subject,
source, recorded time, valid-from/valid-to, certainty, version, correction lineage and visibility scope.
Have adapters expose current authoritative facts from existing stores. Owner corrections invalidate
dependent conclusions, queued reviews and action proposals. Conflicting statements stay unresolved
until disambiguated; similarity alone must not decide which fact to erase.

Keep separate views of working context, dated episodes, stable personal facts and reviewed procedures.
Search by relevance and time as well as recency. Summaries must retain source links and be retractable;
deleting/forgetting a source must remove or invalidate its derived representations too.

## Acceptance tests before claiming a better brain

- A correction changes the next relevant decision, including after restart; old conclusions are not reused.
- A blocked/cancelled/uncertain execution never becomes a success through reasoning or a persuasive reply.
- A pending confirmation cannot be consumed by another channel, session or changed target.
- An unchanged situation does not trigger repeated model calls; budgets survive restart and concurrent workers.
- Background review can notice a useful task without a new prompt, and can also choose silence.
- Model failure preserves deterministic local commands and essential reminder scheduling.
- A model cannot generate a tool permission, execute a saved plan or overwrite a confirmed fact as an inference.
- Multi-day recall distinguishes current facts, earlier facts and missing evidence. Unknown answers abstain.
- Track verified completion, false completion claims, correction propagation, interruption usefulness,
  command latency, CPU/RAM and provider usage. Compare against current behavior before expanding scope.

## Primary sources and limits of the inference

[Anthropic's agent engineering guidance](https://www.anthropic.com/engineering/building-effective-agents)
supports simple loops that use actual environment/tool feedback and stopping conditions. That supports
extending the existing execution engine; it does not establish that one architecture is best for FRIDAY.

[LongMemEval](https://arxiv.org/abs/2410.10813) evaluates extraction, multi-session and temporal reasoning,
knowledge updates and abstention. Those categories inform the proposed memory evaluations; FRIDAY has
not been run against that benchmark and no benchmark improvement is claimed.

[Generative Agents](https://arxiv.org/abs/2304.03442) studies memory, retrieval, planning and reflection
for believable behavior in a simulated environment. It motivates separating these responsibilities;
believable simulated behavior is not evidence of human-like cognition or reliable desktop task completion.

The ranked recommendation is an engineering judgment based on FRIDAY's current code and these sources.
The first executive milestone is implemented as noted above. The wider temporal/episodic memory and
general action-control roadmap remains future work, with further evaluation required.
