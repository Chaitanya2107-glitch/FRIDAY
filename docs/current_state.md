# current_state.md
# F.R.I.D.A.Y — Current State

*Update this file every session. It's the first thing to read when picking up the project.*

**Last updated:** 2026-10-28

**Personal assistant awareness (2026-10-28):** Friday's mandatory role now
prioritizes the owner's day, schedule, routines, preferences and everyday
assistance. Fresh app/window metadata, explicit task labels and personal app
uses are separate from inferred app categories and unverified model explanations.
Unknown apps go to the model first, using process identity without window titles;
an exact, current owner confirmation promotes the displayed definition/category.
Legacy model definitions are retained as unverified proposals. Task labels are
scoped to the observed window/runtime and stop being current across switches,
idle, stale gaps and restart. No automatic screenshot monitoring is enabled.
See `docs/PERSONAL_ASSISTANT_AWARENESS.md` and the source-bound
`tasks/personal-assistant-verification.json` / activation receipt.
Final checks: 5,752 passed, 13 optional skips; 352 relevant focused cases passed.
Desktop reloaded; the grounded activity API and real command-bar clock reply
both passed. Probe URL/startup-timeout corrections affected only the verification
utility; runtime and test source hashes match the passing full run.

**Telegram upgrades (2026-10-28):** private-chat `/! <command>` skips that
request's confirmations; `/cc <keys>` validates and presses keys in the focused
laptop window. Local brain/executive/notification/reasoning inspections reply to
the authenticated owner in their private chat. Normal confirmations, lockdown,
forwarded-command rejection, remote clipboard/login restrictions and conversation
isolation remain. Daily/nightly/weekly/learning reports use emoji sections and
bullets; long replies are sent in full. A SQLite inbox persists incoming updates
before acknowledging them, catches up offline commands in order and reports
ambiguous interrupted execution instead of replaying it. Telegram retains unseen
updates for up to 24 hours. Usage: `docs/TELEGRAM_UPGRADES.md`; implementation
and acceptance criteria: `docs/specs/2026-10-27-telegram-upgrades.md`.
Verification: 1,069 regression tests passed; exact source hashes, test artifact
and local activation state are recorded in `tasks/telegram-upgrades-verification.json`.
The desktop and managed backend were reloaded successfully; health is ready and
the new Telegram startup marker is present with no new inbox/polling failures.
The subsequent `/h` addition shares a full categorized command guide with
`/help` and `/start`. All 72 focused Telegram checks and 40 concurrent
app-learning regression checks pass, including complete multi-message help
delivery and lockdown access. Its separate source and
activation receipt is `tasks/telegram-help-verification.json`.

**Command bar Sending fix (2026-10-27):** a native poll timer cancelled itself
on its first 100 ms tick while a request was still pending, leaving completed
replies undisplayed. The timer now stays active until the reply is ready.
Two regressions cover delayed replies and multi-update automation. Focused checks:
97 passed, 9 opt-in skips; desktop reloaded and a real native Enter/backend/reply
round trip displayed the clock in 0.906 seconds. Receipt:
`tasks/command-bar-fix-receipt.json`; the earlier full-suite receipt remains
historical evidence for the preceding assistant batch.
The separate greeting API check returned a nonempty response in 20.328 seconds;
logs show OpenRouter failure followed by Ollama startup. Provider failover latency
remains visible even though completed replies now reach the command bar.

**Personal-assistant upgrades (2026-10-26):** owner approved Android phone bridge,
interruptible conversation and Friday DJ as one batch. KDE Connect Windows 26.08.2
is installed; owner paired Android and enabled notification access. Native D-Bus
readiness verifies one paired/reachable phone and its notification interface.
Private local notification selection and confirmed reply submission bind device,
bus/service lifetime and content; notification bodies/drafts bypass AI/history/logs.
Conversation-only capture spans streamed generation/playback, shares microphone
ownership, and fences stop/queued speech with capture epochs and TTS generations.
DJ adds bounded mood mixes, artist-based queue continuation and explicit saved
playlist/search preferences using supported Spotify endpoints. Spotify is connected;
read-only catalog search works; no playback device was active during the probe.
The existing startup path can open Spotify for playback. No live notifications,
replies, ringing, microphone capture or playback were exercised by readiness probes.
Usage/limits: `docs/PERSONAL_ASSISTANT_UPGRADES.md`; final verification/source
receipt: `tasks/assistant-upgrades-verification.json`. Original desktop appearance
is preserved. Conversation echo rejection is lexical, not acoustic cancellation.
Final verification: 5,638 full-suite tests passed, 13 existing opt-in skips,
zero failures/errors, one existing warning; 498 focused checks passed. All 445
source inputs remained unchanged. The desktop and backend were reloaded together
on 2026-10-27. Live API checks passed health, conversation/private-response schema,
private phone status and DJ preference reads; microphone recording was off. No
notification contents, real audio capture, replies, ringing or playback were probed.
The full source receipt preserves the earlier sandbox/runtime-access failures
and speech-test-double updates separately from the successful final run.

**Desktop appearance restored (2026-10-26):** owner rejected the reactive orb.
The original desktop robot and its controls/defaults are restored; orb code,
tests and previews are removed. Keep the existing desktop appearance unless
the owner explicitly requests another visual change.

**Gaming optimization removed (2026-10-24):** owner requested full deletion.
Automatic game detection, process-priority changes, profiles/reports, idle reclamation,
API/browser/native controls and optimizer-specific background/voice restrictions are removed.
Saved optimizer settings and telemetry are deleted. General custom modes and activity awareness
remain independent. See `tasks/optimizer-removal-receipt.json` for source and validation evidence.

