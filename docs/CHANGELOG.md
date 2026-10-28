# CHANGELOG.md
# F.R.I.D.A.Y — Changelog

All meaningful changes are logged here. Newest first.

Format: [vX.Y.Z] Date — What changed and why.

---

## [Unreleased] - 2026-10-28 - Personal assistant personality and verified app learning

- Prioritize the owner's day, commitments, routines, preferences, communication
  and continuity in default/custom/serious persona prompts. Coding is on request.
- Ground current-activity answers in fresh foreground evidence and explicit
  owner task labels. Keep general app purpose and personal app use separate
  from today's intent. Timetables do not establish attendance.
- Stage model-first app explanations instead of saving them as facts.
  Display the proposed category, require exact current owner confirmation,
  preserve owner corrections, and quarantine older model definitions without
  removing usage history.
- Bind approvals to offered questions, source revisions, session/channel and
  inquiry epochs; fence delayed requests and exclude approval replies from
  generic personal learning. Preserve uncertainty and shush controls.
- Close task labels across app/title/window changes, idle, stale tracking
  gaps and restarts; integrate owner-label deletion with memory/activity
  controls. Automatic screenshots remain off.
- Usage and verification: `docs/PERSONAL_ASSISTANT_AWARENESS.md`.

## [Unreleased] - 2026-10-28 - Telegram commands and readable reports

- Add `/h` as the full categorized command guide, shared with `/help` and
  `/start`, covering slash shortcuts and ordinary requests. Long help messages
  are delivered in full; help remains available during lockdown.
- Add `/! <command>` to skip confirmations for one private Telegram request,
  including file upload, typing and power actions; keep normal confirmations
  for subsequent messages and retain remote action restrictions.
- Add `/cc <keys>` for immediate validated keyboard presses, including
  hyphenated arrow names, with Windows failure replies.
- Process offline messages through a durable SQLite inbox with ordered delivery,
  persistent cursors, duplicate suppression and interrupted-execution reporting.
  Expire old cursors for Telegram's randomized IDs after inactivity. Queued old
  confirmations cannot approve a fresh prompt.
- Allow authenticated private-chat inspection of local brain, executive,
  notification, reasoning and recorded-event status. Group chats retain private
  data restrictions; local-only mutation controls remain at the laptop.
- Format daily/nightly/weekly/learning reports with emoji headings and bullets;
  retain full long replies across Telegram message boundaries.
- Usage and delivery limits: `docs/TELEGRAM_UPGRADES.md`.

## [Unreleased] - 2026-10-27 - Command bar reply polling

- Keep polling while an HTTP reply is pending; the first 100 ms tick previously
  disabled the timer and left the command bar stuck on Sending.
- Add delayed-response and automation-update regressions. Focused checks: 97
  passed, 9 opt-in skips. Reloaded desktop and verified an actual command-bar
  Enter/backend/display round trip with a clock request.

## [Unreleased] - 2026-10-26 - Phone bridge, interruptible conversation and DJ

- Add local paired Android notification selection, confirmed reply submission,
  ring requests and device selection through KDE Connect; keep private content
  out of chat history, models, transcript logs and speech caches.
- Capture conversation interruptions during streamed reply generation/playback;
  retain the correction and fence cancelled captures and queued speech. Add
  cancellation to the Windows voice fallback on its audio thread.
- Add Spotify mood mixes, artist-based queue continuation and explicit saved
  playlist/search preferences, preserving ordinary song commands and reporting
  partial queue or optional preference-storage failures accurately.
- Preserve the original desktop robot. Usage and limits:
  `docs/PERSONAL_ASSISTANT_UPGRADES.md`.

## [Unreleased] - 2026-10-26 - Restore original desktop robot

- Revert the reactive orb at the owner's request and restore the previous
  desktop robot, interactions, positioning and sound defaults.

## [Unreleased] - 2026-10-24 - Remove gaming optimization

- Remove the optimizer, automatic game detection, process-priority changes,
  profiles/reports, idle cleanup and related commands, API routes and controls.
- Remove optimizer-specific restrictions on voice, local Ollama, file indexing
  and background work. Customization now has four tabs.
- Delete saved optimizer settings, telemetry and dedicated feature artifacts.
  General custom modes and activity awareness remain available.

## [Unreleased] - 2026-10-23 - Tkinter customization window

- Add native editors for contacts, routines, gaming profiles, projects and modes,
  accessible from Customize FRIDAY in the desktop controls or as a standalone module.
- Searchable lists, labeled forms, folder browsing, draft/discard protection,
  background I/O and actionable offline/validation/conflict messages.
- Reuse backend-owned validation with shared command-write locking, atomic saves,
  stale-edit checks and corrupt-file preservation. Gaming reset retains recovery.
- Fence old WhatsApp/project confirmations after settings changes; preserve active
  mode state, project metadata/cache, website attribution and historical recount.
- Five native synthetic previews inspected; 237 focused checks passed. Full
  verification/source receipt: `tasks/customization-verification-summary.json`.
- Full run: 5,672 passed, one startup import failure during concurrent source
  changes, two native-taskbar skips. Fresh updated-source integration recheck:
  61 passed / 2 skips; updated launcher checks pass. Editor Tk checks all ran.
  Final combined editor/service/startup checks: 250 passed / 2 opt-in taskbar
  GUI skips, with 443 source inputs unchanged during verification.
- Guide: `docs/CUSTOMIZATION_UI.md`. No new dependencies, models or action execution
  from configuration forms. Existing taskbar work retained.

## [Unreleased] - 2026-10-22 - Current commitment topics across chat and voice

- Remember one explicitly selected saved commitment for 15 minutes. Answer short
  date/countdown/previous-date questions and explicit named topic switches without
  model/search calls. A verified saved date can establish its new revision.
- Reuse existing reference storage with full row fingerprint, token and forget
  epoch. Follow direct history lineage; retain status and calendar uncertainty.
- Isolate Telegram and action authority; retire or invalidate unrelated, stale,
  cancelled and forgotten context. Optional context errors cannot block required
  date routing or send recognized topic questions to generic chat.
- Fence older local save/query/cleanup work from replacing or clearing a newer
  topic while preserving a valid earlier date save.
- Fifty-six new cases and 15 real-route synthetic turns cover the increment.
  Final regression/source receipt: `tasks/topics-verification-summary.json`;
  examples and limits: `docs/COMMITMENT_TOPIC_FOLLOWUPS.md`.
- Final regression: 5,614 full-suite and 215 focused tests passed with zero
  failures/errors/skips and one existing warning; final source/probe bindings verified.

## [Unreleased] - 2026-10-22 - Smaller date reviews and first-call diagnostics

- Use a focused prompt/context only for verified conversation-date answers and
  their exact targets. Retain full original evidence and independent critique;
  additional reviewed evidence keeps the general reasoning context.
- Record existing server/lookup/load stage times. Missing resident context
  metadata is unknown and cannot establish compatible readiness.
- Preserve model, context, settings, quotas, leases, refusal and save guards.
- Fifteen new cases and 280 focused regression checks passed. Final warm median
  fell from 3.453 to 2.837 seconds in the small frozen comparison. First-round
  saves increased from 2/4 to 3/4, but cold generation STILL timed out safely.
  Cold-start reliability remains unresolved; no general latency claim is made.
- Full regression/source receipt: `tasks/firstcall-verification-summary.json`;
  evidence and limitations: `tasks/firstcall-review-notes.md`.
- Final full regression: 5,558 passed in 341.79 seconds, zero failures/errors/
  skips and one existing warning; source snapshot and final live inputs match.

## [Unreleased] - 2026-10-22 - Ordinary-chat commitment follow-ups

- Clarify ambiguous postponements against offered saved commitments in chat and
  voice. Support named dates, punctuation-free speech and name-then-date replies.
- Retain original question/answer/receipt dates and exact target versions in a
  bounded local ledger; use existing local generation, independent critique,
  calendar validation and guarded temporal history before confirming a save.
- Share executive leases and rate limits; defer for attention or unavailable
  inference. `follow-up status` reads the actual committed revision.
- Fence stale, forgotten, cancelled and replaced answers; isolate Telegram;
  retire optional questions without training unrelated answers. Withhold
  unresolved/intermediate/retired episodes from recall.
- No provider, model, dependency, quota or external-action permission changes.
- Verification and runtime limits: `tasks/ordinary-followups-review-notes.md`.
- Final regression: 5,543 full-suite and 327 focused tests passed, zero failures/
  errors/skips and one existing warning. Warm installed-model controls passed;
  initial inference timeouts safely withheld updates and remain disclosed limits.

## [Unreleased] - 2026-10-21 - Bounded local review reliability

- Separate prompt-free readiness and inference inside existing executive ownership.
- Compact one-work native schema; strict validation and separate source critique.
- Private stage/timing diagnostics in brain status and the existing read API, with
  safe forgetting and honest interrupted/rejected states.
- Recover only an unambiguous omitted calendar phrase from an exact owner quote;
  deduplicate identical temporal items, preserving conflict refusal.
- Preserve settings, models, quotas, permissions and TLS verification for HTTPS.
- Verification: 5,197 full-suite tests and 355 focused checks passed; zero failures/errors/skips, one existing deprecation warning. Full run: 325.34 seconds. Sixteen affected Python files parsed; whitespace clean. Two frozen five-case installed-Ollama probes produced eight useful saves and two safe evidence rejections; both separately proposed unrelated groups were rejected. Useful reviews took 2.50-7.91 seconds; nonresident startup wall time was 5.59/5.63 seconds. No owner facts, commands or notifications were created. Evidence: tasks/reliability-final-verification.*, tasks/reliability-final-focused.*, reliability-final-live-probe-a.json/-b.json, reliability-source-validation.txt and reliability-review-notes.md. These small synthetic controls do not establish general model reliability; continue the saved phase 6 coverage work.
- Limits and continuation: docs/BRAIN_LIFE_ROADMAP.md, phase 6 first increment.

## [Unreleased] - 2026-10-21 - Extractive memory consolidation

- Connect original local experiences inside existing executive generation/critique;
  preserve source wording, paired questions, dates and uncertainty instead of a factual recap.
- Keep bounded threads/source snapshots through episode retention and restart. Retire
  affected summaries on commitment corrections; preserve the latest correction source.
- Recheck sources/corrections atomically; reuse attention, inference budgets and forget fences.
- Share local memory with reasoning, inquiry/notification context and diagnostics; exclude
  private summary conclusions from remote prompts, mirrored offers and public rejection logs.
- Shorten the cognitive review instructions while retaining evidence, date and authority rules;
  use a focused independent critique for a pure memory grouping. Budgets are unchanged.
- Verification: 5,145 full-suite tests and 337 focused checks passed, including 27 memory-specific cases; zero failures/errors/skips and one existing warning. Full run: 291.78 seconds. Ten affected Python files parsed; whitespace clean. Final installed-local-model positive control saved a source-linked thread in 9.55 seconds after an independent critique rejected the first proposal; a validated retry passed. Original uncertainty, paired question and dates survived simulated pruning/restart. Earlier latency, mixed outputs and inconsistent critique judgments remain limits, not a claim of reliable human cognition. Evidence: tasks/consolidation-final-verification.*, tasks/consolidation-final-focused.*, tasks/consolidation-source-validation.txt and tasks/consolidation-memory-positive-control.json.

## [Unreleased] - 2026-10-21 - Purposeful curiosity

- Rank supported blocker/date gaps; require an actual planning choice and distinct
  possible-answer/next-step branches before asking. No gap means no model call.
- Close retained discussed versions and reopen relevant source changes under existing
  quiet, attention, source and interruption budgets. Preserve historical answer context.
- Add gap/purpose fields to existing inquiry jobs; fence forgetting and late callbacks.
  Question answers never mark tasks or actions complete.
- Share conditional question evidence with local reasoning and executive review.
  Explain last-question purpose after silence; keep private diagnostics out of remote
  prompts and mirrored offers. No extra inference loop, provider change or dependency.
- 5,118 full-suite tests and 332 focused checks passed, with zero failures/errors/skips and one existing warning. Full run: 402.29 seconds. Thirteen affected Python files parsed. Evidence: tasks/curiosity-final-verification.* and tasks/curiosity-final-reviewed-focused.*. Scope, live-model limits and phase 5 continuation:
  docs/BRAIN_LIFE_ROADMAP.md.

## [Unreleased] - 2026-10-21 - Verified outcome learning

- Verify shared master-volume/mute writes and saved mode selection before claiming
  success. Separate partial setup/cleanup problems from truthful mode on/off status.
- Persist bounded expected/observed receipts with unknown/failure states, guarded
  completion and forget support. Checks still run when memory is unavailable.
- Feed repeated unverified outcomes into local evidence, life priorities, diagnostics
  and failure explanations. Verified recovery resets the streak; no automatic retry.
- Keep private setting conclusions out of remote replies/mirrored offers; restrict
  task/reminder plan targets to supplied IDs. Preserve independent semantic critique.
- Add read-only local outcome API. Model-abstention limits and future work remain in
  BRAIN_LIFE_ROADMAP.md. 5,084 full-suite tests and 385 focused checks passed, with zero failures/errors/skips and one existing warning; 121 final status/reasoning checks passed after two additional partial-mode readback cases and response clarification. Fourteen affected Python files parsed. Artifacts: tasks/outcome-learning-reviewed-verification.*, tasks/outcome-learning-reviewed-focused.* and tasks/outcome-learning-delivery-focused.*.

## [Unreleased] - 2026-10-20 - Behavioral life state

- Connect attention, responsibilities, temporal uncertainty and quiet preferences to independent silent
  review/optional interruption gates shared by executive cognition, inquiry, notifications and life reports.
- Learn timing from offered autonomous question reactions in their original activity/mode/time context;
  persist bounded, deduplicated receipts with source/forget/concurrency protection. Explicit requests
  remain one scoped reply, without training autonomous welcome or lifting quiet preferences.
- Replace sulking/negative warmth after quiet or silence with respectful restraint. Add local life-state
  API and brain diagnostics; omit local behavioral context from remote conversations/feeling reports.
- Preserve essential/requested notification contracts and classify mode-end notices as actual status
  transitions. Constrain local cognitive schemas to actual evidence/source/check IDs and retain semantic
  critique and guarded persistence. Keep the existing model stack and inference budgets.

## [Unreleased] - 2026-10-20 - Temporal situation memory

- Save the five-phase brain/life roadmap and begin temporal memory using the existing local executive
  report, independent critique, source guards and SQLite transaction; no new worker or dependency.
- Retain dated owner commitments, explicit corrections, uncertainty and revision history. Calendar code
  resolves source date words; old-date source revisions invalidate dependent conclusions.
- Share current situation with reasoning, inquiry, notification review, local conversation and life
  reports. Add local situation/history APIs and brain-status context. Preserve forget/channel controls;
  temporal interpretations do not edit canonical task, class, reminder or deadline services.

## [Unreleased] - 2026-10-20 - Connected cognitive inquiry

- Replace scheduled evening batches and six-second question continuations with one local, evidence-cited
  inquiry decision or silence. Retire stale queues, share durable interruption limits across proactive
  question sources, and enforce source/attention/preferences/duplicate checks with bounded claims.
- Retain dated owner dialogue and paired answers; feed them into local executive reasoning, notification
  review and relevant conversational recall. Preserve channels, original dates and report/inference distinction.
- Wake local executive attention from shared request/action/owner/notification events and generic local
  feature-write lifecycles. Record intentions before synchronous actions and close their outcome state.
- Expose local brain/question status and decision reasons. Add current integration evidence; preserve
  action confirmations and privacy exclusions. Forgetting fences in-flight work without resetting budgets.
- Measure cold local-model latency; require all inquiry output fields and allow a bounded 50-second
  local generation. Synthetic trial generated a project-blocker question and withheld a repeated follow-up.
  No live trial notifications, commands or owner-data changes. See `tasks/connected-inquiry-live-probe.json`.
- Verify **4,976 passed** full regression and **638 passed** final focused checks. Harden immediate local
  question stop controls and preserve disabled-computer-command privacy. See final-named `tasks/connected-*` artifacts.

## [Unreleased] - 2026-10-20 - Clear gaming, mode and Spotify status

