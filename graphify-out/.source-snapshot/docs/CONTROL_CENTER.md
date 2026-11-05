# FRIDAY Control Center

A native Tkinter home for FRIDAY's features, commands, usage guides and controls.
It reuses the existing backend, permissions and native editors. No extra package
installation is needed in the existing FRIDAY Python environment.

## Open the window

Double-click `interfaces/control_center/launch.vbs`, or run from the FRIDAY folder:

```powershell
venv/Scripts/pythonw.exe -B -m interfaces.control_center
```

For a visible console when diagnosing startup:

```powershell
venv/Scripts/python.exe -B -m interfaces.control_center
```

After restarting the existing FRIDAY desktop, its **All controls** / tray menu
also has **Control Center & Guide**. A second launch focuses the existing window.
Closing the control center leaves FRIDAY running.

## Your first command

1. Open **Capabilities**. Search for what you want, such as reminders, Spotify,
   files, tasks, phone, browser, screen, or classes. Filter by category.
2. Read **What it does**, **How to use it**, and **What it needs**.
3. Select an example and choose **Use command**. This prepares an editable draft.
4. If the backend is offline, choose **Start FRIDAY** on Overview. Startup may
   take a few minutes when local models load; use **Refresh** to check readiness.
5. Edit names, times or details. Choose **Send** or press **Ctrl+Enter**.

Enter adds a new line. A failed request retains the draft. Requests are submitted
once; an HTTP failure may occur after an action ran, so inspect its result before
retrying. Examples never execute merely because you browse or select them.

## Commands to try

| What you want | Example |
| --- | --- |
| Plan the day | `brief me` |
| Next class | `what's my next class` |
| Reminder | `remind me in 10 minutes to stretch` |
| Find a document | `find my resume` |
| Check tasks | `show my tasks` |
| Read memory | `what do you remember about me` |
| Daily habits | `open habit tracker` |
| Browser/research help | `browser help` |
| Phone setup status | `phone status` |
| Screen-awareness status | `screen awareness status` |
| Development changes | `development status` |

The catalog includes all families in FRIDAY's production command phrase registry,
their aliases, and additional current capability groups. The full local guides
describe further parameterized commands, automatic behavior and limitations.
Examples use illustrative project/subject names; substitute your saved names.

## Confirmations and tasks

FRIDAY's reply appears in **Command chat**. When it requests confirmation, read
the question before choosing Yes/No or typing a more specific answer.
Browser automation uses **Browser yes** / **Browser stop**; the computer agent
uses `\c yes` / `\c stop`. Their approvals stay scoped to the proposed step.
Desktop tasks use **Desktop yes**, which starts the target-app countdown before
approving the step. Computer-agent approvals use the same handoff.
Task progress is polled only for a job started from this chat. **Tools & controls
→ Stop automation** requests cancellation through the existing runtime.

## Work with another app

Screen questions, selections and desktop tasks must act on the intended app.
Choose **Target app (3s) → Send**: this window minimizes. Click the target app
within three seconds. FRIDAY checks that the same window/process is still active
before submitting the request. A completed reply restores this window.

For typing/dictation, keyboard steps are shown as **Prepared input**. Review the
text/keys, then choose **Apply prepared input to app (3s)** and click the editable
destination. Input is applied once with foreground checks before each step.
If an operation stops, inspect the destination before retrying; some input may
already have been submitted. Keyboard shortcuts can change the active window,
which intentionally stops later steps in the same prepared sequence.

The existing **Ctrl+Shift+F** command bar remains available for target-aware
commands. See [all features](FEATURES.md) and [browser supervision](BROWSER_AUTOMATION.md)
for the computer agent's existing restrictions.

## Providers, voice and native tools

The chat provider selector overrides the provider for this chat request only.
**Speak this chat's replies** controls speech for typed replies from this window.
It does not change the desktop's global preference. Available provider names are
registrations, not evidence that credentials or models are ready.

Typed chat here requires desktop listening, Hey Friday and conversation to be
off, so a microphone turn cannot race a typed answer or confirmation. Turn them
off in Tools & controls before sending, or use the existing Ctrl+Shift+F command
bar, which supports typing during a voice conversation. This window's voice
buttons still use the existing controller; it does not run its own recording loop.

**Tools & controls** opens the existing Customize, College Schedules, and Habits
& To-do windows. These retain their own editing, validation and draft safeguards.
The same page delegates microphone, Hey Friday, conversation, body, all-controls
and restart actions to FRIDAY's authenticated desktop controller. These are
requests: **Live status** reports the resulting state. It does not create a
second microphone controller or backend. The integrated desktop bridge must be
available; ordinary chat still works through the local REST API when it is not.

| Keyboard shortcut | Action |
| --- | --- |
| Ctrl+K | Search capabilities |
| Ctrl+L | Focus command chat |
| Ctrl+Enter | Send chat draft |
| F1 | Open this guide |
| F5 | Refresh runtime status |
| Ctrl+Shift+F | Existing FRIDAY command bar |
| Ctrl+Alt+Space | Existing listen/stop hotkey |
| Ctrl+Alt+H | Existing Hey Friday toggle |
| Ctrl+Alt+C | Existing conversation toggle |

## Offline, privacy and status

Capabilities and guides work without backend, internet, microphone or AI.
Opening the control center never starts FRIDAY or a recording session by itself.
Runtime reads show unavailable data explicitly, and a lost connection replaces
the prior status. Spotify status describes saved authorization, not a live
playback test. Optional integrations keep their existing setup requirements.

This interface does not write a transcript to disk, export private replies, or
log chat text, phone contents, tokens or keyboard steps. Backend chat keeps its
existing history policy; private commands keep their existing exclusions.
**Load history** explicitly loads recent shared history. **Clear shared chat
history** asks before clearing chat/context/caches and preserves owner facts.
Screen questions and online providers keep their existing data-handling rules.

Read [screen-awareness privacy](screen-awareness.md), [phone setup](PERSONAL_ASSISTANT_UPGRADES.md),
[AI setup](AI_ASSISTANCE.md), [college](COLLEGE_SCHEDULES.md), and
[habits & to-do](HABITS_AND_TODO.md) in **How to use**.
