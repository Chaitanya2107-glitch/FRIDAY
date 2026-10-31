# College Schedules

A separate native Tkinter window for FRIDAY's classes, faculty, assignments,
homework, exams and events. It uses the existing local backend and shared stores.

**Quit FRIDAY from the tray and relaunch to load.** With the taskbar widget,
exit/relaunch the widget too so its All controls menu reloads. A backend started
manually must be restarted in its own terminal.

## Open the window

- **All controls → College Schedules…**, beside Customize FRIDAY in the tray menu.
- Tell FRIDAY **“open college schedules”**.
- Double-click `college_schedules.vbs` or `college_schedules.bat`. The launcher
  uses the project's venv pythonw and the existing taskbar startup when the
  backend is offline. A second launch restores the existing college window.
- With the backend running: `venv\Scripts\python.exe -B -m interfaces.college`.

The standalone module can stay open while the backend is offline. Start FRIDAY
and choose **Retry / Refresh**. Closing this window leaves FRIDAY running.
The client connects to `http://127.0.0.1:8000`; it has no browser or phone UI.

## Tabs and editing

- **Home:** current/next effective class, faculty, room, saved class Join link,
  today's timeline, work due within seven days (including overdue work), next
  exam and upcoming events. “who takes my next class” uses the same registry.
- **Timetable:** a weekly day/time grid. Select a time row and day, or click a
  class cell. Add/edit/remove weekly slots or choose **Change this date only**.
  Dated edits preserve duration and use FRIDAY's existing cancellation,
  attendance, future-time and linked-reminder guards. Cancellations are read-only.
  Use the separate **Subject details** list to save faculty, room, email and
  notes. Faculty changes do not modify a weekly template or detach dated edits.
- **Assignments & Homework:** filter by subject, status and kind. Create, edit,
  complete or delete the same deadlines FRIDAY lists in chat/voice. Completed
  rows remain available to the window's Done filter; active chat/countdowns omit
  them. Existing completion behavior removes correction history/reminder links.
- **Exams:** subject, date, time, venue and notes are stored as recognizable exam
  deadlines, preserving the existing briefing/countdown. No new exam notifier.
- **Events:** dated campus plans, start/end, location and notes. These appear in
  the window and `show college events` answers. The local briefing includes up
  to three events in the next seven days. No new event notifications are scheduled.
- **Upload:** an editable timetable preview and reviewed merge/replace diff.

Enter dates as `YYYY-MM-DD` and times as 24-hour `HH:MM`. Server validation is
authoritative. **Ctrl+N** creates, **Enter** edits/saves, **Escape** closes a
dialog, **Delete** confirms removal, **F5** refreshes. Use Tab/Shift+Tab through
fields; Ctrl+Enter saves from multiline notes.

Drafts require confirmation before discarding. All HTTP/file reads run in the
background. The window refreshes on focus and every 60 seconds, retaining drafts
and upload previews. A stale save is refused; the draft stays open and the list
reloads. **Review current version** explicitly rebases a reviewed draft. A changed
weekly template must be selected again to avoid editing a different class.

Due-date changes can show **“N reminder updates pending — tell FRIDAY 'review
reminder updates for X'”**. Apply or reject them through FRIDAY's existing local
conversation controls. The window never shifts reminders automatically.

Class links stay in the existing college store. Save one with, for example,
“DBMS class link is meet.google.com/…”. Home enables Join only for saved HTTP/HTTPS
links. Subject aliases/acronyms reuse the existing timetable naming rules. Local
class answers and the spoken briefing read the same subject-room override as
Home. Existing class warnings can be mirrored, so they omit a superseded room
instead of exposing the new registry value. Structured Telegram reports retain
legacy template rooms. New event/faculty commands are refused over Telegram;
event briefing content is local only.

## Uploads and limits

Choose PNG/JPG, PDF, DOCX, XLSX or UTF-8 CSV, at most **10 MiB**. The API accepts
bytes, never an arbitrary local path; it checks extensions and actual content.
No original upload, manifest or timetable change is saved before **Confirm**.
Pending previews are held in memory for 15 minutes, at most four files.

Local tables should have **Day, Start, End, Subject, Room** headings. Day-column
matrices such as `Time, Monday, Tuesday` with `09:00-10:00` ranges are also
supported. XLSX reads the active worksheet; DOCX reads labeled tables or delimited
paragraphs. Text PDFs require recognizable delimited rows; unfamiliar text layouts
offer manual preview-row entry and stay local. Only PDFs with no extractable text
use the vision consent step. PDF extraction uses the first three pages;
encrypted PDFs and documents over 30 pages are refused. Tables are limited to
300 class rows and 100 columns. Arbitrary decorative timetable layouts are not
guaranteed to parse correctly. Review and correct every imported time/subject.

Images and scanned PDFs require a consent dialog naming the exact provider and
model before any image is sent. This upload request uses that fixed recipient;
it does not try other providers or OpenRouter backup models. Existing provider
policy is preserved, including its assist-only refusal of this extraction
purpose. If unavailable, enter preview rows manually or use a local table.
No live provider inference was used for verification.

Edit preview rows, inspect warnings, choose **merge** (default) or **replace**,
then **Review diff** and **Confirm import**. Changed rows/mode require a new
review. Unknown subjects are warnings; invalid fields/overlaps block Confirm.
An intervening chat edit refuses the stale confirmation and loads the current
revision for another review. Unchanged legacy template dictionaries are retained
in both modes. Intentional weekly value changes can detach existing dated records
for that modified slot, matching FRIDAY's existing weekly-edit behavior.

Confirmed originals use random names under `memory/college/uploads/` and can be
listed/deleted without deleting the imported classes. This first version imports
**timetables only**; enter exam schedules in the Exams tab. Office ZIP expansion
is bounded; PDF text decoding still depends on the installed parser's resource
behavior. Schedule, manifest and original bytes are individually atomic files,
with rollback on caught publication errors; they are not one crash transaction.

No attendance/marks/syllabus editor, class cancellation control, Telegram access,
additional packages, model-policy changes or notification logic is included.

## Implementation and evidence

`interfaces/college/` is an HTTP client; `services/college/` owns validation and
projections; `interfaces/api/routes/college.py` exposes loopback-only
`/api/v1/college/{overview,timetable,subjects,deadlines,exams,events,uploads}`.
Subject details/events use the existing atomic publisher and SQLite writer guard.
Deadline history keeps `source: owner_report` with additive `origin: college_ui`.

Discovery: `tasks/college-schedules-discovery.md`. Design:
`docs/specs/2026-10-29-college-schedules.md`. Verification counts, source hashes,
limits and changed files: `tasks/college-schedules-verification.json`.
Synthetic native images: `tasks/college-schedules-preview/` (six actual tabs).

Reproduce isolated checks with `venv\Scripts\python.exe -B
tasks/run_college_checks.py focused`, `full`, and `native`. Full plus native
covers the suite in separate processes, avoiding the earlier incomplete combined
native baseline. Tk checks run normally, following Customize FRIDAY's convention;
unrelated opt-in GUI tests retain their existing skip mechanism.
