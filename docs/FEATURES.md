# F.R.I.D.A.Y — Everything She Can Do

*Last updated: 2026-10-28.* A tour of every feature, with example phrases. Anything in quotes can be typed in the
command bar or said by voice unless it says otherwise. How it's built: `docs/current_state.md` and `docs/architecture.md`.

Different wording for the same task: [command synonyms and sentence examples](COMMAND_LANGUAGE.md).

Friday's default role is your personal assistant: your day, schedule, routines,
preferences and activities. “What am I doing” reports fresh app/window evidence
and any task you explicitly labelled. “I'm studying graphs” saves a scoped task;
“I use this app for college notes” saves personal app use separately. “Learn this
app” asks the model first and verifies its exact explanation/category with you
before treating it as confirmed. App metadata alone does not establish exact
intent or progress. [Activity awareness and examples](PERSONAL_ASSISTANT_AWARENESS.md).

AI also understands unfamiliar phrasing and typos by default. For example, “bro the speakers r too loud
bring em down to 23” becomes the local `set volume to 23` command. Ordinary chat and voice conversation
use AI replies with recent history. Existing commands execute locally, with existing confirmations.
Background cognition and notification decisions use local Ollama only; language uses OpenRouter with
Ollama fallback. See [language settings](AI_ASSISTANCE.md). Unsupported abilities still need implementation.

### Android bridge, conversation interruptions and Friday DJ

With paired KDE Connect, read/select phone notifications, preview a reply and
confirm submission, or ring your phone. In conversation mode, say “wait” or
“hey Friday” during a reply to interrupt and continue. Spotify DJ supports mood
mixes, more tracks from the current artist and saved playlist/search preferences.
Examples, setup and limits: [personal assistant upgrades](PERSONAL_ASSISTANT_UPGRADES.md).
The original desktop robot remains unchanged.

### Native customization window

Open **All controls → Customize FRIDAY…**, or the same tray item, for four
Tkinter tabs: contacts, routines, projects and modes. Search,
add, edit, rename and remove saved entries with validation and draft protection.
Active modes must be ended before renaming/removing. Projects include folder browsing and resume commands.
Saving configuration does not execute those commands. See [usage and previews](CUSTOMIZATION_UI.md).

### Ordinary-chat follow-ups

Name a saved commitment with "When is my robotics exam?", then ask "When is it
again?", "How many days left?" or "What was the previous date?" in chat or
voice. "What about my maths exam?" selects another unique saved commitment.
These read-only questions use the same checked revision without model/search
calls. Context expires after 15 minutes or an unrelated turn; ambiguous, changed
or forgotten references need a full name. See [topic examples](COMMITMENT_TOPIC_FOLLOWUPS.md).

“My exam was postponed” asks which saved exam when several match. Answer
“Robotics, November 3”, say “Robotics November 3”, or choose “Robotics” and then
give its new date. Typed questions and spoken answers share the laptop context.
FRIDAY confirms only after local review and a committed revision; uncertain or
stale answers cannot change the date. Say “follow-up status” to check a deferred
answer, or “never mind” to cancel an unsaved update. Existing inference and
attention limits apply. See [examples and limits](ORDINARY_CHAT_FOLLOWUPS.md).

### Connected local cognition and useful questions

Owner dialogue now retains its original question/date and feeds shared local reasoning. A short answer
such as “tomorrow afternoon” stays attached to what FRIDAY asked. Recent owner episodes, observed
patterns, current mode/Spotify/network state, goals/tasks and future dated commitments inform inquiry.
Owner utterances remain reports; generated interpretations do not become confirmed facts or completed tasks.

Meaningful requests, command intentions/results, feature writes, answers and notification outcomes wake
local executive attention. The existing watcher reconciles missed/due work. Clocks can wake observation;
they do not mandate questions. Expensive inference defers during gaming, typing, speech and pending replies.
Direct commands keep their existing local execution checks and confirmations.

Each inquiry decision can produce one question or choose silence. No mandatory startup interview,
scheduled evening batch, announced count or six-second follow-up. Autonomous questions across proactive
features share a ceiling of three per day and at least 45 minutes between attempts; these are ceilings,
not targets. Duplicate topics are withheld for seven days, and rejected/ignored interactions inhibit
further interruptions. Explicit `ask me something`, `ask me about my day` and `start learning session`
request one newly considered question, not an unattended series. Missing reasoning produces silence.

Use `brain status`, `question status` or `why did you ask me that` locally to inspect the latest decision
and interruption limits; `executive status` shows durable review progress. The local `/api/v1/mind/brain`
endpoint exposes attention/inquiry status. Dialogue retains up to 500 episodes, with bounded retrieval;
history/forget controls clear these derived memories and fence in-flight questions without resetting budgets.
Quit FRIDAY and run `launch_friday.vbs` again to load both processes and retire old queued interviews.
See [connected brain boundaries](CONNECTED_BRAIN.md) for the exact wiring and remaining limits.

### Clear tray status

The tray menu and hover tooltip show the current mode: Normal, Gaming, Study, Work or a saved custom
mode. Quick actions show Spotify's saved connection status; an existing
connection displays Connected, Now playing and Disconnect instead of asking you to connect again.
Status refreshes on the normal five-second tray poll and immediately after a tray quick action.
An unavailable backend/status read shows Status unavailable rather than a stale on/off state.

Mode replies put the final mode first. Repeating `turn on gaming mode` says it is already on and
does not rerun setup. `is gaming mode on` / `gaming mode status` only read status. Setup failures
are reported separately from the mode being on. `what mode am I in` reports Normal when none is selected.
Quit FRIDAY from the tray, then launch `launch_friday.vbs` again to load backend and tray changes.

### Shared executive cognition

FRIDAY maintains bounded, versioned situation snapshots from saved facts, goals/tasks, explicit local
focus, dated constraints and historical execution receipts. Before the supported project-folder action,
she records a local assessment and expected observable result, rechecks sources before OS submission,
and records the verified/blocked/cancelled/uncertain outcome. Opening context never completes your task.