Tkinter customization (2026-10-23): four editors are implemented:
contacts, routines, projects and modes. Native searchable lists,
labeled forms, folder browsing, unsaved-draft protection and background HTTP work
use backend-owned validation/atomic configuration writes. Stale edits refuse;
existing command writers share the lock. Edits preserve pending-confirmation
safety and mode lifecycle. Project domain/URL support, cache
and activity recount are integrated. The taskbar's All controls menu and tray
offer Customize FRIDAY; a standalone module also opens it. Five synthetic native
previews and 237 focused checks cover the feature. Full regression/source receipt:
`tasks/customization-verification-summary.json`; usage: `docs/CUSTOMIZATION_UI.md`.
Restart FRIDAY to load the new desktop entry and backend routes.
Verification: final combined editor/service/startup checks: 250 passed / 2
opt-in taskbar GUI skips, with 443 source inputs unchanged during the run. Earlier
focused checks passed 237. Full run: 5,672 passed, 1 concurrent startup-import
failure, 2 skips. The updated launcher checks pass in fresh runs. New editor
Tk tests and all five previews ran; full and current source manifests are kept
separately. See the final receipt for exact bindings and limits.

Current commitment topics (2026-10-22): one unique named saved commitment now
supports short date, countdown and direct previous-date questions across local
chat/voice. Successful saved date answers also select their verified revision.
Existing reference storage binds the exact row, token and forget epoch for 15
minutes; unrelated turns, cancellation, source changes and forgetting retire it.
No models/search, date edits, new table/dependency or action permission. Telegram
is isolated. Optional context failures preserve existing mandatory routes and
return unavailable for recognized pronouns. Request-order fencing prevents older
save/query/cleanup work from replacing a newer topic. Fifty-six new cases and all 15
isolated real-route probe turns passed. Final regression and source bindings:
`tasks/topics-verification-summary.json`; usage:
`docs/COMMITMENT_TOPIC_FOLLOWUPS.md`. Arbitrary topic inference and the prior cold
first-generation timeout remain unresolved. Restart from the tray to load code.
Final verification: 5,614 full-suite tests passed in 362.12 seconds; 215 focused
tests passed in 30.32 seconds. Zero failures/errors/skips, one existing warning;
the 399-input source snapshot and final probe match the current code.

First-call reliability follow-up (2026-10-22): verified ordinary-chat date answers
use smaller generation/critique inputs while retaining complete source evidence,
independent checks and guarded saves. Extra reviewed evidence keeps the general
context. Readiness exposes server/lookup/load wall timings and treats missing
context metadata as unknown. No model, settings, inference quotas or lease changes.
Two candidate runs each saved 3/4 first-round dates and all four warm dates, with
all six negative controls passing in both rounds. Final warm median: 2.837 seconds
versus 3.453 baseline (about 18% lower; small sequential synthetic comparison).
The first cold generation still timed out safely; that availability problem
remains unresolved. Fifteen new cases, 280 focused checks and 5,558 full-suite
tests passed; zero failures/errors/skips and one existing warning.
Full regression and exact source/artifact bindings:
`tasks/firstcall-verification-summary.json`; limits:
`tasks/firstcall-review-notes.md`. Restart FRIDAY from the tray to load code.

Ordinary-chat follow-ups (2026-10-22): laptop chat/voice can clarify a reported
postponement, select an offered saved commitment and retain its date answer with
original question, receipt calendar and exact source versions. Local generation,
independent critique and atomic history persistence precede confirmation.
Punctuation-free voice and name-then-date replies work; ambiguity, stale sources,
cancellation and forgetting refuse or fence updates. Foreground review shares
the executive lease/rate limits and respects other requests, gaming, typing and
audio gates. Deferred answers use existing idle review; `follow-up status` reads
the committed receipt. No provider, dependency or action permission changes.
Usage: `docs/ORDINARY_CHAT_FOLLOWUPS.md`; evidence/limits:
`tasks/ordinary-followups-review-notes.md`. Quit FRIDAY and relaunch
`launch_friday.vbs` to load backend and tray code.
Verification: 5,543 full-suite and 327 focused tests passed; zero failures/errors/skips,
one existing deprecation warning. Warm round: ten frozen installed-model controls
passed; first-round generation/budget timeouts safely withheld two date updates.
These runtime limits remain disclosed. Artifacts: `tasks/ordinary-followups-full.xml`,
`ordinary-followups-final-focused.xml`, `ordinary-followups-final-live.json` and
`ordinary-followups-verification-summary.json`.

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

**Previous: behavioral life state.** Shared attention, responsibilities, uncertainty, explicit quiet
preferences and learned timing now guide silent executive review and optional interruption decisions.
Persona mood no longer punishes quiet/absence. Original-context feedback persists with deduplication,
source validation and forget support. Essential/requested notices and actual status/work completion
retain separate review contracts. Local `brain status` and `/api/v1/mind/life` explain behavior.
The real Ollama trial completed a silent blocker review with conversation off and zero question calls;
see `tasks/life-state-live-probe.json`. Spec and next phase: `docs/BRAIN_LIFE_ROADMAP.md`.
Final evidence: **5,045 full-suite tests**, **505 focused checks**, **two final delivery checks** passed,
zero failures/errors/skips; one existing warning. `tasks/life-state-final-*` and
`tasks/life-state-delivery-focused.*`. Eighteen affected Python files parsed. Phase 2 is complete;
resume with phase 3 (verified outcome learning). Quit/relaunch FRIDAY to load this code.

**Latest: temporal situation memory and saved brain/life roadmap.** The existing local executive
can now retain source-linked commitment interpretations, anchored original dates and explicit correction
history. Shared current/past/upcoming/unresolved/closed context reaches reasoning, inquiry, notification
review, local conversation and life feeling reports. Corrections invalidate derived conclusions based
on old source dates. Unknown dates remain unknown; no canonical reminder/class/task changes occur from
this memory path. Roadmap/next phases: `docs/BRAIN_LIFE_ROADMAP.md`; behavior and limits:
`docs/CONNECTED_BRAIN.md`. Changes require quitting/relaunching FRIDAY to load.
Verification: **5,011 full-suite tests**, **232 final focused checks**, zero failures/errors/skips.
Synthetic local Ollama review saved October 21 from “tomorrow” on October 20, then revised to Friday,
October 23, preserving history. No notifications/actions ran. Artifacts: `tasks/temporal-final-*`
and `tasks/temporal-live-probe.json`. Next saved phase: behavioral life state.

