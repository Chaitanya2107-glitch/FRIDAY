# Browser automation, Windows controls and subject research

Implemented 2026-10-22 following the owner's approved Playwright/pywinauto/Scrapling
design. Restart FRIDAY after installing/updating to load the new commands.

## Use it

| Command | Behavior |
| --- | --- |
| `browser task open https://www.python.org` | Start a supervised task in a visible, task-owned Chromium browser. |
| `browser task headless open https://www.python.org` | Same action/observation path, without a browser window. |
| `\b headless find the documentation link on https://www.python.org` | Short browser-task form. |
| `research PID versus reinforcement learning for robotic arms` | Search, read up to six pages and save a cited report; visible browser by default. |
| `research headless PID versus reinforcement learning for robotic arms` | The same rendered research path, without a window. |
| `browser status` / `research status` | Actual current phase, latest receipt and pending proposal. |
| `browser yes` / `\b yes` | Approve exactly one displayed step. |
| `browser stop` / `stop the browser task` | Cancel work, invalidate pending approval and close owned resources. |
| `research report` | Read the last report and its saved location. |
| `desktop task open Notepad` | Propose opening Notepad, then observe its controls. |
| `desktop task type exactly Hello world into the editor` | Work with foreground Notepad/Notepad++ using Windows UI Automation. |
| `desktop yes` / `desktop status` / `desktop stop` | The same explicit task controls for native Windows work. |

The command bar automatically refreshes progress after starting/approving a task
and displays the next reviewable step without taking app focus. Opening the bar
to enter a new command ends the old progress subscription. Voice supports the
same spoken commands; ask for status and approve with the explicit task prefix.
Generic `yes` does not approve an automation step.

Only one browser/research/native automation task runs at a time. An unrelated
local command abandons a pending proposal; it does not cancel a running research
collection. Tasks and approvals are ephemeral and are not resumed after restart.

## What each dependency does

- Playwright owns browser navigation, page/control observation, reviewed input
  and rendered research fetching. Its isolated context uses no personal Chrome
  profile or stored login. Task completion/stop closes this owned browser.
- Scrapling 0.5 parses the same page HTML with adaptive storage disabled. It
  extracts title/content without another browser stack; visible main/article
  text takes precedence for rendered visibility. Fetcher/stealth extras are not
  installed. Source text is always untrusted data.
- pywinauto 0.6.9 provides Windows UIA control targeting and readback. Its initial
  scope is foreground Notepad/Notepad++ and recognizable English Open/Save file
  dialogs, not arbitrary Windows applications. Other desktop tasks retain the
  existing separately gated `\c` feature.

Headless is a visibility option, not a reduction in evidence checks. Both modes
use the same browser engine, viewport and rendered extraction. Individual sites
may still behave differently or block automation; failures are reported rather
than silently switching visibility or claiming equivalent coverage.

## Reviewed actions and evidence

Browser/native tasks use a closed proposal schema: navigate, launch Notepad,
click an observed control, enter literal text, press a small set of keys,
download a direct public link, finish with observed evidence, or request help.
The configured language provider can propose a step only for an explicit task.
It receives bounded observations, never arbitrary execution tools. Every input
proposal requires owner approval, including form submission and file overwrite.

Approval expires after 120 seconds and is consumed once. Before input, the
adapter checks the current page/window fingerprint, field state and target
identity; a changed page/control fails closed. Native text entry also checks
foreground/focus and reads the resulting value. Password/protected payment
fields are excluded. No arbitrary scripts, selectors or shell commands are
accepted from the model.

Click/key receipts mean the input was submitted. They do not independently prove
a purchase, send, file save or other business outcome. The following observation
must support the proposed completion; the model must quote that observation.
This is still a model judgment, not a guarantee of correct task completion.

Downloads support direct public HTTP(S) GET links, with bounded redirects,
30-second streaming budget, 100 MiB cap, cancellation checks and unique names.
Completed receipts include actual file size and SHA-256. Files are never opened
or executed. Authenticated, blob and button-only downloads need owner help.
Partial download files are removed from the task's owned directory.

## Research reports

Research generates up to two complementary search queries alongside the original
topic, discovers results through existing DDGS search, deduplicates URLs and
prefers distinct domains before taking additional pages from one domain. It reads
at most six HTML pages, with no automatic form submissions or browser inputs.
There is no recursive site crawl or claim of exhaustive subject coverage.

The report contains findings, exact supporting evidence, source links, retrieval
time, search queries and uncertainties/fetch failures. A synthesis claim must
identify a retrieved source and copy an exact supporting quote; total copied
words per source are capped at 25. This validates evidence location, not semantic
entailment or source truth. A separate bounded model call checks each complete
claim against its named source and removes unsupported claims; that judgment can
also be wrong. The model is asked to flag disagreements and gaps.
Publication dates are not independently verified; retrieval time is explicit.

