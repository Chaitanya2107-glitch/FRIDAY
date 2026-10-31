# F.R.I.D.A.Y

Browser/research automation (2026-10-22): Playwright, Scrapling and pywinauto
now support explicit supervised browser/Windows tasks and bounded cited research.
Browsers are visible by default; `research headless <subject>` or
`browser task headless <task>` hides the window. Use `browser status`,
`browser yes`, `browser stop`, and `research report`. See
[commands, setup and current limits](docs/BROWSER_AUTOMATION.md).

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


A personal AI assistant for Windows, in the style of Iron Man's FRIDAY. She lives in the system tray, takes typed and
spoken commands, controls apps and the PC, remembers things about you, keeps track of college work, and talks on her
own when it's a good moment.

**Everything she can do, with example phrases: [`docs/FEATURES.md`](docs/FEATURES.md).**

Brain/life upgrades and the continuation plan: [saved roadmap](docs/BRAIN_LIFE_ROADMAP.md).
The first increment adds locally reviewed, dated commitments with correction history shared by
conversation, reasoning and life reports. See [temporal situation memory](docs/CONNECTED_BRAIN.md#temporal-situation-memory-2026-10-20).
Behavioral life state now guides silent review, responsibility focus and optional interruptions. Quiet
preferences and learned timing affect decisions; silence does not cause sulking. Inspect `brain status`
or the local `/api/v1/mind/life` API. Later phases remain in the saved roadmap.

## Setup (once)

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

FRIDAY's direct commands and local memory work without a model or API key.
By default AI understands informal commands and typos, and handles conversation through chat,
voice and Telegram. Known commands stay fast and local. Unfamiliar requests are translated into
commands for the existing local router, which retains confirmations and channel restrictions.
OpenRouter handles the language layer online, with installed Ollama as the offline/failure fallback.
Background cognition and notification judgement use local Ollama only, with no cloud fallback.
FRIDAY now retains dated dialogue/paired answers for shared local reasoning and relevant recall.
Meaningful changes wake executive attention. Autonomous inquiry can ask one useful question or remain
silent; the scheduled evening questionnaire is removed. Use `brain status` to inspect decisions.
See [connected cognitive processing](docs/CONNECTED_BRAIN.md) for scope and limits.
Her executive layer also reviews changed goals, tasks, dated facts and execution receipts in the
background, with at most four reviews per hour. It produces evidence-backed proposals and preserves
source task progress. Use `executive status`, `executive review off` or `executive review on`.
Before opening a project session, local preflight checks record the intention and expected outcome.
Her notification brain also checks proposed notices against current facts and activity before sending.
Use "notification status" or "why did you not send that notification" to inspect decisions.
Due reminders remain recoverable if brain review or delivery fails; "retry failed reminders" queues a fresh review.
If neither language provider answers, FRIDAY reports that the language AI is unavailable;
direct local commands continue working. Set `AI_LANGUAGE_ENABLED=false` for prepared local replies.
Notification reviews instead keep reminders pending until a valid decision becomes available.

For local AI assistance, install [Ollama](https://ollama.com) and pull the model named in `OLLAMA_MODEL`.
FRIDAY starts it silently on demand and closes the server she started after five idle minutes.
See [AI assistance and offline behavior](docs/AI_ASSISTANCE.md) for settings and limitations.

Use `train_friday.bat` to review Friday's saved predictions. Mark each correct, wrong or unsure; definite feedback teaches future guesses automatically. See [prediction review](docs/PREDICTION_TRAINING.md).
See [Training FRIDAY](docs/TRAINING.md) for the commands and what each lesson changes.

## Starting her

| How | What it does |
|---|---|
| FRIDAY taskbar button | Click to start FRIDAY and open its control flyout |
| `launch_friday.vbs` | Shows the taskbar widget without a console |
| `launch_friday.bat` | The same, with a console window |
| `run.bat` | Backend only, with its output visible (for debugging). API docs at http://127.0.0.1:8000/docs |

Install with `venv\Scripts\python.exe -B -m interfaces.taskbar.install --startup --launch`.
The widget appears when signing in; FRIDAY starts when you click its button.
The flyout includes listening, wake word, conversation, spoken replies, start, stop and restart.
**All controls** contains the previous tray menu, including the body, provider and routines.
Click outside or press Escape to dismiss the flyout. **Stop FRIDAY** keeps the taskbar button available.
**All controls > Exit taskbar widget** closes the resident widget and its owned backend.
An already-running backend started elsewhere is left alone; stop it in its own terminal to switch to managed startup.
See [taskbar setup](docs/TASKBAR.md) for details.

The launchers find the project folder automatically. Launching again shows the existing flyout
without starting another backend. Quitting preserves applications FRIDAY opened for you.

## Main hotkeys

| Keys | |
|---|---|
| **Ctrl+Shift+F** | Command bar: type anything |
| **Ctrl+Alt+Shift+F** | FRIDAY taskbar controls |
| **Ctrl+Alt+Space** | Talk (stops on silence) |
| **Ctrl+Alt+H** | "Hey Friday" on/off |
| **Ctrl+Alt+C** | Conversation mode |
| **Ctrl+Alt+F** | Dictate into the command bar with Handy |

From a terminal: `friday open spotify`, `friday "what's due"`, or pipe into it (`git diff | friday "review this"`).

## More docs

- [`docs/FEATURES.md`](docs/FEATURES.md): every feature and how to use it
- [`docs/current_state.md`](docs/current_state.md): what's built and how
- [`docs/architecture.md`](docs/architecture.md): how the code is organised
- [`docs/roadmap.md`](docs/roadmap.md): what's next
- [`docs/CHANGELOG.md`](docs/CHANGELOG.md): what changed when
