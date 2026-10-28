# Friday's personal assistant role and activity awareness

Friday's default agenda is the owner's day: schedule, commitments, routines,
preferences, reminders, communication, music and continuity. Coding and diagnosis
remain available when requested. This role applies to custom and default persona
prompts, including serious mode. Banter follows the owner's lead.

## What she can know

- A recent foreground app and its cleaned window title are observations.
- An app category is an interpretation of metadata, not proof of the exact task.
- “I'm studying graphs” is an explicit owner report attached to that observed
  app/window. Progress, understanding and completion remain unverified.
- “I use Chrome for college notes” records a personal use separately from the
  app's general purpose and the task being done today.
- A timetable is a plan. Friday does not treat it as observed attendance.

Existing activity tracking continues to collect its configured foreground,
browser-history and Recent-file metadata. This change adds no screenshot loop,
keystroke recording, document scraping or clipboard monitoring. Historical
activity durations remain sampling estimates. New app-knowledge accounting does
not credit long gaps without observations.

Fresh foreground evidence expires after 20 seconds. Owner labels stop being
current after an app/title/window switch, idle, a tracker gap or restart; an
unchanged label also expires after four hours. The command bar can attach an
explicit report to the app seen in the preceding two minutes, while clearly
calling it recent activity. That does not make an unobserved app current.

## App learning

Friday first asks the configured model about an unfamiliar app's process name,
after at least a minute of observed use. Window titles and page/document text
are excluded from that automatic lookup. Explicit general knowledge questions
can still use the name supplied by the owner.

The answer is stored as an unverified proposal. When the inquiry system finds an
appropriate moment, Friday can ask whether the exact explanation and proposed
category are correct. Existing interruption spacing and quiet controls apply.
If the model is unavailable or cannot identify the app, she asks the owner for
an explanation instead.

Only a clear answer to the exact, current, offered question can promote the
candidate. “Maybe” and qualified guesses leave it unconfirmed. “No” rejects it;
“actually, a music player” saves an owner correction. Owner teaching takes
precedence over delayed model results. Old unverified model definitions are
preserved as proposals and removed from authoritative app categories.

The confirmation is bound to the candidate version, question, local channel,
desktop session and inquiry epoch. It is single use, expires three minutes after
offering, and cannot authorize a separate action. Older slow requests cannot
replace newer questions. Confirmation replies bypass generic personal-fact
extraction, so “yes” cannot become an app definition or an unrelated owner fact.

## Commands

| Say | Result |
| --- | --- |
| `what am I doing` | Fresh observed app/title, any scoped owner task, and clearly labelled history |
| `learn this app` | Model-first app identification followed by owner verification |
| `yes`, `no`, `actually, ...` | Answer the current app-verification question |
| `this app is a music player` | Save an explicit explanation of the recent/current app |
| `I'm studying graph algorithms` | Save an owner-reported task for this activity |
| `I'm working on a birthday note` | Save another explicit task label |
| `I use this app for college notes` | Save personal app use separately from current intent |
| `I'm done with this activity` | Close the current task label |
| `stop asking me` | Apply the existing pause to unsolicited questions |
| `forget graphs` | Remove matching owner activity/app-use statements through memory controls |
| `forget everything about me` | Also delete owner task/use memories and withdraw app explanations |
| `clear my activity log` | Also delete activity-attached task labels |

New task-label/app-use commands and app approvals are local to the laptop.
Activity reports retain the existing authorized inspection routes. The new
ambient-activity prompt section is omitted in remote turns; ordinary conversation
and event history retain their existing sharing controls. Explicit owner reports
may be used by the configured conversational provider in local chat.

## Storage and verification

`memory/mind/brain.db` stores app usage, versioned explanation proposals, owner
task labels and personal app uses. Explanations remain distinct from observations.
Forgetting fences model work already in flight so it cannot restore a withdrawn
candidate. No past activity data was deleted as part of this upgrade.

Focused trust tests cover model-first lookup, private-title exclusion,
provisional categories, owner precedence, old-data migration, uncertain replies,
stale/duplicate offers, API learning isolation, inquiry metadata, same-title
windows, idle/restart/gap boundaries, forgetting and grounded timelines.
Validation and activation receipts are in `tasks/personal-assistant-*.json`.
The final source-bound suite passed 5,752 tests, with 13 optional checks skipped;
the relevant focused subset contains 352 passing cases.
