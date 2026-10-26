# AI_HANDOFF.md
# F.R.I.D.A.Y — AI Handoff Document

> Drop this file into any AI chat session to get it fully up to speed on the project.
> Always read this FIRST before making any implementation decisions.
> Then read `docs/FEATURES.md` (everything she can do), `docs/CHANGELOG.md` (newest first, with the why)
> and `docs/roadmap.md` (backlog).

*Last updated: 2026-10-24*

**Gaming optimization removed (2026-10-24):** owner requested full deletion.
Automatic game detection, process-priority changes, profiles/reports, idle reclamation,
API/browser/native controls and optimizer-specific background/voice restrictions are removed.
Saved optimizer settings and telemetry are deleted. General custom modes and activity awareness
remain independent. See `tasks/optimizer-removal-receipt.json` for source and validation evidence.

Tkinter customization (2026-10-23): `interfaces.settings` provides four searchable
tabs for contacts, routines, projects and modes. Open through
All controls / Customize FRIDAY (also in the tray menu), or `python -B -m
interfaces.settings`. UI I/O is off the Tk thread and drafts survive failures.
Backend CRUD uses typed local endpoints, shared command-write locking, atomic
replacement and stale-edit detection.
Saving never runs stored commands or sends messages. Contact/project changes
invalidate pending sends/resume offers, with reviewed recipient/project snapshots
rechecked before use. Active-mode rename/delete is blocked. Project metadata,
domain/URL attribution, cache and activity refresh are preserved. Taskbar work
present during this change was retained; its All controls menu exposes the new
tray action. Usage: `docs/CUSTOMIZATION_UI.md`; evidence/source bindings:
`tasks/customization-verification-summary.json`. Restart FRIDAY to load both UI
entry points and the new endpoints.
Verification: final combined editor/service/startup checks are 250 passed / 2
opt-in native-taskbar skips, with 443 source inputs unchanged during that run.
Earlier focused checks passed 237; the full run recorded 5,672 passed,
one concurrent-source launcher import failure and two skips. The updated launcher
checks pass in fresh runs. All new editor Tk checks and five synthetic previews
ran. Preserve the exact source/result distinction in
`tasks/customization-verification-summary.json`.

Current commitment topics (2026-10-22): the owner selected broader chat/voice
follow-ups. A unique named saved-commitment query or verified saved date result
now establishes one local 15-minute topic. Short date/countdown/previous-date
questions and explicit "what about <saved name>" switches work across laptop
chat/voice with zero model/search calls. Reuse reference_context with exact row
fingerprint, token and forget epoch; previous date follows the direct correction
link. Reads do not edit commitments or grant action permission. Telegram cannot
read, replace or retire local context. Unrelated turns, cancellation, stale rows,
forgetting and history/workspace clear fence it. Optional context failure cannot
block a valid date save or send recognized pronouns to generic AI. Older local
request work cannot replace/clear a newer topic, including a slow date save.
Fifty-six new
cases and a 15-turn no-model route probe cover the increment. Full source/results:
`tasks/topics-verification-summary.json`; usage: `docs/COMMITMENT_TOPIC_FOLLOWUPS.md`.
Broader arbitrary topic inference and cold first-generation reliability remain
open. Restart FRIDAY from the tray to load the code.
Final regression: 5,614 full-suite and 215 focused tests passed; zero failures/
errors/skips, one existing warning. All 399 snapshot inputs and final probe
sources match the current implementation.

First-call reliability follow-up (2026-10-22): narrowly scoped ordinary-chat date
answers now use smaller model instructions/context and omit duplicate critic
serialization. Original evidence and independent critique remain mandatory;
additional reviewed evidence keeps the full general context. Readiness reports
server, residency lookup and prompt-free load times; missing context metadata
is unknown. The configured model, context, settings, quotas and leases stay.
Two candidate runs each saved 3/4 first-round dates and 4/4 warm dates;
all negative controls passed. Final warm median was 2.837 seconds versus 3.453
in the saved baseline, about 18% lower in this small sequential comparison.
The first cold generation STILL timed out without saving; cold reliability is
unresolved. Do not present warm gains as a cold-start fix. Fifteen new tests,
280 focused checks and 5,558 full-suite tests passed (one existing warning).
Final full regression/source evidence:
`tasks/firstcall-verification-summary.json`; details and next diagnostic boundary:
`tasks/firstcall-review-notes.md`. Restart FRIDAY from its tray to load code.

Ordinary-chat commitment follow-ups (2026-10-22): the owner continued the queued
feature after integration research/browser work. A bounded SQLite ledger links
an ambiguous postponement question to offered target snapshots and original
owner answers across laptop chat/voice. Name-plus-date, punctuation-free voice
and name-then-date replies use existing local generation, critique, calendar
validation and atomic temporal history. Confirm only a matching committed
revision; silence/completed review alone is insufficient. Existing attention and
executive rate/lease limits persist; retained answers can use idle review and
`follow-up status` checks actual persistence. Cancellation, stale sources, newer
postponements and forgetting fence late results. Telegram cannot consume local
questions; unresolved/intermediate/retired reports are withheld from recall.
No models, provider settings, dependencies or action permissions changed.
See `docs/ORDINARY_CHAT_FOLLOWUPS.md`, the matching spec and
`tasks/ordinary-followups-review-notes.md` for evidence and model limits.
Restart from the tray to load. General conversational topic tracking and broader
useful paraphrase recall remain future work in `docs/BRAIN_LIFE_ROADMAP.md`.
Final verification: 5,543 full-suite tests and 327 focused tests passed with zero
failures/errors/skips and one existing warning. A warm ten-case installed-model
round passed; two first-round requests safely timed out without a date update.
Keep those failures as availability limits, not successful saves. Source bindings
and final artifacts: `tasks/ordinary-followups-verification-summary.json`.

Local review reliability (2026-10-21): cognitive reviews now separate prompt-free model
loading from inference within the existing executive lease, use a compact single-work
response, and retain private timing/failure diagnostics. `brain status` and the existing
brain read API show the last recorded result, including rejected or interrupted work.
Original sources and independent critique still govern saves. Exact repeated temporal
items are deduplicated; one unambiguous omitted date can be recovered from an exact
owner quote using the local calendar. Model judgments can still be wrong.
Verification: 5,197 full-suite tests and 355 focused checks passed; zero failures/errors/skips, one existing deprecation warning. Full run: 325.34 seconds. Sixteen affected Python files parsed; whitespace clean. Two frozen five-case installed-Ollama probes produced eight useful saves and two safe evidence rejections; both separately proposed unrelated groups were rejected. Useful reviews took 2.50-7.91 seconds; nonresident startup wall time was 5.59/5.63 seconds. No owner facts, commands or notifications were created. Evidence: tasks/reliability-final-verification.*, tasks/reliability-final-focused.*, reliability-final-live-probe-a.json/-b.json, reliability-source-validation.txt and reliability-review-notes.md. These small synthetic controls do not establish general model reliability; continue the saved phase 6 coverage work.
Continuation: finish phase 6 semantic/cold-start coverage before relevance-based recall;
see `docs/BRAIN_LIFE_ROADMAP.md` and the local-review reliability spec.

