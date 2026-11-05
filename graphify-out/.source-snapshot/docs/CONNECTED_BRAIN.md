# Connected cognitive processing

The shared brain is a set of working software paths, not a claim of consciousness or an unrestricted
agent. It tracks meaningful changes while the application/laptop run, retrieves evidence, applies local
inhibition, reasons within explicit budgets, and keeps outcomes distinct from intentions.

| Boundary | Shared cognitive path | Authority and limit |
| --- | --- | --- |
| Chat and transcribed voice | Request lifecycle, working context, dated owner episodes, relevant dialogue recall | Commands/private keyboard or computer-agent payloads are not copied into owner episodes |
| Answers to questions | Original question + answer + channel + receipt date; source IDs enter executive evidence | A short answer retains its meaning; utterances/inferences do not become confirmed facts automatically |
| Command interpretation | Shared context plus existing local router; generic intention event | Language AI proposes canonical commands; existing capability/channel/confirmation checks remain authoritative |
| Synchronous action execution | `action_intent` before execution, closed outcome afterward, existing action/result records | A started operation is not success; driver/OS evidence remains the authority |
| Local feature writes | Generic `feature_request` lifecycle and event wakeup | No request bodies, credentials or arbitrary private payloads are captured; saved-source adapters supply semantics |
| Goals/tasks, reminders, classes and deadlines | Existing source-versioned evidence and seven-day effective calendar in inquiry | Plans are proposals, progress is owner-reported, historical receipts are not current app state |
| Current integrations | Actual mode, saved Spotify login and network/provider configuration | Saved login/configuration is not a claim of live online authorization or successful playback |
| Observations and curiosity | Original thought IDs and observations enter inquiry; a selected thought preserves its answer-feedback link | A pattern/hypothesis is not an owner fact; no fixed question bank drives live inquiry |
| Autonomous questions | Local structured inquiry; notification brain review; source/attention rechecks and durable claims | One question or silence; topic suppression, global spacing and daily ceilings; no six-second continuation |
| Other proactive feature questions | Existing notification brain plus the same anonymous interruption ledger | Attendance/task-followup/optional question candidates cannot bypass global spacing by using a different feature |
| Reminders and essential notices | Existing dated notification/reminder review, source checks and recoverable delivery receipts | User-requested reminders and urgent warnings retain their separate timing/transport contracts |
| Cross-channel work | Shared records with privacy flags, local request ownership and separate Telegram recall | Telegram traffic cannot answer the laptop's pending question or retrieve local brain diagnostics |
| Forgetting/reset | Derived dialogue, question contexts and claims are cleared; epochs fence in-flight acceptance | Anonymous attempt/interruption timestamps remain so reset cannot restart a burst |

`cognitive_runtime.run()` wakes executive review on meaningful events and reconciles at most once a
minute without events. The existing executive gate allows at most four starts per hour with five-minute
spacing and source-version validation. Inquiry has a separate four automatic reviews/hour ceiling.
Idle timers are opportunities to observe/review, never orders to speak. Expensive work defers while
gaming/busy, typing, speaking/listening, or awaiting a reply. Explicit local commands remain available.

Automatic questions share at most three interruptions per local day and a 45-minute gap across midnight.
These are upper limits, not quotas. Repeated topics/questions are withheld for seven days. Explicit
requests allow one newly considered requested reply; they do not start an unattended sequence.

The local inquiry schema now requires the five decision fields plus a typed purpose (null for silence). The measured installed model needed roughly 20
seconds for a cold load; inquiry therefore permits a bounded 50-second generation, followed by existing
notification review for autonomous output, under a 90-second claim. Unavailable/invalid inference means
silence. A live synthetic trial generated a relevant blocked-project question and rejected a follow-up
that repeated its answered topic. No OS notifications or commands were submitted during the trial.

## Temporal situation memory (2026-10-20)

The local executive report can also propose at most three source-linked commitment interpretations.
The model identifies the actual owner statement, stable subject, original date words, uncertainty and
explicit revision target. FRIDAY's deterministic calendar anchors supported date words to the source's
original receipt date; it does not rely on model date arithmetic. The existing independent critique,
source fingerprints, review lease and atomic transaction must all succeed before persistence.