- Put final mode first when switching, make repeated starts idempotent, distinguish setup failure
  from an enabled mode, and refresh gaming optimization on manual gaming-mode transitions.
- Answer named mode-status questions locally without changing mode. Report Normal when no mode
  is selected, and unknown for corrupt/unavailable status.
- Add typed local `/system/status` and display current mode in tray menu/tooltip. Distinguish
  selected mode from automatic gaming optimization. Replace fixed Connect Spotify quick action
  with actual saved connection state and connect/disconnect controls. Clear stale state on errors.
- Refresh status on the existing poll and immediately after tray commands. Preserve credentials
  and saved connection; the owner's saved Spotify login was confirmed connected without changing it.
- Verification: **4,939 passed** full regression, **168 passed** focused, one existing dependency warning.
  Evidence: `tasks/runtime-status-verification.*`, `tasks/runtime-status-focused.*`.

## [Unreleased] - 2026-10-20 - AI language with local thinking

- Fix the assist-only routing barrier that dropped unfamiliar commands and returned prepared replies.
  Enable bounded AI translation of informal commands/typos, followed by the existing local parser and
  executor. Keep confirmations, remote restrictions, batch validation and named close-target checks.
- Add shared AI conversation with recent history for chat/voice and Telegram through chat. Keep
  model tools and unscoped planning disabled. `AI_LANGUAGE_ENABLED=false` restores the old policy.
- Keep cognitive and notification judgement on local Ollama, with no cloud fallback. Language uses
  configured OpenRouter/Ollama; model choices, private settings and credentials remain unchanged.
- Live synthetic trial translated two informal commands and produced an Ollama conversation reply.
  The trial executed no actions. Evidence: `tasks/language-live-probe.json`.
- Full suite: **4,924 passed**; final focused **92 passed**. Direct cloud trial confirmed HTTP 429
  `free-models-per-day`; cloud stays enabled with Ollama fallback while its account quota is exhausted.

## [Unreleased] - 2026-10-20 - Shared executive cognition

- Add immutable bounded situation snapshots, source versions, local project pre-action assessments and
  outcome feedback. Preserve selected task/goal focus beyond recency caps. Historical workflow receipts
  distinguish uncertain effects and exclude paths/notes; generating context never completes source tasks.
- Reuse the watcher and strict reasoning/critique for a new proposal-only `cognitive_review` purpose in
  assist-only mode. Durable claims, 5-minute spacing, four starts/hour and backoff span restart/off/on.
- Reject stale/disabled/superseded reports; commit reasoning report and review completion atomically,
  including recovery from interruption immediately after saving. Keep general tool permissions unchanged.
- Add local typed/voice status/on/off/why controls and shared context status. Clear private derived
  snapshots/reviews through forget/history/workspace reset without resetting hourly attempt budgets.
- Spec: `docs/specs/2026-10-19-executive-cognition.md`. Restart from the tray to load.
- Cognitive provider attempts are bounded within the total inference budget; the schema prohibits new
  owner facts. Internal executive bookkeeping is excluded from notification freshness fingerprints.
  Reminder workflow fixtures now use a fixed same-day clock, preserving real midnight/date semantics.
- Final full suite: **4,906 passed**, zero failures/errors/skips, one existing warning (270.46 seconds);
  final focused checks: **172 passed**. Live project checks passed. Configured cognitive-provider trials
  failed safely under cloud limits/local validation or critique; no live model-quality claim is made.
  Evidence: `tasks/executive-final-verification.*`, `tasks/executive-final-focused.xml`,
  `tasks/executive-project-live-probe.log`, `tasks/executive-live-probe.json`.

## [Unreleased] - 2026-10-19 - Verified project execution

- Extend the existing brief engine with a claimed external checkpoint to open and observe a saved
  project's exact Explorer folder. New local named start/status/resume/cancel commands retain progress.
- Keep desktop I/O outside SQLite transactions. Tokens, finite leases, source checks and observation-only
  recovery prevent duplicate submissions and late completion after cancellation.
- Independently verify the folder after launch and recheck brief integrity. Historical completion never
  reopens closed windows. No arbitrary project commands, keyboard input, AI settings or task progress changes.
- Verified using isolated SQLite/files, race/interruption tests, chat/voice integration and a live
  temporary Explorer folder. Restart from tray to load. Evidence: `tasks/project-execution-*.xml`.
  Final full suite: **4,861 passed**, no failures/errors/skips, one existing warning; focused: **550 passed**.
  The requested cognition assessment selects shared executive cognition with versioned evidence next;
  see `docs/2026-10-19-brain-assessment.md`. Autonomous reasoning is proposed, not enabled by this change.

## [Unreleased] - 2026-10-19 - Gaming profile editor

- Added **Gaming profiles** to the tray menu, opening a local browser editor for game profiles.
- Add/remove app limits and keep-normal exceptions, distinguish inherited limits, create custom profiles,
  edit voice/deep-idle settings and save/discard explicitly. Opening the page never creates settings.
- Reuse game/system/launcher validation and atomic settings storage. Preserve other profiles and the
  recovery journal; stale edits return 409, with errors and unsaved drafts kept visible.
- Local static assets, responsive/keyboard controls and restrictive CSP; no new dependency or model use.
  Restart FRIDAY from the tray. Evidence: `tasks/gaming-ui-focused.xml`, full regression report and
  browser flow checks/screenshots under `tasks/gaming-ui-*`.

## [Unreleased] - 2026-10-19 - Automatic game profile creation and selection

- Identified games now receive persistent profiles, with foreground-game preference and Alt-Tab
  continuity. Newly discovered executable names are remembered; Minecraft retains client-specific detection.
- Preserve owner-selected settings. New profiles add no app limits and inherit only existing global
  selections. The owner chooses app limits, voice and idle settings; pressure reports stay informational.
- Added `automatic gaming profiles status/on/off` for new profile creation, leaving saved profiles active.
  Creation is bounded to 100 profiles and uses existing atomic settings persistence.
- Restart from the tray. Verification: focused and full test reports in `tasks/gaming-auto-*.xml`
  and an isolated live detection/persistence probe in `tasks/gaming-auto-live-probe.json`.

## [Unreleased] - 2026-10-19 - Gaming reports, profiles, pressure checks and deep idle

- Added per-game limits/keep lists, voice availability and deeper-idle preferences, with separate
  GoWR/Minecraft aliases and laptop-only setting controls. Defaults preserve voice and unselected apps.
- Record 30-second CPU/RAM session aggregates, backend overhead, applied limits, pressure evidence,
  cleanup and restoration outcomes. Keep 50 sessions, support current/ID/history commands and exclude
  downtime on restart. CPU readings are normalized and missing readings remain unavailable.
- Detect repeated high CPU/RAM readings and suggest eligible competing apps; preserve protected/kept
  apps and owner control. Recent completion summaries can enter existing notification review once after gaming.
- Reclaim idle search models/vector caches/audio safely; voice-off profiles can also release STT/Piper.
  Locks prevent releasing active inference. Models reload on demand. New gaming-time search/Whisper loads
  use CPU; Parakeet uses CPU without eagerly importing torch. Profile voice-off pauses wake processing
  without discarding its owner setting. Cleanup failures do not stop game optimization.
- Isolated Windows GoWR probe released 47.92 MB of synthetic caches, retained enabled voice and checked
  report persistence; no real weights were loaded, no user apps selected and no FPS/GPU gain measured.
  Restart from the tray. Evidence: `tasks/gaming-upgrades-live-probe.json` and focused verification logs/XML.
- Verification: **4,807 passed** in the full suite (405.68 seconds), plus **270 final focused checks
  passed** (23.73 seconds) after avoiding an audio-executor startup for empty cleanup. Zero failures,
  errors or skips; one existing test-client deprecation warning. Evidence:
  `tasks/gaming-upgrades-verification.log` / `.xml`, `tasks/gaming-upgrades-final-focused.log` / `.xml`.

## [Unreleased] - 2026-10-19 - Automatic gaming resource profile

- Added automatic game detection, explicit God of War Ragnarök/Minecraft support, Alt-Tab continuity,
  manual gaming-mode support and local status/enable/disable/register-game commands.
- Defer optional indexing/embedding, startup prewarming, learning refresh and periodic brain/reasoning
  work. Block new local Ollama requests while gaming and stop only FRIDAY-owned idle servers early.
  Commands, on-demand voice and essential reminder scheduling remain available.
- Lower explicitly selected competing apps from Normal to Below Normal CPU priority. Keep the backend
  Normal so games/apps it launches cannot inherit reduced priority.
  Restore original priorities on game exit/shutdown and recover from an atomic local journal on restart.
  Foreground apps, games, protected Windows processes and preexisting non-Normal priorities are excluded.
- Added isolated detection, routing, recovery, corruption, denied-permission and workload-deferral checks.
  Corrected a follow-up button test to use its notification's fixture clock rather than the current date;
  production expiry behavior is unchanged.
  Live isolated Windows probes detected GoWR and verified priority lowering/restoration, including a
  dedicated helper process. Existing user applications were not selected. No gameplay/FPS benchmark
  was performed. Restart from the tray.
- Verification: **4,773 passed** in the full regression run (426.00 seconds), plus **109 final focused
  checks passed** (8.38 seconds) after the final local/remote Ollama and backend-priority adjustments.
  Zero failures/errors/skips; one existing test-client deprecation warning. Evidence:
  `tasks/gaming-verification.log` / `.xml`, `tasks/gaming-final-focused.log` / `.xml`,
  and `tasks/gaming-live-probe.json`.

## [Unreleased] - 2026-10-18 - Goal-aware proactive task help

- FRIDAY can follow up on unchanged active tasks and recorded blockers, ranking active goal priorities
  and leaving recent progress, paused work and finished tasks alone. Suggestions describe saved state;
  they never claim that no real work happened or execute planned steps.
- Exact task/goal evidence enters notification review. Fresh source/preferences/attention checks and
  cross-process delivery claims prevent stale/duplicate suggestions. Existing owner switches and guards apply.
- Added Review task / Not now / Stop asking buttons, local scoped short replies and named/global
  pause/stop/resume controls. Preferences, sources and outcomes persist in the cognition DB. Status and
  explanations show why a task was selected; Telegram cannot consume laptop short replies.
- Review/delivery limits, spaced attempts and increasing same-task gaps reduce repetition. Failed/unknown
  transport never establishes reply context or triggers replay. Workspace reset removes follow-up state;
  conversation clearing preserves preferences. No new UI, dependency or model permission. Restart from the tray.
- Tests cover real SQLite, source changes outside shared context, feedback, concurrency, process restart,
  chat/voice routing and actual watcher integration. Evidence: `tasks/task-followups-focused.log` / `.xml`,
  `tasks/task-followups-verification.log` / `.xml`.
- Corrected date-dependent reasoning test mocks exposed by midnight rollover: report validity follows
  the caller's time and explicit-time approval uses the same fixture time. Production expiry remains unchanged.
- Final full suite: **4,737 passed**, zero failures/errors/skips, one existing warning (270.14 seconds).
  Broad focused checks: **1,670 passed** (44.04 seconds); final focused checks: **85 passed** (6.62 seconds).
  Final focused evidence: `tasks/task-followups-final-focused.log` / `.xml`.

## [Unreleased] - 2026-10-17 - Dated class time changes

- Added `tomorrow's DBMS class moved from 9 AM to 11 AM`, dated recall and correction history.
  Only that occurrence changes; duration, original times, exact quote and weekly template are retained.
  Subject aliases and scoped ambiguity choices resolve repeated sessions without guessing.
- All effective timetable consumers follow the new times. Notification review fingerprints include
  effective classes; attendance buttons reject stale starts/revisions. Cancellation facts retain
  precedence. Started/recorded classes, wrong old times and invalid target times are refused.
- Explicit class reminder links preview shifts and require scoped review/apply/reject. Existing batch
  transaction, delivery-state checks and replay receipts are reused. Pending previews defer delivery;
  cancellation suppresses an explicitly linked occurrence. Cross-class/deadline link ownership is unique.
- Added atomic dated storage using the deadline writer lock, restart/finalization recovery checks,
  concurrency and corruption tests, and chat/voice routing checks. No dependencies or model policy changes.
  Same-date time changes are supported; cross-date moves remain future work. Restart from the tray.
  Evidence: `tasks/class-changes-focused.log` / `.xml`; `tasks/class-changes-verification.log` / `.xml`.
  Full suite: **4,688 passed**, zero failures/errors/skips, one existing warning (301.92 seconds).
  Focused checks: **1,704 passed** (58.10 seconds).

## [Unreleased] ? 2026-10-17 ? Deadline corrections and reviewable reminder shifts

- Deadline changes now update the canonical saved record, retain original/corrected dates and owner
  provenance, preserve the clock when omitted, and reject mismatched old dates or past targets. Recall
  and history commands work locally; ambiguous references accept scoped saved names/ordinals.
- Explicit reminder links preserve their offset to the deadline. Corrections preview shifts; review,
  apply and reject commands keep approval explicit and channel-scoped. Stale proposals, changed/delivered
  reminders, past reminder times and active/uncertain/partial deliveries are refused. Batch updates,
  readback and replay receipts share a SQLite transaction; interrupted JSON finalization is recoverable.
- Pending updates defer matching reminders at notification review/recheck. Current dates feed shared
  workspace/brain prompts and reasoning evidence. Matching task handoffs/project briefs capture current
  deadlines and refuse stale publication; older completed artifacts remain dated snapshots.
- Deadline JSON writes are atomic and serialize across processes. Countdown/removal/college writes use
  the same lock; unreadable data is retained. No model permissions or dependencies changed.
- Tests cover real files/SQLite, another Python process, concurrent corrections, stale choices/proposals,
  corrupt data, publication failure, receipt recovery, delivery state and chat/voice routing.
  Evidence: `tasks/deadline-changes-verification.log` / `.xml`; focused evidence in
  `tasks/deadline-changes-focused.log` / `.xml`. Restart FRIDAY from the tray.
  Full suite: **4,630 passed**, zero failures/errors/skips, one existing warning (221.13 seconds).
  Final focused checks: **84 passed**; see `tasks/deadline-changes-final-focused.log` / `.xml`.

## [Unreleased] ? 2026-10-17 ? File choices and handoff corrections across turns

- File results, selected targets and clarification choices now survive process restart for up to
  15 minutes, independently on laptop and Telegram. `open it` uses the selected/sole file or asks which
  result; replies may use offered names or ordinals. `actually use project-notes.pdf instead` selects
  without opening. Explicit open/reveal commands recheck file metadata and claim the saved snapshot.
- Handoffs accept task corrections and saved ambiguity replies. Revisions publish fresh verified
  artifacts, retain completed outputs and cancel superseded pending/blocked jobs atomically. Changed
  choices, expired references and stale tokens are refused; late finishes do not restore retired context.
- Chat/voice share local context and classify it before search, screen interpretation, question learning
  and multi-command parsing. Unrelated turns and history/workspace resets retire short references;
  Telegram cannot consume laptop handoff choices. Existing result aliases and file forwarding remain.
- Isolated tests exercise real temporary files/SQLite, another Python process, chat/voice, ambiguity,
  expiry, changed tasks/files, replay and blocked-job supersession. Evidence:
  `tasks/conversation-references-verification.log` and matching XML. Restart FRIDAY from the tray.
  Parser corpus: 252 family/action outcomes across 54 families, 504 frozen phrase examples.
  Full suite: **4,588 passed**, zero failures/errors/skips, one existing warning (204.44 seconds).
  Final focused checks: **22 passed**; see `tasks/conversation-references-final-focused.log` / `.xml`.

## [Unreleased] — 2026-10-17 — Follow-up instructions for project briefs

- After a project session, `leave out the notes`, `include the notes again`,
  `actually, use the college project` and `refresh that brief` update the intended workflow without
  repeating its full command. Each revision creates a new verified artifact with fresh source snapshots;
  prior completed briefs remain, and superseded pending/blocked jobs cannot resume old instructions.
- Note inclusion carries across refresh/project changes, and excluded notes are never read. Old saved
  sessions retain their original include-notes default. Ambiguous switches wait for a saved project name
  or offered ordinal; changed project identities and stale concurrent context cannot silently retarget work.
