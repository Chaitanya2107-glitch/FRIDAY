# Command language coverage checkpoint

Proactive-task increment (2026-10-18): **265 family/action outcomes, 56 families, 530 frozen
examples**. Three new outcomes cover status, named/global controls and scoped responses. The broader
paraphrase inventory now has 56 families, 104 canonical requests and 208 alternatives. Stateful review,
feedback, source rechecks, budgets, concurrency, restart, chat/voice and watcher checks are in
`tests/test_task_followups.py` and `tests/test_proactive.py`. Evidence: `tasks/task-followups-focused.log`
/ `.xml`, `tasks/task-followups-verification.log` / `.xml`.
Verification: **4,737 passed**, zero failures/errors/skips, one existing warning (270.14 seconds).
Broad focused checks: **1,670 passed**; final focused checks after date-fixture correction: **85 passed**.

Class-rescheduling increment (2026-10-17): **262 family/action outcomes, 55 families,
524 frozen examples**. Five outcomes cover dated time changes, recall/history, explicit reminder links
and scoped update controls. The paraphrase inventory now has 55 families, 103 canonical requests and
206 alternatives. Real state, restart, concurrency, cancellation, corruption, delivery and chat/voice
checks are in `tests/test_class_changes.py`. Evidence: `tasks/class-changes-focused.log` / `.xml`
and `tasks/class-changes-verification.log` / `.xml`.
Verification: **4,688 passed**, zero failures/errors/skips, one existing warning (301.92 seconds).
All **1,704 focused checks passed** (58.10 seconds).

Deadline correction increment (2026-10-17): **257 family/action outcomes, 54 families,
514 frozen examples**. Five new deadline outcomes cover corrections, due recall, history, explicit links
and reminder-update controls (review/apply/reject). Stateful/recovery tests are in
`tests/test_deadline_changes.py`; evidence: `tasks/deadline-changes-verification.log` / `.xml`.
Verification: **4,630 passed**, zero failures/errors/skips, one existing deprecation warning (221.13 seconds). All **84 final focused checks passed**, including the prompt-budget regression; see `tasks/deadline-changes-final-focused.log` / `.xml`.

File/handoff context increment (2026-10-17): current corpus is **252 family/action outcomes,
54 families, 504 frozen examples**, including explicit file selection. Stateful correction, selection,
chat/voice, expiry and cross-process checks are in `tests/test_conversation_references.py`.
Evidence: `tasks/conversation-references-verification.log` / `.xml`.
Verification: **4,588 passed**, zero failures/errors/skips, one existing deprecation warning (204.44 seconds). All **22 new focused checks passed** after subprocess log isolation; see `tasks/conversation-references-final-focused.log` / `.xml`.

Brief follow-up increment (2026-10-17): the execution parser includes bounded project-brief revision
requests. Current corpus: **251 family/action outcomes, 54 families, 502 frozen examples**. Additional
stateful chat/voice, ambiguity and restart checks are in `tests/test_brief_followups.py`; verification is
saved in `tasks/brief-followups-verification.log` / `.xml`.

Notification-brain follow-up (2026-10-16): the source inventory now includes three additional cognition
outcomes with six frozen examples: notification status, decision explanation and reminder retry.
Corpus at that milestone: **250 family/action outcomes, 54 families, 500 frozen examples**. The historical language
checkpoint below is preserved; notification-brain regression evidence is saved separately in
`tasks/notification-brain-verification.log` and `.xml`.
Final notification-brain suite: **4,510 passed**, no failures/errors/skips, one existing warning.

Request: improve equivalent wording feature by feature, within the user's remaining
account allowance. Account quota is not exposed to the agent; no exact token/time
estimate can be calculated from “25% remaining”. Keep work incremental and saved.

## Current parallel follow-up

The user authorized multiple agents for the five remaining areas. Work is saved
directly in the workspace. **All five planned areas are complete; zero checklist
areas remain.** This is bounded language coverage, not every possible sentence.