| Command | Behavior |
|---|---|
| `executive status` / `cognitive review status` | Effective review switch, hourly usage and latest review/assessment |
| `executive review off` / `disable cognitive review` | Persistently pause optional background review and invalidate in-flight results |
| `executive review on` / `enable cognitive review` | Reenable review within existing budgets and environment switches |
| `why did you decide that` / `show your last executive decision` | Last project assessment, expected/recorded result and source versions |
| `reasoning status` | Existing evidence-cited conclusions and proposals; existing explicit apply/reject controls still govern changes |

Controls and detailed assessments are laptop-only, through typed chat or voice. Project preflight is local
and needs no model; switching off background review leaves those action checks in place. With
`COGNITIVE_REVIEW_ENABLED=true`, `REASONING_ENABLED=true` and cognition enabled, the watcher can review
changed evidence without a new message, including in assist-only mode. At most one review starts every
five minutes, and four per rolling hour, including failed/interrupted attempts. Claims, budgets, backoff
and switches survive restart. Unchanged completed situations do not generate new model calls.

Reviews defer while gaming, busy, speaking/listening or waiting for an answer. They may suggest a next
step or remain silent. The scoped model purpose cannot create owner facts, run tools or automatically
apply service changes. Notification review still decides whether a proposal should interrupt you.
Corrected/withdrawn sources invalidate dependent conclusions; stale, disabled or superseded in-flight
reviews cannot commit. Explicit forgetting/history/workspace clearing retires derived private snapshots
and active reviews while retaining hourly usage counters. Local records are bounded to 200 per kind.

Restart FRIDAY from the tray to load the feature. This milestone covers project preflight and shared
background review; extending assessments to every older tool and general temporal/episodic memory is
later work. It does not claim human consciousness or continuous screen understanding.

### Verified project execution

`start project session for college` prepares a brief for the saved project `college`, opens its exact
folder in Explorer and verifies Explorer's actual folder path. Use `project session status`,
`resume project session` or `cancel project session`; add `for <saved name>` to select another session.
The brief remains in `memory/project-executions/`. Named focus and checkpoints survive restart.

This is a laptop-only workflow for chat/voice, with no AI or new dependencies. Existing
`prepare my project work session` commands still produce briefs without opening applications.
Existing folder windows are reused. Interrupted desktop actions are observed before continuing;
uncertain actions are never automatically repeated. If nothing can be verified, open the saved folder
and resume, or explicitly start a new session. Cancellation stops further checkpoints; an OS operation
already submitted may finish. Status rechecks the brief and folder; historical completion does not
reopen a window you closed. It does not run saved resume commands, type text, close apps or complete
your source tasks. Restart FRIDAY from the tray to load the new commands.

## 1. Ways to talk to her