- Added short SQLite context with 15-minute expiry, restart persistence and token checks. Unrelated local
  turns and history/workspace clearing retire short references; explicit status restores durable focus.
  Chat/voice classify follow-ups before search, screen interpretation and pending-question learning.
  Remote messages cannot read or consume the laptop's brief context. Existing note deletion commands
  retain their meaning. No model policy, dependency or source-task progress changed.
- Isolated tests cover revisions, old artifact preservation, blocked-job recovery, cross-process choice
  continuation, stale/expired references, ambiguity, existing commands and chat/voice privacy. Frozen
  command corpus: 251 outcomes across 54 families, 502 phrases. Verification evidence:
  `tasks/brief-followups-verification.log` and matching XML. Restart FRIDAY from the tray.
  Full suite: **4,564 passed**, zero failures/errors/skips, one existing warning (252.57 seconds).
  After the final distinction between initial-request and pending-choice prompts, **82 focused checks passed**;
  saved in `tasks/brief-followups-final-focused.log` / `.xml`.

## [Unreleased] — 2026-10-17 — Verified project work-session briefs

- `prepare my project work session for friday` collects a saved project's matching task/goal progress,
  blockers, file metadata and saved notes into a verified local Markdown brief. Check/resume/cancel commands
  retain their own focus across restarts, independently of task handoffs. Laptop chat and voice are supported.
- Reused checkpoint transactions, cancellation, restart recovery, atomic no-overwrite publication and
  artifact hash verification. Tagged workflows cannot consume each other's executions. Changed registered
  folders, captured file metadata or matching tasks block stale publication; conflicting output stays intact.
- File discovery is metadata-only and bounded (100 files/500 entries/two nested folder levels). Hidden/key
  files, links and common generated/storage folders are excluded; truncation is explicit. Matching is by
  project-name words, not semantic inference. No project commands, source-task completion, model-policy
  change or dependency was introduced. Telegram requests are refused before local source access.
- Isolated tests cover chat/voice, separate-process resume, concurrency, interrupted publication, malformed
  sources, cancellation, tampering, links, bounds, literal names and privacy. Evidence:
  `tasks/project-session-verification.log` and matching XML. Final suite: **4,537 passed**, zero failures,
  errors or skips; one existing deprecation warning in 184.17 seconds. Restart FRIDAY from the tray to load this pass.

## [Unreleased] — 2026-10-16 — Fact-aware notification brain and recoverable reminders

- Explicit reminders now pass a bounded brain review against dated owner facts, memory provenance,
  confirmed reasoning facts, goals/tasks, recent outcomes and current attention/routing. Decisions
  send, defer, withhold or retain for retry; model replies must name the exact reminder and valid evidence.
  Facts/context and the original reminder are rechecked before each destination and optional speech.
- Class cancellation blocks actual attendance reminders without cancelling homework/deadlines.
  Learned guesses and unrelated/stale dated memories cannot cancel explicit reminders. Busy/voice
  context defers reminders without consuming them; model outage or malformed output also retains them.
- Added `notification_review` as an explicitly authorized purpose even with `AI_ASSIST_ONLY=true`.
  General model reasoning/chat/planning remain controlled separately. Provider calls are bounded,
  preserve time for fallback and use structured output where the configured provider supports it.
- Reminder delivery now uses lazy additive SQLite outbox state, just-in-time leases, source-version
  checks and independent desktop/Telegram acknowledgements. Failed transports retry with bounded
  backoff, exhausted failures remain recoverable, and successful destinations do not replay. Interrupted
  or ambiguous timeout submissions require explicit retry; a transport acceptance is not proof of reading.
- Proactive watcher candidates, ordinary work/download completions and filing suggestions use the
  same notification gate, preserving memory provenance and rechecking facts/attention before sending.
  Existing private command previews/filenames stay private in cognition. Requested command feedback,
  security/system outcomes and Claude permission requests retain their direct paths.
- Added local `notification status`, `why did you not send that notification` (or why it was sent),
  `retry failed reminders` and the protected read-only `/api/v1/mind/notifications` endpoint.
  Retry queues a fresh review and never sends immediately or overrides current facts.
- Tests use isolated stores and simulated delivery; live probes use synthetic facts only. The first
  four-scenario probe matched all expected decisions; a repeat exposed provider timeout/invalid output,
  which was retained safely. Model correctness and availability remain practical limits.
  Final verification: **4,510 passed**, zero failures/errors/skips, one existing Starlette/httpx
  deprecation warning in 185.82 seconds. The initial inventory drift failure was corrected by adding
  six frozen examples for the three new cognition commands; the prior report is preserved separately.
  Verification artifacts: `tasks/notification-brain-verification.log` / `.xml` and the synthetic probe
  report. Restart FRIDAY from the tray to load this pass. Audit F3 is resolved; six findings remain deferred.

## [Unreleased] — 2026-10-16 — Laptop and Telegram conversation isolation

- Pending action approvals now belong to the conversation that requested them. A Telegram yes/no,
  unrelated message or cancellation cannot consume the laptop's approval, and vice versa. Typed and
  spoken laptop requests still share confirmations; each approved action is consumed before execution.
- File results, selections and their existing expiry are separate for laptop and Telegram. Interleaved
  searches, opening/revealing results and forwarding "that file" retain their own conversation's target.
- Telegram shortcuts and upload/typing confirmations clear older Telegram command questions without
  touching laptop questions. Their worker threads retain remote restrictions, including failure paths.
- Ordinary Telegram messages no longer cancel a laptop computer-agent proposal. Memories, goals, tasks
  and provider policy remain shared as before. Restart FRIDAY from the tray to load the changes.
- Verification: full suite **4,419 passed**, zero failures/errors/skips, with one existing
  Starlette/httpx deprecation warning in 326.95 seconds. Regression evidence:
  `tasks/channel-isolation-verification.log` and its matching JUnit XML.
  Tests use temporary files/storage and simulated effects; no real messages, power actions or UI input.

## [Unreleased] — 2026-10-15 — Telegram text messages and file follow-ups

- Fixed literal Telegram messages such as 'send me a "hi" through telegram' being treated as files.
  Chat and voice send the supplied text through the existing bot, preserving punctuation, line breaks
  and contractions, without invoking AI or file search. Runtime capability guidance includes messages.
- Explicit file labels now resolve the filename. When FRIDAY asks which file, the next filename,
  result number or send request can continue the Telegram delivery for two minutes; unrelated requests
  end the follow-up, and remote conversations cannot consume a laptop follow-up.
- Added regression coverage for both interfaces and AI modes, file/message separation, missing setup,
  empty text, delivery failures and expired/interrupted file follow-ups. Debug logs record the action kind.

## [Unreleased] — 2026-10-15 — Task names and remembered references

- Task/goal controls and handoffs accept names, current selections and explicitly requested latest matches.
  Numeric IDs remain available. User-facing replies and follow-up instructions use task names.
- Selected targets survive restart, with separate laptop/Telegram focus. Ambiguous names require a more
  specific request without running anything; finished/missing references cannot silently retarget work.
- Names ending in "Friday" remain literal names. Handoff controls work across chat/voice without model calls.
- Verification: full suite **1,951 passed**, with one existing test-client deprecation warning. Reference tests
  cover restart persistence, channel separation, ambiguity, duplicate names, invalid IDs and finished focus.

## [Unreleased] — 2026-10-15 — Assistant roadmap and persistent local handoffs

- Saved the owner-approved assistant upgrade roadmap, capability dependencies and flagship experiences in
  `docs/assistant-roadmap.md`; archived the completed training plan before starting the new implementation plan.
- Added `prepare task handoff <task-id>` with three durable phases: task snapshot, related saved notes,
  and atomic Markdown publication verified by readback. Status, resume and cancel work through chat/voice.
- Interrupted executions resume checkpointed work. Changed tasks block stale output, conflicting files stay
  untouched, completed status rechecks artifact hashes, and generating a handoff does not complete its task.
- The first workflow is local, works with assist-only mode, excludes diary/general file contents and refuses
  Telegram access. General natural-language planning and arbitrary tool execution remain roadmap work.
- Verification: full suite **1,925 passed**, with one existing test-client deprecation warning. Separate-process
  resume, interrupted publication, concurrency, stale tasks, source failures and private reply handling are covered.

## [Unreleased] — 2026-10-15 — Combined clock questions and local command sequences

- "What's the date and time" now returns both from the laptop clock, without a model call.
- Recognized app, device, media, stats and clock steps run locally in order. Shared opening/closing verbs,
  punctuation separators and quoted payloads are handled. Unknown trailing steps cannot silently run
  just the first local command. Confirmation requests pause the batch and preserve the pending action.
- `/system` now uses the same router as chat and voice, including local clock answers and multi-command
  handling in both AI modes. Its confirmation actions remain restricted to chat/voice.

## [Unreleased] — 2026-10-14 — Evidence-cited reasoning, critique and service proposals

- Added a bounded general-language reasoning pass across chat/voice and explicit fact declarations.
  Exact owner quotes remain separate from implications, predictions and questions. Current goals/tasks,
  reminders, original receipt dates, a dated class calendar and public outcomes supply cited evidence.
- Typed reports reject unknown effects, fabricated quotes, stale targets, invalid/reanchored dates and
  uncertain withdrawals. A separate model grounding pass and one repair share a 25-second inference budget.
  Valid owner quotes can survive rejected conclusions without applying their effects. Model checks remain
  fallible; they do not independently prove claims true.
- Real adapters cover dated class availability, task plans and moving reminders. Only explicit confirmed
  class changes may apply automatically; other changes use one-shot owner proposal approval. Stable IDs,
  atomic task-version checks, pending-reminder guards and readback verification prevent replay/stale writes.
  Raw timetable/attendance data is preserved; historical cancellations remain after active expiry.
- Shared reasoning evidence/proposals feed replies, brain awareness and notification decisions. Changed
  facts/objectives/reminders can trigger a background review at most every five minutes. Fresh proposals
  can nominate notices behind normal activity/busy/nudge controls and model send/silence decisions; source
  validity is checked again before delivery. Explicit rejections inform later reasoning.
- Added `reasoning status`, `apply/reject reasoning proposal <id>`, `reconsider my situation` and protected
  read-only `/api/v1/mind/reasoning`. Facts survive restarts/chat clearing; forgetting invalidates their
  dependents and removes duplicate literal owner memories. Monotonic IDs cannot replay after clearing.
- Added optional structured provider completion and native Ollama JSON-schema format/context for reasoning;
  normal reply streaming remains unchanged. `REASONING_ENABLED` controls new passes/nominations.
- Live synthetic probes found free text providers rate-limited/unavailable. The existing local 3B fallback
  later responded, with valid quotes/guidance and inconsistent calendar/effect deductions. Unsupported
  conclusions were refused or retained as facts only. No live owner facts, sends or service changes were
  made by these probes. Arbitrary autonomous tool execution is not implemented. Restart from the tray.
- Final verification: **1,813 tests passed**, including 28 reasoning regressions, with one existing
  Starlette/httpx deprecation warning. Coverage includes non-keyword class wording, generic evidence,
  source/date/correction checks, schema repair/critique, facts-only fallback, stale/one-shot approvals,
  task/reminder readback, historical attendance constraints, nomination/suppression and chat/voice wiring.
  Backend health remained online; the new code still needs a tray restart. No provider/model settings
  or live owner state were changed by the integration probes.

## [Unreleased] — 2026-10-14 — Ten layer foundations and persistent goals/task progress

- Audited the ten requested cognitive layers against actual services. Most already had foundations;
  preserved them and exposed an honest capability/limits inventory through `brain layers` and the
  read-only `/api/v1/mind/layers` route. Architecture docs map each layer to its implementation.
- Added persistent arbitrary owner goals with priorities and explicit task plans, progress, blockers
  and completion evidence. SQLite transactions share the cognition DB; goals/tasks survive event pruning,
  chat clearing and restarts. Explicit controls manage their lifecycle without provider calls.
- Active goal/task summaries enter shared chat/voice cognition context, brain awareness and notification
  decisions. Read-only `/api/v1/mind/workspace` exposes the bounded view. Workspace commands do not consume
  pending proactive questions or trigger file/web search.
- Plans remain inert and permissions stay with existing executors. Completion evidence is an owner report,
  not independent verification; unfinished plans cannot be silently completed or progressed while blocked.
  No arbitrary request/screenshot/computer context is automatically retained. General reasoning and
  cognition upgrades are deferred until after this foundation pass. Restart from the tray to load it.
- Verified: full suite **1,785 passed** (one existing Starlette/httpx deprecation warning). New tests cover
  restart persistence, arbitrary goals, priority ordering, block/resume/step evidence, unfinished-plan
  protections, retention independent of event pruning/chat clearing, credentials, local command routing,
  pending-question preservation, protected read-only APIs and notification reasoning inputs. All 33 module
  references in the ten-layer inventory point to existing files. No live owner goals/tasks were added.

## [Unreleased] — 2026-10-14 — Dated facts govern classes and FRIDAY reasons before notifying

### Fixed
- The October 12 owner-told four-day placement-training/no-classes instruction was stored without
  a date window, while warnings and attendance read the weekly timetable directly. New
  `services/memory/schedule.py` resolves that original receipt date to October 12–15 and constrains
  effective dated classes. Warnings, study-mode offers, attendance questions/counts, class answers,
  briefing/prompt context, journals, class-sensitive humour and download filing use the same result.
  All weekly timetable entries and raw attendance records remain intact; classes resume after expiry.
- Ordinary class cancellation/resumption declarations persist before any provider/embedding request.
  Days/weeks, today/tomorrow, weekdays and ISO dates are supported. Hypothetical/unresolved dates are
  not invented. Explicit resumptions restore classes from their stated date. Operational facts appear
  in memory listings and support forgetting. Cancelled sessions don't lower attendance, and stale
  attendance buttons can't mark them missed. Recall gives owner-told facts and fixed date bounds
  precedence over an AI's newer inference.

### Changed
- `services/mind/notifications.py` reasons over watcher candidates once per tick using dated facts,
  remembered facts, current activity/system observations and recent public notification outcomes.
  A strict model decision approves or suppresses each known candidate; invalid/unavailable answers
  stay silent. Class constraints are checked again before delivery. Timers/observations nominate
  candidates and no longer directly authorize proactive notifications.
- Self-started questions need approval before becoming pending. Explicit "ask me something" requests,
  user-requested reminders and configured Telegram report schedules keep their requested paths.
- Cognition connects decision/rationale, Windows submission/failure and button reaction. Approved
  FRIDAY-originated proactive notices enter shared model context; other private OS notices stay local.
  Brain awareness includes active dated facts. No dependency or UI was added.

### Validation
- **1,776 tests passed**, one existing Starlette/httpx deprecation warning. Regressions reproduced the
  four-day failure, incorrect attendance/buttons, automatic sending despite rejection/model failure,
  and pending questions recorded before approval. Python compilation and source whitespace passed.
- Read-only check of actual saved data: no regular classes October 14–15, Friday classes restored
  October 16, all 22 weekly timetable entries preserved. A bounded live AI probe with synthetic facts
  rejected a contradicting DBMS warning. Tests/probes sent no test notification or private context.
- Activated with one scoped FRIDAY restart. Live health remained online; actual chat requests for
  today's/tomorrow's classes returned "No classes today" / "No classes tomorrow" via the local command
  path, without an AI call or speech. No further restart is needed for this session.

## [Unreleased] — 2026-10-14 — Duplicate launches no longer shut down FRIDAY

### Fixed
- Re-launching the silent launcher while the tray was already running started another backend,
  then the duplicate tray exited and the launcher killed every backend for this project. Real
  logs showed repeated duplicate-tray exits and conflicting Telegram polling. The launcher now
  detects the existing project tray before starting anything and leaves that session running.
- Windows process creation returns the exact backend PID owned by a launch. Quitting that tray
  stops only that backend and its children, with a command-line check before termination to guard
  against PID reuse. Other backend instances and Python programs are left running.
- Both launchers locate the project from their own script folder. The batch launcher delegates
  to the same VBS lifecycle, removing its unrelated-Python PID lookup and reloader-enabled launch.
  `main.py --no-reload` explicitly disables reload for the WMI-created process, which does not
  inherit WScript's process environment; ordinary manual starts retain their configuration.