- Task editing: 38 representative variants, 36 bounded patterns; 357 parser checks.
- Spotify: playlist/album/artist/queue wording and literal title preservation.
- Spoken numbers: explicit durations and labeled result selectors; routine waits.
- Typing mistakes: 14 explicit first-word spellings; native match required.
- Multi-command feature expansion and validated typo routing are integrated in
  `services/automation/intent.py`. Batches recognize notes, reminders, health,
  limits, watches, deadlines, timetable/marks, reading/files, workspace goals/tasks
  and other direct native actions before execution.
- Shared number/task hooks passed 1,237 adjacent checks. All 38 new task examples,
  with and without polite prefixes, plus integration regressions pass 98 router checks.
- Router tests exposed and fixed title truncation, collection batch boundaries,
  saved mode definitions, generic progress reports advancing steps, and URL paths
  being mistaken for battery alerts. Step completion requires explicit wording.

Final verification on 2026-10-16: **4,387 passed, zero failures/errors/skips** across
three disjoint groups covering all 112 test files (787 more tests than the previous
3,600-test baseline). Each process reports the existing Starlette/httpx deprecation
warning. The last group finished in 44.04 seconds. No new dependencies or changes
to the default AI action policy.

Durable evidence: `tasks/command-language-verification.log` and
`tasks/command-language-verification.xml`, with the three per-group reports next
to them. The aggregate XML contains every test once. Snapshot:
`tasks/command-language-checkpoint.zip`, 42 selected source/test/documentation and
verification files, plus a SHA-256 manifest. The ZIP is read back and every entry
checked. It excludes credentials, runtime databases/logs, models and the virtualenv.

The first integration run exposed one outdated lowercase-search assertion, journal
search losing its native route, and three legacy AI test inputs now intentionally
rejected by all-step validation. The router precedence is corrected; the AI tests
use single unfamiliar requests and explicitly verify classifier calls. Parallel
verification also exposed a pre-existing class-setting test hidden by an earlier
provider fixture's instance setting. Reproduced it with failover tests first, then
isolated the test's class setting; all 51 related tests pass. Application credential
redaction was unchanged. Earlier reports are preserved under `tasks/archive/`.

The previous verified 3,600-test snapshot and reports remain under
`tasks/archive/command-language-3600-tests-*`. An interim source snapshot is also
saved as `tasks/command-language-parallel-source-checkpoint.zip`.

## Existing verified baseline

- Shared politeness, app sentence patterns, volume/brightness comparisons and
  spoken percentages, screenshots, media, reminder and note synonyms implemented.
- Previous full regression run: 2,052 passed; later expanded phrase suite: 222 passed.
- Examples: `docs/COMMAND_LANGUAGE.md`.

## Saved implementation

- Added `services/automation/command_phrases.py`: 54 feature families, 102 canonical
  requests and 204 alternative sentences. Shared polite prefixes also work.
- Added parameterized wording for workflows, WhatsApp text, Telegram forwarding,
  file finding/questions, web research, diary entries, due dates, attendance,
  online classes, revision notes, logins, handovers, goals and tasks.
- Chat and voice recognize paraphrased cognition/Telegram requests before choosing
  search or screen interpretation. This protects literal forwarded text and makes
  recall requests bypass pending-question learning.
- Added parser tests, local-router integration checks, negation/payload guards,
  known-subject/saved-login fixtures, and power/remote restriction checks.
- No new dependencies or changes to the default AI action policy.
- Detailed inventory: `docs/COMMAND_FEATURE_COVERAGE.md`.

## Two-area follow-up

The first two checklist areas are implemented:

1. **Action corpus and source audit:** 247 family/action outcomes across all 54
   families now have 494 frozen phrase examples. A source inventory test fails on
   missing/stale outcomes or unknown computed action expressions. Media and Spotify
   share a parser, so these counts intentionally include overlapping family rows.
   The two YouTube helper outcomes excluded from media are explicitly checked as
   belonging to the apps parser. See `docs/COMMAND_ACTION_COVERAGE.md`.
2. **Saved-state routing:** added bounded phrasing and end-to-end local tests for
   routine edits/running/deletion; mode edits/quiet/start/end/deletion; project
   registration/resume-step edits/resumption/unregistration; file result selection;
   saved contacts and confirmation; reading-list items. Unknown/deleted names,
   expired results, invalid indices, exact message text and surviving project files
   are checked with temporary stores and mocked integration boundaries.