**Latest: connected cognitive inquiry.** Live questions no longer come from the fixed evening queue.
Local inquiry chooses one grounded question or silence from dated owner dialogue, current attention,
observations, operational state and upcoming commitments. Paired answers feed local executive reasoning
and notification review; relevant original dialogue enters conversation recall. Event-driven attention
connects request/action/feature-write/outcome boundaries without model inference for UI polls/keystrokes.
Shared anonymous budgets prevent separate proactive question sources from bypassing global spacing.
Local `brain status`/`question status` explain current reasoning and inquiry decisions. Old queued interviews
are retired on startup. See `docs/CONNECTED_BRAIN.md`, the current inquiry spec and `tasks/connected-*`.
The synthetic local Qwen trial generated a useful project question; repeated-topic output was blocked.
This is bounded software cognition; arbitrary autonomous tool planning remains deferred.

**Latest: clear runtime status.** Mode switches lead with the final mode; repeated starts do not
toggle or rerun steps. Named mode questions only read state. The tray menu/tooltip now show selected
mode. Quick actions use actual saved Spotify connection
instead of a fixed Connect label. Typed local `/api/v1/system/status` supplies these states without
network/model calls or credentials; unavailable reads clear stale claims. Saved Spotify was read as connected and left intact.
Quit FRIDAY from tray and run `launch_friday.vbs` again to load both processes.
Spec: `docs/specs/2026-10-20-runtime-status.md`; verification: `tasks/runtime-status-*`.

**Latest: AI language, local background thinking.** Owner reversed the prepared-replies-only restriction.
Default `AI_LANGUAGE_ENABLED=true` adds AI translation of informal/unmatched commands and conversation
in chat/voice/Telegram. Proposals are parsed and executed locally with existing confirmations and
channel checks; malformed/unsupported commands do not gain tool access. Background cognitive and
notification judgement now use Ollama alone, with no cloud fallback. Language uses OpenRouter then
Ollama. A live synthetic trial translated two informal commands and answered conversationally on
installed `qwen2.5:3b-instruct-q5_K_M`. Cloud is enabled but a direct probe confirmed OpenRouter
HTTP 429 `free-models-per-day`; no free-model switch can resolve an exhausted account daily quota.
No live trial actions ran.
Restart FRIDAY from the tray to load this change. See `docs/AI_ASSISTANCE.md` and `tasks/language-*`.

> **The full, current feature list is `docs/FEATURES.md`**; the newest changes are in `docs/CHANGELOG.md`.
> The file-by-file sections below date from 2026-09-21 and don't cover everything built since
> (activity, mind, college, Telegram, body, conversation mode, memory 2.0 …).

---

## Status

**Shared executive cognition (2026-10-20):** owner authorized the next upgrade from the saved assessment.
Immutable bounded situations join source versions, explicit local focus, dated evidence and historical
execution receipts. Project preflight records intention/expected outcome and rechecks source/local claim
before OS input; feedback preserves verified/blocked/cancelled/uncertain distinctions without advancing tasks.
The existing watcher now supports durable, proposal-only `cognitive_review` in assist-only mode. Reviews
have one active lease, 5-minute spacing and four starts/hour across restart/off/on. Report and completion
receipt commit together. Stale sources, switched/cleared reviews and expired workers cannot save results.
Typed/voice controls: `executive status`, `executive review on/off`, `why did you decide that`.
Forget/reset paths clear derived contexts while retaining budgets. General AI chat/tools remain unchanged.
Spec: `docs/specs/2026-10-19-executive-cognition.md`; verification artifacts: `tasks/executive-*.xml`.
Live temporary-folder trial verified five checkpoints, the executive assessment and recorded outcome;
see `tasks/executive-project-live-probe.log`. A synthetic configured-provider probe reached Ollama after
cloud timeouts/rate limits/unavailable free models. Local generated reports failed validation/critique
or the total time budget; zero new owner facts, conclusions or task progress were accepted. Provider
availability/quality remains a live limitation, separate from tested control/recovery behavior. Evidence:
`tasks/executive-live-probe.json` (synthetic responses only). No provider/model or private `.env` was changed.
Final regression: **4,906 passed**, zero failures/errors/skips, one existing warning (270.46 seconds).
Final focused: **172 passed**. Evidence: `tasks/executive-final-verification.log` / `.xml` and
`tasks/executive-final-focused.xml`. Initial midnight-only fixture failures remain preserved separately.

**Verified project execution (2026-10-19):** `start project session for <saved name>` reuses the existing
brief engine then opens/verifies the registered Explorer folder. Separate named durable focus supports
status/resume/cancel. External work uses token/lease claims outside database transactions; interrupted
effects reconcile without replay, and late results cannot revive cancellation. Source changes and
tampered briefs block completion. No model policy/settings, dependencies or source task progress change.
A real temporary-folder Explorer trial completed five checkpoints with observed folder evidence.
Final full suite: **4,861 passed**, zero failures/errors/skips, one existing warning (332.02 seconds).
Focused workflow/command corpus: **550 passed**. Evidence: `tasks/project-execution-final-verification.log`
/ `.xml`, `tasks/project-execution-final-focused.xml`, `tasks/project-execution-live-probe.log`.
Restart from the tray to load commands. Arbitrary tool plans and the older routine keyboard issues
remain separate work; this new workflow never uses deferred keyboard payloads.

**Useful proactive task help (2026-10-18):** saved next steps/blockers can now become suggestions,
ranked by active goal priority and age of the last recorded update. Active tasks need two days of
unchanged records; blocked tasks need one day. Recent progress, paused/finished work and inactive goals
are excluded. Exact evidence enters existing notification review; fresh state/preferences/attention
checks and a durable claim guard delivery. No task step is executed or inferred complete.

Review task / Not now / Stop asking buttons display progress, snooze for 24 hours or stop that task's
follow-ups until resumed. Local short replies (`not now`, `show that task`, `why this followup`) persist
for 15 minutes, expire on unrelated turns and cannot be consumed by Telegram. `show task followups`
shows sources, outcomes and owner switches; `pause/stop/resume task followups [for <task>]` controls
global/named preferences. Limits: four reviews/day, two claimed notifications/day, four hours between
claims, same-task backoff from one to seven days. Existing nudges/free-will and attention guards apply.
Failed/uncertain submissions are retained without replay. No new dependency, UI or model permission.
Restart from the tray. Evidence: `tasks/task-followups-focused.log` / `.xml`,
`tasks/task-followups-verification.log` / `.xml`.
Verification: **4,737 passed**, zero failures/errors/skips, one existing deprecation warning
(270.14 seconds); **1,670 focused checks passed** (44.04 seconds), plus **85 final focused checks**
(6.62 seconds) after correcting date-sensitive test mocks. Production expiry behavior is unchanged.

