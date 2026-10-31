# architecture.md
# F.R.I.D.A.Y — System Architecture

*Last updated: 2026-10-29 (native College Schedules; older sections remain)*

---

## Design Principles

### Native college client and shared schedule data (2026-10-29)

`interfaces/college` uses Tkinter/ttk and background HTTP workers, following the
Customize FRIDAY client. `/api/v1/college` routes delegate typed validation,
revisions, CRUD and upload previews to `services/college`; existing loopback
Host/Origin protections remain unchanged. No static/browser interface or CORS.

`timetable.next_class_occurrence` is the structured selection shared by existing
next-class prose and the new overview. Effective dates still use class_sessions
and services.memory.schedule. `memory/college/subjects.json` stores faculty/room
metadata separately, preserving complete weekly-template equality and dated
snapshots. Timetable and college writers reuse the atomic JSON publisher and
cross-process SQLite guards. Deadline optional metadata/done status is additive;
legacy active readers omit completed rows. Corrections still use deadline_changes
and class_changes, with reminder proposals requiring the existing chat approval.
Exams remain recognizable deadlines, preserving exam briefing logic. Shared
`services/college/reading.py` supplies registry rooms to local class descriptions,
and upcoming events to overview, local chat and local briefing. Mirrored class
warnings omit superseded rooms; structured Telegram reports retain legacy room
fields. Optional unreadable metadata falls back for existing commands, while the
college API refuses an unreadable registry without overwriting it.
Events alone add a new store; notification scheduling is unchanged. New college
commands and event briefing content are excluded from Telegram.

Raw uploads have bounded bytes/type checks, ephemeral editable previews, reviewed
diff hashes and stale-revision refusal. Confirm publishes random-name originals
and the shared timetable. Each file is atomic; multi-file crash atomicity is not
claimed. Local Office/CSV/text-PDF parsing uses installed libraries. Consented
image extraction pins one provider/model through the existing prompt/parser and
registry policy; legacy chat import fallback stays as before. See
`COLLEGE_SCHEDULES.md` for format, resource and vision-policy limits.

### Connected cognitive inquiry and event-driven attention (2026-10-20)

`brain_memory.py` stores dated, channel-scoped owner utterances/paired answers in the cognition database.
Their source IDs enter `ReasoningStore.evidence()` alongside observations and actual integration state.
Executive review can derive cited conclusions while keeping the original report separate from inference.
Conversation recall retrieves bounded relevant original dialogue; it does not run automatic fact deletion.

`inquiry.py` performs local-only typed question-or-silence reasoning over past/present/future context.
Claims, epochs, source fingerprints, interruption timestamps, review budgets and topic history prevent
replays and bursts across restart/forgetting. Notification review remains an additional gate for autonomous
questions. Other proactive question candidates use the same anonymous day/spacing ledger at delivery.
Explicit day-review/learning requests generate one question and do not schedule another after an answer.
The old evening queue/continuation path is retired; catalogue collection serves the manual trainer only.

`cognitive_runtime.py` registers an event wakeup for meaningful cognition records/completions and local
feature-write lifecycles. A minute timeout reconciles missed work. Existing executive claims/budgets/source
guards remain authoritative. Model inference defers during busy/typing/speech/pending interactions.
Command interpretation and synchronous action intentions/results join the shared ledger; existing local
capability/channel/confirmation checks and specialized project preflight still control physical effects.
See `CONNECTED_BRAIN.md` for exact boundaries, privacy exclusions and limits.

### AI language and local thinking (2026-10-20)

`services/mind/language.py` provides structured translation and conversational generation.
`intent.py` keeps known commands local; unmatched assist-only requests receive a command string
that re-enters the existing local router once. A request-scoped guard prevents recursive inference.
Complete batches are parsed before execution. Local confirmation/channel checks remain unchanged;
translated close targets must be named in the original request, including within batches.
Chat/voice share conversational generation with bounded recent history. Language providers receive
no tools, and general owner-fact extraction/planning stays disabled in assist-only mode.
`AI_LANGUAGE_ENABLED=false` restores the earlier prepared-reply policy.
Purpose-scoped failover routes cognitive/notification review exclusively to Ollama; language can use
OpenRouter and Ollama. Local review failure never sends reviewed evidence to a cloud fallback.

### Shared executive cognition (2026-10-20)

`services/mind/executive.py` reuses the cognition database for bounded immutable situations, source
fingerprints, local project assessments/outcomes, durable review jobs, leases and attempt budgets.
`ProjectExecutionEngine` records the intention/expected outcome before its desktop phase, then checks
sources and active local ownership immediately before OS submission. Canonical execution checkpoints
remain the authority; historical receipts expose no artifact paths/notes or current-window claims.
Explicit local task/goal focus is retained in reasoning evidence even outside the five newest records.