Memory consolidation (2026-10-21): the existing local executive review can now connect
related original chat/voice experiences into extractive historical memory threads. A
separate local critique checks the grouping; stored excerpts retain wording, paired
questions, original dates and uncertainty. No generated factual recap becomes an owner
fact. Up to 100 threads retain reviewed source snapshots through routine episode retention.
Commitment corrections retire affected threads, preserve the latest correction source,
and invalidate conclusions using the retired summary. Forgetting clears snapshots and
fences active reviews. Local reasoning, inquiry/notification context, brain status and
GET /api/v1/mind/reasoning share the memory; remote prompts and mirrored offers exclude
private summary conclusions. Existing review budgets, attention gates and local model stay.
Verification: 5,145 full-suite tests and 337 focused checks passed, including 27 memory-specific cases; zero failures/errors/skips and one existing warning. Full run: 291.78 seconds. Ten affected Python files parsed; whitespace clean. Final installed-local-model positive control saved a source-linked thread in 9.55 seconds after an independent critique rejected the first proposal; a validated retry passed. Original uncertainty, paired question and dates survived simulated pruning/restart. Earlier latency, mixed outputs and inconsistent critique judgments remain limits, not a claim of reliable human cognition. Evidence: tasks/consolidation-final-verification.*, tasks/consolidation-final-focused.*, tasks/consolidation-source-validation.txt and tasks/consolidation-memory-positive-control.json.
Phase 5 continuation was local inference reliability; use the newer phase 6 entry above.
Quit FRIDAY from the tray and relaunch launch_friday.vbs to load the code.

Purposeful curiosity (2026-10-21): generated inquiries now rank supported task-blocker and
missing-commitment-date gaps, then asks only when different possible answers change
a useful decision. Typed purpose records retain the planning choice, distinct possible
answers and conditional next steps. No open gap means silence without a model call.
Answered/offered/declined versions stay closed while retained; relevant source changes
can reopen them without bypassing quiet preferences or the global question budgets.
Question-purpose history enters shared local reasoning as conditional evidence, never
proof that a task or blocker was resolved. Brain status and /api/v1/mind/brain retain
the last question's purpose after later silence. 5,118 full-suite tests and 332 focused checks passed, with zero failures/errors/skips and one existing warning. Full run: 402.29 seconds. Thirteen affected Python files parsed. Evidence: tasks/curiosity-final-verification.* and tasks/curiosity-final-reviewed-focused.*.
Phase 4 continuation was memory consolidation; see the newer phase 5 entry above.
Quit FRIDAY from the tray and relaunch launch_friday.vbs to load the code.

Verified outcome learning (2026-10-21): phase 3's first increment verifies shared
master-volume/mute writes and mode selection using independent readback. Historical
requested/applied/verified/failed/unknown receipts feed local evidence, repeated-failure
explanations and life focus. Partial setup/cleanup retains truthful mode status.
Forget, concurrency, private context and disabled/broken storage are covered. Local
brain status and /api/v1/mind/outcomes explain the checks and their limits. No task
completion or automatic retry is inferred. Local inference proposed diagnostics but
critique withheld overstated guidance; deterministic lessons remain usable. Cognitive
schemas exclude invented plan targets. 5,084 full-suite tests and 385 focused checks passed, with zero failures/errors/skips and one existing warning; 121 final status/reasoning checks passed after two additional partial-mode readback cases and response clarification. Fourteen affected Python files parsed. Artifacts: tasks/outcome-learning-reviewed-verification.*, tasks/outcome-learning-reviewed-focused.* and tasks/outcome-learning-delivery-focused.*.
At phase 3 delivery, phase 4 was the next saved milestone; use the latest continuation above.
Quit FRIDAY from its tray and relaunch launch_friday.vbs to load the code.

**Behavioral life state (2026-10-20):** owner continued phase 2 of `docs/BRAIN_LIFE_ROADMAP.md`.
`life_state.py` derives independent review/interrupt gates, source-linked responsibility/uncertainty
focus and contextual engagement. Existing executive, inquiry, notification review, local conversation
and life feeling reports consume it. Quiet preferences permit silent review; busy/typing/gaming/calls
and active requests defer it. Optional delivery rechecks restraint. Actual status/work-completion
notices and essential/requested notifications retain separate contracts. Timing reactions are bounded,
deduplicated and source-checked in cognition SQLite; only offered autonomous questions train timing.
Explicit requested replies, withheld/prepared-only and forgotten questions cannot train it. Forgetting
clears the ledger and cannot race it back into existence. Negative warmth/sulking was removed, including
legacy negative counters. Diagnostics: local brain status and `/api/v1/mind/life`. Cognitive schemas
now enumerate actual citation/source/check IDs; invalid model outputs remain rejected. Real local
probe completed silent blocker review with conversation off, zero inquiry calls/actions/notifications.
Spec: `docs/specs/2026-10-20-behavioral-life-state.md`; final evidence/continuation are in the roadmap.
Next saved phase: general verified outcome learning (phase 3), not arbitrary tools.
Verification completed: 5,045 full-suite tests, 505 focused checks and two final delivery lifecycle
checks passed; zero failures/errors/skips. The first full/probe diagnostics are preserved separately.
Final artifacts: `tasks/life-state-final-*`, `tasks/life-state-delivery-focused.*`; 18 Python ASTs parsed.

**Brain/life roadmap and temporal memory (2026-10-20):** owner authorized beginning the proposed
brain/life upgrades and saving the plan for later. Continuation: `docs/BRAIN_LIFE_ROADMAP.md`.
First increment: `temporal_memory.py` adds source-linked commitment interpretations and revision
history to the existing local executive report, critique and guarded transaction. Exact date words
are resolved by the local calendar against original receipt dates. Unknown dates stay unresolved;
corrections preserve history and invalidate conclusions based on superseded source dates. Current
evidence enters reasoning/inquiry/notifications, local conversation and life feeling reports. These
records do not mutate canonical deadlines/reminders/classes/tasks. New local read APIs expose situation
and history; brain status includes commitments. Forgetting clears all derived temporal state.
At that phase-1 milestone, behavioral life state and later learning phases were still planned.
Behavioral life state is now implemented above; general outcome learning, purposeful curiosity and
consolidation remain planned. Phase 1 itself did not change warmth/curiosity mood mechanics.
Tests and live evidence are recorded in the roadmap and `tasks/temporal-*`; do not infer success from
an earlier diagnostic probe. Spec: `docs/specs/2026-10-20-temporal-situation-memory.md`.