| How | What |
|---|---|
| **Command bar** | **Ctrl+Shift+F** — type anything (chat, commands, `\s` search, `\f` find files, `\d` ask files, `\v` screen, `\o` open). Shows guesses under the box ("Tab: resume catjang · open spotify"); Tab cycles, Enter runs |
| **Voice hotkey** | **Ctrl+Alt+Space** — listens, stops on silence (or press again). Pressing it while she talks cuts her off |
| **"Hey Friday"** | **Ctrl+Alt+H** switches it on (tray dot turns blue). "Hey Friday, work mode" in one breath, or "Hey Friday" … pause … "open Notepad" (the mic stays open 2 s for the command), or "Hey Friday" alone and wait for the beep. Off after 30 min without a wake |
| **Conversation mode** | **Ctrl+Alt+C**, tray, or say/type "let's talk". A back-and-forth with no hotkey: she replies aloud, beeps, listens again. Type instead of talking any time (it's a turn, and typing never counts as silence). Ends with "bye" / "that's all", Ctrl+Alt+C, or two silences |
| **Interrupting** | While "Hey Friday" is on: "Hey Friday, …" over her voice stops her and takes the new command; "Hey Friday, stop" just silences her |
| **Speak via Handy** | **Ctrl+Alt+F** — opens the bar and dictates into it with Handy; sent automatically |
| **Terminal** | `friday open spotify`, `friday "what's due"`, `git diff \| friday "review this"`, `npm run build 2>&1 \| friday "why did this fail"`, bare `friday` for a back-and-forth |
| **Telegram** | Message the bot from your phone: any command/chat, plus /lock, /sleep, /shutdown, /restart, /cancel, /away, /menu. `/! <command>` skips that command's confirmations; `/cc enter` or `/cc right-arrow` presses a key. Local diagnostics such as `brain status` reply in your private chat. Offline commands catch up, and briefings/reports use emoji sections. [Examples and queue limits](TELEGRAM_UPGRADES.md). Send links, files and `copy <text>` to the laptop. |
| **File right-click** | Right-click a single file in Explorer → **Show more options** (Windows 11) → **Send to Chaitu through Friday** → **Telegram** or **WhatsApp**. Telegram sends to the configured account; WhatsApp opens the saved `chaitu` contact and pastes the selected file for you to review and press Send. Friday must be running |
| **Her body** | Click her to talk, double-click for the command bar, right-click for a menu |
| **Tray menu** | Status, command bar, Talk to FRIDAY (listen, conversation mode, Hey Friday, free will, speak voice / typed replies aloud), Quick actions, Routines, System stats, Clipboard history, File search, AI provider, Clear chat memory, Quit |

**Separate conversations:** Telegram keeps its own pending approvals and file results/selections.
A phone reply cannot approve or cancel a laptop action, and a phone search cannot change what
"open 1" or "send that file" means at the laptop. Typed and spoken laptop requests share those
references. Memories, goals and tasks are still shared, and Telegram messages preserve a laptop's
pending computer-agent step.

**Spoken replies:** voice replies are spoken (tray: *Speak voice replies aloud*); typed replies too with *Speak typed replies
aloud*, and always in conversation mode. "talk faster" / "speak slower" / "normal speed". Offline she speaks with Piper;
Hindi text uses a Hindi voice.

The file-sharing menu is installed for the current Windows user when Friday starts, without administrator
permissions. It accepts any regular file, up to Telegram's 50 MB or WhatsApp's 2 GB limit; folders are excluded.
Limits follow [Telegram's Bot API](https://core.telegram.org/bots/api#senddocument) and
[WhatsApp's document-sharing guidance](https://www.whatsapp.com/messaging?lang=en).
The WhatsApp option requires WhatsApp Desktop, replaces the clipboard with the selected file, and leaves the
final Send action to you. Failure or loss of WhatsApp focus is reported instead of claiming delivery.
To install manually, run `venv\Scripts\python.exe -m interfaces.shell_menu install`; to remove it while Friday
is closed, use the same command with `remove`. Starting Friday again refreshes the registration.
Windows integration follows [Microsoft's shortcut-menu registration guidance](https://learn.microsoft.com/en-us/windows/win32/shell/context-menu-handlers);
Windows 11 puts legacy verbs under [Show more options](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/integrate-packaged-app-with-file-explorer).

---

## 2. Her personality and mind

- **Evidence-based reasoning:** ordinary statements can be remembered as owner quotes and connected to
  consequences, predictions and proposed changes using current goals, tasks, reminders, dated classes
  and public outcomes. This is model interpretation, not placement-training keyword matching.
  `reasoning status` shows what she remembers/inferred and what is proposed or applied. Use
  `apply reasoning proposal 7`, `reject reasoning proposal 7` (use the actual ID), or `reconsider my situation`.
  Supported changes cover class availability, saved task plans and moving requested reminders.
  Explicit confirmed cancellations/replacements can change dated classes without rewriting the weekly
  template; uncertain/inferred changes and reminder/task-plan updates require your approval. Verified
  task plans stay pending; they do not execute tools or complete steps. Corrections/forgetting invalidate
  dependent conclusions, and expired class changes still protect historical attendance. Fresh proposals
  may prompt a useful notice, with the normal reasoning and busy/away/nudge controls choosing whether to send.
  A separate evidence check and bounded repair reduce errors, but reasoning quality still depends on the
  available model. Unsupported conclusions remain unapplied; valid owner quotes can still be remembered.

- **Ten layer foundations:** `brain layers` describes perception, attention, working/long-term memory,
  goals, reasoning/prediction, executive control, action/communication, verification and learning,
  with each layer's current limits. Most were already present; reasoning was subsequently upgraded as above.
- **Persistent goals and task progress:** `add goal high: Prepare for placements`, `show my goals`,
  `set goal Prepare for placements priority normal`, `pause goal Prepare for placements`, or
  `resume goal Prepare for placements`. Priorities may be `low`, `normal` or `high`.
  `start task for goal Prepare for placements: Practise interviews` (or `start task: Practise interviews`),
  then `plan task current: Arrays; Graphs; Mock interview`.
  `finish task step current: I completed the array exercises` records evidence and advances one step.
  `block task current: Waiting for feedback`, `resume task current`, `pause current task` and
  `cancel task Practise interviews` manage progress. An unplanned task can finish with
  `complete task current: I checked the result`; planned tasks finish when all steps are reported complete.
  Names and remembered current references work locally; numeric IDs remain optional. Ambiguous names
  prompt for a more specific request. `latest task` and `latest <name>` explicitly select the newest match.
  Goals/tasks survive restarts and chat clearing; `clear my goals and tasks` resets them explicitly.
  Active goals and progress reach chat/voice context and notification decisions. Completion is recorded
  as your report; plans do not execute tools or grant permissions. Goal and linked task statuses are separate.

- **Verified local task handoffs:** `prepare a handoff for my FRIDAY project`, `prepare a handoff for my current task`,
  or simply `prepare a handoff` when a task is selected or there is one eligible task. Friday captures
  its progress, collects related saved notes by keyword, saves a dated Markdown handoff in `memory/handoffs/`,
  and checks the saved bytes before reporting completion. The reply names the task and includes the file path.
  `check the handoff`, `check the latest handoff`, `check the handoff for FRIDAY project`,
  `resume the handoff` and `cancel the handoff` control it without remembering IDs. Current selections
  survive restart. Laptop and Telegram task/goal focus are separate; handoffs remain laptop-only.
  Completed checkpoints survive restart. Failures block progress, stale task edits require a new handoff,
  and conflicting files are not overwritten. The underlying task remains open until its own work is finished.
  This works locally without models; it does not read diary entries or automatically search project files.
  Handoffs are laptop-only. Clearing goals/tasks removes execution records; already generated files remain.

- **Handoff follow-ups:** after preparing/checking a handoff, `actually, use the notification bug`
  creates a fresh verified handoff for that saved task. Completed older artifacts remain; superseded
  unfinished handoffs are cancelled. If the task name is ambiguous, reply with a unique saved name or
  an offered ordinal. Choices survive process restart for 15 minutes and are rechecked before use.
  Unrelated turns/history resets retire short corrections; `check the handoff` restores its context.
  These follow-ups stay laptop-only and do not complete the source task.

- **Project work-session briefs:** `prepare my project work session for friday` uses the saved project named
  `friday`. With one saved project, `prepare my project work session` also works; ambiguous names require
  a more specific request. Four durable checkpoints capture matching active/paused/blocked tasks and goals,
  inventory local file metadata, collect matching saved notes, then publish and verify a Markdown brief in
  `memory/project-sessions/`. Task/goal and note matching uses all meaningful project-name words, not inference.
  `check my work session`, `check the latest work session`, `resume my work session`, and
  `cancel my work session` use persistent focus. Add `for <project-name>` to select that project's latest brief.
  The inventory covers at most 100 files and 500 inspected entries, through two nested folder levels;
  hidden files, key files, links and common generated/storage folders are excluded. Truncation is labelled.
  Captured file metadata, project registration and matching tasks are rechecked before later checkpoints;
  changed sources block stale publication. The brief is a dated snapshot, not continuous synchronization.
  Status rechecks its content hash; missing output can be republished, conflicting edits stay untouched.
  This is laptop-only chat/voice, works without models, and reads no project file contents or diary.
  It does not start programs, execute saved resume commands or complete source tasks. Restart from the tray.

  **Follow-up instructions:** after preparing/checking a session, say `leave out the notes`,
  `include the notes again`, `actually, use the college project`, or `refresh that brief`.
  Each revision generates a new verified brief with fresh source snapshots; earlier published briefs remain.
  The note preference carries across refreshes and project switches. Excluding notes skips reading them.
  A pending/blocked older execution is superseded and cannot resume under the old instructions.
  Ambiguous switches ask which saved project; reply with its full name or an offered `first/second ... one`.
  The choice and brief reference survive restart for 15 minutes. Unrelated local turns, chat-history clearing
  or workspace reset retire short references; `check my work session` restores context from durable focus.
  Changed registrations/choices and stale concurrent context are refused before creating a replacement job.
  Laptop chat and voice share this context; Telegram cannot inspect, replace or answer it. These are bounded
  project-brief follow-ups, not general cross-tool pronoun understanding or new model access.

- **Manual training alongside normal life:** double-click `train_friday.bat`, or run
  `venv\Scripts\python.exe train_friday.py`. A separate terminal lets you list/show/review her captured
  questions and proactive notifications, with timestamps, situation, raw observation context, thought,
  delivery state, and the answer/reaction from the live conversation. Her normal nudges, questions and
  answer learning keep running; reviewing never consumes her pending question.
  Enter a corrected answer, what she should remember, optional preferred wording and review notes.
  Approval and applying local learning are separate steps. Applied facts/wording enter her shared prompt;
  reviewed app explanations and pattern reasons also reach her local brain. Add your own question/desired
  answer pairs. Reject/withdraw removes the manual lesson, while preserving its captured evidence.
  Export explicitly opted-in approved examples as chat JSONL for future fine-tuning. Raw context and review
  notes stay local; approved learning text can go to the configured AI provider. This updates local memory,
  not model weights. Restart FRIDAY once from the tray to enable collection; subsequent lessons are read live.
- **Persona:** Iron Man's FRIDAY — calls you "Boss", calm status-report answers with a dry, cheeky line; serious topics
  stay joke-free. "roast me", "roast my week", "be serious" / "sarcasm off", "sarcasm on".
- **Shared cognition:** chat, voice, proactive questions, desktop notifications, Telegram delivery,
  system actions and speech now report into one local event record. Her brain reads it alongside live
  activity, mood, pending questions and operations in progress; permitted recent facts enter the shared
  AI prompt. This gives her continuity about what she said/did rather than relying on separate histories.
  "what did you just say", "what notification did you send", "what did you send through telegram",
  "what action did you just take", "what did you ask me", and "cognition status" read recorded facts.
  Recalling her question doesn't count as answering it. Notification text is local-only; exact recall
  bypasses AI and chat memory. A notification marked "submitted" means Windows accepted the submission,
  not that you read it; failed sends and interrupted speech are recorded separately.
  Events survive restarts, with a default limit of 500 events/16,000 characters each and a 3,200-character
  AI context budget. "Clear chat memory" clears the cognition record too. This is software working memory,
  not human consciousness. She knows what the connected services record, and can still miss or misinterpret things.
- **Humour that learns:** per situation (studying, deadline, late night, gaming, coding, chilling) she learns whether
  jokes land from your next message — a laugh counts up, "not now" counts down.
- **A brain of her own (no AI model):** she watches every move — each app and what its window is about — and
  thinks about it by herself, every few seconds:
  - **Knows your things:** every app and topic she has seen, with its category, first/last time, how often, how
    long, on how many days and at which hours. "what do you know about catjang". Your explanations of new or
    unknown apps are remembered even when she already knows their category.
  - **Past, present, next:** your day cut into episodes ("9:10–9:50 working on friday"), what you're on now, what
    you left hanging, and what usually comes next. "what am I doing", "what was I doing", "where did I leave off".
  - **Wonders why:** something never seen before, an app back after weeks, an app at an hour you never use it,
    restless window-flicking, leaving 25+ min of focused work for a game or video, something started and not
    come back to, a regular that hasn't shown up today. Each becomes a thought with her own guess at the reason;
    thoughts fade (half as strong every 45 min). Your answer is kept as the reason, so next time she remembers.
  - **Curious:** an app (after 1 min) or page (after 10 min) she can't place gets looked up — one bare question,
    "What is <name>?" — and the answer is stored, so she never asks twice and the activity log sorts it into
    the right category from then on. If identification fails, the observation becomes a candidate for local
    inquiry; it is not permission to ask immediately or fall back to a scripted question.
  - **A life:** grounded behavioral state (quiet, attentive, curious, engaged, content) connects attention,
    commitments, uncertainty and learned timing to review and interruption decisions. Quiet requests can
    allow silent thinking; absence/unanswered questions never cause sulking or emotional obligations.
    Light positive persona counters and a daily diary remain. "how are you feeling",
    "how was your day", "what did you learn today". A "?" pops over her body when she notices something.
- **Predictions she earns the right to act on:** two predictors — her own counting (which app follows which, what
  you start at what time of day) and the nightly-trained model — both guess your next app at every switch and are
  scored against what you actually did; when they disagree she believes the one with the better recent record.
  Then she asks you: "around 10:35 PM you'll open Spotify, right?" (10 minutes to 2 hours ahead) or "after X
  you'll open Y next, right?" — usually at least one a day. Your yes/no is kept, and confirmed ones become extra
  training examples for the model. After 3 confirmations, with the model trained and not disagreeing, she asks once
  "shall I just open it myself from now on?" — yes and she does (once a day, at its time, only if it isn't open,
  never while you're gaming/fullscreen) and tells you; no and she never asks again.
  "how do your predictions compare", "what have you automated", "stop opening spotify".
- **Day review:** `ask me about my day` requests one local brain decision using actual context. No scheduled
  evening batch, fixed count or automatic next question after an answer. Original paired answers remain
  recorded locally and enter shared reasoning.
- **Free will (talks on her own):** on by default, with local inquiry choosing one grounded question or silence.
  Past reactions, current activity and future commitments inform the choice; a shared durable governor
  prevents separate features from taking turns interrupting. There is no forced startup question or
  scripted fallback when inference fails. Busy/away/typing/microphone/speech and pending replies inhibit
  autonomous inquiry. The daily ceiling is three questions, at least 45 minutes apart, never a quota.
  "stop talking on your own", "you can talk freely", "quiet for an hour", "ask me something",
  "what do you want to know about me".
- **Reflection:** every 3 hours (when there's something new) and nightly, she rereads what you said to her (not
  what you did on the PC), rewrites a short profile of you that every reply sees, saves new facts and adds
  questions she wants to ask. "what's on your mind?" shows her mood, her live thoughts and all of this.
- **Corrections:** "no, I meant open spotify" does it — and from then on the missed wording means that.
- **Self-training predictor:** a model retrained nightly on your app switches; it takes over "what will I open next"
  and the bar's guesses only while it beats simple counting.

---

## 3. Memory

- **Chat history** shared by typed, voice and conversation mode.
- **Long-term facts:** learned by herself from what you say, or "remember that my sister is Priya".
  The most relevant facts are recalled into every reply.
  "what do you remember about me", "what do you know about Ravi", "forget that …", "forget everything about me",
  "what did you learn this week" (and a Sunday review so wrong guesses can be forgotten).
- **Plans with a date:** "my DBMS exam is on Friday" is stored with the date — she knows it's coming up, asks how it
  went afterwards (once), and treats it as past from then on.
- **Updates replace old facts:** a changed fact ("sister is Anya now") replaces the old one — decided by a cloud model
  (the small local model isn't trusted to delete facts; then both are kept and the newer wins).
- **Strength:** facts heard again or used get stronger; guesses nobody uses fade and drop out after ~2 months.
  Facts you told her never fade.
- **Conversations remembered:** a chat that's gone quiet for 20 min is summed up in a sentence or two.
  "what did we talk about yesterday / today / last time".
- **Notes:** "note buy milk", "idea: …", "read my notes", "delete note 2", "clear my notes" (in the journal and briefing).
- **Diary:** "journal: …", "dear diary …" — only into that day's journal.
- **Reading list:** "add this to my reading list" (the page you're on), "what's on my reading list", "open reading list 2",
  "done with reading list 1".
- **Profile facts:** "my USN is …", "what's my USN", "type my USN".

---

## 4. Apps, windows and the PC

- **Date and time:** "what's the date and time", "tell me the time and date" — read from the laptop's
  clock, including when AI features are off.
- **Multiple commands:** "mute and open chrome", "mute, then open chrome", "open chrome and notepad",
  "what's the date and mute". Recognized clock, app, device, media and system-stat steps run locally in
  order and return one combined reply. Commas, semicolons, "and", "then" and "and also" are supported.
  All steps must be recognized before local execution begins. A confirmation request pauses the batch;
  remaining commands must be requested again. Quoted text stays together, and dictation, reminders,
  search queries and clipboard text keep their contents. Unfamiliar combinations can use AI routing
  when enabled. Chat, voice and `/system` share the same router; `/system` directs confirmation actions
  to chat or voice.
- **Open anything:** "open chrome", "open black myth" (any installed app or game via Everything), folders ("open
  downloads"), websites ("open youtube"), "search chrome for …", "search youtube for …". Opened apps come to the front.
- **Close like Alt+F4:** "close spotify" (save prompts still appear).
- **Volume / brightness:** "volume 30", "turn it up a lot", "mute", "brightness max".
- **Screenshots**, **clipboard** ("read my clipboard", "copy …"), **clipboard history** (last 20 copies, memory only,
  private items skipped; tray submenu), **clipboard transforms** ("make my clipboard uppercase", "…on one line",
  "clean up my clipboard", "paste as plain text", "count the words in my clipboard").
- **Typing into any app:** "type see you at 5", "write an email asking for Friday off" (the AI writes, she types),
  "press ctrl+s", "select all", "type hi and send it".
- **Organise a folder** (asks first). **Installers:** "what installers are in my downloads", "delete my installers" (asks).
- **Power:** "lock the laptop", "put the laptop to sleep", "shut down in 30 minutes", "restart" (ask first), "cancel the shutdown".
- **System stats:** "how's my system?", "battery", "cpu usage", "how hot is my gpu", "what's using my ram",
  "why is my laptop so slow" (tray submenu too).
- **System health:** "how's my battery health", "how long has the laptop been on", "do I need to restart",
  "what's taking up space". Eye breaks: "turn on eye breaks" (20-20-20).
- **App limits:** "limit valorant to 2 hours a day", "what are my app limits" — warnings, nothing is closed.
- **Screen questions:** "what's on my screen?", "explain the error on my screen", "read my screen", `\v …`.
- **Computer agent (first version, typed commands):** open the app you want to work in, leave the mouse on
  that monitor, and press **Ctrl+Shift+F**. Type `\c open the File menu` or `\c type Hello in the focused field`.
  She looks at the screen and proposes one click/double-click, scroll, text entry or key press. Review it,
  press **Ctrl+Shift+F** again, and type `\c yes` to run that exact step. She looks again and proposes the next
  step or reports visible completion. `\c no` / `\c stop` cancels; `\c status` repeats the proposal.
  Every step needs approval, which expires after 120 seconds; tasks stop after 20 input steps. If focus or the
  visible screen changes, she proposes again instead of running the old step. Errors say whether input ran,
  input failed, or the vision check failed afterward, and stay visible for 90 seconds (or until dismissed).
  OpenRouter image requests use separately configured
  `OPENROUTER_VISION_BACKUP_MODELS`, rather than ordinary chat backups. Another ordinary chat/command
  cancels the task. Uses `VISION_PROVIDER` / `VISION_MODEL`; screenshots go to that AI and remain only in
  temporary context, outside chat history and speech caches. Telegram is refused. Use the command bar for
  the first trial; unattended tasks, voice entry and drag/drop are not built yet.
- **Read aloud:** "read this" (the selection), "stop reading".

---

## 5. Automation

- **Routines:** "create a routine called work mode to open vs code, play my focus playlist and set volume to 30",
  then "work mode". Steps can wait ("wait 5 seconds"). "list my routines", "delete routine …". Tray Routines menu.
- **Modes:** "start study mode (for DBMS)", "end study mode". Steps run on start; quiet modes hold nudges and her
  own talking; ending closes what it opened and restores the volume. "when I start study mode, open …",
  "make study mode not quiet", "what mode am I in", "list my modes".
  - **Left on by mistake:** after 15 min on apps that don't fit (videos/social/games in work or study mode;
    coding/documents in gaming mode) she reminds you with an [End mode] button; after 45 min, or an hour away,
    the mode ends itself.
- **Sessions:** after 10 min of work/study/gaming/chill with no mode on she offers the mode; a 20+ min session gets a
  summary when it ends.
- **Logins:** "save my github login" (password only in Windows Credential Manager), "log me in to github".
  Campus Wi-Fi auto-login; "open lms".
- **WhatsApp:** "message mom on WhatsApp: I'll be late" (asks first). "save mom's number as …", "list my contacts".
- **Web watches & alerts:** "tell me when blender closes", "tell me when it's done", "tell me when it's charged",
  "tell me when <url> changes", "tell me when catjang logs an error", "what are you watching", "stop watching …".
- **Done alerts (automatic):** long Claude Code replies and permission requests, long terminal commands (pass/fail,
  failed ones get [Explain]), finished downloads, heavy CPU/GPU work finishing.
- **Downloads filing:** a new download naming a subject or project → "Move it to College\\<Subject>?"
  [Move it] [Move & rename] [Leave it]. Screenshots taken in class / study mode are filed to the subject.

---

## 6. Music (Spotify)

- Media controls for any player: play, pause, next, previous, "what's playing".
- With Spotify connected ("connect Spotify", Premium): "play believer", "play arijit singh", "play my gym playlist",
  "play the album divide", "shuffle my liked songs", "shuffle on", "repeat this song", "add kesariya to the queue",
  "play … next", "like this song". Spotify minimizes itself when music starts.
- **Wrapped:** "my spotify wrapped (this semester / all time)", "who are my top artists", "what are my top songs".

---

## 7. Files and search

- **File follow-ups:** after a search, `open it` uses the selected file or the only result. If several
  are possible, she asks which one; answer `the second one` or an offered filename to finish the pending
  open/reveal action. `actually use project-notes.pdf instead` selects it without opening, then `open it`
  or `show it in folder` acts on that selection. `actually use the other file` selects the sole alternative.
  Results and pending choices survive a process restart for up to 15 minutes. Unrelated turns retire
  short references; laptop and Telegram stay separate. Moved/deleted/metadata-changed targets require
  a fresh search. Opening reports Windows submission, not proof the application displayed the contents.
- **Find files** (Documents, Desktop, Downloads): "find my resume", "where did I save the hackathon ppt",
  "which file mentions sensors", `\f …`; then "open 1", "show 1 in folder". "rescan my files".
- **Answer from files:** "what does my invoice say about the total?", "according to my notes, …", `\d …`.
- **Send files to your Telegram bot:** "send me my resume through telegram" or, after a search,
  "send me that file through telgram bot". Typed and voice commands both work. "That file" means the
  single recent result or the result you opened/revealed; with several results she asks which one.
  "send me file 2 through telegram" selects explicitly. Files go to your configured private chat,
  up to 50 MB, without sending their contents to an AI. "telegram status" checks the bot connection.
  Explicit labels also work: "send me the file notes.pdf through telegram". After she asks which file,
  reply with its filename, a result number, or "send the file notes.pdf" within two minutes. A different
  request ends that follow-up; laptop and Telegram conversations keep separate follow-ups.
- **Send a Telegram message:** 'send me a "hi" through telegram', "send me hi through telegram", or
  'send me a message through telegram saying "Hi, Boss!"'. Message text keeps its wording and punctuation;
  long text is split across messages. Use an explicit "message" or "text" label when the text looks like
  a filename. These commands work in chat and voice without AI or a file search.
- **Forward an answer:** after FRIDAY answers, say/type "send me the answer in telegram", "send your last
  answer through telegram bot", or "share that reply on telgram". She sends the latest saved reply exactly
  as written, including links and code blocks, splitting long answers across messages without truncation.
  Chat and voice share the saved reply. Repeating the request sends that answer again; delivery confirmations
  don't replace it. If there is no saved reply, she asks you to get an answer first.
- **Web search:** "look up …", `\s …` — answers cite sources.

---

## 8. Activity awareness (all local, no AI)

- **Activity log:** which app is in front and for how long, every command she runs (never typed text or titles
  sent anywhere). "what have I been doing today", "clear my activity log".
- **Ask your history:** "what was the repo I looked at yesterday", "what video did I watch last night",
  "when did I last open WhatsApp", "how long did I spend on YouTube this week", "what apps did I use today".
- **Projects:** "this is a project", "save catjang as a project", "resume catjang" / "pick up where I left off",
  "how long did I work on catjang this week", custom resume steps ("when I resume catjang, run npm run dev …").
  Say "I wanna work on Friday" or "let's work on catjang" and she asks whether to resume that saved project.
  Yes opens its workspace using its saved resume steps; no, another message, or a two-minute timeout dismisses
  the suggestion. Works in the command bar and by voice. Project names can be spoken without punctuation.
- **Git:** "any uncommitted work?", "what did I change in catjang today", "write a commit message for catjang";
  evening reminder about uncommitted work.
- **Coding helpers:** "what's running on port 3000", "what dev servers are running", "kill port 3000",
  "did CI pass on catjang", "check outdated packages".
- **Habits:** learns time habits, app chains and app groups; suggests them with [Open it] [Not now] [Stop suggesting].
  "what are my habits", "why did you suggest that", "forget the spotify habit", "pause habit suggestions".
- **Predictions:** "what will I open next", "how good are your predictions / bar guesses / suggestions".
- **Insights:** "when do I usually start", "when do I study best", "how long will this session last".
- **Fun numbers:** "how many hours did I game this week", "what's my study streak", "semester wrap-up".
- **Journal:** written every night at 10 PM to `Documents\FRIDAY Journal` (time per kind, projects, commits, classes,
  videos, songs, notes, diary). "write my journal", "open yesterday's journal", "search my journal for viva".
- **Weekly summary:** Sundays, plus "how was my week", "open last week's summary".

---

## 9. College

- **Temporary class time changes:** `tomorrow's DBMS class moved from 9 AM to 11 AM` changes that
  occurrence and preserves duration, weekly timetable and correction history. `when is tomorrow's
  DBMS class` recalls the current time; `show class history for tomorrow's DBMS` shows original/new
  times. Dates also accept weekdays or YYYY-MM-DD. Repeated subjects ask which session; reply with an
  offered number or subject/time. Cancellation facts remain in force. Started classes, existing attendance,
  wrong old times and invalid/past/cross-midnight targets are refused. Warnings, briefing, next-class
  answers, study-mode offers and attendance follow effective times; stale attendance buttons are refused.
- **Class-linked reminders:** `list reminders`, then `link reminder 1 to tomorrow's DBMS class`.
  A later class correction previews shifts; `review class reminder updates for tomorrow's DBMS`,
  `apply class reminder updates for tomorrow's DBMS` or `reject class reminder updates for tomorrow's
  DBMS` keeps approval explicit in the same conversation/channel. Pending updates defer delivery;
  a cancelled linked occurrence suppresses its reminder. Rejection keeps existing reminder times.
  Changes use the same verified batch/receipt recovery and delivery guards as deadline reminders.
  A reminder can link to one class or deadline. Time changes within a date are supported; cross-date
  moves remain future work. Weekly edits do not silently rebind old dated records.
- **Timetable:** "read my timetable from the screen / from <file>", "what classes do I have tomorrow",
  "what's my next class", "add class …". A warning 10 min before each class (with [Join] if you saved its link).
- **Class links:** "DS class link is meet.google.com/…", "join my class". When a class starts: "Start study mode for EVS?"
- **Study time per subject:** "how long did I study DBMS this week", "study hours today".
- **Attendance:** after each class "attended?" [Attended] [Missed]; "I bunked EVS today", "my attendance",
  "how many DS classes can I skip".
- **Marks:** "I got 18 out of 25 in DBMS CIE 1", "my DBMS marks", "what do I need in the DBMS exam for an A".
- **Correct a deadline:** `my DBMS deadline moved from Friday to Monday`, or `move deadline DBMS to
  2026-10-20 at 9am`. A date without a time keeps the saved clock. She changes one saved deadline,
  checks any supplied old date, and asks which one if ambiguous. Reply with its full name or an offered
  ordinal; choices expire after 15 minutes or an unrelated turn. `when is my DBMS deadline` gives the
  current saved date; `show deadline history for DBMS` shows old/new dates and owner provenance.
  New matching task handoffs/project briefs use the current date; old completed artifacts stay historical.
- **Linked reminder updates:** first `list reminders`, then `link reminder 1 to deadline DBMS`. Linking
  records that explicit reminder's time relative to the deadline and does not reschedule it. A later
  deadline change previews reminder shifts. Say `review reminder updates for DBMS`, then `apply reminder
  updates for DBMS` or `reject reminder updates for DBMS`. Apply/reject must use the conversation that
  created the proposal. Pending linked updates defer reminder delivery at brain review; rejection keeps
  existing times. Changed/delivered reminders, past proposed times and active/uncertain delivery block
  updates. Interrupted application can recover from its receipt without moving a reminder twice.
  Explicit deadline removal/completion/clearing removes its history and links; reminders stay independent.
- **Deadlines:** "DBMS assignment due Friday 11:59pm", "what's due", "done with …", "start the DS assignment"
  (makes and opens its folder). Countdown notifications; exams counted down in the briefing.
- **Syllabus & revision:** "DS syllabus is in <file>", "what's in DS unit 2", "make a revision pack for DBMS".

---

## 10. Proactive help

- **Goal-aware task follow-ups:** FRIDAY can suggest reviewing an unchanged active task or saved
  blocker, using active goal priorities and current activity. Active tasks become candidates after two
  days without a recorded update; blocked tasks after one day. Recent progress, paused/finished work
  and inactive goals are left alone. Unchanged records do not prove you did no work. Every suggestion
  passes notification review and fresh state/attention checks. No plan step is run.
- **Respond to task help:** buttons offer **Review task**, **Not now** (24 hours) and **Stop asking**
  (until resumed). After a submitted notice, local chat/voice accepts `show that task`, `not now`,
  `why this followup` or `why did you suggest that` for 15 minutes. Unrelated turns, expiry and changed
  task/goal state invalidate the reference. Review shows saved progress without launching or completing
  work. Telegram cannot answer a laptop's short follow-up.
- **Control task help:** `show task followups` shows suggestions, factual reasons, delivery state and
  owner switches. `pause/stop/resume task followups` applies globally; add `for Review code` to select
  one saved task. Pauses last 24 hours. Nudges/free-will controls and busy/voice/typing/away guards apply.
  Maximum four reviews/day and two notification claims/day, at least four hours apart; unanswered
  same-task attempts back off from one to seven days. Failed/unknown submissions do not create reply
  context or replay automatically. Preferences survive restart/history clearing; workspace reset removes them.

- **Morning briefing:** the first time you're at the laptop each day — weather, reminders, classes, deadlines, notes,
  battery, yesterday. "brief me" any time; it also goes to Telegram every day at **7 AM**.
- **Telegram recaps:** nightly at **9 PM** (today's activity and deadlines), weekly on **Sunday at 9 PM**
  (the week's activity report). These use laptop local time and require FRIDAY to be running, including
  while gaming or at the laptop. Starting after a scheduled hour catches up that day's due reports.
  Successful deliveries are remembered across restarts; failed sends retry after five minutes.
  "send me my daily summary through telegram", "send me my weekly summary through telegram", or
  "send me my morning briefing through telegram" sends one now. FRIDAY's shared prompt knows this capability.
- **Reminders:** "remind me in 20 minutes to stretch", "remind me at 5pm to call mom", "any reminders?" — with
  [Snooze 10 min]. Her brain checks current facts, due/event dates, remembered sources, goals and activity
  before sending. A cancelled class doesn't cancel homework. Busy/voice context can defer; contradicted
  or unavailable review retains the reminder. Failures retry with backoff; submitted destinations do not
  repeat. Exhausted failures and uncertain submissions stay visible; uncertain delivery needs explicit retry.
  "notification status", "why did you send that notification", "why did you not send that notification",
  or "retry failed reminders" work locally by text/voice. Retry queues a fresh check, not an immediate send.
  Notifications need valid brain review even in assist-only mode; if the model is down they remain pending.
- **Nudges:** low battery, hot GPU, full memory, hours in one app, low disk. "pause nudges for an hour", "turn off nudges".
- **Busy = quiet:** while gaming or fullscreen, nudges wait and nothing is spoken on her own.
- **Learning data audit:** Friday screens and categorizes retained learning records locally. The weekly
  Telegram recap includes new categories, collected/appropriate/excluded/quarantined records, historical
  backfill, eligible next-app examples, actual training/evaluation counts and measured results or skip reasons.
  "learning report" or "training data status" shows the audit; "send me my learning report through telegram"
  sends it now. Weekly learning periods use consecutive scheduled cutoffs and catch up after downtime.
  Reports contain aggregate counts, category labels and reason descriptions. Original records stay in their
  source stores. Historical app activity without verified origin is cataloged but cannot train the ML model;
  new observed user/requested switches accumulate eligible examples. Friday's autonomous opens, idle/runtime
  boundaries and brief sessions break training continuity. Facts and conversations are cataloged separately
  from the current next-app model. Screening is a quality filter; accuracy is measured on held-out data.
- **Online/offline:** notices lost internet (and why), switches to the local model, and back.
- **Notifications:** quick confirmations disappear by themselves; answers and questions stay. When you're away from
  the laptop, notifications go to Telegram.

---

## 11. Her body

A pixel robot on the desktop. Eyes follow the cursor (also while thinking), she blinks and glances around; typing taps
her feet and heats her screen teal → red; scrolling scrolls her screen; shaking the mouse near her → she hunts it;
stroking her head → hearts; drag her around (she dangles). Stretches every 25–40 min, sleeps after 5 idle minutes.
Her mind shows: talking → waveform mouth, listening → glowing antenna, **thinking → dots and a thought cloud**,
Claude Code done → a happy jump, Claude needs permission → "!". Her questions and reminders appear as speech bubbles.
She hides during fullscreen apps.

---

## 12. Security & privacy

- The API only answers local requests (no CORS). Secrets live in `.env` and Windows Credential Manager.
- **Wrong-password alert:** a failed sign-in takes a webcam photo and sends it to Telegram (set up once with admin rights).
- Private things never go to an AI or chat memory: clipboard contents, passwords, notes/diary (from reflection),
  typed text, WhatsApp messages. "Hey Friday" never logs what it hears.
- Your activity (apps, window titles, sites, files, minutes) is recorded and analysed locally. Telegram summaries
  share activity reports with your configured chat on the schedule above; requested files also go there.
  AI calls receive the name of something she's looking up ("What is <app or page title>?") or the facts of the
  one thought she's about to say, for wording. Private/incognito windows and banking/login pages are never recorded.
- Destructive actions ask first (organise, delete installers, shutdown, WhatsApp, killing a port).

---

## 13. Under the hood

- **AI providers:** OpenRouter (default), Anthropic, OpenAI (any compatible gateway), Ollama (local
  `qwen2.5:3b`). Automatic failover; short simple chats try the local model first; offline → local.
- **Speech-to-text:** NVIDIA Parakeet TDT 0.6B v2 (int8 ONNX on CPU, ~0.2 s per command), Whisper as fallback.
- **Text-to-speech:** edge-tts (en-US-AriaNeural), Piper offline, cached confirmations.
- **Command understanding:** local word lists first, a meaning-based command cache, then an AI with tool calling.
- **Local embeddings** (bge-small, GPU) for file search, memory and the command cache.
- **Remembering changes your schedule:** "I have placement training for the next 4 days, so I won't
  have classes" stores a dated exception immediately. Class warnings, study-mode offers, attendance
  questions and timetable answers respect it; the weekly schedule resumes afterward. Correct it with
  "classes resume tomorrow" or forget the training fact. Older remembered instructions use the date
  you originally told her, so "next four days" doesn't move forward every day.
- **She decides whether to notify:** proactive observations become candidates. Her reasoning model
  reads remembered facts with dates/source, date constraints, activity and recent notification outcomes,
  then chooses send or silence. Current facts/context are checked again before each send. Ordinary
  completion/download alerts and filing suggestions also go through this gate while retaining their
  privacy. Unavailable reasoning stays silent; requested reminders remain recoverable for review.
  Cognition records the decision and actual transport outcome. General model chat/automation permissions
  are unchanged; `NOTIFICATION_REVIEW_ENABLED` controls this purpose separately.