**Temporary class rescheduling (2026-10-17):** `tomorrow's DBMS class moved from 9 AM to 11 AM`
updates that date's effective class, preserves duration and the weekly template, and retains owner
provenance plus start/end history. Recall/history, subject aliases, ambiguity choices and scoped
chat/voice/Telegram routing are supported. Cancellations remain authoritative; started classes,
recorded attendance, wrong old times and invalid/past/cross-midnight targets block the correction.
Timetable answers, briefing/prompt, next-class selection, warnings, study offers and attendance use
effective times. Changed context blocks in-flight notices; stale attendance buttons cannot record.

Explicit links (`link reminder 1 to tomorrow's DBMS class`) produce previews after a correction.
`review/apply/reject class reminder updates for tomorrow's DBMS` reuses scoped approval, exact reminder
snapshots, transaction/readback/receipt recovery and delivery guards. Pending previews defer delivery;
cancelled linked occurrences suppress it. No automatic reminder shifts or model-policy changes.
Dated records live in `memory/class-sessions.json`; weekly edits never silently rebind old overrides.
Same-date time changes are supported; cross-date moves and general commitment reconciliation remain
future work. Restart from the tray. Evidence: `tasks/class-changes-focused.log` / `.xml` and
`tasks/class-changes-verification.log` / `.xml`.
Verification: **4,688 passed**, zero failures/errors/skips, one existing deprecation warning
(301.92 seconds); **1,704 focused checks passed** (58.10 seconds).

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


**Brief follow-up continuity (2026-10-17):** project sessions now accept note inclusion/exclusion,
project corrections and `refresh that brief` across laptop chat/voice turns. Revisions preserve the note
preference, create a new verified artifact, retain earlier published briefs and cancel superseded unfinished
jobs. Ambiguous project choices pause until a saved name or offered ordinal is supplied. SQLite context
survives restart for 15 minutes; unrelated local turns/history clearing retire short references, while
explicit session status restores durable focus. Token/source-identity checks refuse stale retargeting.
These turns bypass search and proactive-question learning. Telegram cannot access laptop brief context.
No model permissions, arbitrary execution or source-task progress changed. Full verification evidence:
`tasks/brief-followups-verification.log` / `.xml`. Restart from the tray to activate.
Full suite: **4,564 passed**, zero failures/errors/skips, one existing warning (252.57 seconds).
Final wording checks: **82 passed**, with evidence in `tasks/brief-followups-final-focused.log` / `.xml`.

**Project work-session briefs (2026-10-17):** the second local execution workflow is implemented.
`prepare my project work session for friday` captures a registered project's matching task/goal progress,
blockers, bounded file metadata and saved notes, then publishes a verified Markdown brief. Check/resume/cancel
controls keep their own durable focus and cannot operate a handoff accidentally. Restart recovery,
concurrent publication, source changes, file links, ambiguous names and private chat/voice replies are tested.
Project file contents are not read; task progress, project commands and AI policy are unchanged.
Final suite: **4,537 passed**, zero failures/errors/skips, one existing deprecation warning (184.17 seconds).
See `docs/FEATURES.md` for scope/commands and `tasks/project-session-verification.log` / `.xml` for verification.
Restart FRIDAY from the tray to load this pass. The six deferred wiring findings remain deferred.

**Notification brain and reminder recovery (2026-10-16):** owner-approved notification reasoning
now has its own `notification_review` model purpose without changing `AI_ASSIST_ONLY`. Reminders
use current dated facts, authoritative memories/reasoning facts, goals/tasks, activity and outcomes;
validated decisions/evidence are rechecked before transport. Busy/voice, contradictory facts and
unavailable review retain reminders with visible reasons. Desktop/Telegram acknowledgements, leases,
bounded retries, restart recovery and explicit uncertainty prevent false completion or blind replay.
Optional proactive/completion/filing notices use fact/context rechecks and preserve source privacy.
`notification status`, `why did you not send that notification`, `retry failed reminders` and protected
read-only `/api/v1/mind/notifications` expose decisions/outcomes. No general reasoning or tool planning
was enabled. Real synthetic probes confirm the path but also observed free-provider timeout/invalid
output; held reminders remain recoverable. Final suite: **4,510 passed**, no failures/errors/skips,
one existing deprecation warning. Evidence: `tasks/notification-brain-verification.log`
and its XML. Restart from the tray to activate. Audit F3 is fixed; the other six findings remain deferred.

**Laptop/Telegram isolation (2026-10-16):** audit findings F2 and F6 are fixed. Pending action
confirmations and file results/selections/expiry use separate laptop and Telegram scopes; laptop
chat and voice still share them. Telegram shortcuts clear only their own older questions, and ordinary
Telegram traffic preserves laptop computer-agent proposals. Shared memories/goals/tasks and model
policy are unchanged. Regression tests exercise real chat/voice/bot paths with simulated side effects;
full suite: **4,419 passed**, zero failures/errors/skips, one existing deprecation warning.
Evidence is saved in `tasks/channel-isolation-verification.log` and its JUnit XML.
Restart FRIDAY from the tray to load this pass. F3 was subsequently fixed in the notification pass above.

**Persistent execution foundation (2026-10-15):** `docs/assistant-roadmap.md` saves the owner-approved
assistant upgrade direction. `prepare a handoff for my current task` or `prepare a handoff for <task-name>` snapshots a saved task,
collects related saved notes by keyword, publishes a local Markdown handoff and verifies its bytes.
SQLite checkpoints survive restart; `check the latest handoff`, `resume the handoff` and
`cancel the handoff` expose control. Task/goal controls accept names; IDs remain optional. Selected targets
persist across restart in `workspace_focus`, scoped separately for laptop and Telegram. Ambiguous names
require a more specific request; completed or missing focus cannot silently retarget another task.
Conflicting existing output is never overwritten; changed task
versions block stale publication. Diary and general project-file contents are excluded from this first
workflow. Replies/logs contain status metadata, not note contents. Works in local assist-only mode and is
restricted to laptop requests. Source task progress is preserved. General tool-plan execution is deferred.
Generated files live in `memory/handoffs/`; clearing goals/tasks clears tracking records, retaining files.