**Connected cognitive inquiry (2026-10-20):** the owner reported repetitive scheduled questions and
unprocessed answers, and authorized shared local brain processing. `brain_memory.py` retains bounded
owner utterances/paired answers with original date, channel and source, feeding reasoning, notification
review and relevant conversation recall. `inquiry.py` chooses one source-cited question or silence using
past reports, present attention/integrations and future commitments. Typed required fields, duplicate
topics, source/preference rechecks, leases and durable budgets inhibit invalid/repetitive questions.
Questions from other proactive features share anonymous spacing/day limits through notification dispatch.
There is no automatic evening queue, announced count, forced startup question or six-second continuation.
Explicit day-review/learning requests permit one question; old persisted queues/callbacks are retired.
`evening.collect()` is now used only by the explicit manual Train Friday catalogue.
`cognitive_runtime.py` wakes bounded executive review on meaningful request/action/owner/notification
events and local feature-write lifecycles; command intentions precede existing local execution guards.
Private payloads are not captured by generic feature events; keyboard/computer-command input is excluded
from dialogue episodes. Telegram cannot consume the laptop's pending question. Operational evidence
includes actual mode, saved Spotify login and network/provider configuration.
Forget/reset clears private episodes/claims and fences in-flight decisions; anonymous ceilings survive.
Local controls: `brain status`, `question status`, `why did you ask me that`; `/api/v1/mind/brain` is read-only.
Spec: `docs/specs/2026-10-20-connected-cognitive-inquiry.md`; wiring/limits: `docs/CONNECTED_BRAIN.md`.
Live synthetic trial: installed local Qwen generated a relevant blocked-project question; a proposed
follow-up on the same answered topic was withheld. No notifications/commands were delivered. Cold-load
measurement (~20s model load) led to a 50s inquiry generation budget and 90s lease. The local model
remains fallible; its duplicate/invalid outputs do not become questions or facts. Existing action permissions
and proposal-only reasoning remain intact. Quit/relaunch FRIDAY to activate the loop and retire old queues.
Final full regression: **4,976 passed**, zero failures/errors/skips, one existing warning (427.35 seconds).
Final focused after stop-control/private-input review: **638 passed**. Use final-named XML/log artifacts;
earlier connected-brain runs include diagnosed failures and are not completion evidence. Stop controls
are handled locally before filler normalization; pausing/off clears pending questions and blocks late delivery.
Computer-command input remains ephemeral even when the computer feature is disabled.

**Runtime status correction (2026-10-20):** mode replies now lead with final state; repeated starts
do not end/restart or rerun setup. Setup failures retain an explicit on-state message. Named status
questions do not execute mode changes; no mode reports Normal.
New typed `/api/v1/system/status` reads mode and saved Spotify connection
without model/network calls. Tray polls it, shows mode in menu/tooltip, and replaces the static Connect
Spotify row with current connection plus suitable actions. Offline/status failures clear stale claims.
Saved Spotify was read directly and is connected; no reconnection/credential change was made.
Spec: `docs/specs/2026-10-20-runtime-status.md`; verification: `tasks/runtime-status-*`.
Final full regression: **4,939 passed**, zero failures/errors/skips, one existing warning (358.46 seconds).
Focused: **168 passed**. Nine affected Python files parsed; scoped whitespace check passed.
Both tray and backend need reloading: Quit FRIDAY, then run `launch_friday.vbs`.

**AI language / local thinking correction (2026-10-20):** the owner explicitly superseded the old
prepared-replies-only policy. `AI_LANGUAGE_ENABLED=true` now enables structured canonical-command
translation for unmatched language and conversational replies with recent history in chat/voice.
`AI_ASSIST_ONLY` remains true: local routing/execution, confirmations and Telegram restrictions stay
authoritative. No model tools, recursive translation or unscoped planning. Cognitive/notification
review provider chains now contain only Ollama, including after local failure. Language still uses
OpenRouter then Ollama. Private settings, model choices and credentials were preserved.
Live synthetic probe translated two informal commands and generated an Ollama reply; no actions ran.
Direct cloud probe confirmed HTTP 429 `free-models-per-day`, including a currently listed free model.
The cloud route stays enabled; its account daily quota must recover for cloud language to work.
Spec: `docs/specs/2026-10-20-ai-language-local-thinking.md`; evidence: `tasks/language-*`.
Final full suite: **4,924 passed**, zero failures/errors/skips, one existing warning (347.90 seconds).
Final focused: **92 passed**. Scoped whitespace check passed; ten affected Python files parsed.
Earlier statements below that general conversation is disabled describe the superseded policy.

**Shared executive cognition (2026-10-20):** user approved implementing the selected next upgrade.
`executive.py` supplies immutable bounded situations, source fingerprints, project pre-action decisions
and outcomes, plus durable review jobs/leases/attempts. The watcher delegates changed-evidence review
through a new `cognitive_review` purpose while keeping `AI_ASSIST_ONLY` unchanged. Review is proposal-only:
no owner facts, tools, automatic changes or task completion. Five-minute spacing/four starts per rolling
hour and backoff survive restarts/switches. All source versions/attention and lease/epoch are checked;
report and completion receipt are atomic, including the post-save crash boundary. Forget/history/workspace
reset retires private derived contexts/in-flight work without resetting budgets. Selected old task/goal
focus is retrieved beyond recency caps; historical execution receipts exclude private artifact payloads.
Local typed/voice: `executive status`, `executive review on/off`, `why did you decide that`.
Restart from tray to load. Broader preflight for old tools and full temporal/episodic memory remain future.
Spec: `docs/specs/2026-10-19-executive-cognition.md`; tests/evidence: `tasks/executive-*.xml`.
Live project probe: five verified checkpoints plus assessment/outcome feedback. Cognitive-provider probe:
configured free cloud models returned timeouts/limits/unavailability; Ollama fallback generated reports
that were rejected or exceeded the review budget. No source task progress or owner facts changed.
Do not claim this established model reasoning quality. Artifacts: `tasks/executive-project-live-probe.log`,
`tasks/executive-live-probe.json`. Runtime model settings/private `.env` were preserved.
Final full suite: **4,906 passed**, zero failures/errors/skips, one existing warning (270.46 seconds).
Final focused: **172 passed**. Evidence: `tasks/executive-final-verification.log` / `.xml`,
`tasks/executive-final-focused.xml`. Earlier failed midnight fixture runs are retained, not final results.

**Verified project execution (2026-10-19):** user authorized extending the existing execution engine
before assessing cognition/memory/reasoning. New `start project session for <saved name>` prepares
the existing verified brief then opens/verifies the exact registered Explorer folder. Local named
status/resume/cancel use separate persistent focus. External checkpoints claim token/lease, run without
SQLite locks, revalidate sources and reconcile uncertain actions without replay. Completed sessions
do not reopen windows on resume. No arbitrary plan text/keyboard/shell steps execute. The existing
routine typing/cleanup audit remains open. Live temporary-folder trial passed; see
`docs/specs/2026-10-19-project-execution.md` and `tasks/project-execution-*.xml`.
Final regression: **4,861 passed**, no failures/errors/skips, one existing warning (332.02 seconds).
Focused workflow/corpus checks: **550 passed**; real Explorer probe: **5/5 checkpoints verified**.
Final evidence: `tasks/project-execution-final-verification.log` / `.xml`,
`tasks/project-execution-final-focused.xml`, `tasks/project-execution-live-probe.log`.
The follow-up assessment selected shared executive cognition with versioned evidence; its first
milestone is now implemented above. Broader autonomous execution remains future work.

