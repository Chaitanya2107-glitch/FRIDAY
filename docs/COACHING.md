# Private care and goal coaching (P6)

Everything described here works with the LLM disabled. All care types begin off.
These are personal reminders and arithmetic, without health assessments or app blocking.
The Android companion continues supplying only signals you have separately enabled;
P6 needs no new phone permission or native APK. Its new phone controls live in the PWA.

## Start here

1. Restart FRIDAY after the update. Source changes intentionally invalidate an older
   P0 remote session: enable remote access and pair again if FRIDAY requests it.
2. Use the **laptop's private chat or voice** to choose a care type or goal. Read the
   preview, edit it if necessary, then say **yes**. Say **cancel** to discard a draft.
   Remote `ask` cannot enable care, alter goals or approve scenes.
3. Open the paired PWA Home screen. Wellbeing buttons become available only after
   confirmation and inside your chosen window. **View private check** reveals a current
   phone-use question; **View private goals** reveals progress and manual **+1** buttons.
   These details clear when the page hides, disconnects or changes screens.
4. Use `care status`, `my coaching goals`, or `goal 1 progress` to review your choices.
   `disable sleep care`, `disable phone use care`, etc. stop that care type.

Nothing is queued from these private PWA controls. A manual goal tap uses a receipt so
retrying a lost acknowledgement in the same page session cannot add progress twice.
After a reload the receipt is gone: view the fresh server total before logging again.

## Example conversations

The observations in this example are illustrative, not measurements of your habits.

**You:** Set up sleep care.

**FRIDAY:** Your screen-off/charging records suggest a bedtime around 23:15 over
five observed nights. That estimate is uncertain. Review the bedtime, protected wake
time, reminder window, weekdays and daily cap, then confirm or change them.

**You:** Bedtime 23:00 wake 07:00 from 21:30 to 23:30 weekdays cap 1.

**FRIDAY:** Sleep: bedtime 23:00, protected wake 07:00, Monday–Friday,
21:30–23:30, at most one check per day. It starts at Ask. Confirm yes or change it.

**You:** Yes.

**FRIDAY:** Confirmed. This care type runs only inside the displayed windows and cap.

With insufficient baseline data FRIDAY asks you to choose times instead of inventing
them. A bedtime check can cite tomorrow's effective first class. Wind-down is a
separate opt-in: `set up wind down care bedtime 22:30 from 22:00 to 23:00 cap 1`.
Accepting its question previews the existing sleep scene before asking again to start
it. `offer phone DND` is a separate, fresh confirmation; it needs the companion's DND
grant and expires/restores after 15 minutes. No scene or phone setting changes on a nudge.

**You:** Finish 100 DSA problems by Dec 15.

**FRIDAY:** Track 100 problems for DSA by the displayed date, using manual logs.
Weekly check-in: Sunday 18:00–21:00. Data stays local, outside every model. Save it?

**You:** Yes.

**FRIDAY:** Goal 1 saved privately. 0/100 problems logged; 100 remaining.

**You:** Log 5 problems for goal 1.

**FRIDAY:** Shows the recorded total, remaining work, required daily pace and, when
there is a recorded pace, an estimated finish. It compares only completed days with
the straight-line plan; a newly created goal is not labelled behind.

Other supported examples include `study 2 hours every weekday`, `gym 3 times a week`,
`walk 8000 steps every day`, and `read 20 pages every day`. Gym begins with manual logs;
`use visits to gym for goal 2` offers a named-place source for confirmation. Focus
minutes can use a recorded session label or an app category. Steps use the latest
read-only Health Connect daily aggregate, not a sum of repeated cumulative reports.
No setup command enables a phone signal or asks for a permission.

For changes, use `change goal 1 target to 80`, `move goal 1 deadline to 2026-12-20`,
or `goal 1 review on sunday 18:00 to 20:00`; review and confirm each. To plan study time:
`suggest study blocks for goal 1`, `add block 1`, then **yes**. Effective classes,
existing private blocks, the confirmed sleep interval and current exam/sleep scenes
constrain proposals. Without sleep care, conservative planning bounds are 07:00–22:00
with a default 23:00–07:00 sleep exclusion. Saving a block does not start a timer.

## Care rules, limits and measurements

| Type | What triggers it | What the data cannot prove |
| --- | --- | --- |
| Breaks | Your chosen continuous screen interval, taking the union of phone and laptop use | Activity intervals cannot prove that you were looking continuously. A five-minute gap resets the interval. Only your explicit break log counts as a break taken. |
| Eye rest | Chosen interval; the preview offers 20 minutes and a 20-second, approximately 20-foot look away | This is an optional reminder, not a medical assessment. The old eye reminder does not run alongside confirmed care. |
| Sleep/bedtime | Your confirmed bedtime, uncertain sleep estimate and tomorrow's effective first class | Screen off and charging do not establish sleep. Health Connect and estimated sleep stay labelled separately; missing nights are unavailable. |
| Wind-down | Your chosen clock time; offers the reviewed sleep scene, tomorrow's first class and optional DND | It cannot know whether you are ready for bed. Every setting-changing step still needs approval. |
| Water/stretch | Only intervals you choose, from setup or your last explicit log | There is no inferred hydration, movement or health state. Without prior logs you choose the interval. |
| Phone-use awareness | Your selected categories/packages exceed your own minutes inside the chosen clock and study/class context | An app category cannot establish which content you watched or whether its use was distracting. Nothing blocks apps. |
| Wellbeing | An optional end-of-day question inside the confirmed window | The 1–5 value is your own entry. FRIDAY neither derives it from signals nor uses it to infer mood or a condition. |
| Weekly review | Confirmed Sunday window | Compares your last seven days with your preceding seven days. Screen categories can overlap across devices; missing sleep is not zero. |