### Validation
- Windows integration tests reproduced both failures before the fix using disposable backend/tray
  processes. Both pass after the fix; command-line reload tests and tray regressions also pass:
  **56 focused tests passed**.
- Real `/health` and provider checks succeeded. Re-running the fixed launcher against the running
  FRIDAY exited successfully and left `/health` online. No restart of the working session is needed.

## [Unreleased] — 2026-10-14 — Computer-agent vision routing and failure visibility

### Fixed
- The computer task failed against an overloaded vision model, then tried ordinary chat backups that
  were unavailable or couldn't accept images. OpenRouter image requests now use a separate optional
  `OPENROUTER_VISION_BACKUP_MODELS` list; blank means no extra OpenRouter models. Text requests keep
  their existing backups. The local vision setting now uses `dots-studio/dots-3-note-preview:free`,
  verified with a synthetic click task; configured vision backups also use free image-capable models.
- Computer failures distinguish planning/screen checks, Windows input and verification after input.
  A failed follow-up vision call now says the approved step ran, without claiming task completion.
  Failed tasks clear their proposals so approval cannot replay the step. Logs record phase/error type
  and changed-screen rejection, without task text, screenshots or exception payloads.
- Computer results use the existing 90-second popup lifetime instead of disappearing after 2.5 seconds.
  Completed/stopped results show a dismissal hint rather than asking for another approval. OpenRouter
  responses report the actual responding model.

### Validation
- 117 focused computer/API/popup/vision/failover tests passed. Regression tests reproduced the old
  fallback, ambiguous failure messages and disappearing popup before the fixes.
- Live model test: synthetic button screenshot → valid click proposal → simulated approved click →
  fresh synthetic screenshot → completion. No private desktop image or real desktop input was used.
- Full suite: **1,749 passed**, one existing Starlette/httpx deprecation warning. Python compilation
  and whitespace checks on the affected tracked files passed.
- Restart FRIDAY from the tray to load the code and vision settings; retry the real task afterward.

## [Unreleased] — 2026-10-12 — Parallel manual review and local training

### Added
- `train_friday.py` and double-clickable `train_friday.bat` provide a separate manual review terminal:
  list/show/review/add/approve/reject/withdraw/train/export. No backend shutdown, live question consumption,
  provider request or Telegram message is involved. Existing live learning and nudge timing continue.
- `services/mind/reviews.py` keeps questions, proactive notifications, observation/context snapshots,
  thought/pattern/app targets, timestamps, delivery evidence, live answers/reactions and manual reviews in
  `memory/training/reviews.db`. SQLite supports separate app/reviewer processes. Logging uses IDs/statuses;
  unavailable collection storage does not prevent live questions or notification delivery.
- Approval is distinct from applying a lesson. Applied teaching statements/preferred wording enter the
  common chat/voice/proactive prompt (latest 20, at most 3,500 characters); approved app descriptions and
  pattern reasons overlay existing local brain knowledge. Withdrawal/rejection removes the overlay without
  overwriting the original knowledge or live pending state. Previously automatic learning remains separate.
- Explicit per-example dataset consent exports only approved/trained question/output pairs as chat JSONL,
  with review provenance, excluding raw activity context, live answers and review notes. Existing files are
  never overwritten. Manual pairs preserve user/assistant roles; captured FRIDAY questions are framed as
  recall/wording tasks rather than mislabelled as user questions. Known credentials are redacted. No language
  model weights are trained; the dataset is ready for a later separately configured fine-tuning workflow.
- Restart once from the tray for capture hooks. Run `venv\Scripts\python.exe train_friday.py --help` for
  batch commands. No dependency or GUI changes; tests isolate the training DB and all external effects.

### Validation
- Review/store/CLI tests cover approval gates, concurrent connections, secret/private-context exclusion,
  export consent, role correctness, offline operation, preservation of live questions, and reversible lessons.
- Full suite: **1,557 passed**, with one existing Starlette/httpx deprecation warning. CLI `--help` verified.

## [Unreleased] — 2026-10-12 — Shared cognition and factual self-awareness

### Added
- `services/mind/cognition.py` connects chat/voice replies, system-action outcomes, Windows notifications,
  Telegram messages/files, speech lifecycle, activity categories and proactive questions/reactions to one
  local event record. Turn IDs connect a request and its thread-offloaded effects; concurrent requests keep
  separate context. The existing `brain.awareness()` reads the same record rather than only app activity.
- `cognition_context.py` adds permitted recent events and live activity/mood/pending-question/speaking/
  listening/thinking/operation state to the shared system prompt. Latest events per kind prevent multipart
  Telegram chunks from crowding out the last reply/action. Stored text is treated as data, not instructions.
- Direct chat/voice recall: "what did you just say", "what notification did you send", "what did you send
  through telegram", "what action did you just take", "what did you ask me", and "cognition status".
  These read evidence without search/AI, use safe chat-history placeholders, and do not replace the recalled
  reply. Asking what FRIDAY's question was no longer consumes it as an answer or trains her on that query.
- Notifications record exact local text and submitted/failed state, without claiming the Boss read them.
  Telegram records one whole multipart message plus individual chunks and success/failure; file events do
  not retain file contents/paths. Interrupted speech records cancellation and no speech payload. Computer
  proposals stay ephemeral, and private command replies use their existing safe memory messages.
- `memory/mind/cognition.db` survives restarts with configurable limits (500 events, 16,000 characters each,
  3,200 prompt characters by default). Local-only contents stay out of AI context and remote recall; known
  configured credentials are redacted. Clearing chat history clears cognition too. Disk failures degrade
  without preventing a reply; prior-runtime pending rows aren't reported as live tasks. Tests isolate the DB.
- This provides common working memory and event awareness, not biological consciousness. Existing service
  specialisations, provider routing and action confirmations remain. No new dependency/UI was added;
  restart FRIDAY from the tray. Configuration defaults are documented in `.env.example`.

### Validation
- 203 focused cognition/brain/talk/Telegram/voice/reminder tests passed. A full-suite personality regression
  exposed "Boss" in a neutral context header; corrected it, then 68 focused cognition/personality/body/
  forwarding tests passed. Final full suite: **1543 passed**, one existing Starlette/httpx deprecation warning.
  Python compilation and affected source/docs whitespace checks passed. Notifications, speech and Telegram
  transports were mocked; no real outbound delivery, desktop input or private event capture was used in tests.

## [Unreleased] — 2026-10-12 — Forward the exact previous answer to Telegram

### Added
- "Send me the answer in telegram" forwards FRIDAY's latest saved assistant reply exactly as written.
  Answer/reply/response aliases and "in Telegram" are recognised; ordinary filenames still resolve as files.
  Chat and voice share the saved answer. The command bypasses search and AI generation, preserves links,
  code blocks, Unicode and whitespace, and splits long replies without truncation through the existing client.
- Chat leaves this delivery exchange outside history, so success/failure confirmations cannot replace the
  original reply and repeated requests send the same answer. Voice already excludes system confirmations.
  Missing answers, unreadable memory, unconfigured bots and delivery failures return honest errors.
- Shared capability prompts and usage/handoff notes describe the new command. No dependency was added;
  restart FRIDAY from the tray to load it. Tests isolate the chat database as well as all outbound sends.
- Validation: 123 focused Telegram/voice/memory tests passed; full suite: **1519 passed**, one existing
  Starlette/httpx deprecation warning. Python compilation and affected source/docs whitespace checks passed.
  Outbound delivery was mocked; no private answer was sent during testing.

## [Unreleased] — 2026-10-12 — Telegram awareness, file delivery and scheduled summaries

### Added
- FRIDAY's shared system prompt now includes her configured Telegram capability and schedule, without
  exposing credentials or recipient IDs. "telegram status" performs a live bot identity check instead
  of relying on an AI claim. Real getMe/getChat checks verified the bot and configured private recipient.
- Laptop chat and voice support "send me that file through telgram bot", explicit filenames/full paths,
  and numbered recent search results. "That file" uses the current selected/single result; ambiguous
  matches ask which. Uploads go through the existing bot client to the configured recipient, with a
  50 MB limit and success reported only after delivery. File transfers bypass AI file excerpts/web search.
- Telegram reports use the Boss's chosen laptop-local schedule: daily briefing at 07:00, nightly recap
  at 21:00, and weekly recap Sunday at 21:00. They run while FRIDAY runs, including while gaming/at the
  laptop and without college classes. On-demand briefing/daily/weekly summary commands are also supported.
- Reports use existing local builders, split long text without truncation, persist successful periods,
  and retry failed sends after five minutes. A process-local marker prevents repeated sends if saving
  the delivery state fails. No new dependency was added. Restart FRIDAY from the tray to load changes.

### Fixed and validated
- Gave the existing activity day-summary test a fixed midday clock: its two-hour lookback previously
  crossed into yesterday when the suite ran just after midnight. Production activity behaviour is unchanged.
- Full pytest suite: **1504 passed**, one existing Starlette/httpx deprecation warning. Python compilation
  and whitespace checks on affected source/docs passed. Delivery tests use mocks and temporary files;
  live verification made read-only Bot API calls, without sending test messages or user files.

## [Unreleased] — 2026-10-11 — First supervised computer agent

### Added
- `services/computer/`: an on-demand screenshot/action loop with strict typed proposals. The command bar's
  `\c <task>` proposes one action; `\c yes` approves and executes it, then checks a fresh screenshot.
  Supports clicks/double-clicks, scrolling, Unicode typing and key combinations. `\c no` / `\c stop`
  cancels, `\c status` repeats the proposal. Every input needs approval; proposals expire after 120 seconds;
  each task is limited to 20 input actions and model calls time out after 45 seconds.
- Physical-pixel coordinate mapping handles resized screenshots and negative monitor origins. Before input,
  the service checks window/control focus and screen differences (small clock/caret changes are tolerated;
  click targets get a separate local check). Changed views require a fresh proposal and approval.
- Command-bar focus is restored before computer requests; proposals appear without taking focus. Stop
  invalidates in-flight planner results, and concurrent requests cannot consume the same approval twice.
- Computer task context bypasses chat memory, learning, search and speech. Only the latest frame and last
  executed action are sent to the configured vision provider. Telegram computer commands are refused.
  Debug logs contain action kinds and step numbers, not screenshots, task text or typed content.
- Validation: final full pytest suite: **1476 passed**, one existing Starlette/httpx deprecation warning.
  Python compilation and whitespace checks passed. Native Windows
  capture verified at 1568×882 from a 1920×1080 monitor with active window/control detection. Live model-driven
  desktop input still needs a user trial after restarting FRIDAY. No new dependency was added.

## [Unreleased] — 2026-10-11 — Knowledge answers and deadline test fixes

### Fixed
- Answers to FRIDAY's questions about new or unknown apps are now saved even when the app already has a category.
  Previously, knowing that an app was a game prevented her from saving the Boss's explanation of what it was.
- The deadline command test now uses a fixed clock and covers both the current year and next-year rollover, so
  its expected date no longer depends on when the suite runs. Production deadline parsing is unchanged.
- Regression coverage checks that explanations without category keywords preserve the app's existing category.
- Validation: 104 focused tests passed; full suite: 1435 passed, 1 warning (2026-10-11).

## [Unreleased] — 2026-10-01 — A brain of her own

### Added
- **Brain, mind and life** (`services/mind/brain.py`, `knowledge.py`, `thoughts.py`, `life.py`, `wording.py`): FRIDAY
  now thinks locally, with no AI model. `brain.sense()` runs with the activity tracker on every move and files each
  app and topic (cleaned window title) in her knowledge store (`memory/mind/brain.db`); `brain.think()` runs once a
  minute. The day is cut into episodes (past / present / left hanging / next). What doesn't fit becomes a thought —
  new, returned, odd_hour, restless, jump, dropped, skipped, learned, unknown — holding raw facts and her guess; the
  Boss's answer is stored as the reason for that pattern. Unplaced things are looked up with one bare question
  ("What is <name>?") and feed `categories.LEARNED`, so the activity log sorts them from then on. `life.py` keeps a
  mood and a nightly diary (`memory/mind/diary.jsonl`). New commands: "what am I doing", "where did I leave off",
  "what do you know about <thing>", "how are you feeling", "how was your day".

- **Foresight** (`services/mind/foresight.py`): her own counting and the trained model both guess the next app at
  every switch and are scored against what happened (`foresight_tally`); the better recent record wins a
  disagreement. A guess with enough behind it becomes a `prediction` thought the Boss answers yes/no — time habits
  from `services/activity/habits.py` ("around 10:35 PM you'll open Spotify") and non-trivial next-app patterns.
  Measured on the real log first: next-app guesses are almost all "alt-tab back" or File Explorer (one non-trivial
  pattern in 800 switches), so those are never asked about and time habits carry the daily prediction. Confirmed
  predictions are stored (`foresight_patterns`, `foresight_labels`) and weigh 3× in the nightly training
  (`learner.py` now always keeps the latest model as `next_app_shadow.pkl`). After 3 confirmations, a trained model
  and no disagreement from it, an `automate` thought asks once; yes → she opens the app/site herself once a day and
  the habit's "Open it?" notification is muted. "how do your predictions compare", "stop opening <thing>".

- **End-of-day questions** (`services/mind/evening.py`): once a day from `JOURNAL_HOUR`, when the Boss is at the
  laptop and free, she asks up to 8 questions in a row — the day's biggest work and leisure episodes, what happened
  away from the laptop, the day's unsaid thoughts (`thoughts.unsaid_on`), data she can't sense (`DATA_WISHES`), and
  questions from `wonder.py`. The list is built locally; each answer (via `talk.hear`) is kept in
  `memory/mind/evening.jsonl` and triggers the next question after her reply has been spoken. A brush-off or no
  answer ends it. "ask me about my day" starts it on request.

### Changed
- **The model only words what she decided** (`services/mind/talk.py`, `wording.py`): free will no longer hands the
  model app names, minutes and memory and asks it to think of something. `talk.choose()` picks the topic locally
  (a thought, a plan follow-up, a question from her list, a check-in) and `wording.say()` sends only those facts.
  No model, only the small local fallback model, or a line that lost the thing's name → her own plain sentence
  (measured: qwen2.5 3B answered her questions itself and invented names). Each kind of thought is its own learned
  situation (`notice_<kind>`). The old "apps I can't place" question is replaced by the brain's `unknown` thought.
- **Reflection no longer sends activity totals** (`services/mind/reflection.py`): only what the Boss said to her and
  how her jokes landed. "what's on your mind" now starts with her mood and live thoughts.
- Tests no longer send the real chat history to a real model through the reflection path (`tests/conftest.py`).

## [Unreleased] — 2026-09-30 (evening) — Parakeet STT, conversation mode, memory 2.0, modes left on

### Changed
- **Speech-to-text is now Parakeet** (`services/voice/stt.py`, new dependency `onnx-asr`): NVIDIA Parakeet TDT 0.6B v2,
  int8 ONNX on the CPU — the same model family the Boss uses in Handy (Handy's GGUF files can't be loaded from Python).
  ~0.16 s for "Hey Friday" vs ~0.84 s for Whisper small on the GPU; Whisper stays as the fallback if Parakeet can't load.
  Wake phrases gained "k friday" and "hay friday" (how Parakeet sometimes hears a quick "hey").
- **OpenRouter backups:** removed `nex-agi/nex-n2.5-pro:free` and `z-ai/glm-5.2:free` from `.env` (404: no longer free).

### Fixed
- **"She doesn't know my timetable"** (2026-10-01, `services/proactive/timetable.py`, `core/config.py`,
  `command_words.py`): the saved timetable was fine, but only a few exact phrasings reached it — "whats on my
  timetable tom", "What do I have on my timetable tomorrow?", "don't u have my timetable" went to the chat AI, which
  didn't know it existed and said so. Questions about the timetable/classes/lectures now match loosely (tom/tmrw/tmr
  understood), and the chat prompt carries today's and tomorrow's classes. Also: a trailing "friday" was stripped as
  her name, so "classes on friday" / "due friday" lost the day — it's kept after on/by/this/next/due/….