For example, an exam reported “tomorrow” on October 20 stays dated October 21 after restart. An explicit
postponement to Friday replaces its current revision with October 23 and retains the original quote and
history. “It was postponed” without a replacement date becomes unresolved. “Next week” stays undated;
a past due date never proves completion. New interpretations cannot silently rewrite unrelated subjects.
Corrections also mark the source of the old date as historical, invalidating conclusions based on it.

Reasoning, inquiry and notification context consume current temporal evidence. Local conversation and
life feeling reports receive the same bounded situation view alongside canonical mode/integration state.
Current owner messages take precedence over snapshots awaiting review. Telegram episodes cannot change
the laptop situation and local situation data is not added to Telegram conversation. Interpretation does
not schedule reminders, cancel classes or complete tasks. Such changes retain their existing contracts.

Read `GET /api/v1/mind/situation` for the current view and
`GET /api/v1/mind/situation/history?subject=<exact subject>` for up to 50 retained revisions. Local
`brain status` includes current/upcoming/unresolved commitments. Review runs under the existing local
executive budgets and attention deferrals; new dialogue is not guaranteed to be interpreted immediately.
Unavailable/invalid inference leaves existing records intact. Forget/reset clears revisions as well as
episodes and invalidates in-flight review.

Memory remains bounded: 500 owner episodes, at most 100 lexical recall candidates, at most 100 current
temporal records in model evidence, 500 recent revisions plus active commitments retained in SQLite,
and at most six interpretations in the shared conversation/life snapshot. Exact supported date phrases
include simple relatives, ISO dates/ranges and existing single-date calendar parsing. Ambiguous or
unsupported phrases retain null dates. Semantic entity linking and general temporal fact reconciliation
remain limited by local model interpretation and exact stable subject matching.

The saved [brain/life roadmap](BRAIN_LIFE_ROADMAP.md) tracks behavioral life state and later verified
outcome learning, purposeful curiosity and consolidation. Arbitrary autonomous tool planning, universal
independent verification, model-weight learning and expanded action permissions remain outside this increment.

## Behavioral life state (2026-10-20)

`life_state.py` connects canonical attention, ranked responsibilities, temporal uncertainty, explicit
conversation preferences and timing feedback. It exposes independent `can_review` and `can_initiate`
gates: conversation off/paused can permit silent thought; typing, gaming, calls, active requests and
unavailable attention defer background review. Busy/away/pause/cooldown/imminent timed commitments
inhibit optional questions and nudges. Existing model enable switches, review budgets and global
interruption caps remain authoritative; these gates do not grant action permission.

The executive receives a cited focus such as supporting a commitment or investigating a blocker.
Inquiry and notification models use the same state and recheck it before optional delivery. Explicit
requested questions allow one reply despite conversational quiet; they do not enable autonomous speech
or train welcome. Requested reminders, urgent/class warnings and actual status/work-completion notices
retain existing separate relevance, source and transport checks. Mode-end results use the status kind.

Timing feedback is captured in the original activity/mode/broad time-of-day context, after an autonomous
question was offered/attempted for delivery. It never claims the owner saw or heard the question.
Withheld/prepared-only questions and explicitly requested questions cannot train autonomous timing.
SQLite source checks, deduplication and transactions cover restart, callback replay and concurrent
forgetting. Store limits: 500 reactions/seven days; at most 50 recent samples per context. No raw answers
or question texts enter this ledger. An unanswered offer is weaker evidence than an explicit decline.
Repeated same-context declines lengthen cooldown to at most four hours; unanswered streaks to at most
two hours. Positive replies cannot bypass quiet, attention or the existing interruption ceilings.

Persona warmth remains light positive engagement; quiet/absence never causes sulking or abandonment
claims. The local feeling report uses the actual behavioral state and explains restraint in plain words.
`brain status` and `GET /api/v1/mind/life` expose posture, evidence IDs, gates, reasons and current timing
feedback. Local life context is omitted from remote conversation and remote feeling replies.

All thinking still uses the existing local model stack. Cognitive schemas enumerate actual evidence
IDs and disallow temporal interpretations when no local owner episode exists. A separate critique
checks each actual item, followed by the existing source/lease/transaction guards. Model interpretation
remains fallible; invalid review abstains. The synthetic Ollama probe completed silent review with
conversation disabled and made zero question-model calls. Verified outcome learning is the next saved
roadmap phase; this increment does not add a general action verifier or arbitrary goal pursuit.