**Useful proactive task help (2026-10-18):** the owner chose goal-aware proactive help before
desktop reliability/project-control work. `mind/task_followups.py` reserves suggestions from saved
active/blocked tasks, ranked by active goal priority, blocker status and age. Active tasks need two
days without a recorded update; blocked tasks need one day. Paused/finished work, inactive goals and
recent progress are excluded. An unchanged record is not proof that no real work happened. Suggestions
show a saved next step or ask about an explicit blocker; they never execute steps or mark work complete.

The watcher queues one candidate into existing notification review, with exact task/goal evidence even
outside shared top-five context. Fresh source/preferences/attention checks and a durable single-use
claim guard transport. Nudges/free-will switches, busy/fullscreen/quiet mode, typing, away state,
microphone use and pending questions apply. Generic/evening questions wait during live task reply context.
Only the already authorized `notification_review` model purpose is used; general policy is unchanged.

`workspace_followups` and `workspace_followup_preferences` share the cognition SQLite DB. Selection
serializes across processes: 30-minute attempt gap, at most four reviews/day, two claimed notification
attempts/day and four hours between claims. Same-task gaps begin at 24 hours and lengthen up to seven
days after unanswered attempts. Failed/unknown submissions never create reply context or replay
automatically. A crash after claim leaves an unconfirmed submission that still counts toward cooldowns.
Only actual transport acceptance is recorded as submitted; no claim of being read/heard is made.

Buttons: **Review task / Not now / Stop asking**. Review shows saved progress; Not now snoozes that
task for 24 hours; Stop asking persists until resumed. Submitted local follow-ups accept `not now`,
`show that task`, `why this followup` and `why did you suggest that` for 15 minutes. Unrelated turns,
expiry/reset and changed snapshots invalidate replies. Telegram cannot consume laptop reply context;
explicit named controls operate shared owner preferences. OS button tokens remain process-local.

Commands: `show task followups`; `pause/stop/resume task followups`; add `for <saved task name>` for
one task. `review/explain/snooze/dismiss this task followup` uses current scoped context. Status shows
factual selection reasons, submission state and owner switches. History clearing preserves preferences;
clearing goals/tasks removes the new records. No new UI, dependency, application action or timetable
extension. Restart FRIDAY from the tray. Evidence: `tasks/task-followups-focused.log` / `.xml`,
`tasks/task-followups-verification.log` / `.xml`.
The initial full run exposed three existing date-sensitive reasoning checks after midnight: mocked
"starting today" reports were fixed to an October 14–17 window while routes/approval used the real
clock. The report mock now derives its dates from the caller's timestamp and the explicit-time approval
test supplies that same test time. Production expiry checks are unchanged. All 85 final focused checks
passed after this correction; the initial failure evidence is retained as
`tasks/task-followups-before-clock-fix.log` / `.xml`.
Final verification: **4,737 passed**, zero failures/errors/skips, one existing deprecation warning
(270.14 seconds). Broad focused checks: **1,670 passed** (44.04 seconds). After the date-fixture
correction, **85 final focused checks passed** (6.62 seconds); see `tasks/task-followups-final-focused.log` / `.xml`.

**Temporary class rescheduling (2026-10-17):** the owner approved the next temporal-memory slice.
`tomorrow's DBMS class moved from 9 AM to 11 AM` changes only that dated occurrence, preserves
duration and the weekly template, and retains original/new start/end times, exact owner quote and
receipt time. Recall with `when is tomorrow's DBMS class`; inspect `show class history for tomorrow's
DBMS`. Dates can be today, tomorrow, a weekday (next occurrence including today), or ISO YYYY-MM-DD.
Repeated subjects ask for an offered number or subject/time. Choices expire after 15 minutes,
on unrelated turns/reset, and stay separate on laptop and Telegram. Wrong old times, started classes,
past/cross-midnight targets and occurrences with recorded attendance are refused.

`link reminder 1 to tomorrow's DBMS class` explicitly links a displayed reminder without moving it.
A later class shift previews changes. Use `review/apply/reject class reminder updates for tomorrow's
DBMS` in the channel that created the preview. Approval reuses the deadline batch transaction,
delivery-state guards and replay receipt. Pending shifts defer linked reminders at review/recheck;
cancellation suppresses that explicitly linked occurrence, including during interrupted finalization.
One reminder cannot belong to both a deadline and a class. Rejection keeps existing reminder times.

`class_sessions.py` stores dated records atomically in `memory/class-sessions.json`, using the shared
deadline writer lock. `class_changes.py` owns parsing, resolution, provenance and scoped controls.
Effective classes feed timetable answers/prompt/briefing, next-class selection, warnings, study-mode
offers and attendance. Notification context fingerprints include effective classes; changed times
invalidate in-flight notices. Attendance buttons recheck start/revision. Already submitted notices
cannot be recalled. Cancellation facts keep precedence. A changed/removed weekly template does not
inherit an old override; linked reminder delivery is held for review. Corrupt records are retained.
This pass supports time changes within one date; moving a class to another date and general commitment
reconciliation remain future work. No model policy, integration or dependency changed. Restart FRIDAY
from the tray. Verification evidence: `tasks/class-changes-focused.log` / `.xml` and
`tasks/class-changes-verification.log` / `.xml`.
Verification: **4,688 passed**, zero failures/errors/skips, one existing deprecation warning
(301.92 seconds). All **1,704 focused checks passed** (58.10 seconds).

**Deadline correction and linked-reminder consistency (2026-10-17):** owner approved the first
scoped temporal-memory workflow. `my DBMS deadline moved from Friday to Monday` updates one saved
deadline, preserves its existing clock unless a time is supplied, and keeps the old/new dates, exact
owner statement, source and the time of correction in history. Wrong old dates, past targets and ambiguous names
are refused or clarified. `when is my DBMS deadline` and `show deadline history for DBMS` read the
canonical record. Workspace/brain prompts and reasoning evidence expose current owner-reported dates;
new matching task handoffs/project briefs include them and block stale snapshots.

`link reminder 1 to deadline DBMS` explicitly records the displayed reminder's identity, text, due time
and offset. A correction previews shifts; it never moves reminders automatically. Use `review reminder
updates for DBMS`, then `apply reminder updates for DBMS` or `reject reminder updates for DBMS`.
Approvals are channel-scoped and guard deadline revision, proposal digest, exact reminder snapshots,
future times and delivery state. A SQLite transaction moves the whole batch, verifies readback and
records a receipt. If JSON finalization fails, retry reconciles the receipt without replay. Pending
updates defer matching reminders at notification review/recheck; rejection keeps their existing times.
Active/uncertain/partially submitted deliveries must be resolved before rescheduling.

Deadlines stay in `memory/deadlines.json`, now atomically published with a cross-process SQLite writer
lock. Added IDs/history/link/proposal fields remain compatible with legacy rows; malformed data is
refused without overwriting it. Ambiguity choices use existing scoped 15-minute context and expire
on unrelated turns/reset. Explicit deadline removal/completion/clearing removes its stored history and
links as well; it does not cancel independent reminders. Existing completed artifacts remain historical.
No model policy, general inference authority or dependency changed. Classes and other commitments
remain future temporal-memory work. Evidence: `tasks/deadline-changes-verification.log` / `.xml`.
Restart FRIDAY from the tray to load this pass.
Verification: **4,630 passed**, zero failures/errors/skips, one existing deprecation warning (221.13 seconds). All **84 final focused checks passed**, including the prompt-budget regression; see `tasks/deadline-changes-final-focused.log` / `.xml`.

