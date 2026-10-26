# Different ways to ask FRIDAY

You do not need to memorize one exact sentence. These phrases express the same
supported tasks, and work with the default `AI_ASSIST_ONLY=true` setting.
Use an actual app name, folder, song, time or note in place of the examples.

With the default `AI_LANGUAGE_ENABLED=true`, unfamiliar phrasing and typos also reach AI for
translation into local commands. For example: “could u get chrome running for me pls” → `open chrome`.
Conversation uses AI replies with recent history. The examples below remain available through local
matchers when language AI is unavailable. See [AI language and local thinking](AI_ASSISTANCE.md).

The [feature coverage matrix](COMMAND_FEATURE_COVERAGE.md) lists the broader pass:
56 command families, 104 representative commands and 208 explicit alternative
sentences, plus parameterized requests. The [saved checkpoint](COMMAND_COVERAGE_PROGRESS.md)
records verification, remaining action-level gaps and how to resume.

The [action-level follow-up](COMMAND_ACTION_COVERAGE.md) covers all currently
inventoried parser outcomes and tests the saved-state commands below.

| Saved task | Additional wording |
| --- | --- |
| Inspect proactive task help | Show task followups; show proactive task help |
| Control task followups | Pause/stop/resume task followups; stop task followups for Review code |
| Respond to a task suggestion | Not now; show that task; why did you suggest that; explain this task followup. Short replies use the last submitted local followup for 15 minutes. |
| Correct a dated class | Tomorrow's DBMS class moved from 9 AM to 11 AM; move monday's OS class to 2 PM |
| Recall class changes | When is tomorrow's DBMS class; show class history for tomorrow's DBMS |
| Link/review class reminders | Link reminder 1 to tomorrow's DBMS class; review/apply/reject class reminder updates for tomorrow's DBMS |
| Edit/run/delete a workflow | Replace steps in workflow Desk with open Chrome and mute; execute my workflow Desk; remove workflow Desk |
| Edit/control a saved mode | Change actions in Focus mode to open Chrome; keep Focus mode silent; activate saved mode Focus; end saved mode Focus; remove saved mode Focus |
| Register/resume a project | Register project Atlas; change launch steps for project Atlas to open Chrome and mute; reopen saved project Atlas; unregister project Atlas |
| Inspect/reset project steps | Show startup steps for project Atlas; restore default startup steps for project Atlas |
| Follow up on a file | Open that one; answer the second one when asked; actually use project-notes.pdf instead; open it. Corrections select without opening. |
| Correct a deadline | My DBMS deadline moved from Friday to Monday; move deadline DBMS to 2026-10-20 at 9am |
| Recall a deadline | When is my DBMS deadline; show deadline history for DBMS |
| Link/review reminder changes | Link reminder 1 to deadline DBMS; review reminder updates for DBMS; apply reminder updates for DBMS; reject reminder updates for DBMS |
| Correct a handoff | Prepare a handoff for the login bug; actually, use the notification bug. Reply with a name/ordinal when asked. |
| Select a search result | Open search result 2; show search result 1 in its folder. Requires a recent file search. |
| Manage a contact | Store contact Mom with number 9876543210; update contact Mom with number 9876543211; forget WhatsApp contact Mom |
| Message a saved contact | Message saved contact Mom: Keep CAPS, please! Sending still asks for confirmation. |
| Manage saved reading | Save https://example.com/Article to read later; open saved reading item 2; mark reading item 1 as read |

| Task | Equivalent requests |
| --- | --- |
| Open an app | Open Chrome; launch Chrome; start Chrome; run Chrome; load Chrome; fire up Chrome; boot up Chrome; bring up Chrome; pull up Chrome; pop open Chrome; access Chrome; get Chrome running; get Chrome started; get Chrome open |
| Bring up an app | Bring Chrome to the front; bring Chrome to the foreground; switch to Chrome. These use the existing app-opening action; whether an existing window is focused depends on the app. |
| Close an app | Close Spotify; quit Spotify; exit Spotify; terminate Spotify; force close Spotify; shut Spotify down; close Spotify down |
| Open a folder | Open downloads; show my downloads folder; take me to downloads; go to downloads; open my download directory |
| Open a website | Open YouTube; go to YouTube; take me to YouTube; visit youtube.com; youtube.com |
| Search the web | Search for cat videos; look for cat videos; Google cat videos; search Google for cat videos; find me cat videos |
| Search YouTube | Search cat videos on YouTube; find cat videos on YouTube; YouTube cat videos |
| Increase volume | Increase volume; raise the volume; turn the volume up; make it louder; make the volume more loud; make the sound less quiet |
| Decrease volume | Lower the volume; reduce volume; turn the volume down; make it quieter; make the volume less loud; make the sound more quiet |
| Set a volume | Set volume to 25; set volume to 25 percent; set volume to twenty five percent; volume twenty-five |
| Mute / unmute | Mute; silence the speakers; turn the sound off / unmute; turn the sound on |
| Increase brightness | Increase brightness; brighten the screen; make the display brighter; make the screen more bright; make the screen less dim |
| Decrease brightness | Lower brightness; dim the screen; make the display darker; make the screen less bright; make the display more dim |
| Set brightness | Set brightness to 75; set brightness to seventy five; set brightness to seventy-five percent |
| Take a screenshot | Take a screenshot; capture my screen; grab the screen; take a picture of my screen; save an image of the display; capture a snapshot of the desktop |
| Resume music | Resume the music; unpause; continue playing; carry on playing; get the music going again |
| Pause music | Pause the music; stop the music; pause playback; put the music on hold; put playback on hold; pause the audio |
| Next song | Next song; next track; skip this song; change the song; move to the next track; skip ahead a song |
| Previous song | Previous song; previous track; play the last song; go back to the previous track |
| Play a song | Play Believer; listen to Believer; play Believer on Spotify; listen to Believer on Spotify |
| Play music | Play music; put on some music; start the music; turn on music; listen to music |
| Create a reminder | Remind me in 10 minutes to stretch; set a reminder in 10 minutes to stretch; create a reminder in 10 minutes to stretch; schedule a notification in 10 minutes to stretch; set an alert in 10 minutes to stretch |
| Save a note | Note Buy USB-C Cable; jot down Buy USB-C Cable; take a note Buy USB-C Cable; save a note Buy USB-C Cable; add a note Buy USB-C Cable; create a note Buy USB-C Cable |
| Find your files | Find my resume; locate my resume; look for my resume; search for my resume; where is my resume |
| Remember a fact | Remember that my favourite colour is green; memorize that my favourite colour is green; keep in mind that my favourite colour is green; don't forget that my favourite colour is green |