The existing watcher calls `reasoning.review()`, which delegates to executive review when enabled.
Stable attention plus relevant evidence/date/due-state fingerprints avoid self-triggered thinking loops.
SQLite claims allow one active review, a 300-second minimum gap and four starts per rolling hour.
Budget attempts survive off/on and forgetting. The scoped `cognitive_review` provider purpose works
in assist-only mode but cannot request tools. The existing Report/Checks validation and critique stay
in place; no new owner facts or automatic reasoning effects are permitted for this purpose.

Acceptance rechecks all snapshot sources and local attention, then checks lease/token/settings epoch
inside `ReasoningStore.save()`'s transaction. Report rows and the completed review receipt commit together,
preventing duplicate inference after a crash between saving and acknowledgment. Disabling, source changes,
history/workspace clearing or forgetting reject stale results. Derived private records are bounded and
cleared through existing forget/reset paths; hourly counters are retained. Shared live context includes
compact executive status. Local cognition commands expose policy, usage and factual project assessments.
This is the first executive milestone; general preflight for every old automation path remains future work.

### Verified project execution (2026-10-19)

`ProjectExecutionEngine` reuses the four ProjectSessionEngine brief checkpoints and adds a fifth
external checkpoint: open/observe the registered folder through Windows Shell COM. `ExecutionEngine`
supports external phases using `workspace_execution_claims`: a short transaction claims a token/60s
lease, the adapter runs outside SQLite, and a new transaction revalidates sources, token, lease and
cancellation before saving evidence. An expired/interrupted claim reconciles observed state only;
it cannot submit the action again. Normal local checkpoints retain their existing transactions.
The adapter checks the independently observed folder after launch; a successful launch API return
alone is insufficient. Current verification rechecks the artifact digest and folder presence.
Completed sessions never reopen a closed folder on resume. Project execution has separate durable
focus/workflow ownership; `conversation_context` routes it before handoff/reference/search handling.
No arbitrary saved plan, shell command or keyboard step is executed by this workflow.

