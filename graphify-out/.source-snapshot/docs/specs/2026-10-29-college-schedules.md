# College Schedules — 2026-10-29

Build a separate native Tkinter HTTP client, runnable with
`python -m interfaces.college`. Six notebook tabs: Home, Timetable,
Assignments & Homework, Exams, Events, Upload. Timetable includes a subject
details editor for faculty/room/email/notes. Existing chat/class links remain
authoritative. Reuse Customize FRIDAY's ttk theme, background result queue,
draft baselines, native test and preview conventions.

## Data and service boundaries

`services/college` owns typed validation, snapshots, mutations, uploads and
overview. Routes under `/api/v1/college` delegate and translate errors only.
The desktop client uses HTTP; it never imports these services or reads stores.
No website, static mounts, CORS, additional packages or Telegram controls.

- Timetable CRUD retains every untouched template dictionary. Catalog revision
  is a SHA-256 of its complete JSON content; IDs in responses are projections,
  never stored template fields. Existing writers gain atomic JSON publication
  and shared cross-process guards. Structured next-class selection is extracted
  from the existing algorithm and reused by both prose and overview.
- Faculty/room/email/notes live in a separate subject registry, keyed by existing
  alias resolution. Room in the registry overrides the display fallback only.
- Deadline optional metadata: kind, subject, done, notes, venue and origin.
  Legacy rows remain valid. Active `deadlines.load()` omits done rows; explicit
  include_done reads serve the window. Atomic saves preserve retained done rows.
  Chat and window completion share the existing mutation path and remove
  correction/reminder linkage metadata, matching existing completion behavior.
  Due-date edits call `deadline_changes.move`, keeping history source
  owner_report and adding origin college_ui. No reminder is auto-shifted.
- Exams use these deadlines, named with exam wording; the existing briefing
  code remains unchanged. Events alone use a new guarded atomic JSON store.
- Every edit/delete carries a catalog revision. Compare under the writer lock.
  Stale changes return 409 without writing. Dated moves additionally bind the
  template and class-sessions snapshot and call `class_changes.move`.
- Overview projects current/next class, today's effective timeline, read-only
  cancellation facts, due soon, upcoming exams/events, faculty/room/join link.
  Shared reading helpers also project registry rooms into local class prose and
  events into local chat/briefing; no new notification scheduling. Mirrored
  warnings omit superseded rooms; structured Telegram reports keep template rooms.
  Event/faculty/window commands stay unavailable over Telegram.

## HTTP contract

GET overview; GET/PUT/DELETE timetable, subjects, deadlines, exams, events.
PUT accepts `{revision,id,value}`; null id creates; DELETE `{revision,id}`.
GET timetable?date=YYYY-MM-DD includes effective dated sessions; POST
timetable/date changes just one future occurrence with the expected snapshot.
GET catalogs return `{revision,items}`. Consistent errors have
`{error,message,status_code}`; server validation is authoritative.

POST uploads takes raw bytes with a filename query field (no local paths),
maximum 10 MiB, extension/signature/decoder checks. CSV/XLSX/DOCX parse locally
as labeled row tables; text PDFs support delimited lines. Images/scanned PDFs
reuse current timetable vision extraction and policy, maximum three pages.
GET uploads/vision reports the selected eligible provider/model and policy availability;
POST uploads/{token}/extract requires matching explicit consent before calling
that fixed provider/model; provider and OpenRouter model fallback are disabled
for this request. Existing chat import fallback and provider policy remain unchanged.
In-memory previews expire after 15 minutes, max four files.
No upload bytes or schedule changes are persisted until explicit Confirm.
Preview rows are editable; server returns row warnings and merge/replace diff.
POST uploads/{token}/preview checks edited rows and returns the diff; POST
uploads/{token}/confirm revalidates rows/revision under the timetable lock.
Confirm also requires the server-issued hash of the reviewed rows/mode/revision.
Default merge keeps existing rows exactly, replacing a matching day/start slot
only when explicitly represented in the reviewed diff. Replace is explicit.
Successful confirm atomically publishes random-name bytes/manifest and schedule
under guards, with rollback on a caught publication failure. Independent files
are not a filesystem-wide crash transaction; disclose that limit.
GET uploads and DELETE uploads/{id} operate only on opaque safe identifiers.
Timetable import is the target; exam imports are deferred unless equally tested.

## Native behavior

All HTTP/file reads run in a worker and callbacks return through after().
Backend offline shows “FRIDAY backend is not running” with Retry. Refresh on
window focus and every 60 seconds; skip/retain dirty forms and upload previews.
409 refreshes lists while retaining editable drafts and requiring a fresh review
before saving. Dialogs have inline errors, Enter/Escape, close/discard protection.
Ctrl+N creates, Delete confirms removal, Tab navigates. Grid/list scrollbars and
HiDPI support. Distinct Windows mutex; second launch restores the same window.
Join accepts saved HTTP/HTTPS class links only. Launch via command vocabulary,
adjacent tray/taskbar entry and project-venv BAT/VBS using existing startup.

## Acceptance and evidence

Run full tests before and after with isolated temp stores, no new failures.
Focused tests cover services, stale writes, authoritative validation, active/done
compatibility, real intent-router sharing, reminder proposals, template equality,
upload spoof/size/traversal/bomb checks, CSV/XLSX/DOCX edit-preview-confirm,
consent and policy refusal, client offline handling, view functions, native tabs
and single-instance behavior. Render all six actual native tabs using synthetic
data and inspect clipping/contrast. Bind receipts to source hashes, baseline and
final counts, previews and limits. No performance claim without measurement.
Update college docs, feature §9, architecture/current state and changelog.
Quit FRIDAY from the tray and relaunch to load.
