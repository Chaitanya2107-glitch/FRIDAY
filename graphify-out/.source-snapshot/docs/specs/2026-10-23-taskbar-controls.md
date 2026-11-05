# FRIDAY taskbar controls

The owner authorized implementation after agreeing to a pinned FRIDAY taskbar
icon and compact controls. Root owns all writes in this checkout; startup and
UI helpers are read-only. Existing unrelated changes are preserved.

Use Tkinter and the existing FridayTray controller, command bar, hotkeys and
desktop body. The normal launcher opens a dark native taskbar window without
a visible tray icon. Minimize/close keeps FRIDAY accessible on the taskbar;
Quit stops the UI and gracefully closes its owned backend. Start/restart run
off the UI thread. A second launch restores the existing panel before any
backend is started. An existing manually started backend is never stopped.

Create a shortcut with matching Windows AppUserModelID, relaunch command and
FRIDAY icon. Windows' standard Pin to taskbar action makes it permanent; do
not rewrite Explorer's taskbar registry or restart Explorer. Installing a
Start menu shortcut and opening the real GUI requires the environment's
approval for writes outside the workspace and GUI launch, after validation.

Verify duplicate launch, readiness failures, owned process cleanup, restart,
all microphone modes stopping together, existing tray/voice regressions,
shortcut property round trip and a synthetic real-Tk UI preview. No provider
requests, model downloads or owner data modifications are needed for checks.

Coordination discovery: no Ruflo MCP guidance tools are registered. Cached
CLI memory search reports Database not found. Local policy state is legacy
with no action capabilities, rules or lease harness. The receipt records
user-authorized local development, not a production capability or release.
