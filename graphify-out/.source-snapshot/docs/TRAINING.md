# Train FRIDAY locally

Open `train_friday.bat` beside FRIDAY, or use the commands below in PowerShell from the project folder.
This applies owner-reviewed lessons to local recall. It never calls a provider, downloads an embedding model,
or modifies language-model weights. Dataset export is a separate, explicit option.

## Start with useful lessons

The default **Learning queue** contains captured questions and manual examples. Answered items are prioritised.
**Grouped nudges** is separate: it shows the latest occurrence and the number of repeated captures.
Existing captures are retained. Queue grouping covers the latest 10,000 matching captures; display is limited to 100 items.

```powershell
.\train_friday.bat list
.\train_friday.bat list --kind question
.\train_friday.bat list --kind nudge
.\train_friday.bat list --kind all --ungrouped
.\train_friday.bat show 12
.\train_friday.bat show 12 --context
```

Replace example IDs with an ID from your queue. `show` reports whether the lesson is applied and what it affects.
The interactive Review action uses a quicker flow with one approval; the full scripted review remains available.

```powershell
.\train_friday.bat review 12 --quick
.\train_friday.bat approve 12 --teaching "My favourite editor is Zed." --apply
.\train_friday.bat train --all-approved
.\train_friday.bat withdraw 12
```

Approved examples become active only after application (`train` or `--apply`). Applied teachings are searchable
reviewed memories. Preferred responses to manual examples match their exact question, ignoring case and punctuation.
Captured personal questions also support `your` → `my` phrasing. Personal questions can retrieve literal teachings
by matching their topic words. If multiple statements match, FRIDAY shows those statements rather than inventing
a resolution. Local commands retain their execution path: an example reply never runs an action.

Chat and voice consult these lessons before generic knowledge lookup. Reviewed replies keep their literal wording
and are not sent for model polishing. Unknown personal questions stay local. Broader language understanding is
limited to these deterministic rules; arbitrary paraphrases are not guaranteed to match.

`what do you remember about me` and person-specific memory lists include applied teachings with review IDs.
Withdrawing/rejecting a lesson removes it from active recall immediately, including after restart.
The ordinary forget-memory commands can withdraw matching reviewed facts; forgetting all memories also withdraws
reviewed personal lessons and clears new personal answer tracking. Historical review records remain available.

## Nudge feedback changes delivery

Reviewing ordinary notification wording is optional. To change delivery, use explicit feedback:

```powershell
.\train_friday.bat feedback 24 too_frequent --minutes 120
.\train_friday.bat feedback 24 badly_timed --minutes 60
.\train_friday.bat feedback 24 incorrect
.\train_friday.bat feedback 24 useful
```

- `too_frequent`: enforce a minimum interval between successful deliveries of that nudge type.
- `badly_timed`: snooze that type for the specified duration, then resume normal delivery.
- `incorrect`: disable that type until it is marked useful; this does not change sensor readings or thresholds.
- `useful`: remove the snooze, interval restriction and disable preference.

Changing battery/GPU/memory readings share a known nudge type; other notices keep their title/text identity.
Ratings persist in SQLite. Critical notices marked urgent bypass these preferences. Reminders keep their existing
delivery path. Free-text notes or a reviewed preferred nudge response do not change delivery rules.

## More useful questions

Live FRIDAY no longer starts an evening questionnaire. Her local inquiry brain chooses one useful question
or silence from current context. Explicit chat/voice learning requests also ask one question at a time;
answers never schedule an automatic follow-up. The separate manual trainer still has a 40-question starter
catalogue, which is an owner-operated teaching tool rather than the live inquiry policy.
Answers and question timestamps are stored in SQLite so FRIDAY and the separate trainer can update them concurrently.
Answered questions and questions covered by applied teaching are skipped. Unanswered questions become eligible
again after the retry interval. Legacy JSON question lists remain readable.

For a dedicated local conversation about your day and about you, open `train_friday.bat` and choose
**g**. Choose **i** to see the unasked-question inbox first. You can also run:

```powershell
.\train_friday.bat questions
.\train_friday.bat session
.\train_friday.bat session --topic day
.\train_friday.bat session --topic personal
```

The training interview has **no default question limit**. It asks all available questions, one at a time,
until the inbox is exhausted or you enter `/stop`. Optional `--count` accepts any positive count.
`day` covers today's activities, check-in questions and retained observations she never asked about,
including older observations labelled with their original date. `personal` covers unasked curiosity
questions, followed by starter questions. The inbox labels each source. The custom curiosity list is
no longer truncated to 15 entries. Previously discarded questions cannot be recovered.

Answers are saved immediately as drafts, even if the interview is interrupted. Enter skips without
marking a question asked. Existing answered drafts are left for review instead of asking again.
Day questions can return on another day; personal questions already asked are excluded from this inbox.
This local interview does not invent follow-up questions with a model.

Review the displayed answers and approve application once. Short personal answers remain paired with
their questions; day-specific lessons include the date and question. Long answers are kept in full as
drafts for review into concise teachings. Export stays off. The trainer does not consume FRIDAY's current
live pending question.
Live chat/voice interviews keep answers as local question evidence; use the trainer to approve them as recalled lessons.
Answering a live personal question prevents it from being repeated, even before review.

Settings in `.env` (restart FRIDAY after changing):

```dotenv
EVENING_QUESTION_LIMIT=8
LEARNING_SESSION_QUESTIONS=20
QUESTION_RETRY_HOURS=24
```

The first two remain compatibility bounds for legacy catalogue collection; they do not schedule live
questions or set a live interview quota. They do not limit the separate Train Friday interview.

## Collect more useful information per answer

Start with `session --topic day` and describe what happened, why, the outcome, and what comes next.
For example: "I studied DBMS at college because the test is Friday. Joins still confuse me; tomorrow
I'll practise those." This retains more context than a one-word answer to several generic questions.
Review it into separate, complete facts when each needs independent recall or correction.

Use `questions` to spot her actual uncertainty before working through starter questions. Keep temporary
events dated, and teach lasting preferences as complete statements. Correct a wrong lesson instead of
adding a conflicting copy. Applied answers suppress known questions; saved drafts avoid duplicate interviews.

A future improvement is to derive follow-ups from missing details in an answer and rank them by how
much they would improve reminders, planning or personal recall. That is not implemented in this local
interview: its questions come from existing activity, observations and curiosity.