Every care preview includes weekdays, a clock window and a cap of 1–8 checks/day.
The existing quiet hours, scene suppression, presence restraint, shared executive
budget and three-question/day budget can suppress a check even if its care window is
open. Delivery rechecks consent revision, pause, context, window, dedupe and cap.
Reserved delivery attempts conservatively consume the care cap even if a device fails.
Checks that cannot be delivered in their valid window are not replayed later.

For phone awareness, for example:

`set up phone use care category entertainment during study after 50 minutes from 16:00 to 21:00 cap 2 voice off`

Read the preview and confirm. Only approved categories/packages may be mentioned.
There is no raw-video classification. The notification is generic; actual minutes and
approved names require an explicit private view. Choose **Remind me in 15 min** or
**Leave it**. A follow-up must still fit the same consent, context, window and daily
cap, and expires if it cannot. Voice remains off unless explicitly enabled for this
care type; the same choice covers care settings, weekly summaries and experiments.
Three accepted checks allow `move phone use care to do and tell` to offer a
separate confirmation; it never promotes itself. A refusal returns it to Ask.

Use `i took a break`, `log eye rest`, `log water`, or `log stretch` after actually doing
it. Acceptance of a reminder alone is not a completion measurement.
Set up optional wellbeing with `set up wellbeing check-in from 20:00 to 22:00 cap 1`,
then confirm; log with a PWA tap or `wellbeing 3` in private laptop voice/chat.

For the Sunday review, `set up weekly care review from 18:00 to 21:00 cap 1`, confirm,
then `weekly care review`. `try care experiment` offers **one** optional seven-day
experiment: phone in another room for the first study block. It compares recorded
phone minutes overlapping study against the preceding week, through the existing
outcome learner's separate private numeric records. Confirm before it begins.
`care experiments` reports baseline, observed value and difference, including a worse
or unavailable result. Total recorded overlap is a proxy: changing study coverage or
leaving the phone unobserved can change it. It does not prove the experiment caused
the difference or that the phone was actually moved.

## Privacy and safeguard

Care records use `memory/mind/care.db`. Source-linked goals, revisions and numeric
experiments use dedicated private tables in the existing cognition database. They
are excluded from owner episodes, semantic indexing, AI context, model wording,
conversation history and training. Local speech explicitly uses the local speech
path without a remote provider or shared speech cache. Wellbeing taps never read out
the score. Public notices and cognition receipts contain only generic delivery text.

“Forget phone data” removes derived care questions/reviews/follow-ups, phone-linked
goal logs and experiment records. Automatic measurements are recalculated from the
remaining source data; explicitly phone-bound sources become unavailable. Your own
confirmed choices and desktop manual logs remain. Anonymous daily/weekly delivery
counts remain so forgetting cannot reset interruption budgets.
The forget boundary also invalidates in-flight care candidates and serializes
experiment source reads with phone deletion; private SQLite deletion overwrites the
deleted payload cells rather than leaving them on the database's free pages.

The following small English phrase list is in
[`services/mind/care_safeguard.py`](../services/mind/care_safeguard.py). Matching is
rule-based, accepts common contractions, and ignores quoted/code examples, explicit
programming requests and reported/disavowed statements:

```text
i want to die
i wish i were dead
i wish i was dead
i do not want to live anymore
i want to end my life
i want to kill myself
i am going to kill myself
i am thinking about suicide
i am thinking of suicide
i am suicidal
i have been thinking about killing myself
i feel like ending my life
i want to hurt myself
i might hurt myself
i am going to hurt myself
i feel like hurting myself
i am thinking about hurting myself
i cannot keep myself safe
i do not feel safe with myself
i cannot cope anymore
i feel completely hopeless
i cannot go on anymore
i do not want to be alive
i do not want to live
i am in serious distress
i am thinking of hurting myself
i am about to hurt myself
```

A match pauses automatic nudges and coaching for 24 hours, including queued automatic
companion notices, timer-completion nudges and automatic briefing speech. Ordinary
owner-requested help and timer measurements remain available. The response briefly
encourages a trusted person or local crisis helpline, with immediate local emergency
help if necessary. Only the pause deadline is stored; the disclosure and response are
not recorded as chat, cognition, semantic or training text. This finite list can miss
other wording and languages; it is not a crisis-monitoring service.

## Validation and remaining checks

Focused tests cover consent, baselines, quiet/caps, cross-device overlap, explicit
phone choices, private storage/forgetting, weekly numeric fixtures, experiments, ten
goal examples, selected-day projection, free slots, safeguard delivery and model spies
that fail if private data reaches a provider. The PWA has a signed mock API smoke at
360 px including manual log retries after an accepted request loses its response.
See `tasks/coaching/full-receipt.json` for the source-bound full-suite result and
`docs/COACHING-FILES.md` for the P6-only file list.

Final result: **7,539 Python tests passed, 13 skipped**, plus seven passing subtests.
Eight settings-window cases initially failed during Tk library setup; the entire
12-test settings file passed in a fresh process on the identical source. The original
run is retained, and `tasks/coaching/handoff.json` records the reconciled result and
unchanged source hashes. All 45 JavaScript tests passed; the remote PWA build and
360 px signed browser smoke passed. Screenshots are in `tasks/coaching/*-360.png`.

Real seven-day outcomes and real reminder timing on your paired phone still need
observation. The goal grammar is intentionally finite; unknown/private setup replies
are rejected locally rather than guessed by a model. Setup/editing remains on the
laptop; the PWA provides explicit private views, manual logs and check-ins.