**Reasoning upgrade (2026-10-14):** ordinary messages and changed goals/facts/reminders can produce
evidence-cited consequences, predictions, questions and proposals, with bounded critique/repair.
Explicit confirmed class windows can affect real timetable/attendance readers; inferred class changes,
task plans and reminder moves require owner approval and verified service outcomes. Current reasoning
feeds replies, brain awareness and notification decisions; fresh proposals can nominate notices.
`reasoning status` and the protected read-only API expose evidence and state. General arbitrary tool
execution is not implemented. Provider/model quality remains material: current free text models were
rate-limited, and the existing local 3B model rejected/mishandled some complex deductions. Valid owner
quotes are retained when conclusions fail their semantic check, with no inferred effects. Restart
FRIDAY from the tray to load this pass; no live owner state was changed by the synthetic probes.

**Ten layer foundations (2026-10-14):** audited perception, attention, memory, goals, reasoning,
executive control, communication, verification and learning against actual modules. Most foundations
already existed. Added persistent owner goals/priorities and task plans/progress/blockers/evidence,
connected to chat/voice context, brain awareness and notification decisions. `brain layers` reports
capabilities and limits; see architecture/FEATURES for the full map and commands. This is a foundation
pass: general fact-to-consequence reasoning and universal verification are deferred. Restart FRIDAY
from the tray to load this pass; existing running processes retain their prior imports until then.

**Dated facts and notification reasoning (2026-10-14):** `services/memory/schedule.py` anchors explicit
class facts to when received, including the October 12 four-day training instruction (October 12–15).
Effective classes govern warnings, attendance, study-mode offers, timetable answers, briefing/prompt
context and class-sensitive side features. Raw attendance/timetable data stays intact; new declarations
persist without AI/embeddings, and corrections/forgetting/expiry change the effective schedule.

`services/mind/notifications.py` gives watcher candidates a bounded, fact-aware model decision in a
batch per tick. Rejected/invalid/unavailable decisions stay silent. Self-started questions need this
decision before becoming pending. Explicit reminders and configured Telegram reports keep their
requested schedules. Cognition links rationale, actual transport outcome and button reaction; only
FRIDAY-originated proactive notices enter public model context. Full suite: 1,776 passed; live synthetic
AI check rejected a class warning during training. Changes are loaded after one scoped restart;
live health and today's/tomorrow's class queries passed. No additional restart is needed.

**Launcher repair (2026-10-14):** repeating a launch used to kill the running backend when the
duplicate tray exited. The launcher now checks for the existing project tray first, owns one
backend PID, and stops only that process tree on quit. Batch and silent starts share this path;
the backend gets an explicit `--no-reload` flag. Real health checks and a repeated launch passed;
FRIDAY is online. The working session does not need another restart for the launcher fix.

**Manual training (2026-10-12):** run `train_friday.bat` or `venv\Scripts\python.exe train_friday.py`
in a separate terminal while FRIDAY stays running. After one tray restart, questions/nudges/context and
live answers collect in `memory/training/reviews.db`. Review → approve → apply local lessons; export only
examples explicitly marked exportable. Manual question/desired answer pairs are supported. Applied facts
reach the shared prompt and targeted app/reason knowledge without changing live pending questions;
reject/withdraw removes the manual overlay. This teaches local memory, not language-model weights.

FRIDAY is a working local assistant. The **system tray** (plus the **Ctrl+Shift+F command bar**, voice, "Hey Friday",
conversation mode, the desktop body, Telegram and the `friday` CLI) is the interface: the web UI and desktop UI were
removed, and a new UI will be designed later.

Speech-to-text is **Parakeet TDT 0.6B v2** (CPU) since 2026-09-30, with faster-whisper as fallback.
Right now OpenRouter is failing (rate limits / credits), so replies come from the local Ollama model.

Computer agent: first supervised desktop loop implemented in `services/computer/`. In the command bar,
`\c <task>` proposes an action, `\c yes` executes it and checks a new screenshot, `\c no` / `\c stop`
cancels, and `\c status` repeats the pending proposal. Every input needs approval; approvals expire after
120 seconds and tasks stop after 20 input steps. It uses the existing vision provider, keeps context only
in memory, and rejects Telegram requests. Local Windows capture was verified; live model-driven input
still needs a user trial after restarting FRIDAY.

**Computer-agent repair (2026-10-14):** a reported approval failure coincided with vision-provider
failures in the logs. Image requests no longer use ordinary OpenRouter chat backups; configure
`OPENROUTER_VISION_BACKUP_MODELS` separately (blank = no extra models). The local vision model is now
`dots-studio/dots-3-note-preview:free`, verified through a synthetic proposal/approval/result loop
with simulated input. Errors state whether input ran or failed, and remain visible for 90 seconds.
Restart from the tray and retry the real desktop task; actual app interaction still needs that trial.

**Telegram capability (2026-10-12):** FRIDAY's shared system prompt knows the configured bot.
Chat/voice requests such as "send me that file through telgram bot" resolve a recent selected/single
file or an explicit name/path and deliver it to the configured private recipient. Ambiguous results
ask which file. "telegram status" performs a live bot check. Summaries run daily at 07:00, nightly
at 21:00, and Sunday at 21:00, in laptop local time while running, with persistent successful-delivery
markers and five-minute failure retries. Real bot identity and private recipient reachability were verified.
"Send me the answer in telegram" also forwards the latest saved chat/voice reply verbatim, with links and
long-text splitting. Delivery confirmations stay outside history so repeated requests keep the original answer.

Tests: see the latest `docs/CHANGELOG.md` entry for the current validated count.

**Shared cognition (2026-10-12):** `memory/mind/cognition.db` brings replies, notifications, actions,
Telegram sends, speech lifecycle, activity categories and proactive questions/reactions into one factual
event record. The brain and shared prompt use the same recent events/live state. Private notification
contents remain local, and direct recall bypasses AI. Try "what did you just say", "what notification
did you send", "what did you ask me", or "cognition status". Delivery/confirmation/cancellation states
are distinct. Configurable retention/context limits keep it bounded; clearing chat history clears it too.

