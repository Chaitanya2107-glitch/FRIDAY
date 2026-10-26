# FRIDAY taskbar button

FRIDAY has a resident button at the far-left end of the primary Windows taskbar. Clicking it
opens a small control flyout and starts the assistant if it is stopped. Click
the button again, click outside, press Escape or use the close button to dismiss
the flyout. There is no visible tray icon or separate control-panel app button.

Install from the project folder:

```powershell
venv\Scripts\python.exe -B -m interfaces.taskbar.install --startup --launch
```

This creates current-user Start menu and Startup shortcuts. Normal launch shows
the widget and starts FRIDAY's backend in the background. The VBS/BAT launchers
use the same path. Launching again shows the existing flyout and starts FRIDAY
if it was stopped, without creating another desktop or backend. The shortcuts
use absolute paths. Run the installer again after moving the project.

The flyout offers the command bar, listening, wake word, conversation, stopping
the microphone, spoken replies, Start, Stop and Restart. **All controls** contains
the previous tray menu, including **Customize FRIDAY…** for all four Tkinter
editors, plus provider, routines and body controls.
Existing hotkeys remain available. **Ctrl+Alt+Shift+F** toggles the flyout too.

**Stop FRIDAY** stops this desktop's backend and leaves the button available.
The widget stays stopped until a launch, button click or Start request.
**All controls > Exit taskbar widget** exits the resident launcher and its owned
backend. Stop/Restart are enabled only for a backend started by this desktop.
A backend started in another terminal is reused and must be stopped there.
Applications FRIDAY opened for you are preserved when it stops.

The button follows the taskbar's auto-hide setting. It uses a measured free gap
before Start and the app buttons, adjusts to layout changes, and
reconnects after Explorer recreates the taskbar. If there is no safe space, the
button hides; the hotkey or Start menu shortcut still opens the controls. This
uses native window parenting, not a Windows Widgets registration. Explorer does
not reserve the gap, so future Windows taskbar changes may require an update.
No shell injection, Explorer restart or additional dependency is used.

Diagnostics: `logs/desktop.log` and `logs/backend-desktop.log`.

Checks:

```powershell
venv\Scripts\python.exe -B -m pytest tests/test_taskbar_widget.py tests/test_taskbar.py tests/test_launcher.py tests/test_tray.py -q
$env:FRIDAY_PANEL_UI_TEST='1'
venv\Scripts\python.exe -B -m pytest tests/test_taskbar_panel.py -q -s
```

GUI checks use synthetic state, mocked microphone calls and disposable test
windows. They cover native parenting, flyout styles, controls, click dismissal,
repeat activation, stopped-state residency and parent replacement. They do not
restart Explorer, start the real backend or call an AI provider.