Shell adapter references: [Shell.Windows](https://learn.microsoft.com/en-us/windows/win32/shell/shell-windows),
[FolderItem.Path](https://learn.microsoft.com/en-us/windows/win32/shell/folderitem-path).

### Goal-aware proactive task help (2026-10-18)

`mind/task_followups.py` reads owner tasks/goals and uses the existing cognition DB for candidate
snapshots, delivery claims and per-task/global feedback. The bounded scan examines up to 100 tasks,
prioritizing goal priority, blockers and age. Active/blocked records need two/one days without an
update. Paused/finished tasks and inactive goals cannot become candidates. Stored evidence includes
the exact task/goal version, next steps and explicit blocker; absence of updates is not proof of no work.

The watcher queues candidates into existing `notifications.collect/dispatch`. Candidate evidence
travels with the notice rather than depending on the shared top-five workspace prompt. The reviewer
uses the existing `notification_review` purpose, live activity and recent outcomes. State/preferences
and attention are rechecked before an atomic single-use SQLite claim. Only accepted transport becomes
`submitted`; failures/unknown outcomes have no reply context or automatic replay. A crash after claim
retains an unconfirmed submission. SQLite and the OS notification API do not share a transaction.

Selection/claims serialize across processes. Hard ceilings allow four reviews/day and two claimed
notification attempts/day, with 30-minute selection and four-hour claim gaps. Same-task gaps grow from
one to seven days after unanswered attempts. These are interruption ceilings; the model still decides
whether any eligible candidate is useful. Nudges/free-will, quiet/busy, idle, microphone and pending
question gates apply. Generic/evening questions wait during the 15-minute scoped reply window.

`followup_commands.py` owns status, named/global controls and local scoped short replies. Submitted
context uses the existing reference table; unrelated turns/reset retire it and snapshot/token checks
refuse stale feedback. Buttons use process-local protocol tokens plus a durable follow-up token.
Review displays state without executing work; pause snoozes 24 hours; stop persists until resumed.
Telegram cannot consume laptop context, while explicit controls intentionally affect shared preferences.
Conversation clearing preserves preferences; workspace reset removes follow-up records/preferences.
No new UI, dependency, general model permission or task execution authority is introduced.

### Dated class occurrences (2026-10-17)

`proactive/class_sessions.py` keeps dated occurrences in `memory/class-sessions.json`, reusing atomic
JSON validation/publication and the existing deadline writer lock. Each row snapshots the complete
weekly template and carries a stable ID/revision, effective start/end, owner quote/history and explicit
reminder links. Full template equality prevents a weekly edit from silently inheriting an old override.
Unreadable data is retained and refused; orphaned links defer delivery for review. No recurring template
is rewritten. The scope is a time change on one date, with duration preserved.

`class_changes.py` handles explicit owner commands before general routing, validates old/new times,
rejects cancelled/started/recorded occurrences and stores scoped clarification in the existing reference
table. Subject aliases/acronyms are deterministic. Choices check date/template/revision and context
token with 15-minute expiry. Canonical history includes old/new start/end, source and exact statement.
`timetable.classes_for_date` overlays corrections after cancellation filtering; `next_class` uses the
same effective projection and sorts after shifts. Briefing/prompt, warnings, college offers and attendance
consume effective times. Notification fingerprints include the current effective classes; attendance
callbacks compare start and revision. Submitted OS notices remain beyond the recall boundary.

Class rows reuse `deadline_reminders` proposals, transactional batch shifts and durable replay receipts.
Class and deadline link writers serialize under one lock and refuse shared ownership of a reminder.
Scoped approval guards the class identity/revision, proposal digest, exact reminders, future targets
and delivery state. Rejection preserves times and updates offsets. Real reminder review/recheck reads
class-link state: pending shifts defer; cancelled linked occurrences suppress. Receipt reconciliation
also preserves cancellation matching if the reminder transaction committed before JSON finalization.
No new inference authority, model purpose, dependency or general commitment graph is introduced.

### Canonical deadline corrections and linked reminders (2026-10-17)

`proactive/deadline_store.py` retains the JSON source of truth, adds stable IDs/revision tokens,
validates saved metadata, and publishes with same-directory temporary write/fsync/replace. A two-second
SQLite writer-lock timeout on `deadlines.json.lock.sqlite3` serializes mutations across processes;
readers see the old or new complete JSON. Countdown, removal and college updates share this lock.
Legacy rows acquire additive IDs on write. Explicit removal also removes that deadline's history/links.

`deadline_changes.py` handles literal changes, due-date recall, history and scoped ambiguity replies.
Choices store deadline identity/due/revision in the existing reference table with expiry. Corrections
preserve old/new dates, source=owner_report, exact statement and noted time. Dates without a new clock
retain the prior one; from-date checks prevent retargeting an unexpected deadline. Current bounded
records feed workspace/brain prompts and reasoning evidence. Task handoffs and project briefs capture
matching dates using complete task/project-name terms and recheck before publication. No semantic
relationship inference or historical artifact rewriting occurs.

`deadline_reminders.py` records explicit reminder snapshots/offsets inside the deadline row. A correction
replaces unfinished previews with a new scoped proposal. Applying validates revision/digest, link data,
exact current reminder records, future target times and outbox state. All reminder writes, outbox reset,
readback checks and an additive `deadline_reminder_receipts` row share one reminder-DB transaction.
Deadline JSON finalization follows; receipt reconciliation recovers a committed batch without replay.
This is a recoverable operation across two stores, not a single cross-file transaction. Rejection keeps
existing reminder times and adjusts the retained offset for future changes. Links cannot be edited while
an unresolved preview exists. No reminder text or deadline task-completion state is rewritten.

The real reminder reviewer includes pending linked changes in its fingerprint and local defer check,
including immediately before transport. An already submitted OS notification cannot be recalled.
Active, uncertain or partially submitted reminder deliveries block rescheduling until resolved.
History/workspace clearing expires clarification state but preserves canonical deadlines and proposals.
No new model purpose, general fact mutation, application action or external integration is enabled.

### Scoped file and handoff references (2026-10-17)

`conversation_context.py` coordinates classification and retirement alongside existing project-brief
context. Chat/voice observe before search/learning and the intent router handles references before
multi-command parsing. `reference_context.py` stores bounded payloads, expiry and replacement tokens
in the additive `workspace_reference_context` table, keyed by scope/kind in the cognition database.

`files/result_context.py` preserves the existing LastResults surface using SQLite, with separate
laptop/Telegram rows and wall/monotonic expiry. It stores at most 100 result paths/names and file metadata,
selected index and pending open/reveal/select action. File pronouns use selection or a unique result;
ambiguous references wait for explicit choices. The parser carries a snapshot token; resolution checks
current metadata and atomically selects/claims it before Windows opening/reveal. Metadata checks cannot
eliminate OS path races or prove rendering. File contents are not read by this feature.

`handoff_context.py` resolves task corrections and numbered/name clarification replies. It validates
candidate task IDs/titles/versions and context tokens, then inserts a fresh handoff and cancels any
superseded unfinished handoff in one transaction. Existing execution checkpoints/publication verification
remain authoritative. Completed outputs persist. Focus is updated only if the finishing turn still owns
the active context. Remote turns cannot read or consume laptop handoff context. History/workspace
clearing retires short references; unrelated turns retire the affected channel's context. Existing
Telegram file-send parsing retains file results for explicit forwarding and its clarification turns.

### Notification brain and reminder outbox (2026-10-16)

`providers.policy` permits an explicitly scoped `notification_review` purpose independently of general
assist-only restrictions. `reminder_review.py` assembles bounded dated facts, source/date-preserving
memories, confirmed reasoning facts/inferences, goals/tasks, live attention and eligible routing. It
validates exact reminder IDs and evidence references; only authoritative event-relevant facts may support
suppression. Deterministic class constraints and busy/voice checks apply before inference; snapshots are
fingerprinted and rechecked before each destination/speech. Invalid/unavailable inference remains pending.

`reminders/delivery_state.py` adds outbox state lazily without rewriting existing reminders. Atomic
just-in-time claims, leases, source text/due snapshots and CAS protect competing workers, cancellation
and approved reschedules. Known failures back off for at most five attempts; manual retry resets attempts
and runs the brain again. Review deferral/withholding never consumes transport attempts or owner intent.
Desktop/eligible Telegram acknowledgements persist independently; retries skip submitted destinations.
Crashes during submission and read/write timeout ambiguity stay uncertain for explicit recovery. SQLite
cannot prove exactly-once external effects across a crash. Optional speech failure cannot undo delivery.

`notifications.py` applies bounded batch reasoning to watcher, completion and filing candidates and
rechecks stable fact/context fingerprints before transport. Candidate privacy governs both decision and
notification events; private filenames/terminal previews do not enter later shared cognition context.
The local status/why/retry commands and protected GET `/api/v1/mind/notifications` expose recorded reasons,
evidence and per-channel outcomes. Direct user-requested command feedback, Claude permission requests,
security/system reports and screenshot filing outcomes retain their existing transport paths.

### Laptop and Telegram temporary context (2026-10-16)

The existing `intent.remote_request` ContextVar selects two conversation scopes: false for shared
laptop chat/voice, true for Telegram. Pending action storage in `intent.py` and the `_LastResults`
facade in `services/files/assistant.py` retain independent state for each scope. The latter keeps
results, selection and expiry together; existing consumers use the same get/set/selected API.
State lives outside the ContextVar so threadpool mutations persist; `asyncio.to_thread` propagates
the request's scope. Confirmation replies pop their own pending action before execution.

`telegram.bot._run` marks its whole handler remote and restores the token in a finally block.
Bot-owned shortcuts and yes/no replies clear only that scope's old action/file clarification.
Normal chat handles its own confirmation lifecycle. Remote ordinary chat cannot cancel the
local-only computer agent. No new client-supplied channel selector or permissions were added;
shared memories/goals/tasks and existing remote action restrictions are preserved.

### Reasoning upgrade (2026-10-14)

`services/mind/reasoning.py` runs a bounded evidence-to-consequence pass before ordinary chat/voice
replies and after explicit memory/schedule declarations. It uses the requested/configured provider
and existing failover chain. Input includes original owner receipt dates, typed owner/learned evidence,
goals, full current task snapshots, pending reminders, a dated expansion of the weekly timetable and
public observations/outcomes. Private OS notification text, screenshots and computer tasks are excluded.

The typed report separates exact owner quotes from implications, predictions, questions and proposals.
Every conclusion cites supplied/new evidence IDs. Unknown effects, fabricated quotes, stale evidence,
invalid dates and uncertain corrections are rejected before persistence. Existing deterministic dated
owner constraints bound model projections; rereading the same evidence cannot extend its class window.
A second model pass checks grounding, calendar/scope, corrections and plan usefulness. One repair is
allowed within a shared 25-second inference budget (up to four completions). These model checks are
fallible, not independent truth verification. When semantic checks still reject conclusions, valid
owner quotes can be saved alone without inferred effects; malformed/unavailable passes make no changes.

`reasoning_store.py` uses two cognition-DB tables with monotonic IDs, exact quote provenance, status,
source fingerprints, correction state and bounded derived history. Facts survive chat clearing/restarts;
forgetting removes them and invalidates dependent conclusions. Applied projections remain for historical
attendance, even after their active dates expire. Current context is bounded and distinguishes proposed,
inferred, applied and failed outcomes. Archived corrections are inactive and never operational authority.

`reasoning_effects.py` exposes three service contracts: dated class availability, task plans and reminder
time changes. Only explicit, confirmed, high-confidence class changes can apply automatically; inferred
cancellations, task plans and requested-reminder changes need `apply reasoning proposal <id>`. Approvals
are consumed once, sources are rechecked, task updates use an atomic version guard and reminders use
stable IDs/pending-state guards. Changes are read back and recorded as verified service outcomes. Plans
remain inert and do not complete steps or execute arbitrary tools. Failed/unknown outcomes cannot replay.

The watcher reconsiders changed facts/objectives/reminders at most every five minutes; no synthetic user
facts are extracted from background reviews. Fresh proposals can nominate a notification while the owner
is active, not busy and nudges are enabled. The notification decision model still chooses send/silence,
with another source check before delivery. Nomination, transport submission and user reaction remain distinct.
Rejections are available as evidence for later reasoning. Chat, voice, brain awareness and notifications
consume the same current conclusions. `reasoning status`, proposal controls and read-only
`GET /api/v1/mind/reasoning` expose the state behind existing API protections.

Providers can implement optional `complete_structured(schema, ...)`. The default uses their existing
completion method; Ollama supplies native JSON-schema `format` and a larger context only for structured
requests. Ordinary completion/streaming behavior is preserved. This follows the
[official Ollama structured-output contract](https://docs.ollama.com/capabilities/structured-outputs).
`REASONING_ENABLED=false` stops new analysis/nominations; existing approved dated changes keep their
expiry/correction semantics. Live tests found the free text providers rate-limited and the local 3B
model inconsistent at calendar/effect reasoning. The layer does not imply universal autonomy or make a
small model reliable; unsupported consequences remain unapplied. Restart from the tray to load it.

### Ten cognitive layer foundations (2026-10-14)

`services/mind/layers.py` maps the requested layers to actual modules and states their limits.
`brain layers` and read-only `GET /api/v1/mind/layers` expose that inventory. It is a curated
capability map, not a health check or a claim of general intelligence.

| Layer | Foundation | Scope of this pass |
|---|---|---|
| Perception | Chat input, STT, requested screen understanding, activity observations | Existing; preserved |
| Attention | Ranked thoughts, busy guards, candidate notification decisions | Existing; preserved |
| Working memory | Shared cognition events plus persistent task plans/progress/blockers | Added structured task workspace |
| Long-term memory | Semantic facts, episodes, knowledge, preferences and corrections | Existing; preserved |
| Goals and motivation | Explicit owner goals, priority ordering; existing mood/reaction state | Added persistent owner goals |
| Reasoning and prediction | Evidence reports, model critique, predictions, proposals and service adapters | Upgraded after the foundation pass; model quality remains a limit |
| Executive control | Intent routing, confirmations, supervised computer agent; saved task plans | Checkpointed local handoff workflow added; general plan execution deferred |
| Action and communication | Existing tools, chat, speech, notifications and Telegram | Existing; preserved |
| Metacognition and verification | Recorded outcomes, screen rechecks, prediction scoring, review evidence | Existing; universal verifier deferred |
| Learning and adaptation | Corrections, reaction learning, reviewed lessons and scoped predictive training | Existing; preserved |

`services/mind/workspace.py` stores `workspace_goals` and `workspace_tasks` in the cognition SQLite DB,
sharing its locks, transactions and test isolation. Goal priorities are explicit owner choices;
task steps carry a cursor, status, blocker and completion evidence labelled `owner_report`.
Progress does not imply independent verification. Plans are inert data and never permission grants.
Commands persist locally without provider/embedding calls. Completed steps cannot be erased by a
replan, blocked tasks must resume before advancing, and unfinished plans cannot be silently completed.
There is no automatic capture of arbitrary requests or computer-task/screen contents.

Bounded active goals and task summaries enter chat/voice cognition context, `brain.awareness()` and
notification decisions. Full plans and evidence remain in the local store. Goals/tasks survive
event pruning, conversation clearing and process restarts; `clear my goals and tasks` explicitly resets
them. Read-only `GET /api/v1/mind/workspace` exposes the bounded view behind existing API protections.
Existing memory/date constraints, action permissions and notification transport semantics remain.
This foundation pass initially deferred general reasoning; the subsequent upgrade is described above.
Unified attention planning, general automatic task execution/tracking and universal independent result verification
remain future upgrades.

`services/mind/execution.py` implements the first managed workflow in `workspace_executions`, outside event
retention. It checkpoints a task snapshot, keyword-related saved notes, and atomic Markdown publication with
readback verification. `execution_commands.py` exposes explicit laptop-only prepare/status/resume/cancel
requests through the shared router/threadpool. Status rechecks artifact hashes, and publication never
overwrites different bytes. Task-version changes stop stale execution; output is a dated snapshot.
Each short local phase and its cursor/evidence commit are serialized by `BEGIN IMMEDIATE`; an interruption
after publication can recognize identical bytes on retry. A future network/desktop executor requires
claims/leases outside these transactions. No arbitrary task-plan text is executed, and generating a handoff
does not advance or complete the source task. Clearing goals/tasks removes jobs, retaining generated files.

`project_session.py` adds a second concrete executor using the same checkpoint/publication controls:
project/task snapshot, bounded file metadata inventory, project-name-matched saved notes, and a verified
Markdown brief in `memory/project-sessions/`. Its payload is tagged `workflow=project_session`; `task_id=0`
means it has no source task. Existing handoffs keep their original payload/schema and positive task IDs.
Each engine refuses the other workflow's records. Project registration, captured file size/mtime and
matching task/goal snapshots are rechecked before subsequent phases; file contents are not read or hashed.
Hidden files, key files, links, common generated/storage folders and the output directory are excluded.
Inventory is bounded to 500 entries/100 files/two nested folder levels and labels truncation. Publication
uses the existing atomic no-overwrite/readback path. Notes remain the checkpoint's dated saved snapshot.
`execution_commands.py` recognizes laptop chat/voice requests; `project_session_commands.py` supplies
private artifact replies with safe memory placeholders. Neither model access nor project commands run.

`project_session_context.py` stores short references and ambiguous project choices in additive
`workspace_brief_context` rows in the existing workspace database. Token comparisons within the execution
transaction refuse stale concurrent instructions; 15-minute expiry and unrelated local turns retire short
references. Workspace reset and chat-history clearing remove this context; durable session focus remains
available after history clearing. Remote turns neither read nor mutate the laptop context. Chat/voice
classify brief turns before file/search/screen interpretation and proactive-question learning.
The shared router resolves pending project names/ordinals before normal command learning. Corrections
do not become reusable command aliases. A revision stores `include_notes` and `supersedes` in a new
execution payload, takes fresh source snapshots and publishes a new artifact. Completed older artifacts
remain; pending/blocked older jobs are cancelled atomically. Excluded notes are not read. Old payloads
without `include_notes` retain the original include-notes behavior. Saved project identities are checked
again before applying a clarified choice; changed registrations require an explicit new request.

`workspace_focus` persists the last explicitly selected task, goal, handoff and project session by transport scope. Shared
resolution accepts exact names first, unambiguous word matches, current selections and explicit latest
selectors; IDs are optional. Handoff names select the newest handoff for a single matching task. Ambiguous
references return a request to repeat with a specific name and never execute a guessed target. Local and
Telegram focus do not replace each other. Source text ending in "Friday" is preserved as a literal name.

`services/memory/schedule.py` is the operational bridge from owner facts to dated class availability.
It reads legacy owner-told facts with their original receipt timestamp and stores new declarations in
`schedule_facts` beside chat memory. Timetable consumers query `classes_for_date()`; temporary changes
never rewrite the weekly template. Attendance totals exclude cancelled sessions while preserving rows.

The watcher collects notification candidates in a request-local batch. `services/mind/notifications.py`
uses one bounded model decision for the batch, with owner facts, observations and public recent outcomes.
Strict IDs/booleans restrict the model to approve/reject known candidates; unavailable reasoning stays
silent. Dated constraints are rechecked before transport. Cognition records decisions and actual Windows
submission/failure; button reactions point back to the decision. Private OS notices stay local. Learned
talk timing is retained; self-started questions need approval before being recorded as pending.

Train Friday runs separately and now reviews only persisted `kind='prediction'` thoughts in
`memory/mind/brain.db`. `prediction_review.py` records correct/wrong verdicts, optional actual app and
notes under a unique thought ID. A write transaction validates pending state, updates pattern beliefs,
app labels and the thought together. Live prediction replies use the same verifier; uncertain replies
leave review pending. No action permission or live pending-conversation state is changed by the tool.
Scoped owner feedback adjusts app ranking immediately. The existing nightly learner consumes labels;
the clean pathway still requires independently observed transitions and chronological availability.
No provider call or chat-model fine-tuning occurs. Legacy `reviews.db` lessons and their existing
overlays remain readable, but Train Friday no longer exposes interviews, generic lessons or exports.

Computer tasks are an explicit branch before chat memory/search/intent: `\c` commands go from the
command bar through `/api/v1/chat` to `services/computer/agent.py`. That service observes the selected
monitor through `desktop.py`, asks the existing provider failover layer for one JSON proposal, and
validates it with the discriminated models in `actions.py`. Proposals wait for `\c yes`; the service
rechecks the screen and focus, consumes approval, sends Windows input, then observes again. Stop
invalidates in-flight planning responses. Only the latest screenshot and last executed action enter
the next model call; no computer context is persisted. The interface owns focus restoration, while
the backend owns input execution and validation. Remote Telegram requests are refused.

Telegram capability facts enter the shared `core.config.SYSTEM_PROMPT` via
`services/telegram/capabilities.py`. Chat/voice detect explicit Telegram commands before screen,
file excerpts or web search; the shared intent service delegates to `telegram/commands.py`.
File sends resolve a current selected/single search hit, numbered result, filename or absolute path,
then upload to the configured recipient through the existing client. Recaps use local briefing,
activity and weekly report builders. `telegram/summaries.py` is ticked by the proactive watcher
outside busy guards, deduplicates successful periods using atomic persisted markers, and retries
failed sends after five minutes. Schedules use laptop local time and run only while FRIDAY runs.
Answer forwarding is another explicit Telegram command: the memory service retrieves the latest saved assistant
reply and the existing long-message client sends it verbatim. Chat delivery confirmations are excluded from history
so another forwarding request sees the same answer; voice already excludes system confirmations. No new answer
cache or AI call is needed, and clearing chat history also removes the source answer.

### 1. Small Stable Core

`services/mind/cognition.py` is the common event boundary, stored locally in a separate bounded SQLite DB.
Request decorators establish turn IDs and channels; thread offloads inherit these via ContextVars. Output
boundaries record completed/failed/cancelled operations, and notification submission uses the distinct
`submitted` status. Speech captures lifecycle only, with no payload. System results respect `memory_message`;
computer proposals remain ephemeral. Telegram multipart sends have one whole-message event plus chunk events.
`cognition_context.py` assembles the latest event per kind and current activity/mood/pending-question state
within the configured prompt budget, treating recorded text as data and omitting local-only content.
The existing brain consumes this via `awareness()` and publishes activity-category observations.
Direct introspection goes through `cognition_commands.py`, skips AI/search and doesn't consume pending questions.
Exact private notification recall stays outside chat history and remote Telegram. The UI's animation buffer
remains transient; the cognition DB holds semantic events. This adds shared awareness without replacing
specialist services or claiming human consciousness.

`core/` holds only config, errors and logging. Features live in `services/`.

### 2. Provider-Agnostic
Nothing imports a specific provider except `providers/registry.py`. Every AI call goes through
`BaseProvider`, normally via `providers/failover.py`. Switching providers means changing `.env`
or picking one in the tray.

### 3. Interface Separation
The backend knows nothing about UI. The tray and command bar are HTTP clients of the local API,
and a future UI will be one too.

### 4. Local-Only
The API binds to 127.0.0.1. `TrustedHostMiddleware` rejects other hosts, and a middleware
returns 403 to requests carrying another website's `Origin`. There is no CORS, so a web page
can't drive FRIDAY.

### 5. Config-Driven
`.env` holds secrets and settings; `core/config.py` validates them at startup.

### 6. Non-Blocking Backend
Recording, transcription, speech and PowerShell calls run in threads, so reminders,
clipboard polling and health checks keep working while FRIDAY listens or talks.

---

## Processes

```
launch_friday.vbs  (sets CurrentDirectory + API_RELOAD=false)
 │
 ├─► main.py ─────────────── FastAPI backend, 127.0.0.1:8000
 │     lifespan background tasks:
 │       • run_scheduler(reminders)     — delivers due reminders (toast + speech)
 │       • watch_clipboard(history)     — polls the clipboard sequence number
 │       • stt.preload()                — loads faster-whisper onto the GPU
 │       • tts.prewarm()                — caches common confirmation audio
 │
 └─► python -m interfaces.tray.app ─ one process, single instance (named mutex)
       • pystray tray icon (green online / red offline / amber listening), polls /health every 5 s
       • Win32 command bar (interfaces/popup/app.py)
       • RegisterHotKey: Ctrl+Shift+F → command bar, Ctrl+Alt+Space → voice toggle
       • interfaces/tray/backend.py → HTTP calls to the backend

When the tray quits, the launcher runs taskkill /F /T on this project's main.py processes only.
```

---

## Layers

```
┌──────────────────────────────── INTERFACES ────────────────────────────────┐
│ interfaces/tray (tray.py, backend.py, app.py)   interfaces/popup (command bar)│
│                                   │ HTTP                                      │
│ interfaces/api/app.py — TrustedHost + Origin check, error handlers, /health   │
│   routes/chat.py       /chat  /history  /memory/facts  /providers             │
│   routes/voice.py      /voice  /voice/stop                                    │
│   routes/clipboard.py  /clipboard/history                                     │
│   routes/system.py     /system (legacy), /system/stats (tray)                 │
└───────────────────────────────────┬──────────────────────────────────────────┘
                                    ▼
┌──────────────────────────────── SERVICES ──────────────────────────────────┐
│ search/web_search.py         build_search_context() — ddgs results → prompt │
│ vision/screen.py             ask_about_screen() — screenshot → vision model │
│ automation/intent.py         try_system_action() → ActionResult | None      │
│ automation/command_words.py    every command word/phrase + filler stripping │
│ automation/device_commands.py  strict local matcher (volume, brightness…)   │
│ automation/app_commands.py     local matcher (apps, sites, folders, search) │
│ automation/media_control.py    play/pause/next via Windows media sessions   │
│ automation/system_stats.py     CPU/RAM/battery/GPU/disk reports             │
│ automation/keyboard.py         types text / presses keys (SendInput)        │
│ automation/typing_commands.py  dictation, "write …", key presses            │
│ automation/writer.py           the AI writes the text to type               │
│ automation/command_cache.py    saved AI decisions per message (friday.db)   │
│ automation/system_control.py   the actual Windows actions                   │
│ automation/clipboard*.py       clipboard access + in-memory history         │
│ reminders/parser.py, service.py  parse, store (SQLite), schedule, deliver   │
│ memory/sqlite_memory.py        conversations + user_facts                   │
│ voice/recorder.py, stt.py, tts.py                                           │
└───────────────────────────────────┬──────────────────────────────────────────┘
                                    ▼
┌──────────────────────────────── PROVIDERS ─────────────────────────────────┐
│ failover.py  complete_with_failover() → provider_chain(primary)             │
│ registry.py  get_provider(name, model=None)                                 │
│ OpenRouter · Anthropic · OpenAI · Ollama   (all inherit BaseProvider)       │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow — Typed Message

```
Command bar / tray quick action ─► POST /api/v1/chat {"message", "provider"}

0. extract_screen_question(message)
   Screen question ("what's on my screen?", \v)? → vision/screen.py answers it
1. build_file_context(message), then build_search_context(message)
   File question ("what does my lease say…", "according to my notes", \d)?
   → excerpts from the file index (services/files/) go into the system prompt.
   Web search trigger (\s, "look up", "search the web for", "web search")?
   → add the search results to the system prompt and skip system commands
2. Otherwise, intent.try_system_action(message, provider), in order:
   a. a pending yes/no confirmation (organise_folder, 120 s timeout)
   b. the \o shortcut
   c. reminder commands
   c1. file commands: "find my …" / "open 2" / "show 2 in folder" / "rescan my files"
       (services/files/assistant.py — lists files, no AI)
   d. device_commands.match_device_command (strict)
   b2. typing: dictation, "write …" (the AI writes it), key presses
   (from here on, with wake words and politeness stripped by command_words.normalize_command)
   c2. several commands in one message ("mute and open chrome") → recognize every local step first,
       then execute in order and combine replies; unfamiliar combinations can use f when AI is enabled
   e. app_commands.match_app_command (open app/folder/website, Chrome/YouTube search,
      play music, organise), then a bare web address
      (music commands, including the Spotify ones — shuffle, repeat, queue, like,
      playlists, liked songs — are matched just before d by
      app_commands.match_media_command and run in a thread; with Spotify connected,
      services/spotify/player.py plays through the Web API)
   All local vocabulary lives in automation/command_words.py.
   f. AI fallback with native tool calling (tools in automation/command_tools.py):
      cheap model (INTENT_PROVIDER/INTENT_MODEL or INTENT_DEFAULT_MODELS), retrying on
      the chat model only if it errors. No tool call = chat. Several calls run in order
      and are reported as one reply. close_app only runs for apps named in the message.
   → if it matched, return ActionResult(success, message, memory_message).
     awaiting_reply=True if FRIDAY asked a question.
     memory_message replaces private content in chat memory.
3. Otherwise, AI chat: the last N messages from memory plus the new one
   → complete_with_failover(): the chosen provider, then FALLBACK_PROVIDERS
4. Save both messages to memory and return ChatResponse (with the provider that answered)

While awaiting_reply is true, the command bar stays open with the question selected.
```

---

## Data Flow — Voice

```
Ctrl+Alt+Space ─► tray.toggle_listening()
  already listening? → POST /voice/stop (stops the recorder, cancels the wait, stops speech)
  otherwise          → POST /api/v1/voice {"speak", "provider", "after_speech": false}

Backend (/voice):
1. after_speech=false → tts.stop()  (never talk over the user or record FRIDAY itself)
   after_speech=true  → wait for current speech to finish (409 if cancelled)
2. recorder.record() in a thread
   PyAudio 16 kHz. Silero VAD checks the last 3 s every 0.3 s.
   Stops after 1.5 s of silence following speech, after 8 s with no speech, at 60 s, or on /voice/stop.
3. stt.transcribe() in a thread: faster-whisper small, beam 5, vad_filter, English
4. Same pipeline as typed chat: search → system action → AI with failover
5. Return the reply immediately; speak it in a background task
   (system confirmations use the audio cache unless they show private content)

Tray: shows "You: … / FRIDAY: …" as a notification.
If awaiting_reply, it listens again with after_speech=true to hear the yes/no answer.

TTS (services/voice/tts.py):
  edge-tts stream (Devanagari → EDGE_TTS_HINDI_VOICE)
    → PyAV MP3 decode + resample to float32 mono → PyAudio output stream (single playback thread)
  stop() bumps a generation counter, which interrupts playback mid-sentence
  LRU cache (100) of MP3 bytes for short phrases; pyttsx3 when edge-tts is unreachable
```

---

## Data Flow — Reminders

```
"remind me at 5pm to call mum" → intent (reminder command) → reminders.add_from_message
  → parser.py extracts the time and text → stored in memory/friday.db
run_scheduler loop → deliver_due():
  claim one due source snapshot → brain fact/context review → recheck source/context
  → independently acknowledged Windows/eligible Telegram → delivered_at → optional rechecked speech
  failed/deferred/withheld reminders persist; retry performs a fresh review
  interrupted submission stays uncertain until explicit recovery
  overdue reminders resume review on startup, preserving their original due/event date
```

---

## Future Direction

Not scheduled yet; see `docs/roadmap.md`:
- **New UI:** the user is designing it. It will be another client of the API.
- **Plugin system:** `plugins/` is empty.
- **Semantic memory:** ChromaDB alongside SQLite.
- **Wake word:** on top of the existing recorder/STT.
- **Event bus/orchestrator:** only if coupling between services becomes a real problem. `intent.py` currently fills the orchestrator role.