## Verified outcome learning (2026-10-21)

services/mind/outcome_learning.py stores bounded expected/observed receipts in
cognition SQLite. Native audio drivers and shared mode controllers own verification;
routines, quick actions and mode watchers reuse them. Unavailable optional memory
cannot convert a failed/unknown setting check into success. Epoch/token/target guards
fence forgotten or altered completions. Prior-runtime pending work is unknown, never
replayed. Up to 200 receipts remain; lessons inspect up to 100 recent outcomes.

ReasoningStore supplies historical receipts and source-linked repeated-failure
lessons to executive/inquiry evidence and notification/reminder context. Two unverified
attempts change actual errors. Verified recovery clears the method's streak. LifeState
can focus on check_action_outcome after current commitments without granting tools or
lifting quiet/attention gates. Local dialogue/brain diagnostics use the same history;
remote replies, mirrored reasoning offers and generic public events omit private
setting diagnostics. GET /api/v1/mind/outcomes is read-only and labels historical scope.

Audio checks cover master settings; mode checks cover the saved selector and reported
controller failures. They cannot prove sound, all setup steps, optimization performance
or task completion. Current mode queries still read current canonical state.

The live installed-model probe proposed diagnostics but independent critique withheld
its overstated fix. No conclusion was saved. Provider-double integration tests prove
accepted guidance and stale-source rejection; real inference demonstrates safe
abstention. See BRAIN_LIFE_ROADMAP.md for evidence, limits and phase 4 continuation.


## Purposeful curiosity (2026-10-21)

curiosity.gaps derives supported missing inputs from recorded task blockers and
undated commitments. It ranks current focus and supplied high-priority work, closes
already-discussed source versions, and supplies up to eight open gaps to the existing
local inquiry generation. It contains no question text/templates. No open gap means
an explained silent receipt and no model call. Conflicting commitment identities
are withheld rather than guessed; known dates and locally readable settings are not
question gaps in this increment.

A question needs a planning choice and two separate possible-answer/next-step
branches. The actual gap/source must be supplied; alternatives must differ and the
expected usefulness must change a decision. Automatic questions pass their purpose
to the existing separate notification reviewer. Silence is valid at every gate.
The model can still misjudge usefulness; schema validation cannot prove semantics.

Additive inquiry-job columns retain gap identity, relevant-field version and purpose
inside the existing 200-job history. Clock noise and unrelated activity do not reopen
an answered version. Task/commitment changes may reopen it; arbitrary source paraphrase
equivalence is not solved. Historical question versions are labeled so an earlier
answer does not silently resolve a changed blocker. Answer reactions are terminal;
late delivery callbacks cannot undo them. Existing owner episodes retain exact paired
question/answer dates. No task status, plan step or external system is changed by a
question, answer or conditional branch.

Up to four local question-review receipts enter ReasoningStore/executive evidence.
Brain status and /api/v1/mind/brain retain last_question independently from last_decision,
so later silence does not hide why the last question mattered. Purpose-based conclusions
are excluded from remote prompts and mirrored offers; question-review notification
events are private. Forgetting removes these private receipts and fences in-flight
acceptance, while existing anonymous question budgets remain intact. No new inference
loop or provider/model settings were introduced.

Saved continuation and verification: BRAIN_LIFE_ROADMAP.md, phase 4; next is phase 5.

## Extractive memory consolidation - 2026-10-21

The same executive review can nominate one related group of two to four original local
owner episodes. A separate local model critique checks that connection. The inferred
subject is a label; summaries contain dated source excerpts, not model-written facts.
They cannot execute actions, schedule reminders, resolve blockers or complete tasks.

`services/mind/consolidation.py` stores up to 100 active/retired threads and only their
needed source snapshots/latest correction links. Reviewed excerpts are bounded to 1,200
text and 500 question characters; shared excerpts shorten further and mark truncation.
Snapshots preserve original words and dates after the ordinary 500-episode rolling window.
Corrections accepted by temporal memory atomically retire affected summaries and compress
links to the latest owner correction. Regrouping an old report requires that correction.
Arbitrary new corrections remain historical reports until interpreted; this does not
solve general semantic identity or contradictory free-form memories.