**File and handoff conversation continuity (2026-10-17):** the owner approved the next scoped
conversation-context slice. File results/selections and pending choices persist in SQLite for up to
15 minutes, separately for laptop and Telegram. `open it` uses the selected file or a sole result;
multiple unselected results ask which file, then accept an offered name/ordinal. `actually use
project-notes.pdf instead` selects without opening; `open it` or `show it in folder` performs the action.
`the other file` works when exactly one alternative remains. File opens/reveals/selections recheck
path identity, size and modification metadata, and claim the context token before the OS action.
This is metadata validation, not a file-content checksum or proof an application rendered the file.

Handoffs now accept `actually, use the notification bug` after preparing/checking a handoff, plus
names/ordinals after ambiguous requests. Revisions create fresh verified artifacts, preserve completed
outputs and atomically cancel superseded unfinished jobs. Offered task identities/versions and
context tokens are rechecked; late completion cannot restore retired short context. Source tasks
remain open. Handoff follow-ups stay laptop-only; Telegram cannot consume their choices.
Unrelated turns retire short context, and history/workspace resets clear it. Explicit named controls
retain durable task/handoff focus. Chat/voice classify these turns before search, screen handling,
question learning and multi-command parsing. Existing project-brief follow-ups remain supported.
No model policy or dependency changed; arbitrary cross-tool references remain future work.
Evidence: `tasks/conversation-references-verification.log` / `.xml`. Restart FRIDAY from the tray.
Verification: **4,588 passed**, zero failures/errors/skips, one existing deprecation warning (204.44 seconds). All **22 new focused checks passed** after subprocess log isolation; see `tasks/conversation-references-final-focused.log` / `.xml`.

**Scoped brief conversation continuity (2026-10-17):** owner approved completing the proposed follow-ups.
After preparing/checking a project session, `leave out the notes`, `include the notes again`,
`actually, use the college project` and `refresh that brief` create a new verified brief from fresh snapshots.
Note inclusion carries across revisions; excluded notes are not read. Completed older artifacts remain,
while superseded pending/blocked jobs are cancelled atomically. Workspace payloads remain compatible.
`project_session_context.py` owns SQLite context/choice records, 15-minute expiry and token guards against
stale concurrent changes. Ambiguous switches wait for a saved project name or offered ordinal; choice
identities are rechecked. Unrelated local turns, history clearing and workspace reset retire short references.
Named session controls still use durable focus. Laptop chat/voice classify these turns before search,
screen interpretation and proactive-question learning; Telegram cannot consume laptop brief context.
AI permissions, general reasoning and arbitrary tool execution remain unchanged. This completes the scoped
project-brief follow-ups; general cross-tool context is still future work. Evidence is in
`tasks/brief-followups-verification.log` / `.xml`. Restart FRIDAY from the tray to load this pass.
Verification: **4,564 passed**, zero failures/errors/skips, one existing warning (252.57 seconds).
After the final clarification-prompt wording adjustment, all **82 focused checks passed**;
evidence is `tasks/brief-followups-final-focused.log` / `.xml`.

**Project work-session briefs (2026-10-17):** owner approved the proposed second execution workflow.
`prepare my project work session for friday` captures a registered project, matching task/goal progress
and blockers, bounded file metadata and matching saved notes, then atomically publishes/verifies a brief
under `memory/project-sessions/`. `check/resume/cancel my work session` uses separate durable focus.
`project_session.py` reuses the handoff engine's controls; its tagged records use `task_id=0` (no source task),
and engines refuse records belonging to another workflow. Captured metadata, registration and task context
changes block stale publication. Four checkpoints resume after restart; output conflicts are never overwritten.
Only metadata is inventoried (100 files/500 entries/two nested directory levels); content, diary and saved
project commands are not read/executed. Task/note matches are deterministic project-name word matches.
General plan execution and broad cross-tool context remain future work. AI policy is preserved; Telegram is refused.
Final suite: **4,537 passed**, zero failures/errors/skips, one existing warning (184.17 seconds).
See FEATURES/architecture and `tasks/project-session-verification.log` / `.xml`. Restart from the tray.

**Deferred debugging backlog (2026-10-15):** the owner requested saving the feature-wiring
audit for later fixes. Read [`wiring-audit-2026-10-15.md`](wiring-audit-2026-10-15.md) for
reproduction evidence, operational observations and unverified live trials. On 2026-10-16 the owner
approved laptop/Telegram isolation: F2 (pending confirmations) and F6 (file results/selections) are
fixed, including remote shortcut cleanup and preservation of laptop computer proposals. Laptop
chat/voice retain shared temporary context. F3 was subsequently fixed with owner-approved notification
brain/recovery (below); the other six findings remain deferred. Saving them is not approval to implement
them. Restart from the tray loads this fix; isolation test evidence is
in `tasks/channel-isolation-verification.log` and its matching XML: **4,419 passed**, no
failures/errors/skips, one existing deprecation warning.

**Notification brain (2026-10-16):** the owner explicitly authorized fact/context-based notification
review. New `notification_review` purpose is permitted in assist-only mode; general model access is
unchanged. `reminder_review.py` validates exact IDs/evidence/provenance, uses bounded provider calls,
and rechecks current facts/context. `reminders/delivery_state.py` stores outbox leases, per-destination
acknowledgements, re-review/retry/withheld/uncertain state. Failed or withheld explicit reminders remain
pending; `retry failed reminders` queues a fresh brain review. Unknown submission outcomes require
explicit retry. Proactive/completion/filing notices recheck their context too; private origins stay private.
Local notification status/why commands and protected read-only `/api/v1/mind/notifications` explain the
decisions and transport outcomes. Final suite: **4,510 passed**, zero failures/errors/skips and one
existing deprecation warning. Artifacts: `tasks/notification-brain-verification.log`
and `.xml`. Synthetic live probes exercised four expected choices, with a later repeat showing provider
timeout/invalid decisions safely held. Model judgment remains fallible. Restart from the tray is required.

**Current initiative:** the owner requested saving and starting the eight-part assistant roadmap.
Read `docs/assistant-roadmap.md`, `docs/specs/2026-10-15-persistent-execution.md` and `tasks/plan.md`.
The first implementation is a checkpointed, verified, local task-handoff workflow in
`services/mind/execution.py`, routed through chat/voice. General plan execution remains future work.
Completed training-plan files were preserved under `tasks/archive/`. Current model policy was preserved.

---

## What This Project Is

**F.R.I.D.A.Y** (Female Replacement Intelligent Digital Assistant Youth) is a modular, local-first
personal AI assistant. It runs on one Windows 11 laptop with an RTX 5060 8GB.
It is designed to grow deliberately into a full AI operating framework.