Focused verification: **511 passed**. Final verification, including the assertion
that unregistering preserves the project directory: **3,600 passed, 1 warning in
132.00 seconds** on 2026-10-16. At that stage five areas remained; the parallel
follow-up above implements that list.

### Verification status

- First broad feature pass: 757 tests passed before the later additions.
- Final targeted checks for parameterized requests and protections: 34 passed.
- Previous full run: `venv/Scripts/python.exe -m pytest tests -q --tb=short`:
  **3,089 passed, 1 warning in 309.40 seconds**. The warning is an existing
  Starlette/httpx deprecation; no tests failed or were skipped.
- Final two-area run:
  `venv/Scripts/python.exe -m pytest tests -q --tb=short --junitxml=tasks/command-language-verification.xml`:
  **3,600 passed, 1 warning in 132.00 seconds**. No failures, errors or skips.
  Historical output: `tasks/archive/command-language-3600-tests-verification.log`
  and the matching XML report.
- The interrupted session's result could not be recovered. The resumed run exposed
  an existing date-dependent prediction test: its October 1 data aged outside the
  router's current 14-day scoring window. Reproduced the failure in isolation and
  fixed the test to use its fixture clock throughout. All 15 prediction tests then
  passed. Application scoring was not changed. The failed-run log/XML are preserved
  as `tasks/command-language-verification-before-clock-fix.*`.
- All changed Python files parsed successfully. The checkpoint ZIP was read back
  and each of its 26 files checked against a SHA-256 manifest.
- Previous snapshot: `tasks/archive/command-language-3600-tests-checkpoint.zip`. It contains the selected
  workspace source/test/documentation files, including their pre-existing edits;
  it includes the final verification log/XML and excludes secrets, `.env`, runtime
  logs, databases, model files and the virtualenv.

The repository already contains extensive unrelated uncommitted/untracked work.
Preserve it. Do not stage everything or reset files. Changes are saved directly
in this workspace; no commit or remote push is implied by this checkpoint.

## Five follow-up work areas

The frozen corpus covers every currently inventoried parser action with examples;
it does **not** cover every parameter combination or arbitrary sentence. The original
areas 1 and 2 above are complete. The authorized parallel follow-up implements
these five bounded extensions:

1. Expand creation/editing language for timetable entries, marks, app limits, watch
   conditions, reminders, project steps, and goals/task progress reports.
2. Expand Spotify playlist/album/artist/queue variations and parameterized names.
3. Extend spoken numbers beyond volume/brightness into durations and result indices,
   with date/time ambiguity tests. Do not rewrite numbers inside literal payloads.
4. Extend multi-step planning beyond its existing app/device/media/stats/clock scope.
   Preserve all-or-nothing recognition and confirmation pauses.
5. Add conversational typo tolerance only with ambiguity checks. No global fuzzy
   matching that could turn negation, examples or unknown targets into actions.

Implementation and integrated verification are complete for all five items.
This completes the saved checklist, not every possible English sentence.
Music titles own ambiguous `and`; use `then` or a semicolon for the next action.
Literal note/reminder/message/dictation bodies own the remaining request. Batches
reject unknown steps before execution and pause for native confirmation; runtime
errors do not roll back completed steps. Mode/routine/project execution, login
entry and AI interpretation remain dedicated single requests.

UI-only and background capabilities (body animations, hotkeys, context menus,
automatic notifications/training, wrong-password alerts, provider failover) do not
currently expose separate natural-language commands. Do not invent or claim support
for commands that have no handler. Model-dependent features keep their current limits.

## Resume instructions

Read this file and `docs/COMMAND_FEATURE_COVERAGE.md`, then inspect
`services/automation/command_phrases.py`, `rephrase_command` in `command_words.py`,
the task/spoken-number/typo helpers, `tests/test_feature_language.py`,
`tests/command_action_examples.json` and the new routing/batch test modules.
The planned checklist is complete. For a newly reported missing variation, add a failing phrase test,
implement the smallest bounded mapping, and run the relevant checks. Preserve the
existing dirty workspace. The checkpoint ZIP is a reference snapshot, not permission
to overwrite later edits. Do not rerun a successful full suite unless source changes.
