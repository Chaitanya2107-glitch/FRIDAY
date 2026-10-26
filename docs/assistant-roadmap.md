# FRIDAY assistant upgrade roadmap

Saved 2026-10-15 at the owner's request. This is the agreed direction for incremental implementation,
not a claim that the capabilities below have shipped. Begin with persistent execution and verified outcomes.

## Objective

Understand a goal, retrieve relevant context, plan, act, verify, remember progress and follow up.
Keep the existing voice, memory, goals, observations, predictions and tools, and connect them into
dependable end-to-end experiences. Existing software tests and realistic assistant evaluations are both required.

## Capability map and priorities

| Stable id | Upgrade | Existing foundation | Depends on |
|---|---|---|---|
| task-execution | Persistent steps, explicit tool scope, outcome evidence, cancellation and restart recovery | Workspace goals/tasks, actions, supervised computer loop | Existing local tools |
| conversation-context | References such as "that PDF", corrections and changed instructions across turns | Chat/voice, cognition, file selection, multi-command router | Existing memory; task-execution |
| temporal-memory | Sources, certainty, relationships, validity dates and consistent corrections | Semantic memory, episodes, reviewed lessons, schedule facts | Existing memory |
| application-control | Application APIs, browser structure and Windows UI Automation with visual fallback | Local actions and screenshot-based computer agent | task-execution |
| continuous-voice | Natural interruption, pauses, corrections, faster feedback and clear activity states | Wake interruption, conversation mode and streamed TTS | conversation-context; task-execution |
| goal-aware-proactivity | Prioritize timely help by goals, commitments, blockers and owner reactions | Notifications, activity, goals and reasoning proposals | task-execution; temporal-memory |
| adaptive-interview | Extract reviewable facts from answers and ask useful questions about remaining gaps | Local Train Friday interview, curiosity and notes | temporal-memory |
| assistant-evaluations | Real conversations, complete workflows, memory corrections, failure recovery and model comparisons | Isolated pytest suite and learning quality reports | Start immediately; expand with each module |

Build order: task-execution + its evaluations, conversation-context, temporal-memory,
application-control, continuous-voice, goal-aware-proactivity, adaptive-interview.
Evaluate accuracy, verified completion, response delay, false completion claims and resource use throughout.

## Important operating policy

The configured `AI_ASSIST_ONLY=true` currently disables model reasoning and the computer agent.
Do not silently flip this setting or broaden model access. The first execution workflow must work locally.
Future model access should have explicit purposes for conversation, reasoning, planning and execution.
On 2026-10-16 the owner explicitly authorized `notification_review`: reminders and optional notifications
may use a bounded fact/context decision without enabling general reasoning, chat or tool planning.
The default `NOTIFICATION_REVIEW_ENABLED=true` controls that purpose independently; unavailable review
retains reminders for later retry. `AI_ASSIST_ONLY` itself remains unchanged.
Select models against owner-relevant tasks, availability, latency, cost and the actual hardware.

## First milestone: persistent local task handoffs

`prepare task handoff <task-id>` takes a snapshot of a saved task, collects related saved notes,
creates a local Markdown handoff and verifies its bytes before reporting completion. Each phase is
checkpointed. Status, resume and cancellation are explicit local commands. This supplies a real,
testable execution path while arbitrary task-plan execution remains future work.

Specification: [persistent execution](specs/2026-10-15-persistent-execution.md).
Current implementation plan and acceptance checklist: `tasks/plan.md` and `tasks/todo.md`.

Implementation status: the first local handoff workflow is implemented with SQLite checkpoints,
status/resume/cancel commands, verified atomic file publication and chat/voice integration. Focused tests
cover separate-process recovery, concurrent runners, source failures, stale tasks and artifact conflicts.
General natural-language planning and arbitrary tool-plan execution remain future milestones.
Verification on 2026-10-15: full suite 1,925 passed; one existing FastAPI/Starlette test-client deprecation warning.
Second execution milestone (2026-10-17): a project work-session brief now captures a registered project's
matching tasks/goals/blockers, bounded local file metadata and saved notes, then publishes a verified
Markdown artifact. Four durable checkpoints share the handoff engine's cancel/resume/concurrency and
publication controls. Chat/voice commands use names and separate durable focus; no model, file-content
read, application launch or arbitrary saved command runs. See FEATURES for scope and limits.
Next execution work remains additional explicit, verifiable adapters beyond these two concrete templates;
general natural-language planning and arbitrary tool-plan execution are still future milestones.
Verification: 4,537 passed, zero failures/errors/skips, one existing deprecation warning;
artifacts are `tasks/project-session-verification.log` and `.xml`.

