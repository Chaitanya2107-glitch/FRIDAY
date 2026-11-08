# Briefing card checks

Use the updated Island and full local FRIDAY backend. Weather should be off.
The automated `check_briefings_browser.py` covers both event/reply orderings,
six-line card rendering, the SSE header token and scoped Snooze button payloads.

- Disconnect external networking. `brief me` and `night brief` show a title and
  at most six literal content lines in the expanded FRIDAY tab. Missing fields
  and absent data sources contribute no placeholder/error sections.
- The command result and `ui.card` can arrive in either order: the card stays
  expanded, with one copy of the brief and no duplicate capsule reply.
- Check the real first class, time, stored faculty/room, and total count against
  College Schedules. Do not create/edit schedule data just to test notifications.
- Morning Mochi waves then smiles; night Mochi becomes sleepy. Existing reduced
  motion and Sneak controls continue to work. Morning speech follows the local
  briefing setting; night is silent by default, with no duplicate command speech.
- Snooze 30 removes the card, then offers it once after 30 minutes (also after
  restarting). Skip removes it and does not replay the automatic brief that day.
  Old card buttons cannot affect a later brief. Outside a current brief, skip
  retains its usual media/command meaning.
- Start game/class or put a fullscreen app in front. A brief waits ten minutes
  and retries. End the blocker before the retry; confirm a single delivery.
- At night, Yes uses the normal sleep scene preview/confirmation. Not now does
  nothing to scene/system state. Entering sleep mode delivers the night brief
  once and does not offer to start sleep again.
- Automatic class/deadline cards include stored details. Use pytest's fake clock
  checks for precise 15/5-minute thresholds and restart de-duplication.