---

## How To Run

| What | How |
|---|---|
| Start FRIDAY | Double-click `launch_friday.vbs`. It starts the backend and the tray silently; quitting from the tray stops the backend |
| Command bar | **Ctrl+Shift+F**: type anything (chat, command, `\s` search) |
| Hey Friday | **Ctrl+Alt+H** (or tray → Talk to FRIDAY → Listen for "Hey Friday") switches it on; the dot turns blue. Then "Hey Friday, work mode" / "Hey Friday, what's the weather", or just "Hey Friday" and wait for the beep. Ctrl+Alt+H again switches it off; it also switches itself off after 30 minutes without a wake. While it's on, "Hey Friday, …" over FRIDAY interrupts it; "Hey Friday, stop" just silences it |
| Voice | **Ctrl+Alt+Space** starts listening. Press it again to stop, or just stop talking (1.5 s of silence). Pressing it while FRIDAY is speaking cuts it off |
| Screen questions | "what's on my screen?", "explain the error on my screen", "read my screen", or `\v <question>` (command bar or voice). Uses the monitor the mouse is on |
| Typing | "type see you at 5" (exact words), "write an email asking for Friday off" (the AI writes it), "press ctrl+s", "select all", "type hi and send it". Goes into the app you were using |
| Your files | Find: "find my resume", "where did I save the hackathon ppt", "which file mentions sensors", "find my receipt pdf", `\f <words>`; then "open 1" / "open it" / "show 1 in folder". Answer: "what does my invoice say about the total?", "according to my notes, …", "ask my files …", `\d <question>`. Tray → File search shows index status and "Re-scan my files now" |
| Spotify | One-time: set `SPOTIFY_CLIENT_ID` (see `.env.example`), then "connect Spotify". Then "play believer", "play my gym playlist", "shuffle my liked songs", "play the album divide", "shuffle on", "repeat this song", "add kesariya to the queue", "like this song" |
| Routines | "create a routine called work mode to open vs code, play my focus playlist and set volume to 30", then "start work mode" (or just "work mode"). "list my routines", "delete routine work mode". Edit `memory/routines.json` by hand to fix steps |
| Briefing and nudges | Automatic: first time at the laptop each day after 6am (weather needs `WEATHER_CITY` in `.env`). "brief me" any time. Nudges are notifications (low battery, hot GPU / full memory, hours in one app, low disk); "pause nudges for an hour", "turn off nudges", "turn on nudges". No fixed quiet hours: FRIDAY's own talking and habit suggestions learn late nights from your reactions |
| Sessions + weekly | Automatic: after 10 min of work/study/gaming/chill with no mode on, a notification offers that mode ([Yes] [No]). A 20+ min session gets a summary notification when it ends. Sundays at `JOURNAL_HOUR` the weekly summary is written to `Documents\FRIDAY Journal`; "how was my week", "open last week's summary" |
| System stats | "how's my system?", "battery", "cpu usage", "how hot is my gpu", "what's using my ram", "why is my laptop so slow" |
| Tray menu | Status, command bar, Talk to FRIDAY, Quick actions (incl. "What's on my screen?"), System stats (live numbers), Clipboard history, AI provider, Clear chat memory, Quit |
| Backend only | `venv\Scripts\python.exe main.py`; API docs at `http://127.0.0.1:8000/docs` |

Setup: copy `.env.example` to `.env`, add an API key (OpenRouter recommended), then run
`pip install -r requirements.txt` inside `venv`. The GPU needs the CUDA build of torch.

---

## What Exists

### Core + providers
- [x] `core/config.py`: `.env` settings and validation. Includes intent and vision model routing, `FALLBACK_PROVIDERS`, voice settings and `API_RELOAD`
- [x] `providers/`: OpenRouter, Anthropic, OpenAI and Ollama behind `BaseProvider`. `get_provider(name, model=None)`
- [x] `providers/failover.py`: chat and voice retry on fallback providers when the chosen one fails (optional model per provider)
- [x] Image input: `Message.images` (JPEG bytes) is sent by all four providers
- [x] Native tool calling: `complete(..., tools=[Tool])` returns `ProviderResponse.tool_calls` on all four providers

### API (`interfaces/api/`), bound to 127.0.0.1 only
- [x] Typing is decided by the backend but done by the client that owns the user's focus: replies carry `keyboard` steps (`{"text": …}` / `{"keys": …}`). The command bar hides, restores focus to the window that was active before it opened, then types; the tray types voice replies (the hotkey never takes focus)
- [x] `POST /api/v1/chat`: screen question → web search → system command → AI chat. Returns `awaiting_reply` for yes/no questions
- [x] `GET/DELETE /api/v1/history`, `GET/POST /api/v1/memory/facts`, `GET /api/v1/providers`
- [x] `POST /api/v1/voice`: listen → transcribe → same pipeline as chat → reply spoken in the background. AI replies are streamed: the first sentence is spoken while the rest is still coming (`services/voice/speech_stream.py`, `complete_with_failover(on_text=…)`)
- [x] `POST /api/v1/voice/stop`: stops listening and stops speech
- [x] `POST /api/v1/voice/wake` + `/voice/wake/stop`: wait for "Hey Friday" (`services/voice/wake.py`, per switch-on session id), then the same pipeline as `/voice`. 408 after `WAKE_AUTO_OFF_MINUTES`
- [x] `GET/DELETE /api/v1/clipboard/history`
- [x] `POST /api/v1/system`: legacy endpoint with its own parser. It refuses to organise folders
- [x] `/health`
- [x] Security: `TrustedHostMiddleware` (127.0.0.1/localhost), plus a 403 for requests carrying another website's `Origin`. No CORS
- [x] Background tasks at startup: the reminder scheduler, the clipboard watcher, preloading the speech model and prewarming TTS

