# FRIDAY Habits & To-do

Double-click `interfaces/productivity/launch.vbs`, or run from the FRIDAY folder:

```powershell
venv/Scripts/pythonw.exe -B -m interfaces.productivity
```

Or use **All controls → Habits & To-do** in FRIDAY's taskbar/tray menu.
Restart FRIDAY once after installing this update to load the new menu and commands.
The desktop itself works without a running backend, internet or AI model.

The native Tkinter app has a dark navy/mint interface, a daily progress ring,
search, a daily overview, and separate habit and task views. It refreshes every
15 seconds; F5 refreshes immediately. Ctrl+N creates an item; Ctrl+F searches.

- **Habits:** create your habits and choose repeat weekdays. Check in for today
  or select a past scheduled date in the 14-day history. Uncheck to correct a
  report. Streaks skip rest days and give you until the end of today to check in.
  Archive hides a habit while keeping its full history; use Archived to restore.
- **Load habits:** paste one name per line or open a UTF-8 TXT/CSV file, then
  review and click Import. Existing names are skipped without replacing data.
  TXT defaults to daily habits. CSV requires `name`; `weekdays` and `notes` are
  optional. Weekdays are comma-separated numbers (Monday=0, Sunday=6):

  ```csv
  name,weekdays,notes
  Read 20 pages,"0,1,2,3,4,5,6",Before bed
  Exercise,"0,2,4",Morning
  ```

- **To-do:** loads every task already saved through FRIDAY, including finished
  history. Add/edit names, due dates, priorities and notes; filter by open,
  today, high priority or completed. Pause/resume and cancel preserve history.
  Finish simple tasks with an optional note. Planned tasks finish one step at
  a time with an owner completion report; unfinished steps cannot be bypassed.
  Completed/cancelled tasks stay read-only under FRIDAY's existing task rules.

Commands work through FRIDAY's normal command bar, chat and voice:

```text
open habit tracker
open to-do app
open daily dashboard
add habit: Read 20 pages
check habit: Read 20 pages
uncheck habit: Read 20 pages
habit progress
show my tracked habits
add todo: Buy a book
show my to-do list
complete todo: Buy a book
```

Existing `start task: ...`, `show my tasks` and task plan commands share the same
tasks. Existing `show my habits` still lists learned app-usage habits; those are
separate from your personal check-in tracker. Native window launch commands
are laptop-only; authenticated Telegram commands can manage the shared lists.

Storage uses FRIDAY's existing `memory/mind/cognition.db` (or configured cognition
path), in `tracker_habits`, `tracker_checks`, `tracker_task_meta`, and existing
`workspace_tasks` tables. No demo records are added to your personal database.
Habit summaries join FRIDAY's bounded shared cognition context; check-ins and
task completions are owner reports. Dates use the computer's local calendar.
Editing a weekday schedule applies the new schedule when calculating streaks;
previous check-in records are retained. There are no automatic notifications
or reminders from this app; use FRIDAY's reminder commands for timed alerts.

Validation errors keep drafts open. Concurrent changes reject stale saves or
check-ins: close the draft, refresh and review the current record before retrying.
Closing waits for any in-progress save. Only Tk's main thread touches widgets.
