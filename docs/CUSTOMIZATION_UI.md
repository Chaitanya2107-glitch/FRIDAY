# Customize FRIDAY

Exit the taskbar widget and run `launch_friday.vbs` again to load the new desktop
entry and backend support. In a tray-only layout, use **Quit FRIDAY** instead.
Normal launch starts FRIDAY in the background; after an explicit Stop you can
choose **Start FRIDAY**. In the taskbar panel,
choose **All controls → Customize FRIDAY…**. The same item appears in the tray
menu when using the tray interface.

You can also open it from the project folder:

```powershell
.\venv\Scripts\python.exe -B -m interfaces.settings
```

Keep FRIDAY running while editing. If it is offline, start it and select Reload.
If an older backend is running, the editor asks you to restart FRIDAY.
If the backend was started manually in a separate terminal, restart it there too.

The window has four tabs:

- **Contacts:** add, rename and remove saved WhatsApp contacts. Enter a country
  code explicitly, such as `+44 7700 900123`; the existing default-country rule
  still applies to a local ten-digit number.
- **Routines:** add, edit and remove routines. Put one command on each line, in
  order. Pauses such as `wait 2 seconds` use the existing routine behavior.
- **Projects:** browse to an existing folder, set an optional `owner/repository`,
  add website domains or HTTP/HTTPS URLs, and edit resume commands. Blank resume
  commands use FRIDAY's standard project resume behavior. Removing a project
  keeps its folder and files. Saved changes refresh activity classification.
- **Modes:** add, rename and remove modes, edit startup commands, and choose
  quiet behavior. A running mode must be ended before renaming/removing it.
  Edited preferences apply the next time that mode starts.

Use the filter to find an entry, **+ New** to create one, **Save changes** to
persist it, and **Delete** to remove its configuration.
Renaming an entry does not rewrite commands in other routines that refer to its
old name. Use the scrollbar or mouse wheel for longer forms. Command boxes also
scroll independently.

Keyboard shortcuts: **Ctrl+S** saves the current tab, **Ctrl+N** starts a new
entry, and **F5** reloads. Drafts stay in their own tabs while switching tabs.
Changing selection, reloading or closing asks before discarding unsaved edits.

If chat or another window changes settings while a form is open, saving refuses
the stale edit and keeps the draft. Reload to get the current version. An invalid
saved file is preserved and must be repaired before editing that catalog.

Saving contact/routine/project/mode settings does not send messages, run stored
commands, open projects or activate a mode. Use the existing chat/tray controls
when you want to run them. Contact edits invalidate pending WhatsApp sends, and
project edits invalidate pending resume offers, so an old confirmation cannot
silently use a newly edited recipient or project setup.

No new packages or AI calls are required. The editor uses the local backend and
its existing settings files. It runs separately from FRIDAY's body and command
bar; closing it leaves FRIDAY running.

Synthetic previews: [Contacts](../tasks/customization-preview/contacts.png),
[Routines](../tasks/customization-preview/routines.png),
[Projects](../tasks/customization-preview/projects.png),
[Modes](../tasks/customization-preview/modes.png).
Verification: [review notes](../tasks/customization-review-notes.md).
