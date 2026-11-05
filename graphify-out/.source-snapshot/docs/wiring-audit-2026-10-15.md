# FRIDAY wiring audit — 2026-10-15

Status: F2, F3 and F6 fixed on 2026-10-16 after owner approval; six findings remain deferred.
Isolation verification: **4,419 passed**, no failures/errors/skips, one existing warning.
Notification-brain/recovery verification: **4,510 passed**, no failures/errors/skips, one existing warning;
see `tasks/notification-brain-verification.log` and matching XML.

The owner requested an audit of feature wiring and real-world behavior, explicitly
asked for findings before code changes, then requested saving them for a later
debugging session. This document preserves the findings; it does not authorize
starting implementation by itself. No application code or settings were changed by the
original audit. The later owner-approved isolation fixes are recorded below; existing
uncommitted work is preserved.

## What was verified

- Full existing suite: **1,947 passed, 1 warning**, in 186.76 seconds.
- All **197 Python source files** under core, interfaces, providers and services
  parsed successfully using AST parsing without writing bytecode.
- `venv\Scripts\python.exe -B -m pip check`: no broken requirements found.
- Running API: health, providers, file-index status, talk switch and system stats
  responded. Health is a basic server check, not proof that each feature works.
- File-index snapshot: **3,238 files**, **1,650 readable**, not scanning.
- SQLite quick checks passed for activity, file index, cognition, brain, training
  reviews and learning databases. This checks storage integrity, not semantic accuracy.
- Telegram `getMe` and `getChat` succeeded without sending messages or consuming updates.
- Windows registry entries existed for notification links and both Explorer file-sharing options.
- Everything answered a direct read-only query, despite earlier startup timeout warnings.
- Additional reproductions used temporary storage and simulated effects. They did
  not shut down the PC, type into real applications, or send messages.

Most tests set `AI_ASSIST_ONLY=False` in `tests/conftest.py::isolated_caches`.
Passing tests therefore do not establish that all advertised features are available
under the current configuration. No claim of exhaustive real-world validation was made.

## Deferred findings

F2, F3 and F6 are resolved; all other items below remain open. Priorities are suggested triage,
not an implementation approval. Original reproduction evidence is retained for reference.

### F1 — Capability-mode mismatch (high; owner decision)

- Evidence: current configuration resolves `AI_ASSIST_ONLY=True`.
- Relevant code: `core/config.py`, `providers/policy.py`,
  `interfaces/api/routes/chat.py::chat`, `interfaces/api/routes/voice.py::_reply`,
  `services/mind/reasoning.py::analyze`, and assist-only guards in `services/automation/intent.py`.
- Impact: general model chat, screen interpretation, computer-agent tasks, drafting,
  timetable image import and model-based reasoning are disabled or restricted.
  File/web requests return retrieved material rather than full generated answers.
  `REASONING_ENABLED=True` does not override the assist-only guard. Local commands,
  explicit schedule capture, goals/tasks and rule-based notifications can still work.
- Reproduced under current-mode settings with optional wording/knowledge calls
  disabled in the isolated probe:
  - `\c open the File menu`: local-command guidance, `action_success=False`.
  - `what is on my screen`: screen interpretation unavailable in this mode.
  - `write an email asking for Friday off`: drafting disabled.
  - `explain why this Python code fails: x = 1 / 0`: no general debugging answer.
  - `reasoning.analyze(...)`: `{"status": "disabled"}`.
- Next step: confirm intended capabilities before changing policy. Do not silently
  disable assist-only mode; it may be intentional. Align advertised availability,
  configuration visibility and regression coverage with the chosen behavior.

### F2 — Laptop and Telegram share pending confirmations (high)

**Resolved 2026-10-16:** pending actions, replies and cancellation are scoped by the existing
remote-request context. Laptop chat/voice share one scope; Telegram has the other. Bot shortcuts
also discard older Telegram approvals without affecting laptop work. Ordinary remote messages
preserve laptop computer-agent proposals. New regressions failed before the fix and pass after it;
see `tasks/channel-isolation-verification.log` and its matching JUnit XML for verification.

- Relevant code: `services/automation/intent.py::_pending`, `_ask_first`,
  `_handle_pending_reply`; `services/telegram/bot.py::_run`.
- Reproduction: create a laptop pending shutdown, then pass `yes` through the real
  Telegram-to-chat path with outbound delivery and action execution replaced by stand-ins.
- Observed: the stand-in received `('shutdown', True)` and the bot returned its result.
- Impact: a confirmation on one interface can approve an unrelated pending action
  from another interface. An unrelated message can also discard the shared pending action.