- **"Hey Friday" took no command** (`services/voice/wake.py`): a live mic probe showed the wake listener ended the
  utterance at the breath after "Friday", so the command landed in a separate clip and its start was lost while the mic
  reopened for the beep. A bare wake phrase now keeps the mic open for `COMMAND_WAIT_SECONDS` (2 s) and the next
  utterance is the command; only silence falls back to beep-and-listen.
- **Free will never spoke** (`services/mind/talk.py`): (1) with OpenRouter failing, the local qwen2.5 3B answered in plain
  sentences instead of JSON, and every line was thrown away — a short plain reply is now used as the line;
  (2) a work mode left on since the day before (quiet) blocked her — see "modes left on" below.
- Reflection sometimes saved facts as raw `{'fact': …}` text — dict-wrapped facts are unwrapped.

### Added
- **Conversation mode** (`services/voice/conversation.py`, `interfaces/tray/tray.py`, Ctrl+Alt+C, "let's talk"):
  listen → reply aloud → beep → listen again, no hotkey. Ends with "bye" / "that's all", Ctrl+Alt+C, or two silences
  (`/voice` now returns 422 for "no speech"). Typing in the bar during a conversation is a turn (mic closes, the typed
  reply is spoken, then it listens again), and a key pressed in the last 10 s means you're typing, not silent
  (the body's keyboard hook now records `last_key`). Replies are always spoken in this mode.
- **Speak typed replies aloud** (tray checkbox; `ChatRequest.speak`).
- **Thinking animation** (`interfaces/body/`): a thought trail (small bubble, bigger bubble, cloud) puffs up beside her
  head while she's thinking, and her eyes keep following the cursor (they used to lock up-right).
- **Modes left on** (`modes.DOESNT_FIT`, `left_on`, `watcher._check_mode_left_on`): 15 min on apps that don't fit the
  mode (videos/social/games in work or study mode; coding/documents/study in gaming mode) → one reminder with
  [End mode]; 45 min, or an hour away from the laptop → the mode ends itself (volume restored, apps closed).
- **Memory 2.0** (`services/memory/semantic.py`, new `episodes.py`):
  - free will sees what she knows (strongest facts) and never asks what she already knows;
  - plans with a day keep their date (`happens_on`, learning is told today's date): "coming up" before, a follow-up
    question afterwards (a new "followup" situation, once per plan), "already happened" in replies;
  - a new fact that updates an old one replaces it — decided by the cheap cloud model; answers from the local model are
    ignored (it wrongly deleted a true fact in testing, 5/7 right), and facts from the same message never replace each other;
  - strength: heard again +1, recalled +0.05, told facts start at 2; learned facts unused for 14 days fade ×0.97 nightly
    and are dropped under 0.35;
  - conversations: a chat quiet for 20 min is summed up into an "episode" memory; "what did we talk about yesterday".
- **`docs/FEATURES.md`**: every capability in one place.

---

## [Unreleased] — 2026-09-24 — Semantic memory, activity log, OmniRoute, wider failover, routines, voice streaming, briefing and nudges, Hey Friday, interrupting

### Changed
- **Voice back to en-US-AriaNeural** (2026-09-30): the Irish en-IE-EmilyNeural voice was measured at 4–7 s to first audio (Aria about 1 s). That meant long delays, gaps between sentences (the rest of a reply waited on the slow voice), and "No audio received" failures that switched to the offline voice mid-reply. The persona stays.
- **"open code" answered with the AI's inner reasoning** (2026-09-30): three fixes. (1) `app_finder.py`: after a restart only Everything's service runs, so es.exe couldn't reach it (exit 8) and every app outside the built-in list (VS Code, games) went unfound. FRIDAY now starts Everything in the tray when that happens and searches again, and also warms it up at start. (2) Apps unpacked in Downloads (God of War) are allowed as a last resort; anything outside Downloads still wins, and installers are still skipped. (3) `providers/openrouter/client.py`: when the free thinking model runs out of tokens mid-thought, OpenRouter copies the unfinished reasoning into the answer. That's now detected (cut off, and the answer equals the reasoning or is empty). She retries once with 4000 tokens, and if it still isn't finished, fails over instead of showing it.
- **FRIDAY from the films** (2026-09-30, `personality.py`, `config.py`, .env): the chat persona is now the Iron Man FRIDAY — calls the user "Boss", calm status-report answers with a dry, cheeky sarcastic line, deadpan understatement, still gentle and joke-free on serious topics. Command-reply quips come about 1 in 3 everyday commands (was ~1 in 7) and 1 in 2 at 1–5 AM, with new "Boss" lines. Voice: the Irish en-IE-EmilyNeural (default and .env); offline stays Piper. Also fixed a flaky test: the fake memory embedder used Python's per-run `hash()`, so word collisions sometimes failed a recall (now crc32).
- **Commands typed without apostrophes** (2026-09-30, `command_words.normalize_command`): "hows", "whats", "dont", "cant", "im" … get their apostrophe back before any matcher runs, so "hows my battery health" is the command instead of falling through to the chat AI (which claimed it had no access to diagnostics). Not "its" / "ill" / "wont" — real words.
- **intent.py split** (2026-09-29): the action dispatcher (`_run_action` and its helpers — typing, Spotify playback) moved to `services/automation/actions.py`, and `ActionResult` to `services/automation/results.py` (still importable from intent.py). intent.py decides which action a message is; actions.py does it. 1002 → 753 lines; no behaviour change (1194 tests pass; three tests now patch `actions.*`). Still over 500 lines: intent.py (the matcher chain, AI router, mode/routine flows), command_words.py (563), log.py (533), system_control.py (524).
- Tests no longer write to the real `logs/friday.log` (conftest drops the file handler).

### Added
- **FRIDAY's body** (2026-09-30, `interfaces/body/` sprite / animator / sensors / sounds / window, `services/body_state.py`, `GET /api/v1/body`): a desktop robot for FRIDAY, drawn pixel by pixel after the Boss's reference sprite (round lavender body, antenna, ear pods, teal screen face with sparkle eyes). It has catjang's behaviours, rebuilt, with no catjang code or art: eyes follow the cursor, blinks, glances around; typing taps her feet and heats the screen teal → orange → red; scrolling scrolls text on her screen; shaking the mouse near her → lock-on hunt and hop; stroking her head → heart eyes, hearts, hum; drag → dangle with a swinging antenna, squash on landing; a stretch every 25–40 min; asleep (z z) after 5 idle min, wakes with a boop. Her mind shows on her face: talking → waveform mouth, listening → glowing antenna, thinking (AI calls, or Claude Code between prompt and Stop) → dots, Claude done → double jump, Claude needs permission → "!", a laugh at her joke → hearts, a game in study mode → side-eye. Her questions and reminders appear as speech bubbles. Click to talk, double-click for the command bar, right-click for a menu (free will, sounds, hide, quit), drag to move (position saved in memory/body/state.json). She hides during fullscreen apps. Soft robot chirps are generated as WAVs (switchable). Runs in the tray process on its own thread, DPI-aware so the pixels stay crisp. Typing/scrolling come from low-level hooks that only count (never which key), and injected input isn't counted. 1338 tests pass.
- **Quick commands' notifications disappear; answers stay** (2026-09-30, `reminders/service.py show_toast(transient=)`, tray, command bar): every notification used to be a sticky "reminder" toast. Now a command's short confirmation (a command ran, reply of 120 characters or less, one line: "Opening Chrome.") shows briefly and expires after 8 s, including from the notification centre, and isn't sent to Telegram. AI answers, long or multi-line results, reminders and FRIDAY's own questions still stay until dismissed. The command bar now gets `command` from the chat reply (model `system_control`); voice uses `action`.
- **Quiet hours removed** (2026-09-30): `QUIET_HOURS` and `watcher.is_quiet` are gone. Habit suggestions now show late at night too and learn from Yes / Not now / Stop, like FRIDAY's talking. 1322 tests pass.
- **Late nights are learned, not blocked** (2026-09-30, `talk.py`, `wonder.py`, `watcher.py`): quiet hours no longer silence FRIDAY's own talking. 11 PM–5 AM is its own "late" situation, and whether she talks then (get-to-know-you questions included) is learned from your reactions like every other situation. Hard limits left: busy (fullscreen, games, quiet mode), a call, mid-typing, away, 15 min between questions. Quiet hours still hold nudges and habit suggestions. 1326 tests pass.
- **Rethinking during the day** (2026-09-30, `reflection.reflect_if_due`, `watcher.py`): besides the nightly run, FRIDAY reflects every 3 hours when the Boss has said something new since last time. That updates her profile, facts and questions, so answers from the afternoon already shape the evening's questions. The timer is set before each run, so a failure waits for the next round. 1325 tests pass.
- **Curious from the start** (2026-09-30, `talk.py`): free will is now on by default; the tray checkbox or "stop talking on your own" turns it off. Right after FRIDAY starts, her first chance (at the laptop, not busy, not in quiet hours) goes to a greeting and "what are you up to?", with no dice roll. It's skipped only once "not now" at launch has taught her so (welcome < 0.25). Her answer is kept as the session plan for 8 hours, and later check-ins follow up on it. 1324 tests pass.
- **Getting to know you** (2026-09-30, `services/mind/wonder.py`, `talk.py`, `reflection.py`, `semantic.py`): FRIDAY keeps a list of things she wants to know about the Boss. Each night's reflection adds up to 5 new ones (likes, habits and the reasons behind patterns she noticed, people, plans, opinions), and a get-to-know-you starter set fills in until then. With free will on she asks one in relaxed moments (not while studying, near a deadline or late at night). "Ask me something" or "what do you want to know about me" asks one right away. Asked questions come off the list. Answers to her questions are now learned together with the question, so "pizza" after "favourite food?" is remembered. Before, memory skipped any message without "I/my/me". "What's on your mind" lists what she's wondering about. 1322 tests pass.
- **Free will** (2026-09-30, `services/mind/talk.py`, `interfaces/api/routes/mind.py`, tray + command bar): FRIDAY can start conversations herself. Switch it on with the tray checkbox *Let FRIDAY talk on her own* (Talk to FRIDAY menu) or by saying "you can talk freely". "Stop talking on your own" switches it off, and "quiet for an hour" or "be quiet for 30 minutes" pauses her. She checks on you and asks about what you're doing, and about apps she can't place yet. The AI writes the line from app names, categories and minutes only, never titles. When to talk is learned per situation (just back, a long stretch, an app she's curious about, studying, coding, late night …) by Thompson sampling, roughly every 30–45 min at first. A real answer teaches her it was welcome. "Not now" or "shut up" teaches the opposite and pauses her for an hour. No answer within 3 min counts a little against. Hard limits she can't learn past: busy (fullscreen, games, quiet mode), quiet hours, another app using the mic (a call), mid-typing, away, and 15 min between questions. She speaks, shows a toast, and her question goes into the chat history so your answer makes sense and is learned from. The tray opens the mic right after she finishes, and the command bar shows the question *without taking focus*. Ctrl+Shift+F (or a click) jumps in to type an answer, which closes the mic and drops what it heard (`/voice/stop?discard=true`). "What's on your mind" now includes when she's learned talking is welcome. 1310 tests pass.
- **FRIDAY's mind** (2026-09-30, `services/mind/`): she now learns by herself. **Humour** (`humour.py`): the fixed joke chances are gone. For each situation (studying, deadline, late night, gaming, coding, chilling) she keeps a belief about how welcome jokes are and decides by Thompson sampling. Your next message after a joke teaches her: a laugh counts up, "not now" or "be serious" counts down, silence counts down a little. Old evidence fades nightly, and the chat prompt gets a matching "humour right now" line. **Nightly reflection** (`reflection.py`, at `JOURNAL_HOUR`): the online model reads today's messages (not notes, typing or WhatsApp text) plus activity totals (never titles, sites or files). It rewrites a short profile of you that every chat reply sees, and saves new lasting facts as "learned" for the Sunday review. **Corrections** (`corrections.py`): "no, I meant open spotify" (also "I meant …", "I said …", or a bare "no, …" after a miss) does it, and from then on the missed message means that. Text-typing actions are never learned. **Self-training predictor** (`learner.py`): every night a logistic-regression model trains on your app switches and is tested on the last 3 days against the counting predictor. It takes over "what will I open next" and the command bar's app guesses only while it wins top-3 by 2 points without losing top-1. On 2026-09-30's data, counting won (84% vs 81%). **"What's on your mind?"** lists the profile, where jokes land, recent corrections and the predictor's scores. 1297 tests pass.
- **Fun numbers** (2026-09-30, `services/activity/fun.py`, `personality.py`): "how many hours did I game this week" (gaming time per game, any time window the activity questions understand), "what's my study streak" (days in a row with 30+ min of study; today not done yet doesn't break it; best run), "semester wrap-up" / "how was my semester" (writes and opens Documents\FRIDAY Journal\Semester wrap-up <date>.md: active time, time per kind, study per subject, best streak, attendance, games, projects + commits, top Spotify artists/songs for 6 months if connected; starts at SEMESTER_START in .env, else when logging began), "roast my week" (the roast with the last 7 days' numbers).
- **Wrong-password alert** (2026-09-30, `services/security/intruder.py`): a failed sign-in (wrong password or PIN, Security event 4625) takes one webcam photo (PyAV/DirectShow, no new dependency) and sends it to Telegram — "Wrong password on your laptop at 14:32" — at most once per 20 s; photos are kept in memory/intruder/. If the camera fails the text still goes; offline, the photo stays local. Triggered by a Windows scheduled task running as SYSTEM (so it also works at the sign-in screen after boot), set up once with admin rights: `python -m services.security.intruder --install` (also enables failed-logon auditing); `--uninstall`; `--test` sends a test photo now. Verified live: a wrong PIN at the lock screen sent the photo to Telegram.
- **Spotify wrapped** (2026-09-30, `services/spotify/wrapped.py`): "my spotify wrapped" (last 4 weeks), "…this semester" (6 months), "…all time", "who are my top artists", "what are my top songs" — from Spotify's own top lists, so background listening counts. Adds the `user-top-read` scope: the saved login now records its scopes, and "connect Spotify" logs in again when one is missing (needed once for existing logins).
- **Memory extras** (2026-09-30): reading list (`services/memory/reading_list.py`, memory/reading_list.json) — "add this to my reading list" / "save this for later" saves the page most recently visited in Chrome/Edge (read from the browser's history, since the activity log keeps only domains), "add <url> to my reading list", "what's on my reading list", "open reading list 2", "done with reading list 1", "clear my reading list". "search my journal for viva" / "what did I write about X" searches the saved journals plus today's diary entries. "what do you know about Ravi" lists saved memories that name that person. "what did you learn this week", and on Sunday (with the weekly summary) a toast listing what FRIDAY learned by itself that week, so wrong guesses can be forgotten (`SemanticMemory.learned_since`).
- **System health** (2026-09-30, `services/automation/system_health.py`, `proactive/nudges.py`): "how's my battery health" (full charge vs design capacity + charge cycles, from `powercfg /batteryreport /xml` — WMI's design capacity needs admin), "how long has the laptop been on" (since the last restart; Fast Startup shutdowns don't reset it; says if a restart is waiting), "do I need to restart" (Windows Update / servicing registry keys), "what's taking up space" (Everything's 300 largest files added up per folder, Windows system files left out, plus free space). Eye breaks, off by default: "turn on eye breaks" → every 20 minutes at the screen without a 2-minute break, a silent 20-20-20 toast (dropped, not held, while gaming/fullscreen). Not built: boot duration — its event log needs admin rights.
- **Automation extras** (2026-09-30): routine steps can pause — "wait 5 seconds", "pause 2 minutes", "wait a moment" (max 10 min) — and the tray has a **Routines** menu that runs one with a click. Clipboard transforms (`services/automation/clipboard_transforms.py`): "make my clipboard uppercase / lowercase / title case / sentence case", "…on one line", "clean up my clipboard", "strip formatting", "paste as plain text" (then Ctrl+V into the app in front), "count the words in my clipboard". Installers (`services/files/installers.py`): "what installers are in my downloads", "delete my installers" — .exe/.msi/.msix directly in Downloads and older than a day, asks yes/no, then Recycle Bin (pywin32 SHFileOperation). Screenshots (`filing.file_screenshot`, watched in `watch/auto.py`): one taken in Pictures\Screenshots during a class (timetable) or a subject's study mode moves to Documents\College\<Subject>\Screenshots as "<Subject> <date time>.png", with one toast per subject a day; others stay put. App limits (`services/activity/limits.py`, memory/app_limits.json): "limit valorant to 2 hours a day", "remove the limit on valorant", "what are my app limits" — silent toasts 10 min before, at the limit, and every 30 min over, while the app is in front (shown while gaming too); nothing is closed. `ActivityLog.app_seconds`.
- **Voice extras** (2026-09-30, `services/voice/voice_commands.py`, `tts.py`, `wake.py`, `memory/notes.py`): "read this" / "read it out loud" copies the selection in the app in front and reads it aloud, even when typed (from the command bar, which is in front itself, it reads what you copied; not over Telegram; private clipboard contents are never read); "stop reading". "talk faster" / "speak slower" / "normal speed" in 15% steps (−50…+100%), saved in memory/voice.json, used by edge-tts, Piper and the Windows voice (cached phrases are kept per speed). Journal entries by voice or typing — "journal: …", "dear diary …", "add to my journal …" — go into memory/diary.json and only into that day's journal (a new Diary section), never the notes inbox or briefing. Every "Hey Friday" wake is logged in memory/wake_log.jsonl (time + whether it was a mistake, never what was heard): a wake with nothing said after it, or "false alarm" / "I wasn't talking to you", counts as a mistake; "how many false wakes" gives the last 7 days. `ActionResult.speech` = text said out loud whatever the channel. Skipped: "Piper confirmations" — confirmations are already cached and instant, and Piper already speaks everything offline.
- **Power + phone** (2026-09-29, `services/automation/power.py`, `telegram/bot.py`, `telegram/client.py`, `watcher.py`): "lock the laptop" (at once), "put the laptop to sleep", "shut down (in 30 minutes)", "restart the laptop" (these three ask yes/no first — from the laptop or Telegram), "cancel the shutdown"; "shut down spotify" still closes the app. Telegram: /lock, /sleep, /shutdown [minutes], /restart, /cancel, /away ("I'm going out": pause, lock, and notifications go to Telegram at once until you're back at the laptop — the first minute doesn't count, so the lock's own keypress can't end it), /menu (buttons for the 8 most-used commands of the last 30 days, from the command log, plus screenshot / what's due / today's classes; a button runs the command). The morning briefing goes to Telegram at `TELEGRAM_BRIEFING_HOUR` (default 7, blank = off) on days with classes. Not built: the wrong-password alert — reading failed sign-ins (Security log, event 4625) needs admin rights, and FRIDAY runs as a normal user.
- **Insights** (2026-09-29, `services/activity/insights.py`, local counting): "how good are your suggestions" (habit suggestions shown/used/not now/stopped/ignored, by kind and time of day); "when do I usually start" / "my day hours" (median first and last activity, a day running 5 AM–5 AM) and a "Rhythm" line in the weekly summary; "when do I study best" (study sessions by mornings/afternoons/evenings/nights, average length); "how long will this session last" (the running session vs the median of past ones of its kind started within 2 h of it); a briefing "Heads up" for deadlines within 5 days whose subject had under 30 min of study in the last 3 days; `memory/command_examples.jsonl` rewritten nightly with the journal (every command: hour, weekday, app in front, action, target, success, previous command and minutes since) — training data (`log.command_rows`).
- **Coding helpers** (2026-09-29, `services/activity/devtools.py`, `watch/asked.py`, `watch/done.py`, `weekly.py`): "what's running on port 3000", "what dev servers are running" (listening ports of dev programs — node, python, java, mysqld… — not Windows' own, never FRIDAY's port, with the saved project they run in); "kill port 3000" / "stop catjang's dev server" asks first, then stops the program and its children; "did CI pass on catjang" / "CI status" (latest GitHub Actions run via `gh`, "not signed in to gh" when it isn't); "check outdated packages (in catjang)" (npm outdated + the project venv's pip). "tell me when catjang logs an error" (the project's newest .log) / "tell me when server.log says listening" — new lines only, one alert. A failed terminal command's done alert has [Explain]: the vision AI reads the terminal on screen and the answer comes as a notification. The weekly summary has a "Shipped" section (each project's commit messages, up to 8) as a changelog draft.
- **College helpers** (2026-09-29, `services/proactive/college.py`, `memory/college.json`): class links ("DS class link is meet.google.com/…", "join DS class", "join my class" = the one on now / next) and a [Join] button on the class warning; when a class starts and you're at the laptop with no mode on, "EVS has started. Start study mode for EVS?" [Yes] [No] (once per class; `buttons` mode answers now pass a subject); exams (deadlines named exam/CIE/SEE/IA/test/quiz/viva…) counted down in the briefing 3–30 days ahead; "make a revision pack for DBMS" → `College\DBMS\DBMS revision pack.md` (syllabus, files, YouTube videos on it, notes, deadlines, marks, attendance, study time) opened; syllabus units from a PDF/Word/text file ("DS syllabus is in <file>", "what's in DS unit 2", "DS syllabus"; Unit 2 / UNIT-I / Module III headings); "start the DS assignment" makes `College\DS\<deadline name>`, opens it and marks the deadline started; profile facts ("my USN is …", "my section is …", "what's my USN") and "type my USN" types it. Downloads get a third button, "Move & rename" ("Unit2_notes (3).pdf" → "DS - Unit 2 notes.pdf", `filing.tidy_name`).
- **Campus Wi-Fi auto-login + LMS shortcut** (2026-09-29, `services/network/campus.py`, `logins.py`). REVA's portal (`captiveportal.reva.edu.in:1000`) signs in with Microsoft ("Sign in to your account"). When the network watcher sees Wi-Fi connected without internet, it reads where Windows' connection test is redirected (Location header or a redirect in the page); for the campus portal (`CAMPUS_WIFI_PORTAL`, blank = off) it opens that page (its one-time token included) — Microsoft SSO often finishes by itself — and, with a login saved as "wifi" (two pages), signs in with `logins.log_in`'s careful typing. Any other network's login page only gets a notification: the college password is never typed elsewhere. At most every 5 min; "log me in to wifi" by hand. LMS: "open lms", "lms", "lms login", "open my lms" sign in with a login saved as lms/rulms/moodle, else open rulms.reva.edu.in.
- **Meaning-based command cache** (2026-09-29, `services/automation/command_cache.py:similar`, `intent.py`). The cache is no longer tied to the model that decided (CACHE_VERSION 2; only tools + router prompt), so switching models or going offline keeps it. Commands FRIDAY understood by itself (apps/sites, device, media) are saved too (`intent._remember`). A message that means the same as a saved command (bge-small, the file-search model, similarity ≥ 0.86, measured on paraphrase pairs) reuses its actions without an AI call — also for messages that don't start with a command word ("brighten the screen" after "increase brightness"; only if the model is already loaded there). Guards: every name/number the actions use must be said, numbers must match, the direction words must agree (`DIRECTION`: launch = open ≠ close, brighter = up ≠ down, on ≠ off …), and a question never reuses a command. Checked with the real model: "can you launch spotify please", "make the screen brighter", "switch wifi on" hit; "open chrome", "close spotify", "what is spotify", "turn off wifi" don't. Tests run with it off (`SEMANTIC`) except the cache's own, which use a word-hash fake.
- **Guesses in the command bar** (2026-09-29, `services/activity/predict.py:bar_suggestions/bar_outcome`, `interfaces/popup/app.py`). Opening Ctrl+Shift+F shows a line under the box — "Tab: resume catjang · open spotify · open whatsapp": habit-engine habits due now first, then the shadow predictor's next apps from the app you were in, as commands ("open …", "resume …", "go to …"). Tab cycles them into the box, Enter runs one. Every opening that showed guesses is saved to `memory/bar_predictions.jsonl` (picked index / typed something else — text not kept / closed; hour, weekday, app before) as ML 2.0 training data; "how good are your bar guesses" scores it. API: `GET /api/v1/predict/bar`, `POST /api/v1/predict/bar/outcome`. The bar is 70 px tall now; its Win32 plumbing moved to `interfaces/popup/win32.py` (app.py was over 500 lines).
- **Attendance + internal marks** (2026-09-29, `services/proactive/attendance.py`, `memory/attendance.json`). After each timetable class ends (within an hour), one silent toast "DBMS (9:30 am–10:30 am): attended?" [Attended] [Missed] (`buttons` kind `attendance`; reaches Telegram when away). "I attended data structures", "bunked EVS today", "missed DS yesterday", "attended/bunked all classes today", "no college today" (no questions that day), "my attendance" (worst first), "attendance in DBMS", "how many DS classes can I skip" (in a row, staying at 75%). Under 80% = "close to 75%", under 75% = how many in a row to get back; the briefing lists subjects under 80%. Marks: "I got 18 out of 25 in DBMS CIE 1", "my DBMS marks", "what do I need in the DBMS exam for an A" (assumes internals 50 + exam 50 out of 100, grades O 90 / A+ 80 / A 70 / B+ 60 / B 55 / C 50 / P 40 — constants at the top). "I missed the bus" isn't attendance: only the user's subjects count.
- **`friday` in the terminal** (2026-09-29, `interfaces/cli/friday.py`, stdlib only): `friday open spotify`, `friday "what's due"`, `git diff | friday "review this"`, `npm run build 2>&1 | friday "why did this fail"`; bare `friday` = a small back-and-forth. Posts to the local `/api/v1/chat`, so commands, chat, files and memory all work; piped text is attached (its end kept when long, within the API's 4000 chars) and read as UTF-8. A `friday` function in the Windows PowerShell profile runs it with the venv's Python and switches the console to UTF-8 while it runs. Live-checked against the running FRIDAY.
- **Sense of humour** (2026-09-29, `services/automation/personality.py`; user asked for sarcasm "medium but towards the full side", roasting procrastination and gaming during study hours). Chat: a dry, sarcastic PERSONA (answer first, one-line joke at most, never on serious topics) plus a "Right now" line from local data — study mode, the class on now, a deadline within 48 h, today's gaming/video/social vs study minutes. Command replies (`intent.try_system_action` wraps `_try_system_action`; commands a request ran are collected through `log.commands_run`, a ContextVar filled by `log_command`; routine steps are seasoned once): always when a game/video/social app or site is opened in study mode, during a class or with a deadline under 24 h, or the 3rd time in an hour; study mode ended under 20 min; sometimes when study mode starts (60%), at 1–5 AM (35%), on everyday commands (15%). A silent toast when a game is in front during study mode or a class (once per session). "roast me" (the chat AI roasts today's numbers; a plain line if no AI answers), "be serious" / "sarcasm off" / "no more jokes", "sarcasm on" (`memory/personality.json`). Study mode now records when it started. Tests run with sarcasm off.
- **Habit engine 1.0** (2026-09-29, `services/activity/habits.py` + `habit_patterns.py`; replaces the launch-at-this-hour habit nudge and `log.habitual_apps`). Learns by counting over the last 14 days (weekdays/weekends apart), no AI: time habits (an app, website or saved project started around the same time on 3+ days — a project wins over the terminal it runs in), chains (Y within 2 min after X on 3+ days and in 40%+ of X's starts), routines (2–4 apps launched together within 5 min on 3+ days, used in front that day). One suggestion per pattern (`prune`: a routine covers its chains and its other apps' times; a chain's target has no time of its own). Suggested from the watcher around the usual time (−5/+20 min) or right after the trigger, only while active, not busy/quiet, not already open, each once a day, max 3 a day; buttons Open it / Resume it / Save it (routine → `routines.json`, named "morning/afternoon/evening/night setup"), Not now, Stop suggesting. Confidence = support × (accepted+1)/(accepted+declined+0.5·ignored+1), minimum 0.3; 3× "Not now" in a row pauses 7 days; unanswered for 2 h = ignored. Every suggestion's features (time, habit stats, app in front, minutes since last use, past answers…) and every answer go to `memory/habit_examples.jsonl` — labelled data for a trained model (2.0). "what are my habits", "why did you suggest that", "forget the spotify habit", "pause/resume habit suggestions" (`memory/habits.json`). Process names shown/opened as apps ("Windows Terminal"; `windows terminal`/`terminal` → `wt.exe` added to APP_REGISTRY); dev runtimes (electron, node, python) and browsers/Explorer are never habits. On the real 6 days: Windows Terminal ~8:54 AM, FRIDAY project ~9:20 AM, Spotify ~10:34 PM (weekdays, 3 of 4 days).
- **Study hours per subject** (2026-09-29, `services/activity/study.py`): foreground time counts for a subject when the window title names it (short name, initials, or a full name the user gave), or while "start study mode for DBMS" is on (stored in the new `subject` column; games, chat, music and system windows don't count). "how long did I study DBMS this week", "study hours today", "how much did I study data structures yesterday", "my study time last week" (no time said = the past 7 days); a Study line in the journal and a Study section (vs last week) in the weekly summary. Full names in `memory/subjects.json` that a timetable subject abbreviates ("Data Structures" → DS, "Database Management Systems" → DBMS, "Environmental Science" → EVS) are that subject's aliases, not extra subjects (`timetable.abbreviates/aliases`) — filing and deadline matching use them too. The activity log no longer counts the user as away while the app in front is playing media (a lecture video; Windows' current media session). Also: "this is my timetable" imports the timetable on screen; the free vision models were overloaded, so the user's II-A timetable was entered from a screenshot.
- **Shadow predictor, smart download filing, deadlines** (2026-09-29, from the feature-brainstormer's list).
  **Shadow predictor** (`services/activity/predict.py`): next-app counts (after this app / at this hour / weekday-vs-weekend slot, plus "back to the app before" learned as its own choice), scored by replaying the activity log in order with only earlier data — "how good are your predictions", "what will I open next"; a Predictions line in the weekly summary. System windows are left out (`log.app_sequence`). On the first 5 days: top-1 ≈ the naive "go back" guess (~50%), top-3 ~86%; a second-order (last two apps) model didn't help, so it isn't in. Never shows guesses on its own.
  **Filing** (`services/files/filing.py`): the downloads watcher now reports every new finished file (not just slow ones; Firefox's empty placeholder waits); a document naming a subject (timetable + "my subjects are …", `memory/subjects.json`, by name or initials) or saved project gets "Move it to College\\<Subject>?" [Move it] [Leave it] (`buttons` kind `file_move`, works from Telegram too); nothing moves without the click, never overwrites. Subject commands live in `timetable.py`.
  **Deadlines** (`services/proactive/deadlines.py`, `memory/deadlines.json`): "DBMS assignment due Friday 11:59pm", "add deadline … due 5 Oct" (day/month, weekday, today/tonight/tomorrow; no am/pm = evening; no time = 11:59 PM), "what's due", "done with the DBMS assignment", "remove deadline 2", "clear my deadlines". Silent countdown toasts 3 days / 1 day / 3 hours before (only the most urgent after a gap), in the briefing when within 3 days, and appended to that subject's class warning.
- **Speak commands through Handy** (2026-09-29, `interfaces/popup/app.py`): Ctrl+Alt+F opens the command bar and starts Handy (the user's offline speech-to-text app, running Parakeet unified) with `handy --toggle-transcription`; Ctrl+Alt+F again (or Handy's Ctrl+Space) stops it, Handy pastes into the bar, and the bar sends it 0.4 s later. Typing a key yourself turns the auto-send off; Escape/closing the bar cancels Handy (`--cancel`). FRIDAY's own voice (Ctrl+Alt+Space, "Hey Friday", spoken replies) stays on faster-whisper. Spike before it: Parakeet unified int8 (sherpa-onnx, CPU) vs faster-whisper small (GPU) on 60 TTS commands ×2 (clean/noisy) — WER 3.4%/4.7% vs 2.9%/6.9%, ~285 ms vs ~160 ms; a tie, so no engine swap (sherpa-onnx was installed for the spike only).
- **Quick chat on the local model** (2026-09-29, `providers/failover.py:is_quick_chat`): measured first — FRIDAY's own steps take ~0.01 s, the time was all the model (OpenRouter's free `nemotron-3-super` thinks before answering: 5–12 s with chat history; streaming wouldn't help since nothing arrives until it's done). Short, simple messages (≤ 15 words, no "code/explain/why/write/how to…" words, not answered from files/web, no provider picked for the request) now try local Ollama first and fall back to the usual chain (`complete_with_failover(prefer_local=True)`) — typed and voice. Measured: 0.4–0.7 s instead of 5–12 s; "explain why the sky is blue" still goes to OpenRouter. `QUICK_CHAT_LOCAL=true` (default) replaces the unused same-provider `LIGHT_MODEL`. Also: the downloads watcher lists the folder every check (Windows sometimes updates a folder's timestamp late, which delayed alerts).
- **"It's done" alerts, send-to-laptop, notes inbox** (2026-09-29, the third Telegram sub-project). Alerts are ordinary notifications, so they reach Telegram after `TELEGRAM_AWAY_MINUTES` away; Claude/terminal ones are skipped while you're active with a terminal in front. **Always on:** Claude Code replies that took `DONE_MIN_MINUTES` (2) and every permission request (hooks → `POST /api/v1/done/claude`, `services/watch/done.py`); PowerShell commands that took `DONE_MIN_MINUTES`, with pass/fail (the prompt function in the user's profile → `POST /api/v1/done/terminal`); finished browser downloads that took ≥ 1 min (partial `.crdownload`/`.part` files in Downloads, `services/watch/auto.py`); heavy CPU/GPU work (≥ 80% for `HEAVY_WORK_MINUTES`, then calm; not while gaming/fullscreen). **Asked for** (`services/watch/asked.py`): "tell me when blender closes", "tell me when it's done" (the app in front closing), "tell me when it's charged / the battery reaches 80", "tell me when <url> changes" (visible text checked every `WEB_WATCH_MINUTES`, one alert; kept in `memory/watches.json`), "what are you watching", "stop watching …". "FRIDAY ONLINE" now says how long it was offline. **Send-to-laptop** (`services/telegram/bot.py`): a link (or a phone share "Title + link") opens in the browser; a file/photo/video/audio (≤ 20 MB, forwarded is fine) is saved to `Downloads\FRIDAY` and shown in Explorer, never opened; "copy <text>" puts it on the clipboard. **Notes** (`services/memory/notes.py`, `memory/notes.json`): "note …" / "idea …" from anywhere; "read my notes", "delete note 2", "clear my notes"; the day's journal gets a Notes section and the briefing lists them. A note is never taken as a web/file/screen question.
- **Auto-sessions + weekly summary** (2026-09-29, `services/activity/sessions.py`, `services/activity/weekly.py`, spec `docs/superpowers/specs/2026-09-29-auto-sessions-design.md`): sessions are worked out from the activity log (work = coding/project/ai/documents, study, gaming, chill = entertainment; merged across gaps ≤ 10 min, ≥ 10 min to count). A running session with no mode on → "Looks like you're working. Start work mode?" [Yes] [No] (No = not again today, unanswered = not for 2 h; answers saved as `mode:<group>` feedback rows). A 20+ min session that ends → "Work session done: 1h 35m (14:05–15:40) — FRIDAY 1h 10m, 3 commits." with [End mode] if its mode is still on. The journal gets a Sessions section. Sundays at `JOURNAL_HOUR`: `Documents\FRIDAY Journal\Week of <Monday>.md` + a one-line notification; "how was my week", "open my weekly summary", "open last week's summary".
- **Class timetable** (2026-09-28, `services/proactive/timetable.py`): "read my timetable from the screen" / "…from <image or PDF>" — the vision AI reads it once (PDFs: their text, any AI) into `memory/timetable.json`. "what classes do I have today / tomorrow / on Monday", "what's my next class", "add class DBMS on Monday 10 to 11 in room 204", "remove class …", "clear my timetable". Today's classes are in the morning briefing; `WARN_MINUTES` (10) before each class a notification ("DBMS starts in 10 minutes in 204."), spoken unless quiet hours / busy.
- **Daily journal** (2026-09-28, `services/activity/journal.py`): written from the day's activity, locally, no AI — active time per kind, projects (+ commits), commits, classes, YouTube watched, songs, searches, files opened, top apps — as Markdown in `Documents\FRIDAY Journal\<date>.md`. Automatically at `JOURNAL_HOUR` (22) with a notification; "write my journal", "open my journal", "open yesterday's journal", "open my journal for Monday".
- **Modes** (2026-09-28, `services/automation/modes.py`): "start study mode" … "end study mode". Starting runs the mode's steps (normal commands, like a routine); a quiet mode holds nudges and FRIDAY's own speech (counts as busy); ending closes the apps its steps opened and restores the volume. One mode at a time. Defaults study/work/gaming (quiet) and chill; "when I start study mode, open vs code, play lofi and set volume to 20", "make study mode not quiet", "what mode am I in", "list my modes", "delete chill mode". `memory/modes.json` + `mode_state.json`.
- **Login shortcuts** (2026-09-28, `services/automation/logins.py`): "save my github login" opens a small private window (login page, username, password, two-page option); the password goes only into Windows Credential Manager ("FRIDAY login: github"), never FRIDAY's files, logs, chat or any AI. "log me in to github" opens the page, brings the browser forward, waits for it to settle, types the username (Tab or Enter + wait for two-page logins) and password key by key (`keyboard.type_secret`, never the clipboard) and presses Enter — only while the browser is in front on a page whose title looks like a login page (else it stops, e.g. already signed in). "list my logins", "remove my github login".
- **Notification buttons that learn** (2026-09-28, `services/proactive/buttons.py`, `interfaces/protocol_handler.py`): the habit nudge ("You usually open code around now.") has Open it / Not now / Don't suggest this; reminders have Snooze 10 min. Buttons are `friday://` links (registered for the current user at startup, HKCU) handled by a stdlib script that posts to `POST /api/v1/notify/respond`; only a random one-time token of a notification FRIDAY showed counts, with that notification's own answers, and what to open comes from FRIDAY's record, not the link. Each suggestion and answer is saved as a `feedback` row in the activity log (training data for a habit engine); "Don't suggest this" sets `muted_habits` in `proactive.json`.
- **Git check for saved projects** (2026-09-28, `services/activity/git_status.py`, read-only): "any uncommitted work (in catjang)?", "check my projects", "what did I change in catjang today / yesterday / this week", "write a commit message for catjang" (diff sent only to the local Ollama model, result copied to the clipboard). Evening notification at `GIT_REMINDER_HOUR` (default 21, blank = off) listing projects with uncommitted changes, once a day.
- **Auto quiet mode** (2026-09-28, `watcher.is_busy`): while a game (category gaming) or anything fullscreen is in front (Windows' `SHQueryUserNotificationState`), nudges are held and shown afterwards, the briefing and git notification wait, reminders show without being spoken, and "Online."/"Offline." isn't spoken. A dying battery still shows (silently). Replies to the user's own commands still speak.
- **Piper offline voice** (2026-09-28, `services/voice/tts.py`): with no internet FRIDAY now speaks with Piper (`PIPER_VOICE`, default `en_US-hfc_female-medium`, CPU, played sentence by sentence and stoppable) instead of pyttsx3's Windows voice. The voice is downloaded once into `memory/piper/` at startup while online (`prewarm`). When the network watcher already knows the PC is offline, speech skips edge-tts instead of waiting 3 s for it to fail. pyttsx3 stays as the last resort (Hindi text, which the English Piper voice can't read, or Piper missing). Online speech is unchanged (edge-tts Aria). New dependency: `piper-tts==1.8.0`.
- **WhatsApp messages** (2026-09-28, `services/automation/whatsapp.py`): "message mom on WhatsApp: I'll be late", "whatsapp mom …", "send a whatsapp to mom saying …", "text mom …" (saved names don't need the word WhatsApp), or a number said directly. Always asks first (the existing yes/no confirmation; voice listens for the answer); on "yes" opens `whatsapp://send?phone=…&text=…` in WhatsApp Desktop and presses Enter only once WhatsApp is the window in front — otherwise the message is left typed in the chat. Contacts in `memory/contacts.json`: "save mom's number as 98765 43210" (10-digit numbers get +91), "list my contacts", "remove contact mom". The activity log records the contact, never the message.
- **Ask your activity log** (2026-09-28, `services/activity/ask.py`): "what was the repo I looked at yesterday", "what video did I watch last night", "which file did I open this morning for DBMS", "what song was I listening to", "what did I search for on Google", "when did I last open WhatsApp", "how long did I spend on YouTube this week", "what apps did I use today". Answered from the local activity table with no AI model (titles are private): a time window (today, yesterday, this morning, last night, on Tuesday, last week, N days ago; default the past 7 days), a kind (GitHub repos, searches, YouTube, music = Spotify window titles, PDFs, files, sites, games, apps) and topic words matched against title, site, app, category and project. Lists up to 5, newest first, each thing once; "how long" sums foreground time; "apps" totals time per app.
- **Projects + "resume"** (2026-09-28, `services/activity/projects.py`): the user names projects — "this is a project" (the folder of the last window: a File Explorer folder, or the folder a terminal/Claude Code session/program runs in, widened to its git root), "save catjang as a project" (found with Everything under the user folder, git projects first), "list my projects", "remove project X". Kept in `memory/projects.json` (path, GitHub repo from `.git/config`, optional `sites`). Activity rows of a saved project get a `project` column and the category **project**: programs whose process tree runs in its folder (recorded live), window titles with its name (not browser tabs), GitHub pages of its repo, sites named after it or saved for it, and localhost pages served from its folder (listening ports checked each minute) or titled with its name. Saving/removing a project relabels existing rows. "resume catjang" / "pick up where I left off" (the last project worked on) opens Windows Terminal in the folder (`wt -d`), the folder in File Explorer, the GitHub repo page and sites used with it in the last 14 days (never localhost). "how long did I work on catjang today / yesterday / this week"; day summaries add "Projects: …". Not built: which terminal tab is showing when tabs are in different projects (counts as neither). **Custom resume steps** per project (same day): "when I resume catjang, run npm run dev, open vs code and play lofi" saves a `resume` list in `projects.json` (plain sentences, editable by hand); "what does resume catjang do", "reset resume for catjang" (back to the default: terminal, folder, sites). "open the terminal" / "run <command>" become one Windows Terminal window in the folder with a tab per command (PowerShell `-NoExit`, so output and errors stay visible); "open the folder" / "open the sites" are the project's own; any other step runs as a normal FRIDAY command (apps, URLs, music, routines), through the same step runner as routines (`intent._run_steps`). A resume step can't resume another project. Steps are split on commas/"and"/"then", so a terminal command containing "and" has to be written in the file.

### Fixed
- **Timetable reading** (2026-09-28): a timetable covering several sections (II-A…II-E) confused the AI — now only `TIMETABLE_SECTION` (in `.env`, or "…for section II-A") is asked for; PDFs are sent as page images (`pypdfium2`) instead of jumbled text; replies with thinking before the JSON are parsed; more reply room. **Images never go to a model that can't see**: when every vision model failed, the failover had sent the timetable image to the local qwen2.5 (text-only), which invented classes — `complete_with_failover` now skips non-vision local models for image requests and says the vision AI is busy instead (screen questions too).
- **Notepad / Calculator open by their Store app ID** (2026-09-28): `notepad.exe` / `calc.exe` are old redirect stubs; a cold start through them left Windows 11 Notepad without its Windows App Runtime ("Microsoft.UI.Windowing.Core.dll was not found", although the DLL is installed). `APP_REGISTRY` now uses `shell:AppsFolder\…!App`, the same activation as the Start menu.
- **Opened apps now come to the front** (2026-09-28): FRIDAY runs in the background, so Windows left apps it opened behind other windows — and an app already running (Windows 11 Notepad adds a tab to its existing window) stayed wherever it was, even minimized, so "open notepad" looked like it did nothing. `open_app` now waits up to 8 s for the app's window and brings it forward (`app_finder.bring_to_front`: restore if minimized, briefly join the foreground window's input so Windows allows it).

### Changed
- **Spotify minimizes itself when music starts** (2026-09-28): after FRIDAY starts a song, artist, album, playlist or Liked Songs through the Web API, the Spotify window is minimized (`player.minimize_spotify`, waits up to 5 s for a just-opened Spotify's window). Not for "play music" (resume) or the search page opened without a Spotify login, where you still pick the song yourself.
- **Morning briefing is notification-only** (2026-09-28): the automatic daily briefing is no longer spoken, just shown. "brief me" still answers like any command.

### Added
- **Online/offline switching** (2026-09-28, `services/network/status.py`): every 10 s FRIDAY fetches Windows' connectivity-test page (catches Wi-Fi login pages too); when that fails, `netsh wlan` says why (Wi-Fi off / not connected / connected without internet). Offline, chat, voice, vision, writing and the command classifier go straight to the local Ollama model instead of waiting for API calls to time out; back online, the APIs are used again. Wi-Fi off/disconnected switches at once, a failed check on connected Wi-Fi needs two in a row. A notification shows each change ("Wi-Fi is off. FRIDAY is offline — using the local model (…)", "Back online — using openrouter again."), and one at start if FRIDAY starts offline. FRIDAY also says "Online." / "Offline." (not during `QUIET_HOURS`); both are cached at startup (`PREWARM_PHRASES`), so "Offline." plays in the usual voice without internet. Going offline also loads the local model into memory (first reply ~0.7 s instead of ~4 s). Online, an API failure still falls back to Ollama (`FALLBACK_PROVIDERS='ollama'`).
- **Local model is now `qwen2.5:3b-instruct-q5_K_M`** (was `gemma4:e4b` in `.env`, `gemma3:4b` as the code default). It supports tool calling, so offline commands work ("open chrome and then set the volume to 30" → both, ~1.7 s). It can't see images: screen questions need the internet.
- **Open any installed app without listing it** (2026-09-28, `services/automation/app_finder.py`): an app that isn't in `APP_REGISTRY` is looked up with Everything (voidtools, installed with winget together with its `es.exe` command-line tool). It searches shortcuts/programs whose file name has the spoken words, then programs whose folder has them (games: "black myth" → `C:\games\Black Myth Wukong\b1.exe`). Installers, uninstallers, updaters, crash reporters and anything under Windows, Downloads, Recent or temp folders are skipped. Ranking: exact name, then whole words ("code" ≠ "Unicode"), then Start Menu shortcut > Desktop shortcut > program, then the least nested. "open X" tries Everything before handing an unknown name to the AI. Everything must be running (tray; starts with Windows). Not covered: Store apps (keep them in `APP_REGISTRY`).
- **Closing works like Alt+F4, for any app** (2026-09-28): `close_app` no longer uses `taskkill`; it sends the app's visible windows Alt+F4's close message (`WM_SYSCOMMAND SC_CLOSE`), so "save changes?" prompts still appear. The key press itself isn't sent: FRIDAY runs in the background, Windows often won't bring the app to the front, and Alt+F4 would then close whatever window is in front. Apps are matched by process name (`PROCESS_NAMES`), or by the folder they're installed in — listed `.exe` paths and anything Everything finds — so "close black myth" also closes `b1-Win64-Shipping.exe`, which the `b1.exe` launcher starts. In shared folders (`bin`, `Program Files`, Desktop…) only that exact program counts. "close X" for an unlisted app only matches when that app has a window open, so "close the tab" still goes to the AI. Apps running as administrator refuse the message ("it may be running as administrator"). Tray-only apps (no window) count as "isn't open".
- **Activity categories** (2026-09-28, `services/activity/categories.py`): every activity row now gets a `category` (coding, study, ai, communication, documents, music, entertainment, gaming, media, social, shopping, search, files, system, browsing, friday, other). It's worked out from the app name, the browser tab title, the website domain (subdomains included; your own dev servers count as coding), the file extension or the command. New rows are labelled when they're saved, and all rows are re-sorted each time FRIDAY starts, so editing the list relabels old data. Day summaries add "By kind: study 39m, ai 10m…". Games are found without listing them: every `.exe` under the game install folders on any drive (`C:\Games`, Steam libraries, Epic, Xbox, Riot, EA, Ubisoft, GOG) is scanned once per start, and Unreal games (`*-Win64-Shipping`) count anywhere. Fixed: the tray tests checked `icon.notify` after notifications moved to PowerShell toasts (15 failures, and running them popped real toasts).
- **Interrupt by talking**: while "Hey Friday" is switched on, saying "Hey Friday, …" over FRIDAY stops it at once and takes the new command ("Hey Friday, what time is it"); "Hey Friday, stop / be quiet / never mind" just silences it; a bare "Hey Friday" stops it and listens. While FRIDAY talks, the last 3 s of mic audio are transcribed every second and the phrase is looked for anywhere in them, ignoring it when FRIDAY itself is saying it (`tts.saying`). Plain speech without the wake phrase can't interrupt: on laptop speakers FRIDAY's own voice comes back through the mic.
- **"Hey Friday"** (`services/voice/wake.py`), only while switched on: tray "Talk to FRIDAY → Listen for "Hey Friday"" or **Ctrl+Alt+H**; the tray dot turns blue while the mic is open. Always off at start; switches itself off after `WAKE_AUTO_OFF_MINUTES` (30) without a wake. Utterances are found with the Silero VAD and transcribed with the already-loaded speech model; one that *starts* with a `WAKE_PHRASES` phrase wakes FRIDAY and the rest is the command ("Hey Friday, work mode" in one breath; a bare "Hey Friday" beeps and listens). Audio is ignored while FRIDAY speaks or the voice hotkey is listening; other speech is never logged. New endpoints `POST /api/v1/voice/wake` and `/voice/wake/stop` (per switch-on session id). No new dependencies. Not built: interrupting by talking, recognising only the owner's voice.
- **Morning briefing and nudges** (`services/proactive/`). `briefing.py`: the first time you're at the laptop each day after `BRIEFING_AFTER_HOUR`, FRIDAY speaks and shows the weather (Open-Meteo, `WEATHER_CITY`), today's reminders, battery (plus memory/disk only when they need attention) and yesterday's activity; "brief me" any time. `nudges.py`: once a minute, notifications for battery ≤ 20% unplugged (spoken at ≤ 10%), GPU ≥ 85°C or memory ≥ 85% for 3 minutes, `LONG_APP_HOURS` in one app, drive C < 20 GB (once a day) — each once per episode. Nothing spoken during `QUIET_HOURS`. "pause nudges for an hour", "turn off nudges" (kept across restarts in `memory/proactive.json`), "turn on nudges". Activity summaries now say "Yesterday you were…" for yesterday. Not built: calendar/email in the briefing, staying quiet during fullscreen/calls.
- **Voice replies start early**: AI chat replies to voice are streamed (`BaseProvider.stream()`, real streaming on the OpenAI provider, others yield the whole reply). `services/voice/speech_stream.py` speaks the first sentence as soon as it's complete and the rest in one piece when the reply is done — measured ~3–5 s to first sentence vs ~6–9 s for the whole reply. `complete_with_failover(on_text=…)` only switches provider before any text arrived; a failure part-way keeps what was said (`metadata.incomplete`). Pressing the voice hotkey stops both parts. Not streamed: typed chat, screen questions. Streamed replies report 0 tokens.
- **Routines** (`services/automation/routines.py`): one phrase runs several commands in order. "create a routine called work mode to open vs code, play my focus playlist and set volume to 30" (or "create routine work mode: …"), then "start work mode" / "work mode"; "list my routines", "delete routine work mode". Stored as plain sentences in `memory/routines.json`, editable by hand. Each step runs through the normal command flow; one combined reply; logged as `run_routine` for the future habit engine. Not built: scheduled routines, pauses between steps, a tray submenu.
- **Activity log** (`services/activity/log.py`): local training data for learning habits later. A background tracker records which app is in the foreground and for how long (sampled every 5s; idle after 5 min without input, FRIDAY's own windows skipped), and every command FRIDAY runs is logged with its action, target (app, song, search, site — never typed text or clipboard) and the app the user was in. `activity` table in `MEMORY_DB_PATH`. "what have I been doing today" summarises the day; "clear my activity log" wipes it. Setting: `ACTIVITY_LOG_ENABLED`.
- **Semantic memory** (`services/memory/semantic.py`): long-term facts about the user, searched by meaning. FRIDAY learns them by itself (a cheap model reads chat/voice messages that mention "I/my/me" in the background) or on request: "remember that …". Before each chat reply the up-to-8 most relevant facts are added to the system prompt. "what do you remember about me", "forget that …", "forget everything about me". Stored with dates in the `memories` table of `MEMORY_DB_PATH`; vectors come from the local file-search embedding model. Setting: `SEMANTIC_MEMORY_LEARN`.
- `LIGHT_MODEL`: optional faster model for short, simple chat messages (keyword + length check in `providers/failover.py:pick_chat_model`).
- OpenAI provider honours `OPENAI_BASE_URL`, so any OpenAI-compatible gateway (e.g. OmniRoute) works as the `openai` provider.

### Changed
- Default OmniRoute models: `OPENAI_MODEL=antigravity/claude-sonnet-4-6`, `INTENT_MODEL=antigravity/gemini-2.5-flash-lite` (the `auto/best-*` combos took ~18 s to the first word).
- Provider failover now also covers the command classifier (after its cheap and chat models) and the legacy `/system` route.

## [Unreleased] — 2026-09-21 — Local file search

### Added
- **File search** (`services/files/`): Documents, Desktop and Downloads (or `FILE_SEARCH_FOLDERS`) are indexed in the background at startup and every 30 minutes. Every file by name; text, code, PDF, Word, PowerPoint and Excel files by content too, with a local embedding model on the GPU plus full-text search.
- **Find:** "find my resume", "where did I save …", "which file mentions …", "find my receipt pdf", "find my photos", `\f …` list up to 5 files; then "open 1", "open it" or "show 1 in folder". "rescan my files" updates the index now.
- **Answer:** "what does my invoice say about …", "according to my notes, …", "ask my files …", `\d …` send the best matching excerpts to the chat AI, which answers and names the file. Works by voice too (spoken without citation markers).
- Tray "File search" submenu (index status, re-scan now); `GET /api/v1/files/status`, `POST /api/v1/files/rescan`, `GET /api/v1/files/search?q=`.
- `find_files` AI tool for commands the local wordings miss.
- Settings: `FILE_SEARCH_FOLDERS`, `FILE_SEARCH_ENABLED`, `FILE_SEARCH_RESCAN_MINUTES`, `FILE_SEARCH_EMBED_MODEL`.
- New dependencies: sentence-transformers, pypdf, python-docx, python-pptx, openpyxl.

### Security
- `.env` files, key/certificate files, password databases and files named like "password"/"secret"/"credential" are never read or indexed. Skipped folders: program/cache folders (venv, node_modules, .git, AppData…), hidden folders, and FRIDAY's own `memory/` and `logs/`.

## [Unreleased] — 2026-09-21 — Full Spotify control

### Added
- **Spotify Web API** (`services/spotify/`, Premium only): "play <song>" now really plays the song (inside its album, so music carries on), "play <artist>" plays the artist, plus "play my <name> playlist", "play the album …", "play songs by …", "play/shuffle my liked songs", "shuffle on/off", "repeat this song / repeat / repeat off", "add <song> to the queue" / "play <song> next", "like/unlike this song". Also available to the AI command fallback as tools.
- One-time login with "connect Spotify" (chat, voice or the tray's Quick actions): PKCE flow, so only `SPOTIFY_CLIENT_ID` goes in `.env`. Spotify redirects to `GET /api/v1/spotify/callback`; tokens live in `memory/spotify_token.json` and refresh automatically. "disconnect Spotify" forgets them. `GET /api/v1/spotify/status`.
- If no Spotify device is running, FRIDAY opens the desktop app and starts playback once it appears (never on another device by surprise).
- Without a connected account, everything works as before (playlist/album/artist requests open a Spotify search) and the new commands explain how to connect.

### Changed
- Music commands and AI tool calls run in a worker thread so Spotify requests don't block the server.
- `REPLY_RULES` lists the new music commands instead of saying there's no shuffle or playlist command.

## [Unreleased] — 2026-09-17 — Screen questions

### Added
- **Screen questions** (`services/vision/screen.py`): "what's on my screen?", "explain the error on my screen", "read my screen", `\v <question>`, by chat, voice or the tray quick action. The monitor under the mouse is captured, downscaled to a JPEG (never saved) and sent with the question to a vision model.
- **Image input** for all providers: `Message.images`, sent as image blocks (Anthropic), data URLs (OpenAI/OpenRouter) or `images` (Ollama).
- `VISION_PROVIDER` / `VISION_MODEL` settings with per-provider defaults, validated at startup.
- `complete_with_failover(..., model_for=...)` picks a model per provider.
- **Native tool calling**: `BaseProvider.complete(..., tools=...)` and `ProviderResponse.tool_calls` on all four providers. The command AI fallback now uses tools (`services/automation/command_tools.py`) instead of asking for raw JSON, and can run several actions from one message.

- **Command vocabulary** (`services/automation/command_words.py`): one place for every command word and phrase. Wake words and politeness are stripped ("hey friday, can you… please"); many more verbs (kill, terminate, fire up, brighten, crank…), app/website/folder aliases ("the browser", "open youtube", "my photos"), max/min/half and "a lot" levels, "sound on/off", YouTube searches, "play music", and more reminder wordings.
- `services/automation/app_commands.py`: the open/search/folder/organise matcher, moved out of `intent.py`.
- **Music controls** (`services/automation/media_control.py`, new `winrt-*` dependencies): play, pause, next, previous and "what's playing" for Spotify, YouTube and any app in the Windows media overlay, with the real track name in replies. "play music" resumes the player or opens Spotify and starts it; "play <song>" opens a Spotify search.
- **Typing** (`services/automation/keyboard.py`, `typing_commands.py`, `writer.py`): "type see you at 5" types exactly that, "write an email asking for Friday off" has the AI write it and types the result, and "press ctrl+s" / "select all" / "scroll down" press keys. "type hi and send it" adds Enter. Text goes into the app that had focus: the command bar hides and restores focus first, and voice replies are typed by the tray. Multi-line or long text is pasted so editors don't double-indent it.
- `ActionResult.keyboard` and a `keyboard` field on the chat/voice responses carry the steps to the client.
- **System stats** (`services/automation/system_stats.py`): "how's my system?", "battery", "cpu usage", "how hot is my gpu", "what's using my ram", "why is my laptop so slow" — by chat, voice or the tray's new "System stats" submenu. Warns about high memory, low battery, a hot GPU or a full disk, and names the apps using the most.
- `ActionResult.repeatable`: replies that change every time (stats, track names) aren't cached as speech.
- **Command cache** (`services/automation/command_cache.py`): the AI's decision for a message is saved in friday.db, so repeating it skips the AI (about 3 s → 5 ms). Only decisions are stored, never results.
- **Spoken confirmations are saved to disk** (`memory/tts_cache/`), so they play instantly after a restart too.
- "Clear chat memory" (`DELETE /api/v1/history`) also clears both caches.

### Fixed
- Music requests used to reach the chat AI, which claimed to play music and acted out commands with asterisks. Every system prompt now includes `REPLY_RULES` (plain text, never pretend to act, only suggest real commands), and the voice strips markdown before speaking.

### Changed
- Most commands now run locally; the AI is only asked when no word list matches, or when one message asks for several things.
- Open/close targets must be named exactly (after dropping "the", "my", "app"…), and app names match whole words only ("knowledge" no longer opens Edge).
- The default command model on OpenRouter is now `openai/gpt-4o-mini` (was Llama 3.1 8B, which is unreliable with tools).
- The command AI no longer retries on the chat model when it answers with text; that now means "chat".
- AI-chosen `close_app` actions only run for apps named in the message.
- The command bar is excluded from screen captures (`SetWindowDisplayAffinity`), so it doesn't cover what FRIDAY looks at.

---

## [v0.2.0] — 2026-09-14 — Tray, voice overhaul, automation backlog

Also covers the earlier, un-logged work: the first voice pipeline, system control, and the web UI (now removed).

### Added
- **System tray** (`interfaces/tray/`), the main interface:
  - status dot
  - command bar
  - Talk to FRIDAY
  - quick actions
  - clipboard history
  - provider picker
  - clear memory (asks first)
  - quit
- **Command bar** (`interfaces/popup/app.py`): Win32 window on Ctrl+Shift+F in the tray process. Stays open while FRIDAY waits for a yes/no.
- **Web search** (`services/search/web_search.py`, ddgs): `\s`, "look up …", "search the web for …". Chat replies cite sources.
- **More system verbs**:
  - close app (graceful; refuses Explorer)
  - volume set/up/down/mute (pycaw)
  - brightness (WMI)
  - clipboard read/write
  - screenshots to Pictures/Screenshots
- **Destructive-action confirmation**: `organise_folder` asks first and needs "yes" within 2 minutes.
- **Reminders** (`services/reminders/`): stored in SQLite, delivered as a Windows toast plus speech. Missed reminders arrive late on the next start.
- **Cheap intent-classifier model**: `INTENT_PROVIDER`/`INTENT_MODEL` or per-provider defaults, retrying on the chat model.
- **Clipboard history**: last 20 text items, in memory only. Private items are skipped. Available in the tray and by chat/voice.
- **Provider auto-failover** (`providers/failover.py`, `FALLBACK_PROVIDERS`). Replies report which provider answered.
- **Voice hotkey** Ctrl+Alt+Space: toggles listening, auto-stops on silence (Silero VAD), and interrupts FRIDAY's speech.
- **Auto-listen after yes/no questions** (`after_speech`).
- **Hindi voice** for Devanagari replies (`EDGE_TTS_HINDI_VOICE`).
- `launch_friday.vbs`: silent launcher that stops only FRIDAY's backend on quit.
- pytest suite: 246 tests.

### Changed
- STT: `openai-whisper` → **faster-whisper** `small` (CUDA float16, CPU int8 fallback), preloaded at startup.
- TTS: pygame playback → **streamed edge-tts** decoded with PyAV, played via PyAudio. Short confirmations are cached and common phrases prewarmed.
- The voice endpoint replies immediately and speaks in the background. Recording and transcription run off the event loop.
- Replies name folders ("Downloads") instead of full paths. The screenshot reply is shortened.
- `.env` now has intent, failover and voice sections, plus `API_RELOAD`.

### Removed
- Desktop UI and web UI (`interfaces/web/`). A new UI will be designed later.
- CORS. The API now accepts only local requests (TrustedHost plus an Origin check).
- `openai-whisper` and `pygame` dependencies.

### Fixed
- Uvicorn's reloader left an orphaned server holding port 8000 and serving stale code. The launcher now sets `API_RELOAD=false`.
- The launcher killed every Python process on quit.
- PowerShell progress output on stderr made toasts and brightness changes report failure.
- Distorted speech: s16 samples were played as float.
- The command bar closed before the user could answer "yes".

---

## [v0.1.0] — Phase 1 Foundation

### Added
- `core/config.py` — central config singleton with .env loading and validation
- `providers/base_provider.py` — abstract provider interface (Message, ProviderResponse, BaseProvider)
- `providers/registry.py` — factory function for getting providers by name
- `providers/anthropic/client.py` — Anthropic (Claude) provider implementation
- `providers/openai/client.py` — OpenAI (GPT) provider implementation
- `providers/ollama/client.py` — Ollama (local models) provider implementation
- `services/memory/sqlite_memory.py` — SQLite memory service (conversations + user facts)
- `interfaces/api/routes/chat.py` — chat, history, facts, and provider API endpoints
- `interfaces/api/app.py` — FastAPI app factory with CORS middleware
- `main.py` — startup entry point with config validation and ASCII banner
- `requirements.txt` — Phase 1 dependencies
- `.env.example` — template for environment configuration
- Full documentation suite: AI_HANDOFF.md, architecture.md, decisions.md, roadmap.md, current_state.md

### Architecture decisions made
- Provider abstraction via abstract base class (ADR-001)
- SQLite for Phase 1 memory (ADR-002)
- FastAPI as API framework (ADR-003)
- dotenv + singleton config (ADR-004)
- Lazy provider imports in registry (ADR-005)
- Event bus planned for Phase 2 (ADR-006)
- Strict interface separation (ADR-007)

---

*Future entries go above this line.*
