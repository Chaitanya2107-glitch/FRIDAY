# Auto-sessions + summaries — design

Date: 2026-09-29 · Status: approved in chat (user: "go on, finish this"); second of the three
sub-projects after the Telegram bot.

## Goal

FRIDAY notices stretches of one kind of work ("sessions"), offers the matching mode,
sums each session up when it ends, and writes a weekly summary next to the daily journal.
Everything is local, no AI (window titles are private).

## Sessions (`services/activity/sessions.py`)

Worked out from the activity log's foreground-app rows each time; no new table.

- Categories grouped to the default modes: **work** = coding, project, ai, documents;
  **study** = study; **gaming** = gaming; **chill** = entertainment. Everything else is
  neutral (neither breaks nor extends a session).
- A group's stretches are merged while the gap between them is ≤ 10 min. A merged stretch
  with ≥ 10 min of that group's time is a session. It has ended once 10 min pass without
  that group; its end is the last minute of the group, not when that was noticed.
- The app in the foreground right now (not yet saved as a row) counts too.
- Two groups can overlap when they interleave (coding and short YouTube bits back and forth);
  a break longer than 10 min splits the session instead.

## Mode suggestion (watcher, once a minute)

A running session reaches 10 min, no mode is on, a mode named after the group exists, not busy (fullscreen/gaming/quiet mode) → notification
"Looks like you're working. Start work mode?" [Yes] [No].
Yes starts the mode exactly like saying it; No = no more suggestions for that group today;
no answer = not again for 2 h. Answers are saved as `feedback` rows (`mode:<group>`).

## Session summary

A session of ≥ 20 min that ended (within the last 30 min, so a restart doesn't replay old
ones) → one notification: "Work session done: 1h 35m (14:05–15:40) — FRIDAY 1h 10m, 3 commits."
If that group's mode is still on, the notification gets an [End mode] button. FRIDAY never
ends a mode on its own (ending closes apps). Mirrored to Telegram by the existing rule
(only when away ≥ 10 min).

## Daily

The journal gets a "Sessions" section: "14:05–15:40 work — 1h 35m (FRIDAY)".

## Weekly (`services/activity/weekly.py`)

Sunday at `JOURNAL_HOUR`, written to `Documents\FRIDAY Journal\Week of <Monday>.md` with a
one-line notification ("Your week: 32h active — coding 14h (+3h), study 6h (−2h) · top
project FRIDAY · 18 commits"). Contents: active time vs last week, time per category with the
change, projects with commits, sessions per group + longest, active time per day.
Commands: "how was my week" / "open my weekly summary" (this week), "open last week's
summary"; opening always rewrites the file. No "write my weekly summary" ("write …" is the
typing command).

## Not in this project

Ending modes automatically, suggestions for custom modes (only the four group names),
Telegram-always delivery, AI-written summaries.

## Testing

Unit tests for session building (merge, gap, neutral, overlap, live row), suggestion rate
limits, the summary text, the journal section, the weekly file and commands, and the
notification buttons.