- Fix direction: scope confirmation ownership to the conversation/channel while
  preserving intentionally shared laptop chat/voice behavior.
- Acceptance: Telegram cannot confirm or cancel a laptop request, and vice versa;
  confirmation expiration and normal same-conversation yes/no behavior still work.

### F3 — Failed reminder delivery has no retry (high)

**Resolved 2026-10-16:** due reminders are claimed before brain review and acknowledged only after
actual transport acceptance. Failed destinations retry independently with bounded backoff; deferred,
withheld and failed reminders stay pending/listable. Leases recover review interruptions; ambiguous
submissions remain uncertain for explicit retry. Current source/facts/context are checked before each
destination; successful transport survives optional speech failures. Local status/why/retry commands
and a protected read-only API expose reasons and outcomes. Existing due timestamps are preserved.
The owner specifically authorized this notification-review purpose; general model permissions remain.
See the notification-brain verification artifacts above for regression and synthetic-workflow evidence.

- Relevant code: `services/reminders/service.py::take_due`, `deliver`, `deliver_due`.
- Cause: `take_due` marks reminders delivered before transport succeeds;
  `deliver` ignores a false return from `show_toast`.
- Reproduction: create an overdue reminder in a temporary DB, simulate toast failure
  and a busy state that suppresses speech, then run `deliver_due` twice.
- Observed: one failed toast attempt; zero pending reminders; no second attempt.
- Impact: a reminder can be lost without either a notification or spoken output.
- Fix direction: distinguish claiming/attempting delivery from acknowledged delivery,
  with bounded retries and explicit failure state. Consider crash recovery and duplicate delivery.
- Acceptance: a failed delivery remains recoverable and retries; successful reminders
  do not repeat on every scheduler tick; a busy state alone never loses the reminder.

### F4 — Routine typing is deferred past later steps (high)

- Relevant code: `services/automation/intent.py::_run_steps`, `_combine`;
  `interfaces/popup/app.py::_type_into_target`; voice typing in `interfaces/tray/tray.py`.
- Reproduction: simulate `open notepad`, `type hello`, `open calculator` as routine steps.
- Observed: all three backend steps finish before the combined keyboard payload is
  returned to the client. Typing is not executed between the two opens.
- Impact: keyboard actions can run out of order or target the wrong application.
  The command bar additionally restores its pre-request window before typing.
- Fix direction: explicitly sequence client-owned input and its target with other
  routine steps, or reject unsupported combinations clearly until sequencing exists.
- Acceptance: opening, typing, waiting and subsequent actions preserve their actual
  order and intended window. No input goes to an unrelated previous window.

### F5 — CLI/system API report typing success without executing input (medium)

- Relevant code: `interfaces/cli/friday.py::ask`,
  `interfaces/api/routes/system.py::system_control`, `SystemResponse`.
- Reproduction: ask for `type hello` using an isolated chat endpoint; it returns
  `Typing it.` plus `keyboard=[{"text": "hello"}]`. Feed that response to the CLI.
  Also send `type hello` to the isolated `/api/v1/system` endpoint with speech off.
- Observed: CLI returns only the text and drops keyboard instructions. The system
  endpoint returns `success=True` and `Typing it.` without executing or returning input.
- Related inspection: `interfaces/tray/tray.py::run_command` also consumes only
  `.text`; review this path for routines containing keyboard steps.
- Fix direction: either implement an explicit supported input path with target
  handling or report that these clients cannot execute keyboard actions.
- Acceptance: unsupported input cannot produce a successful completion claim;
  supported input is executed once in the intended window and reports failures.

### F6 — Telegram searches replace laptop file-result context (medium)

**Resolved 2026-10-16:** file results, selections and expiry are independent for laptop/Telegram,
including worker-thread searches and file forwarding. Laptop chat/voice continue sharing context.
Regressions cover empty/interleaved searches, selection, expiry and real bot/chat/voice workflows
with temporary files and mocked input/delivery. Verification artifacts are linked under F2.

- Relevant code: `services/files/assistant.py::_LastResults`, `last_results`;
  file references in `services/telegram/commands.py`.
- Reproduction: simulate a laptop search returning `laptop.txt`, then a Telegram
  search returning `phone.txt` through the real chat path, using artificial files.
- Observed: laptop-visible shared results become `phone.txt`.
- Impact: `open 1` or `send that file` can resolve against another interface's search.
  Separate `_pending_files` follow-ups do not isolate the result list or selection.
- Fix direction: scope results and selected-file state by conversation/channel,
  retaining intentionally shared laptop chat/voice context where appropriate.