When inference or evidence checks fail, save labeled source excerpts instead of
inventing conclusions. Collection has a 110-second budget, leaving time to save
a partial report. The complete research job is bounded to 180 seconds.

Reports live under `memory/research_reports/`; downloads under
`memory/automation/downloads/<task-id>/`. Completed files are owner-requested
artifacts. They are not automatically added to brain memory. The command exposes
the most recent report; older saved reports remain files in that directory.

## Settings, privacy and execution limits

Install with the existing venv:

```powershell
venv/Scripts/python.exe -m pip install -r requirements.txt
venv/Scripts/python.exe -m playwright install chromium
```

Pinned dependencies: Playwright 1.64.0, Scrapling 0.5 parser, Windows pywinauto
0.6.9. The packages and Chromium have been installed in this workspace's venv.

`BROWSER_AUTOMATION_ENABLED=true` enables this explicitly requested feature.
`AI_LANGUAGE_ENABLED` controls proposal/query/synthesis model use. Existing
`AI_ASSIST_ONLY` remains enabled; a narrowly scoped `automation_proposal` purpose
permits reviewable JSON proposals and still prohibits model execution tools.
Foreground tasks use the selected/configured provider and existing failover
policy. They do not change brain-review budgets, background local-only policy,
model installation or the existing vision-agent gate.

Each browser observation is capped at 80 controls, 12,000 control-description
characters and 12,000 text characters; model
proposals use at most 500 output tokens. Browser/native tasks allow 20 inputs
and a 10-minute total lifetime. Gaming blocks start and subsequent reviewed
inputs. Approvals and source bodies stay out of ordinary chat/brain history,
command caches and speech caches. Research queries go to the search provider;
observations/source excerpts go to the selected language provider as requested.

The shared handler rejects remote/Telegram start, status, approval, report and
stop requests. Existing API host/origin protection also applies to
`GET /api/v1/automation/status`. Logs retain phases/error types rather than page
bodies or proposed typing.

Browser and UIA adapters run in owned helper processes. Windows browser helpers
enter a kill-on-close job before launching Chromium, bounding cleanup even if a
renderer hangs. UIA's helper can be terminated without closing the owner's target
app. Cancellation cannot undo input already submitted. Repeated stop is idempotent.

Only public standard-port HTTP(S) destinations are accepted, including redirect
and browser subresource checks. These are URL/DNS checks, not a network sandbox:
connection-time DNS rebinding is not prevented by a pinned transport. This feature
does not expose an unrestricted local-network fetch or claim sandbox isolation.

## Verification

Automated cases cover command boundaries, public URL/redirect rejection,
download caps/cleanup, proposal schemas, explicit policy gating, consumed/expired
approvals, cancellation before/during work, repeated stop during cleanup,
report bounds/deduplication, fabricated-quote rejection, remote denial, typed/voice
routing, origin checks and stale progress subscriptions.

Live checks use task-owned fixtures and public read-only pages:

- `tasks/probe_browser_automation.py`: actual headed/headless Chromium, exact
  text readback, owner-edited field rejection, replaced-node rejection, click
  result observation and forced hung-worker/browser-tree cleanup.
- `tasks/probe_browser_native.py`: actual pywinauto control enumeration, literal
  field entry/readback and button-result observation in a disposable Win32 dialog.
  This does not establish compatibility with every Notepad version or Windows app.
- `tasks/probe_browser_research.py`: real installed Ollama model, actual browser
  and Scrapling, grounded two-source synthesis, saved report and validated action
  proposal. Sources are controlled fixtures; no cloud model or owner state used.
- `tasks/probe_browser_public.py`: real DDGS discovery and rendered extraction of
  the public Python tutorial with URL/title retained.

Evidence files: `tasks/browser-automation-live.json`, `-native.json`,
`-research.json`, `-public.json`, and `browser-automation-visible.png`.
Full regression evidence: `tasks/browser-automation-verification.log` and `.xml`.
Final focused run: 317 passed. The initial full run had 5,470 passes and one
voice-route failure, fixed and retested in that focused run. A second complete
run was not performed. See `tasks/browser-automation-review-notes.md` for the
precise verification boundary.

## Later work

Ordinary-chat follow-up/commitment linkage remains explicitly queued in
`BRAIN_LIFE_ROADMAP.md`. Macro recording, reusable browser procedures, persistent
authenticated profiles, arbitrary desktop-app support, and recursive research
crawling are not implemented by this feature.