**This is NOT a quick chatbot. This is a long-term platform.**

---

## Core Philosophy

- Architecture quality over feature speed
- Modularity over monoliths
- Maintainability over cleverness
- Documentation continuity over move-fast-break-things
- **Learned, not fixed:** FRIDAY's behaviour (when she talks, jokes, suggests habits, late nights) is learned from the
  Boss's reactions, not hard-coded rules. Hard limits only where they protect the user (busy, on a call, mid-typing).

---

## The Developer ("Boss")

- Comfortable with concepts; prefers simple, clean code with comments
- Vibe coder: working code matters more than perfect patterns
- Tests features by using them, and reports issues casually ("bro the stt is very bad")
- Builds this as a long-term personal project; a college student (REVA University, section II-A)

## How We Work (important)

- **Light process:** for a new feature, give a short design in chat (a few bullets), get one "yes", then build.
  No spec/plan documents. Bug reports: find the root cause (reproduce it — logs, a probe, a simulation), then fix.
- **Approved batches:** when the Boss approves a list ("let's do all of them"), build them in order without asking
  again per item. Otherwise, wait for approval before starting the next backlog item.
- **Git cleanup and commits are deferred.** Don't raise them unless the user does.
- Keep UI work within the requested surface.
- Keep files under 500 lines. Run the tests after every change. Update the docs after meaningful changes.
- The Boss restarts FRIDAY from the tray to pick up changes; say so when a change needs it.

---

## Current Project State

A working assistant with a lot of features — see **`docs/FEATURES.md`** for the full, current list. In short:

**Reasoning upgrade (2026-10-14):** `services/mind/reasoning.py` interprets ordinary statements into
exact owner quotes, cited implications/predictions, questions and service proposals. A separate model
grounding check and one repair share a 25-second inference budget. Provider failover/model selection
remain configured; native schema output is optional (implemented for existing Ollama). Tests disable
new passes by default; `test_reasoning.py` opts in with deterministic providers and separately tests
the real critique contract. Model self-checks are fallible, not independent truth verification.

`reasoning_store.py` stores owner evidence, source fingerprints, corrections and conclusions alongside
cognition. `reasoning_effects.py` applies explicit confirmed class windows or owner-approved inferred
class changes/task plans/reminder moves. All service changes are read back; plans cannot execute tools
or mark steps complete. Approvals are consumed once, stale task/reminder targets are refused, uncertain
corrections cannot withdraw established facts, and original dated constraints cannot be extended by
rereading. Expired class projections still constrain historical attendance; fact forgetting removes
dependencies and duplicate literal owner memories. IDs are monotonic and do not replay after clearing.

Chat/voice, shared prompt, brain awareness and notification decisions read this state. Changed facts,
goals/tasks/reminders can trigger a watcher review at most every five minutes, and fresh proposals can
nominate notices behind busy/away/nudge controls and the normal send/silence decision. Public rejections
feed later reasoning. `reasoning status`, `apply/reject reasoning proposal <id>`, `reconsider my situation`
and read-only `/api/v1/mind/reasoning` expose it. `REASONING_ENABLED=false` stops new passes/nominations,
without deleting facts or previously approved date constraints. See architecture/FEATURES for scope.

Runtime limit observed: free OpenRouter text models returned rate-limit/unavailable errors. Ollama
was initially unreachable, later responded, but its existing 3B model gave inconsistent calendar/effect
conclusions. Synthetic tests passed quotes/guidance parsing or rejected unsupported conclusions; no
live owner facts, notifications, proposals or service changes were created. Don't claim fully reliable
general autonomy from these probes. Restart from the tray to load this upgrade.
Final verification: 1,813 passed (28 reasoning tests); one existing deprecation warning. Health online.

**Ten layer foundation pass (2026-10-14):** `services/mind/layers.py` inventories actual implementations
and limits of the requested cognitive layers; `brain layers` and `/api/v1/mind/layers` expose it.
Most foundations already existed and are preserved. `workspace.py` adds explicit owner goals/priorities
and persistent task plans/cursors/blockers/evidence in two tables within the cognition DB. Tasks and
goals survive bounded event pruning, chat clearing and restart; explicit workspace reset is separate.
`workspace_commands.py` supplies offline owner commands. Shared cognition prompts, brain awareness and
notification decisions consume a bounded view, also exposed by `/api/v1/mind/workspace` (read-only).
Plan text never executes tools or grants approval, and completion evidence is labelled `owner_report`,
not independently verified. No automatic request/screen/computer-task capture was added. Commands bypass
search/provider calls and do not consume pending proactive answers. The subsequent reasoning upgrade is
described above; unified attention and universal verification remain future work. Don't imply the whole brain is wired.
See architecture/FEATURES for the ten-layer map and command examples. Restart from the tray to load this pass.
Full test suite: 1,785 passed with one existing deprecation warning; no live owner goals/tasks were added.

**Dated fact repair (2026-10-14):** owner-told dated class facts constrain the effective timetable, including
legacy "next four days" statements anchored to their receipt date. The October 12 training block covers
October 12–15; the normal weekly schedule resumes October 16. `services/memory/schedule.py` keeps new
operational facts in the same SQLite DB without provider/embedding dependence. Memory listings,
forgetting, corrections and expiry are wired. Dated readers use `timetable.classes_for_date()`;
cancelled sessions don't lower attendance and stale buttons cannot mark them missed. Raw data stays.

`services/mind/notifications.py` gives watcher candidates one bounded reasoning batch per tick using
facts/live observations/recent public outcomes. Invalid/unavailable answers stay silent; constraints
are rechecked before delivery. Self-started questions need approval before `_record()`; explicitly
requested questions bypass that proactive gate. `cognition_public=True` is reserved for approved
FRIDAY-originated proactive notices, so shared awareness sees their exact submitted/failed text while
other private OS notices remain local. Button reactions link to the decision event. Explicit reminders
and configured Telegram reports keep requested schedules. Tests mock reasoning by default; the
reasoning-specific suite restores the real parser with deterministic provider responses. 1,776 passed.

- **Interfaces:** system tray (main UI), Ctrl+Shift+F command bar, voice (Ctrl+Alt+Space), "Hey Friday" (Ctrl+Alt+H),
  **conversation mode** (Ctrl+Alt+C / "let's talk"), a desktop **body** (pixel robot), Telegram bot, `friday` CLI
- **Voice:** Parakeet TDT 0.6B v2 STT (CPU, ~0.2 s), edge-tts Aria + Piper offline, wake word with interrupting
- **Mind:** free will (talks on her own, learned timing), humour that learns, reflection (profile + facts + questions),
  corrections, a self-training app predictor
- **Memory:** chat history; semantic facts with dated plans + follow-ups, updates that replace, strength/fading;
  conversation summaries ("episodes"); notes, diary, reading list
- **Automation:** apps/windows/volume/brightness/clipboard/typing/power, routines, modes (auto-end when left on),
  sessions, logins, WhatsApp, watches and done alerts, downloads filing
