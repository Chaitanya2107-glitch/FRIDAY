# Read-only schedules, alerts and briefings

Authorized: local implementation, isolated tests, read-only real-data validation.
No commit, push, schedule edits, model calls or dependency downloads. One writer;
schedule-storage and delivery-contract agents are read-only. Existing work stays.
Ruflo guidance tools/CLI and a tracked lease harness remain unavailable; this
specification and the final source receipt record local development decisions.

Reuse College Schedules' confirmed timetable, dated class reconciliation,
subject catalog and shared deadline/exam/homework store. Never reparse uploads.
Effective classes need explicitly supplied read-only owner/reasoning facts:
the ordinary reasoning reader initializes databases and cannot be used here.
Use SQLite mode=ro, validate applied fact fingerprints, and fail closed for an
unsupported applied class constraint. Missing/invalid sources log once per source.

Alerts poll every 30 seconds; persistent item/occurrence/lead keys are claimed
before publishing (at-most-once, including across restart). At late startup only
the nearest crossed lead is shown; older crossed leads are consumed silently.
Normal polling sends both configured class leads. Deadline date changes form
a new occurrence; faculty/room edits do not change class alert identity.

Briefings resolve optional services at use time, have at most six literal-text
lines, and keep delivery dates, opener choices, pending deferrals and current
offer in their own data directory. Civil dates are local; automatic morning
delivery stays inside its window, including catch-up after 07:30. Explicit
commands may repeat; skip/snooze are scoped to the most recent live offer.
Game/class/fullscreen defer ten minutes. Legacy automatic/explicit briefing
paths must not cause duplicate delivery or bypass weather opt-in.

Morning speech defaults on, night speech off; there is no model/provider call.
Weather is opt-in with validated coordinates and one three-second Open-Meteo
request; all failures are silent. Subject/faculty text never leaves the machine.

Existing ui.card actions render in expanded FRIDAY view for the briefings owner,
without changing sizes/hotkeys. Sleep entry uses the public scenes.request API
and retains its confirmation policy. The sleep callback runs outside briefing
locks. Optional schedule sections disappear with missing data; briefings still
work with other sources or only a greeting/closing, as requested by the tests.

Validate fake-clock alerts/restarts, morning timing, fallback, deferrals,
missing sections, six-line cap, no-repeat openers, snooze/skip and offline weather
failure; run plugin/college/focus/scene regressions, frontend tests/build, and a
real-data read-only preview with before/after source hashes.