- Acceptance: interleaved Telegram/laptop searches and selections remain independent,
  with existing ambiguity handling and result expiration preserved.

### F7 — Ending a mode can close pre-existing apps (medium)

- Relevant code: `services/automation/modes.py::begin`,
  `services/automation/intent.py::_start_mode`, `_end_mode`.
- Cause: `begin` records configured `open ...` step names before verifying whether
  they opened successfully or whether the app already existed.
- Reproduction: configure `open notepad` in a temporary mode and end that mode with
  close/volume actions replaced by stand-ins.
- Observed: Notepad is scheduled for closure without evidence that the mode created it.
- Impact: manually ending or automatically expiring a mode can close existing work
  windows. No real windows were closed during this audit.
- Fix direction: track verified resources created by the mode rather than deriving
  ownership from step text. Handle multiple windows and failed opens explicitly.
- Acceptance: pre-existing windows survive mode end; failed opens do not create
  cleanup targets; mode-created resources and volume restoration behave as intended.

### F8 — Combined results lose explicit speech (low)

- Relevant code: `services/automation/intent.py::_combine`;
  `services/automation/results.py::ActionResult`.
- Reproduction: combine `ActionResult(..., speech='selected text')` with another result.
- Observed: combined `speech` is `None`.
- Impact: read-aloud content, or an explicit instruction to remain silent, can be
  lost when multiple results are combined.
- Acceptance: combination preserves defined speech semantics, including the empty
  string used to suppress output, without exposing private content to caches/history.

### F9 — Long CLI questions with piped text exceed API limits (low)

- Relevant code: `interfaces/cli/friday.py::build_message`.
- Cause: the calculated space for piped output can become negative when the question
  nearly fills the message budget; slicing then retains excessive input.
- Reproduction: use a 3,990-character question plus `'log output ' * 1000`.
- Observed: a **14,978-character** message despite the **4,000-character** API limit.
  A 4,100-character question with the same pipe also produced 14,978 characters.
- Impact: the API rejects the request instead of receiving a bounded terminal excerpt.
- Acceptance: every generated message stays within 4,000 characters, including long
  questions, separators, Unicode and piped output; preserve useful error-output tails.

## Operational observations requiring follow-up

- October 14–15 logs show OpenRouter failures and Ollama fallback. Earlier entries
  include rate limits/credits and an unavailable free-model slug; recent failures
  sometimes have empty exception messages. These are historical log observations,
  not proof of a continuing provider outage. Verify current reachability/model
  availability before changing provider settings.
- October 15 logs show Edge TTS returning HTTP 403 and selecting the offline voice.
  Piper model files exist, but audible output was not tested.
- Everything startup queries timed out on October 15, including at backend start.
  A direct read-only query subsequently returned exit 0 with 939 matching shortcuts.
  Investigate startup readiness and timeout recovery rather than assuming it is absent.
- RAM stayed around **92% used (14.4 / 15.7 GB)** in two snapshots, including after
  the suite completed. Profile process usage; the audit did not attribute this to FRIDAY.
- `memory/logins.json` was absent. Saved website/campus login setup needs checking
  if those features are expected; no credentials were inspected or changed.

## Real-world trials still needed

- Microphone recognition, wake phrases, interruptions and conversation turns in actual noise.
- Audible online/offline speech and output-device selection.
- Spotify playback, device selection and token-refresh behavior.
- WhatsApp recipient selection, attachment preview and actual message delivery.
- Computer-agent proposal, approval, input and visible outcome in a real application,
  after resolving F1's intended policy.
- Wrong-password event, scheduled-task execution, webcam access and Telegram alert.
  Task query returned access denied; this does not establish whether the whole alert works.
- Real notification rendering/button activation, scheduled reports and sleep/restart recovery.

Tests and wiring inspection cover these subsystems, but those real-world outcomes
were not established. No microphone recording, webcam capture, real input, message
sending, playback or power action was triggered for the audit.

## Suggested resumption order

1. Reconfirm the current working tree, settings and runtime; preserve existing work.
2. F2/F3/F6 are resolved, including notification brain review and reminder delivery recovery.
3. Address F4/F5, then F7: keyboard execution and mode cleanup.
4. Resolve the intended capability mode (F1) before enabling model-dependent paths.
5. Fix F8/F9 and investigate the operational observations.
6. Add focused regressions for these gaps, rerun the suite, then perform agreed real-world trials.

Resume when the owner asks to debug/fix this backlog. Keep findings open until each
has fresh reproduction and verification evidence; a passing existing suite alone is insufficient.