- **Activity awareness:** local activity log, projects + resume, git, habits, predictions, journal + weekly summary
- **College:** timetable, class warnings/links, attendance, marks, deadlines, study time, syllabus, revision packs
- **Music:** Spotify Web API control + wrapped; media controls for any player

Tests: see the newest `docs/CHANGELOG.md` entry (`venv\Scripts\python.exe -m pytest tests`).

**Computer agent (first version, 2026-10-11):** `services/computer/` separates typed model proposals,
Windows capture/input, and the supervised session loop. Command bar: `\c <task>`, `\c yes`, `\c no`,
`\c stop`, `\c status`. Every input is reviewed, consumed once, then checked with a fresh screenshot.
20 steps maximum; approvals expire after 120 seconds. Window/control focus and visible screen changes
are checked before input; changed views require another proposal and approval. Frames/task text stay in
temporary service context, outside chat history, semantic learning and TTS. The popup restores focus before
requests and shows proposals without activating. Telegram is refused via `intent.remote_request`.
No autonomous mode or voice entry yet. A user trial with the configured vision model is still needed.

**Computer-agent repair (2026-10-14):** vision calls had exhausted an overloaded primary and
unavailable/text-only chat backups. `OpenRouterProvider.complete()` now selects a separate optional
`OPENROUTER_VISION_BACKUP_MODELS` list for image requests (blank = no extra OpenRouter models).
Local `.env` uses the live-tested free `dots-studio/dots-3-note-preview:free` primary and free vision
backups. Error replies/logs distinguish planning/screen checks, input and post-input verification;
failed sessions are cleared and cannot replay an approval. Computer results stay for the existing
90-second popup lifetime. A live synthetic image/action/result loop passed with simulated input;
restart from the tray and retry the real task. No real user desktop input was verified in that probe.

**Telegram awareness and delivery (2026-10-12):** `core.config.SYSTEM_PROMPT` includes safe configuration
facts from `services/telegram/capabilities.py`; no credentials/recipient IDs enter the prompt.
`commands.py` runs explicit chat/voice file sends and on-demand summaries before AI/search contexts.
"That file" uses a current selected/single search hit, otherwise asks which; names/absolute paths and
numbered hits are supported. `summaries.py` runs from proactive ticks outside busy guards: daily 07:00,
nightly 21:00, Sunday 21:00, laptop local time while running. Config: `TELEGRAM_BRIEFING_HOUR`,
`TELEGRAM_NIGHTLY_HOUR`, `TELEGRAM_WEEKLY_HOUR`, `TELEGRAM_WEEKLY_DAY` (Monday=0).
Successful period markers live in `memory/telegram_summaries.json`; failures retry in five minutes.
Tests isolate state, file selection and all sends. Real getMe/getChat checks succeeded without outbound
test messages. Restart from the tray to load changes. Telegram summaries use local report builders, no AI.
Answer forwarding: "send me the answer in telegram" (answer/reply/response aliases) reads the latest saved
assistant message using `MemoryService.get_last_assistant_message()` and sends it unchanged with `send_long()`.
No AI regeneration/search is involved. Chat skips saving this delivery exchange so repeated sends don't forward
the confirmation; voice already leaves system confirmations out of history. Unsaved ephemeral computer context
remains unavailable. `tests/test_telegram_answers.py` covers both interfaces, exact text, retries and errors.

**Shared cognition (2026-10-12):** `services/mind/cognition.py` owns a bounded SQLite event record at
`memory/mind/cognition.db`, shared across the API and tray processes. Async turn decorators use ContextVars
to correlate request/reply and thread-offloaded action/delivery events; failures/cancellation close operations.
`cognition_context.py` combines recent events with live activity category, mood, pending-question state and
active operations in `config.SYSTEM_PROMPT`. Each kind's latest event is retained in the bounded prompt so
multipart sends cannot crowd out the last reply/action. Only explicitly public text enters AI context.
`brain.awareness()` reads this same record. Activity category changes, proactive questions/reactions, chat/voice
replies, `_execute` actions, Windows notification submissions, Telegram message/file sends and TTS lifecycle
are connected. Exact notifications stay in the local event store; clipboard/typing command replies use their
safe `memory_message`, speech payloads and computer task context are not recorded. Known configured credentials
are redacted. `cognition_commands.py` provides local factual recall with safe chat-memory placeholders and
refuses local-only contents over Telegram. Introspection does not consume a pending proactive answer or replace
the recalled reply. Chat-history clearing wipes this store too. New settings: `COGNITION_ENABLED`,
`COGNITION_MAX_EVENTS`, `COGNITION_EVENT_CHARS`, `COGNITION_PROMPT_CHARS`; tests redirect the store to tmp.
This is event awareness/working memory, not biological consciousness or an unrestricted autonomous agent.

**Manual training (2026-10-12):** `train_friday.py` (interactive without arguments; `--help` for commands)
and `train_friday.bat` run beside the app. `services/mind/reviews.py` owns `memory/training/reviews.db`:
immutable captured question/context plus live answer/reaction/delivery evidence and manual review state.
`talk._record` adds review IDs to live pending questions; `hear`/expiry copies evidence without changing
existing learning. The proactive watcher uses `training.show_toast`, recording nudges around normal delivery.
`training.py` supplies bounded approved+trained text to `SYSTEM_PROMPT`, and reversible targeted overlays
through `thoughts.reason_for` and `knowledge._thing`. No cross-process cache, no extra network call.
Approval alone never trains. Reject/withdraw removes manual overlays; existing automatic learning remains.
Dataset export is opted in per reviewed item, excludes raw context/notes/unreviewed answers, frames captured
questions correctly, and never overwrites files. This is local memory learning plus JSONL export, not weight
fine-tuning. Latest 20 lessons fit a 3,500-character prompt; targeted knowledge reads all applied records.
Tests redirect the shared store before any hooks run. Restart the app once for collection, then lessons apply
without another restart. No new UI/dependency; logging records metadata only.

### Known issues right now