You can put politeness or a request before these commands:

- Hey Friday, please …
- Can you … / Could you please …
- Would you be able to …
- Is it possible for you to …
- I was wondering if you could …
- I want you to … / I need you to … / I'd like you to …

For example, **“Could you please get Spotify running?”** and **“Launch Spotify”**
both open Spotify. Supported app/device/media commands can also be combined:
**“Get Chrome running and make the display less bright.”**

Spelled-out volume and brightness levels support zero through one hundred,
including hyphenated numbers such as `seventy-five`. Relative commands such as
"increase volume by twenty" work too. Explicit duration and result selectors also
accept positive spoken numbers, for example `remind me in twenty five minutes to
Call Mom`, `pause nudges for an hour`, and `open result two`. Cardinal quantities
support one through 999; ordinal selectors support first through ninety-ninth.
Clock times, dates, fractional/compound durations and ambiguous bare numbers keep
their existing formats. Words inside reminder bodies and names stay literal.

## More ways to create and edit

These examples map to FRIDAY's existing features and validation:

| Feature | Equivalent example |
| --- | --- |
| Timetable | Schedule a DBMS class on monday from 9am to 10am |
| Marks | Record 18 out of 25 for DBMS CIE 1 |
| App limits | Set Chrome's daily limit to 45 minutes |
| Log watches | Watch Server.log for text: READY and Listening! |
| Reminders | In 20 minutes remind me to Call Mom |
| Project steps | Replace startup steps for project Friday with open VS Code |
| Goals | Set a high priority goal: Build FRIDAY |
| Task step completion | Report completed step for task current: Tests passed! |

Spotify collections and queues also accept wording such as `put the album Divide
on`, `listen to music by Adele`, `start playing my saved tracks`, and `add track
Believer to play next`. Named music requests preserve title words such as `Now`
and `Friday`. Spotify still needs its existing connection and player setup.

Common first-word typing mistakes such as `opne chrome`, `serach cats and dogs`,
`voluem 20` and `shwo my goals` have a small explicit correction list. A corrected
request must still match a native command. FRIDAY does not guess misspelled app
names or change words inside dictated text, names or negated instructions.

You can combine supported local features, for example `show my goals and mute`,
`show my notes then battery health`, or `list my reminders then open Chrome`.
FRIDAY recognizes every step before starting. An unrecognized step prevents the
batch from running; an action needing confirmation pauses the remaining steps.
Literal bodies consume the rest of the request: `mute then note Buy A and B!`
saves one note. For music names containing `and`, separate the next action with
`then` or a semicolon: `play album On and On then mute`. Saved mode/routine/project
execution, login entry and AI interpretation still use their dedicated single
request flows. Recognition does not make a batch transactional: a runtime error
does not roll back steps already run.

## When FRIDAY misses a phrase

Immediately correct her with **“No, I meant open Spotify”**. FRIDAY already has a
correction memory: for supported actions, she remembers that the previous wording
means that task. Exact text operations, such as typing and clipboard contents,
are deliberately excluded from saved action mappings.

Language has unlimited variations, so this is a growing vocabulary rather than a
promise to understand every sentence. Unclear targets, implied requests and arbitrary
rewordings may still need clarification or a correction. Questions, negations and
quoted instructions should not be treated as permission to perform a new task.
Typing, notes, search queries and reminder contents retain their own words;
sentence patterns are applied to whole requests, not substituted inside that text.

The vocabulary lives in `services/automation/command_words.py`. Whole-sentence
patterns live there separately from ordinary text normalization. Reminder and note
handlers keep the original task text after recognizing the command prefix.

See [all FRIDAY features](FEATURES.md) for tasks beyond this example list, and
[AI assistance](AI_ASSISTANCE.md) for how local commands and optional models differ.