Source snapshots are immutable and rechecked in the guarded save transaction. Missing,
altered, remote, recursive and duplicate sources fail closed. Existing executive leases,
epochs, five-minute/four-per-hour budgets and gaming/attention deferral apply. Explicit
forgetting removes summaries AND retained snapshots. Derived summary conclusions remain
private; a retired summary disappears from active evidence and invalidates those claims.

Local `brain status` gives counts; `show reasoning` and GET /api/v1/mind/reasoning show
historical excerpts and provenance. GET /api/v1/mind/brain includes consolidation counts.
Shared evidence prioritizes summaries before duplicate raw context; independent local
inquiry and notification reviewers consume the same reasoning context.

Verification: 5,145 full-suite tests and 337 focused checks passed, including 27 memory-specific cases; zero failures/errors/skips and one existing warning. Full run: 291.78 seconds. Ten affected Python files parsed; whitespace clean. Final installed-local-model positive control saved a source-linked thread in 9.55 seconds after an independent critique rejected the first proposal; a validated retry passed. Original uncertainty, paired question and dates survived simulated pruning/restart. Earlier latency, mixed outputs and inconsistent critique judgments remain limits, not a claim of reliable human cognition. Evidence: tasks/consolidation-final-verification.*, tasks/consolidation-final-focused.*, tasks/consolidation-source-validation.txt and tasks/consolidation-memory-positive-control.json.

## Local review reliability - 2026-10-21

The existing local review now measures startup, prompt processing, generation, critique,
validation retries and acceptance. Missing provider measurements stay unknown. Private
scalar traces use the existing bounded event store; no prompts, source IDs, owner text,
responses or raw errors enter these diagnostics. Forgetting deletes the initial event;
a finishing worker only updates it, so it cannot recreate forgotten diagnostics. A
running event from a prior process is reported as interrupted. The local `brain status`
command and GET /api/v1/mind/brain expose the last recorded trace.

Prompt-free readiness reuses a resident configured model/context or loads it with an
empty Ollama request. Startup and inference share the existing 45-second executive
lease, with one second reserved for acceptance. Inference has at most 25 seconds,
clamped to remaining lease time; startup is outside that window. The existing attempt
allowance, five-minute spacing, four/hour ceiling, gaming/attention checks, source
fingerprints and epoch/lease ownership remain. Source/attention ownership is rechecked
after loading and again before atomic save. No settings/model/provider changes,
downloads, new dependencies, shared-model unloading or new background loop.

The native schema chooses one memory, one conclusion, up to three temporal updates,
or silence. It omits empty report arrays and model-calculated dates; strict internal
validation and an independent model critique still apply. Pure memory critique reads
only cited originals and compares all subjects before its boolean verdict. It checks
retrieval relatedness rather than asserting identical physical events. General
consequence review retains surrounding context. Incomplete output is refused even
when it contains parseable JSON. Loopback plaintext HTTP avoids unnecessary certificate
store construction; remote and HTTPS connections retain default TLS verification.

A missed date phrase is recovered only from a verified exact quote with one supported,
unambiguous date. Corrections, postponements, negation and ambiguous/multiple dates
are withheld; no general intent is inferred by this calendar helper. Exact repeated
temporal items are deduplicated, while conflicting items still fail normal validation.

Verification: 5,197 full-suite tests and 355 focused checks passed; zero failures/errors/skips, one existing deprecation warning. Full run: 325.34 seconds. Sixteen affected Python files parsed; whitespace clean. Two frozen five-case installed-Ollama probes produced eight useful saves and two safe evidence rejections; both separately proposed unrelated groups were rejected. Useful reviews took 2.50-7.91 seconds; nonresident startup wall time was 5.59/5.63 seconds. No owner facts, commands or notifications were created. Evidence: tasks/reliability-final-verification.*, tasks/reliability-final-focused.*, reliability-final-live-probe-a.json/-b.json, reliability-source-validation.txt and reliability-review-notes.md. These small synthetic controls do not establish general model reliability; continue the saved phase 6 coverage work.

Limits and continuation: these are bounded workflow improvements, not human cognition
or a guarantee of model judgment. Earlier probes exposed false approvals of unrelated
quotes and false rejections of related quotes; artifacts are retained. Continue phase 6
with more unseen semantic controls and naturally observed cold starts before expanding
relevance-based recall (phase 7). Do not force a shared model unload for a benchmark,
raise background quotas or replace an explicit rejection with an inferred approval.