- **OpenRouter is failing** (free models rate-limited / "insufficient credits"; two backup models were removed
  because they're no longer free). Chat, free will and reflection currently run on the local Ollama model
  (`qwen2.5:3b`), which is weaker — e.g. memory-update decisions are skipped on it. The Boss needs to check
  openrouter.ai/activity.
- Conversation mode can't be interrupted by just talking over her (hotkey only) — offered as a follow-up.
- `graphify update .` segfaults on this machine; the knowledge graph in `graphify-out/` may be stale.

---

## Architecture Summary

```
launch_friday.vbs
 ├── main.py  →  FastAPI backend on 127.0.0.1:8000 (interfaces/api)
 │               background: reminders, clipboard watcher, activity tracker, proactive watcher (1/min:
 │               briefing, nudges, sessions, modes left on, free will, reflection, episodes, nightly jobs),
 │               network watcher, Telegram bot, done alerts, STT preload, TTS prewarm
 └── python -m interfaces.tray.app  →  tray icon + Win32 command bar + global hotkeys + the body window
                                        (HTTP client of the backend: interfaces/tray/backend.py)

Request pipeline (chat and voice share it):
  message ─► conversation start/end? (voice) ─► screen question / file / web context?
          └► services/automation/intent.py try_system_action()
               corrections → pending yes/no → shortcuts → reminders → routines/modes → … → word-list matchers
               → meaning-based command cache → AI tool calling (cheap model)
               ─► matched: services/automation/actions.py runs it → ActionResult
               └► no match: providers/failover.complete_with_failover() → reply (+ recalled memories in the prompt)
```

More detail: `docs/architecture.md` (partly older than this file — trust the code and the changelog first).

---

## Non-Negotiable Rules

1. **Never tightly couple providers.** Always go through `providers/registry.py` or `providers/failover.py`.
2. **Never put UI logic in the backend.** Interfaces are HTTP clients of the API.
3. **Never hardcode or print API keys.** Use `config` from `core/config.py`. `.env` holds real secrets.
4. **The API is local-only.** Keep `TrustedHostMiddleware` and the Origin check. Don't add CORS.
5. **Destructive actions ask first** (organise, delete installers, shutdown, WhatsApp, kill port).
6. **Private content is never saved to chat memory or sent to an AI:** clipboard, passwords, notes/diary (reflection),
   typed text, WhatsApp messages, window titles/sites/files (only totals). "Hey Friday" never logs what it hears.
7. **Always update the docs** after every meaningful change (CHANGELOG + FEATURES.md at least).
8. **Always add comments** explaining the non-obvious.
9. **Tests never touch real data:** `tests/conftest.py` redirects every state file/DB to tmp — add new ones there.

---

## Architectural Decisions

Full rationale is in `docs/decisions.md` and the changelog.

| Decision | Choice |
|---|---|
| Provider abstraction | Abstract base class, lazy imports in the registry, failover chain, local model for quick chats |
| Memory | SQLite (`memory/friday.db`): history, `memories` (facts + episodes, bge-small vectors), activity |
| API | FastAPI, local-only (TrustedHost + Origin check, no CORS) |
| Main interface | System tray + Win32 command bar + desktop body (web/desktop UIs removed) |
| Speech-to-text | **Parakeet TDT 0.6B v2** int8 ONNX via `onnx-asr` (CPU); faster-whisper `small` as fallback; Silero VAD |
| Text-to-speech | edge-tts (en-US-AriaNeural) streamed via PyAV + PyAudio; Piper offline; pyttsx3 last resort |
| Learning | Thompson sampling (talk, humour), counting (habits, predictor), nightly logistic regression, reflection |
| Reliability | Provider failover; online/offline switching; cheap model for intent classification |

---

## Folder Structure

```
FRIDAY/
├── core/            → config.py, errors.py, logger.py
├── providers/       → base_provider, registry, failover, openrouter/ anthropic/ openai/ ollama/
├── services/
│   ├── activity/    → log, categories, ask, projects, git_status, sessions, habits(+_patterns), predict, insights,
│   │                  study, journal, weekly, limits, devtools, fun
│   ├── automation/  → intent (decides), actions (does), results, command_words, command_cache, command_tools,
│   │                  app_commands, app_finder, device_commands, system_control, system_stats, system_health,
│   │                  keyboard, typing_commands, writer, clipboard(+_history, _transforms), media_control,
│   │                  routines, modes, logins, whatsapp, power, personality
│   ├── files/       → index, extract, embed, search, assistant, filing, installers
│   ├── memory/      → sqlite_memory, semantic, episodes, notes, reading_list
│   ├── mind/        → talk (free will), humour, reflection, wonder, corrections, learner
│   ├── network/     → status (online/offline), campus (Wi-Fi login)
│   ├── proactive/   → watcher (the minute loop), briefing, nudges, buttons, timetable, college, attendance, deadlines
│   ├── reminders/   → parser, service
│   ├── search/      → web_search
│   ├── security/    → intruder (wrong-password photo)
│   ├── spotify/     → auth, player, wrapped
│   ├── telegram/    → bot, client
│   ├── vision/      → screen
│   ├── voice/       → recorder, stt, tts, speech_stream, wake, conversation, voice_commands
│   └── watch/       → auto (downloads, heavy work), asked ("tell me when…"), done (Claude/terminal)
├── interfaces/
│   ├── api/         → app.py, routes/ (chat, voice, system, clipboard, files, spotify, done, mind, body)
│   ├── tray/        → app.py (entry), tray.py, backend.py (HTTP client)
│   ├── popup/       → app.py (command bar + hotkeys), win32.py
│   ├── body/        → window, animator, sprite, sensors, sounds (the desktop robot)
│   ├── cli/         → friday.py (terminal client)
│   └── protocol_handler.py → friday:// notification buttons
├── tests/           → pytest suite (conftest.py isolates all real data)
├── docs/            → all documentation (FEATURES.md = what she can do)
├── memory/          → friday.db + JSON state files (modes, mind/, projects, …)
├── logs/            → friday.log (warnings and errors only)
├── launch_friday.vbs → main launcher (silent; stops the backend when the tray quits)
├── main.py          → backend entry point
├── requirements.txt
└── .env             → secrets (never print or commit)
```

---

## Running + Testing

- Start: `launch_friday.vbs`. Backend only: `venv\Scripts\python.exe main.py`. Restart = Quit from the tray, relaunch.
- Tests: `venv\Scripts\python.exe -m pytest tests`
- The launcher sets `API_RELOAD=false`. Uvicorn's reloader could leave an orphaned server on port 8000 that served stale code.
- Launcher repair (2026-10-14): duplicate starts leave the existing project tray/backend alone. WMI
  returns the owned backend PID; quitting stops only that tree, after rechecking its command line.
  `main.py --no-reload` handles WMI's separate environment. Both launchers derive their folder;
  the batch file delegates to VBS. Native disposable-process regression tests cover duplicate starts,
  ownership on quit, and preserving manual reload settings. The live repeated-launch check passed.
- The backend's console output is discarded and `logs/friday.log` keeps only warnings — to debug live behaviour,
  write a small probe script (e.g. the real mic + `WakeListener` with a printing transcriber) rather than guessing.
- PowerShell calls made from Python prefix `$ProgressPreference='SilentlyContinue'`.

---

## What To Work On Next

Only with the user's approval:
- **Talk over her in conversation mode** (interrupt by speaking, like "Hey Friday" does)
- **Computer agent follow-ups:** try the supervised loop; then consider better targeting, voice entry and unattended tasks.
- **Big ideas for later** (the Boss wants them eventually): day coach, lecture scribe,
  FRIDAY inside Claude Code
- From `docs/roadmap.md`: conversation export/import, bilingual (Hindi) STT, named conversation threads

---

## What NOT To Do

- Keep UI work within the requested surface.
- Don't start an unapproved backlog item
- Don't bring up git cleanup or commits
- Don't re-add CORS or bind the API to anything but localhost
- Don't switch STT back to Whisper as the main engine (Parakeet was chosen after live wake-word failures)
- Don't reintroduce `openai-whisper` or pygame (both replaced)
- Don't add fixed quiet hours or hard-coded "when to talk" rules — let her learn it
- Don't let the small local model make destructive memory decisions (measured unreliable)
- Don't refactor what already works without a reason