Usability follow-up: IDs are optional for task/goal controls and handoffs. Names, durable selected/current
references and explicitly requested latest matches resolve through the workspace. Ambiguous names prompt
for a more specific request without acting. This is the first scoped conversation-context improvement;
general cross-tool pronoun/reference understanding remains future work.

Conversation-context slice (2026-10-17): project briefs accept `leave out the notes`,
`include the notes again`, `actually, use the college project` and `refresh that brief` across laptop
chat/voice turns. Each revision publishes a fresh verified artifact, retaining prior completed briefs and
cancelling superseded unfinished jobs. Inclusion preferences and pending project-name/ordinal choices
persist in SQLite with 15-minute expiry; unrelated turns/history clearing retire short references.
Token and saved-project identity checks guard against stale changes. No model policy was broadened.
This completes project-brief follow-ups; references/corrections across arbitrary tools remain future work.
Evidence: `tasks/brief-followups-verification.log` and `.xml`.
Full suite: 4,564 passed, zero failures/errors/skips, one existing warning. All 82 final focused checks
also passed after the clarification-prompt wording adjustment; see `tasks/brief-followups-final-focused.log` / `.xml`.

Conversation-context slice (2026-10-17): file selections/results and pending choices now persist
for up to 15 minutes with separate laptop/Telegram scope. Pronouns use selection or ask for a choice;
filename/ordinal replies complete a pending action, while file corrections select without opening.
Handoffs accept task corrections and ambiguity replies, creating fresh verified outputs and cancelling
superseded unfinished jobs. Identity/version/token checks refuse stale targets. Chat/voice classify
before search/learning; unrelated turns and resets retire short context. No AI policy change.
This completes the approved file-selection/task-handoff slice; arbitrary cross-tool references and
other conversation-context capabilities remain future work. Evidence:
`tasks/conversation-references-verification.log` / `.xml`.
Verification: **4,588 passed**, zero failures/errors/skips, one existing deprecation warning (204.44 seconds). All **22 new focused checks passed** after subprocess log isolation; see `tasks/conversation-references-final-focused.log` / `.xml`.

Temporal-memory slice (2026-10-17): deadline corrections now maintain one canonical current date,
owner provenance and correction history. Deterministic recall, shared context/evidence, task handoffs
and project briefs consume it. Explicit reminder links generate reviewable scoped shifts; batch approval
validates sources/delivery state and persists a replay receipt. Restart and partial-finalization recovery
are tested. This completes the approved deadline/linked-reminder slice; class/other commitment changes,
general temporal relationships and broad memory reconciliation remain future work.
Evidence: `tasks/deadline-changes-verification.log` / `.xml`.
Verification: **4,630 passed**, zero failures/errors/skips, one existing deprecation warning (221.13 seconds). All **84 final focused checks passed**, including the prompt-budget regression; see `tasks/deadline-changes-final-focused.log` / `.xml`.

Class-time slice (2026-10-17): the owner-approved next temporal workflow now supports corrections
within one date. Saved occurrences retain original/new start/end times and owner provenance while the
weekly template remains intact. Effective classes govern next-class answers, briefing/prompt, warnings,
study offers and attendance. Explicit reminder links preview scoped shifts and reuse verified batch
application/receipt recovery. Ambiguity, stale context/proposals, cancellation, delivery state and corrupt
records are guarded. Cross-date moves, other commitments and broad memory reconciliation remain future
work. Evidence: `tasks/class-changes-focused.log` / `.xml`, `tasks/class-changes-verification.log` / `.xml`.
Full suite: **4,688 passed**, zero failures/errors/skips, one existing warning (301.92 seconds).
All **1,704 focused checks passed** (58.10 seconds).

## Flagship experiences

