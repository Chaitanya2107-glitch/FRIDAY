# Command language coverage matrix

This pass adds bounded equivalent requests for the following command families.
Each listed canonical request and its aliases are checked against the actual feature parser.
Most action families also have integration checks through the shared command router with AI disabled.
This measures representative command coverage, not every action or every possible sentence.

Follow-up: the [action corpus](COMMAND_ACTION_COVERAGE.md) now adds 530 examples for
all 265 currently inventoried family/action outcomes, plus saved-state routing tests.
Parameter-level language coverage remains an ongoing task.

Inventory: **56 families, 104 canonical requests, 208 explicit alternative sentences**.
Shared polite prefixes multiply these variations. Parameterized patterns are listed below.

| Family | Canonical requests covered | Alternative examples |
| --- | --- | --- |
| task_followups | show task followups | show proactive task help<br>proactive task help |
| class_changes | when is tomorrow's dbms class | what time is tomorrow's dbms class<br>when is my tomorrow's dbms class |
| apps | open chrome<br>organise downloads | start my web browser<br>organize my downloads folder |
| device | read my clipboard<br>show clipboard history<br>take a screenshot | show the text i copied<br>show my recent copies<br>save a capture of my screen |
| transforms | paste as plain text<br>make my clipboard uppercase | paste without any formatting<br>capitalize everything in my clipboard |
| typing | select all<br>undo<br>new tab | select the entire document<br>reverse my last edit<br>create a fresh browser tab |
| stats | system status<br>battery | show computer resource usage<br>show remaining battery |
| reminders | list reminders | show my scheduled reminders |
| media | what's playing<br>pause the music | identify the current song<br>hold music playback |
| spotify | connect spotify<br>shuffle on<br>shuffle off | link my spotify account<br>randomize the song order<br>restore normal song order |
| conversation | conversation mode<br>end conversation mode | begin a voice conversation<br>finish our voice chat |
| screen | what's on my screen | describe my current display |
| routines | list my routines | show my automations |
| modes | list my modes<br>what mode am i in<br>start study mode<br>end mode | show available modes<br>which mode is active<br>enable study mode<br>leave the current mode |
| voice | read this<br>stop reading<br>talk faster<br>talk slower<br>normal speed | speak the selected text<br>stop reading aloud<br>increase your speaking speed<br>decrease your speaking speed<br>restore normal speaking speed |
| notes | read my notes<br>clear my notes | show my saved notes<br>empty my notes inbox |
| reading | what's on my reading list<br>add this to my reading list | show my saved reading<br>save this page for later |
| files | rescan my files<br>find my resume | refresh my file index<br>where have i stored my resume |
| installers | what installers are in my downloads<br>delete my installers | show downloaded installers<br>remove downloaded installers |
| health | battery health<br>do i need to restart<br>what's taking up space | check battery condition<br>is a restart needed<br>what is filling my disk |
| limits | what are my app limits | show application time limits |
| watches | what are you watching | show my active watches |
| deadlines | what's due | show upcoming deadlines |
| timetable | what classes do i have tomorrow<br>what's my next class<br>list my subjects | show tomorrow's lectures<br>which lecture is next<br>show enrolled subjects |
| college | join my class<br>make a revision pack for DBMS<br>what's my USN | connect me to my class<br>prepare DBMS revision notes<br>show my student registration number |
| attendance | my attendance<br>my marks | show my attendance record<br>show my recorded grades |
| personality | be serious<br>sarcasm on | use a serious tone<br>enable sarcasm |
| power | lock the laptop<br>put the laptop to sleep<br>restart the laptop<br>shut down<br>cancel the shutdown | secure my laptop<br>put my computer in sleep mode<br>reboot my workstation<br>power down my laptop<br>cancel the pending shutdown |
| insights | when do i study best | when am i most productive studying |
| devtools | what dev servers are running<br>check outdated packages | list active development servers<br>which packages need updating |
| habits | what are my habits<br>pause habit suggestions<br>resume habit suggestions | show my learned habits<br>disable habit suggestions<br>enable habit suggestions |
| projects | list my projects | show saved projects |
| journal | create my journal | generate today's journal |
| weekly | open my weekly summary | summarize my week |
| study | study hours today | show today's study time |
| git | any uncommitted work | check for unsaved git changes |
| logins | list my logins | show stored sign-ins |
| whatsapp | list my contacts | show saved whatsapp contacts |
| telegram | telegram status | check my telegram connection |
| proactive | brief me<br>turn off nudges<br>turn on nudges<br>turn on eye breaks<br>turn off eye breaks | give me a daily briefing<br>disable proactive nudges<br>enable proactive nudges<br>enable eye rest reminders<br>disable eye rest reminders |
| talk | stop talking on your own<br>you can talk freely<br>ask me something | disable spontaneous conversation<br>enable spontaneous conversation<br>ask me a question |
| reflection | what's on your mind | what are you thinking about |
| life | how are you feeling | what is your mood |
| evening | ask me about my day | start my evening check-in |
| foresight | how do your predictions compare | compare your prediction methods |
| brain | what am i doing | show my current activity |
| predict | what will i open next | predict my next app |
| activity | what have i been doing today | show today's activity |
| memory | what do you remember about me | show facts you remember about me |
| wrapped | my spotify wrapped | show my spotify listening recap |
| fun | what's my study streak | show my consecutive study days |
| cognition | brain layers<br>what did you just say<br>what action did you just take<br>executive status<br>executive review off | describe your cognitive layers<br>repeat your most recent reply<br>show your most recent action<br>cognitive review status<br>disable cognitive review |
| workspace | show my goals<br>show my tasks | what goals am i tracking<br>what tasks am i tracking |
| execution | prepare a handoff<br>check the handoff<br>start project session for college | create a task handover<br>inspect my latest handover<br>launch my project session for friday |
| reasoning | reasoning status<br>reconsider my situation | show your inferred conclusions<br>review your conclusions about my plans |
| learning | learning report | show your learning audit |

## Parameterized requests

- Workflow creation and running use the supplied routine name and steps.
- WhatsApp messages preserve the supplied contact and exact message body.
- Telegram forwarding supports text, files and previous answers through the existing Telegram parser.
- File finding accepts arbitrary search terms; explicit file questions keep their original wording.
- Web research accepts arbitrary queries and shared polite prefixes.
- Diary entries keep their original text.
- Deadlines retain their task name and date expression.
- Attendance accepts present/absent and today/yesterday for known subjects.
- Online-class joins and revision packs accept arbitrary subject names.
- Saved-login requests retain their account name and remote restrictions.
- Task handovers retain their task reference, including names ending in Friday.
- Task and goal creation retain the supplied title and punctuation.

The earlier command-language tests additionally cover app targets, screenshots, spelled-out
volume/brightness percentages, comparative directions, and locally recognized multi-step requests.

## Capabilities without a natural-language command surface

Tray/hotkey controls, the desktop body animations, file context menus, wrong-password alerts,
automatic activity collection, nightly training, notifications, provider failover and local API security
are UI, configuration or background features. Their behavior is covered by the existing regression
suite; adding a synonym does not create a new command for them.

Recognition does not enable capabilities disabled by AI_ASSIST_ONLY or remove connection, account,
known-subject, saved-login, confirmation or laptop-only requirements.

See [checkpoint and remaining work](COMMAND_COVERAGE_PROGRESS.md) for verification and gaps.
