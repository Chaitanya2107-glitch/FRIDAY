# FRIDAY embedded taskbar button and flyout

The owner rejected the conventional app window and authorized a persistent
taskbar button resembling the weather entry point, with a transient control
flyout. Root owns all writes; the two existing helpers only research/review.
Pre-existing unrelated changes and the backend's private shutdown event stay.

Use an application-owned native WS_CHILD in measured free Shell_TrayWnd space.
This is an out-of-process hosted control, not a shell-allocated Widgets slot.
No Explorer injection, shell binary replacement, taskbar setting changes or
taskbar process restart. Match the parent's DPI context before creation; keep
the host message thread free of HTTP, UI Automation, disk I/O and Tk work. Native
app-group and notification bounds define a free gap, with intersecting controls
excluded. Auto-hidden group bounds remain usable. Hide when the
layout cannot be measured safely; reconnect after taskbar HWND replacement.

The launcher stays resident when FRIDAY is stopped. Clicking it opens an
unowned top-level toolwindow flyout and starts the backend if needed. Clicking
elsewhere or Escape dismisses it. Stop FRIDAY preserves the button; Exit widget
is the explicit resident-process exit. The owner's later VBS/background-startup
request supersedes the initial stopped-by-default entry point: normal launch
starts the backend once through its worker. Explicit Stop leaves the widget
resident without restarting on idle ticks. Existing hotkeys remain usable.

Verify geometry selection/collision/clamping, DPI behavior, native parent and
styles, no separate app taskbar entry, click/start/stop/click-away/menu behavior,
duplicate launch and taskbar-parent replacement. Use synthetic state for GUI
checks, then switch the authorized installed desktop and verify live state.

Coordination discovery remains as previously recorded: no registered Ruflo
guidance tools; legacy local policy and missing ledger anchor. Do not repair
or bypass that ledger. All local work is based on the owner's explicit build
authorization and the environment's existing permissions; record scoped hashes
and evidence. Installation outside the workspace/GUI activation uses the
environment's approval mechanism after validation.