### Services
- [x] `services/automation/intent.py`: routes a message to a system action. Order:
  1. pending yes/no reply
  2. `\o` shortcut
  3. reminders (also "set a reminder for 5pm to…", "any reminders?")
  4. several commands in one message → validate local steps before execution, run in order and combine replies;
     unfamiliar combinations can use the AI fallback when enabled
  4b. music commands (play, pause, next song, what's playing, play <song>)
  5. device commands, then app commands (all words in `command_words.py`; "hey friday, can you… please" is stripped first)
  6. only if nothing local matched: AI fallback with native tool calling on a cheap model (GPT-4o-mini on OpenRouter/OpenAI, Claude Haiku on Anthropic). Can run several actions from one message; only closes apps the user named
- [x] `services/automation/routines.py`: named routines in `memory/routines.json` (name → list of command sentences, re-read on every use). `intent.py` matches routine commands right after filler is stripped and runs each step back through `try_system_action`; failed steps don't stop the rest, steps that need a yes are skipped, routines can't start routines. Each run is logged as `run_routine`
- [x] `services/automation/command_tools.py`: the system actions described as AI tools
- [x] `services/automation/command_cache.py`: remembers the AI's decision per message (table `command_cache` in friday.db, 30 days, 1000 entries), so a repeated message skips the AI (~3 s → ~5 ms). Stores decisions, never results. Keyed to the tool list and models; cleared with chat memory
- [x] `services/automation/command_words.py`: every command word, phrase and alias (apps, websites, folders, volume/brightness words, filler). Add new wordings here
- [x] `services/automation/device_commands.py`: strict matcher for volume, brightness, mute, close app, screenshot and clipboard commands
- [x] `services/automation/app_commands.py`: matcher for opening apps/folders/websites, Chrome and YouTube searches, organise, and music commands
- [x] `services/automation/keyboard.py`: types text and presses keys with SendInput (Unicode, so any layout). Multi-line or long text is pasted (clipboard + Ctrl+V, clipboard restored) because editors auto-indent typed line breaks
- [x] `services/automation/typing_commands.py`: dictation, "write …" and key presses; `command_words.KEY_PHRASES` holds shortcuts like "select all" → ctrl+a
- [x] `services/automation/writer.py`: the AI writes the text to type (own prompt, output cleaned of preambles/fences/quotes)
- [x] `services/automation/system_stats.py`: CPU, memory, battery, GPU (nvidia-smi), disk and uptime as spoken-style sentences, with warnings (memory ≥ 85%, battery ≤ 20%, GPU ≥ 85°C, < 20 GB free) and the apps using the most memory (Task Manager's private working set, from one Windows call). Matched by `match_stats_command` in `device_commands.py`; runs in a thread (up to ~0.6 s). `GET /api/v1/system/stats` feeds the tray
- [x] `services/automation/media_control.py`: play/pause/next/previous/what's playing for any app in the Windows media overlay (winrt), with the real track name in replies. "play music" resumes the player or opens Spotify and starts it; "play <song>" opens a Spotify search (Spotify can't be told to play a result). Preloads Windows' msvcp140.dll because winrt's older copy breaks torch
- [x] `services/files/`: local file search. `index.py` = SQLite index (`memory/file_index.db`) of every file by name plus text chunks with vectors and FTS5; background scan at startup and every `FILE_SEARCH_RESCAN_MINUTES`, incremental by mtime (first full scan ~4 min for 160k files, rescans ~5 s). `extract.py` = text from text/code/PDF/Word/PowerPoint/Excel; never reads `.env`, keys, "password"/"secret" files or Office `~$` lock files. `embed.py` = local bge-small-en-v1.5 via sentence-transformers on the GPU. `search.py` = names + keywords + meaning merged by reciprocal rank fusion. `assistant.py` = find/open/reveal replies and the answer context (like web search: excerpts go into the system prompt). Commands in `command_words.FILE_*`
- [x] `services/spotify/`: Spotify Web API (Premium). `auth.py` = PKCE login ("connect Spotify" → browser → `GET /api/v1/spotify/callback`), tokens in `memory/spotify_token.json`, auto-refresh. `player.py` = play song/artist/album/playlist/liked songs, shuffle, repeat, queue, like. Opens the desktop app if no device is running. Commands in `command_words.SPOTIFY_*` / `PLAY_*` / `QUEUE_SONG`; without a login, collection requests fall back to a Spotify search
- [x] `services/automation/system_control.py`: open app/folder/URL, Chrome search, organise folder (asks first), close app (graceful), volume (pycaw), brightness (WMI), clipboard, screenshots
- [x] `services/automation/clipboard.py` + `clipboard_history.py`: last 20 text copies, in memory only. Items apps mark private are skipped
- [x] `services/proactive/`: `briefing.py` builds the briefing (weather via Open-Meteo, reminders, system, yesterday's activity), `nudges.py` decides nudges from one system reading a minute (once per episode), `watcher.py` runs the minute loop from app.py's lifespan, quiet hours and the commands; state in `memory/proactive.json`
- [x] `services/reminders/`: natural-language reminders stored in SQLite. Delivered as a Windows notification and spoken aloud; missed ones arrive late
- [x] `services/search/web_search.py`: DuckDuckGo (ddgs) results added to the prompt
- [x] `services/vision/screen.py`: on-demand screen questions. Captures the monitor under the mouse (downscaled JPEG, never saved), sends it with the question and recent history to a vision model (`VISION_PROVIDER`/`VISION_MODEL`; default GPT-4o-mini on OpenRouter/OpenAI, Claude Haiku on Anthropic, `OLLAMA_MODEL` on Ollama)
- [x] `services/memory/sqlite_memory.py`: conversation history plus user facts
- [x] `services/voice/recorder.py`: PyAudio microphone input with Silero VAD auto-stop and beeps
- [x] `services/voice/stt.py`: faster-whisper `small`. It runs on CUDA float16 and falls back to CPU int8. The model preloads at startup
- [x] `services/voice/tts.py`:
  - edge-tts streaming, decoded with PyAV and played through PyAudio
  - can be interrupted, with a cache for short confirmations, also saved to `memory/tts_cache/` so it survives restarts (cleared with chat memory)
  - Hindi voice for Devanagari text
  - pyttsx3 offline fallback

### Interfaces
- [x] `interfaces/tray/`: pystray tray (`tray.py`), HTTP client (`backend.py`) and entry point (`app.py`, single instance via a named mutex)
- [x] `interfaces/popup/app.py`: Win32 command bar and global hotkeys. Runs in the tray process. Hidden from screen captures. Stays open while FRIDAY waits for a yes/no
- [x] `launch_friday.vbs` (main launcher) and `launch_friday.bat`
- [ ] `interfaces/cli/`: empty
- [ ] Web/desktop UI: removed on purpose; to be redesigned later

---

## Known Issues / Gaps

- **Screen questions on Ollama** need `OLLAMA_MODEL` (or `VISION_MODEL`) to be a vision model. Verified live only on OpenRouter (GPT-4o-mini) with a test image.
- **Tool calling** was verified live only on OpenRouter (GPT-4o-mini). On Ollama the model must support tools (the default gemma models don't), otherwise commands the local rules miss are treated as chat.
- The AI fallback only runs for messages starting with a command word (`COMMAND_STARTERS` in `intent.py`), so e.g. "brighten the screen" is still treated as chat.
- **Music:** without a connected Spotify account, "play <song>" only opens a search. "next", "skip" and "back" on their own only count as music commands while a player is open.
- **File search:** answers send the matching excerpts (not whole files) to the AI provider. Images, audio, video and scanned PDFs are only found by name. Tested live on the real folders (find + answers through OpenRouter), but not yet by voice or the command bar. The running FRIDAY must be restarted to pick it up.
- **Spotify** was confirmed working live by the user on 2026-09-21. Needs Premium; dev-mode Spotify apps allow 5 users, whose emails must be added under User Management in the dashboard. Playlist creation and artist top tracks were removed from Spotify's API in Feb 2026.
- `logs/friday.log` only records warnings and errors, so it doesn't show which commands matched.
- **Typing goes to whatever window had focus.** From the command bar that's the window you were in before pressing Ctrl+Shift+F; if that was the desktop, the text goes nowhere. Apps running as administrator ignore it (Windows blocks it).
- Pasted text (multi-line or over 200 characters) can still appear in the clipboard history, even though the clipboard is put back.
- **Not tested live yet:** typing into real apps. Only automated tests and a dry run of the wordings.
- **Speech recognition is English-only** (`language="en"` in `stt.py`). FRIDAY can *speak* Hindi but won't transcribe it yet. Bilingual detection has been offered but not decided.
- The legacy `/api/v1/system` endpoint doesn't know the newer verbs. Chat, voice and the command bar all use `intent.py`.
- **Deferred by the user, don't raise:** git cleanup and commits. `.env`, `memory/friday.db`, logs and `__pycache__` are currently tracked.
- Stray runtime files in the project root (`backend.log`, `backend.pid`, `popup*.log`, `quit.log`) come from older launchers.

---

## Next Up (needs the user's approval before starting)

From the `docs/roadmap.md` backlog:
- **Conversation export/import**
- **Wake word ("Hey Friday")**
- Markdown rendering: blocked until the new UI exists

---

## Last Session Summary

**Date:** 2026-09-21

**Built:** local file search. The user asked for Documents, Desktop, Downloads (+ custom folders in `.env`), every file type, and separate find vs. answer. Every file is indexed by name; text, code, PDF and Office files by content with local GPU embeddings. "find …" lists files (no AI) with "open N" / "show N in folder"; questions about files go to the chat AI with excerpts. Tray "File search" submenu. New dependencies: sentence-transformers, pypdf, python-docx, python-pptx, openpyxl. 37 new tests (36 file search + 1 tray).

**Also built (same day):** full Spotify control through the Web API (user has Premium): real song/artist/album/playlist/liked-songs playback, shuffle, repeat, queue, like/unlike, "connect/disconnect Spotify", tray quick action, AI tools for all of them, 53 new tests. Written against the post-February-2026 API (`/me/library`, search limit ≤ 10, `items` instead of `tracks` on playlists, loopback redirect URI `http://127.0.0.1:8000/...`).

## Session Before That

**Date:** 2026-09-17

**Built:** on-demand screen questions ("what's on my screen?"). Image support in all providers,
vision model routing, capture of the monitor under the mouse, command bar hidden from captures,
tray quick action, 37 new tests.

**Also built:** typing. FRIDAY can dictate exact words, have the AI write something and type it, and press keys.

**Also built:** system stats (chat, voice, tray submenu). Replies aren't cached as speech since the numbers change (`ActionResult.repeatable=False`, also used for music replies).

**Also built:** caching. Measured first: word-list commands take ~0.5 ms and music ~3 ms, so only the AI path (1.3–3 s) and spoken confirmations (~850 ms before audio) were worth caching. "Clear chat memory" also clears both caches. Tests use `tests/conftest.py` to keep the real caches untouched.

**Also built:** real music controls (the chat AI used to pretend to play music and read out *asterisks*). Chat replies now follow `REPLY_RULES` in `core/config.py`: plain text, never claim to have done something. The voice strips markdown before speaking.

**Also built:** much larger local word lists (`command_words.py`) so most commands skip the AI: filler stripping, app/site/folder aliases, more verbs, max/half/"a lot", sound on/off, YouTube search, reminder wordings. Recognized multi-step messages now run locally; unfamiliar combinations can use the AI fallback. The original word-list expansion added 85 tests.

**Also built:** native tool calling for the command AI fallback, replacing the "reply with JSON" prompt. Multi-step commands ("mute and remind me in 10 minutes"), OpenRouter default command model switched from Llama 3.1 8B to GPT-4o-mini, guard against closing apps the user didn't name.

## Previous Session

**Date:** 2026-09-14

**Backlog items built:**
- web search
- more system verbs
- destructive-action confirmation
- reminders
- cheap intent-classifier model
- clipboard history
- provider failover

**Interface:**
- Removed the desktop and web UIs.
- The tray and command bar became the main interface.
- Removed CORS and locked the API to local requests.

**Voice overhaul:**
- faster-whisper on the GPU, replacing openai-whisper, which was uninstalled
- hotkey toggle with silence auto-stop
- streaming TTS with cached confirmations
- fixed distorted audio
- auto-listens for yes/no answers
- the hotkey stops speech
- Hindi voice

**Fixes:**
- stale code from uvicorn's reloader
- the launcher killing unrelated Python processes
- PowerShell progress output reported as errors
- the command bar closing while FRIDAY waited for "yes"
- spoken full folder paths