Execution follow-up (2026-10-19): a saved project can now be started with a verified brief and observed
Explorer folder through `start project session for <name>`. The existing engine gained external
token/lease claims, cancellation-safe finalization and observation-only recovery. Status/resume/cancel
retain separate durable focus. The live temporary-folder trial passed. General arbitrary tool plans,
keyboard sequencing and wider application adapters remain future work.
Final execution regression: **4,861 passed**, zero failures/errors/skips, one existing warning;
workflow/corpus focused checks: **550 passed**. Evidence: `tasks/project-execution-final-verification.log`
/ `.xml`, `tasks/project-execution-final-focused.xml`, `tasks/project-execution-live-probe.log`.

Owner reprioritization (2026-10-18): useful proactive help was selected before desktop reliability and
project-control work. The first shipped slice connects saved goal priorities, task progress, explicit
blockers and live attention to existing notification review. Source-version rechecks, durable claims,
daily budgets, backoff and persistent owner feedback limit stale/repeated interruptions. Local scoped
replies and named controls explain or postpone suggestions without executing task steps. Broad autonomous
goal pursuit and inferred completion remain future work. Evidence: `tasks/task-followups-focused.log`
/ `.xml`, `tasks/task-followups-verification.log` / `.xml`.
Verification: **4,737 passed**, zero failures/errors/skips, one existing warning (270.14 seconds).
Broad focused checks: **1,670 passed**; final focused checks: **85 passed** after date-fixture correction.

- Project copilot: find project context, track blockers, prepare work sessions and preserve handoffs.
- Study assistant: connect syllabi, deadlines, weak topics, practice and revision progress.
- Daily coordinator: connect commitments, unfinished tasks, day interviews and tomorrow's preparation.

## Ideas backlog

Executive cognition milestone (2026-10-19): the owner approved implementing the selected next upgrade.
Bounded versioned situations, explicit local focus, project preflight/outcome feedback and historical
execution receipts now feed shared reasoning. The watcher uses a separate proposal-only cognitive-review
purpose with durable leases, 5-minute spacing, four starts/hour and failure backoff. Full-source/attention
and epoch checks precede atomic report/completion commit. Local status/on/off/why and forget/reset paths
are integrated. General tool permissions and task completion remain unchanged; wider preflight and
temporal/episodic memory remain future. Spec: `specs/2026-10-19-executive-cognition.md`.
Final regression: **4,906 passed**, no failures/errors/skips and one existing warning; final focused:
**172 passed**. The live project preflight/outcome trial passed. Configured provider trials failed safely;
model availability/quality remains a limit, with details in current_state and `tasks/executive-live-probe.json`.

The 2026-10-19 code/research assessment selects **shared executive cognition with versioned evidence**
as the next increment after verified project execution. It connects pre-action checks, selective
background review and outcome feedback, then expands temporal/episodic memory. Detailed rationale,
proposed model-purpose boundary, budgets and acceptance tests are in
[the brain assessment](2026-10-19-brain-assessment.md). This records the requested next-upgrade
selection; its first implementation is recorded above. `AI_ASSIST_ONLY` remains unchanged; cognitive
review has an independently controlled purpose.

[Assistant ideas and improvements](assistant-ideas.md) preserves the 2026-10-15 brainstorming recommendations,
including commitments, project/session continuity, research, study support, communication and device integration.
Further candidates cover consequence previews, partial-failure recovery, live capability checks, deliverables,
engineering experiments, mixed-language interaction, collaboration preferences, resource scheduling,
evidence explanations, backup/restore, reviewed reusable skills and viva/meeting assistance.
These are discussion candidates; saving them does not authorize implementation or change the build order above.

## Evaluation direction

Test paraphrases, references and corrections, memory after several days, complete desktop workflows,
provider/app failures, and whether claimed outcomes are independently observable. Keep stable preferences
separate from dated events. Training interviews update reviewed memory; language-model fine-tuning is separate.

References informing the proposal:
- [Agent feedback loops and tool design](https://www.anthropic.com/engineering/building-effective-agents)
- [Windows UI Automation](https://learn.microsoft.com/en-us/dotnet/framework/ui-automation/ui-automation-overview)
- [LongMemEval: temporal reasoning, updates and recall evaluation](https://arxiv.org/abs/2410.10813)
