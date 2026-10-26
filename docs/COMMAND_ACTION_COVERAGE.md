# Parser action coverage

**265 family/action outcomes across 56 families; 530 frozen phrase examples.**

This inventory includes literal actions, helper actions, dictionary-driven actions, explicit finite computed-action domains, and the non-dictionary outcomes of conversation, cognition, screen, learning and mood parsers.
Media and Spotify share a parser; their outcome rows intentionally overlap. Counts are family/action pairs, not globally unique action names.
A test compares the source inventory with the frozen corpus. A new literal action, unknown computed expression, missing example or stale example fails verification.
Screen, learning and mood are single recognition surfaces rather than action enumerations. Computed action domains have explicit source checks where necessary. This is a bounded source audit, not a formal proof of all runtime behavior.

The shared YouTube helper can produce open_url, but the media entry point deliberately declines those requests; an explicit test verifies that the apps parser owns them.

Two phrases per action demonstrate recognition. Different target values, directions or modes can share one action name; parameter-level exhaustiveness remains separate work.

| Family | Outcome | Tested examples |
| --- | --- | --- |
| task_followups | task_followup_status | show task followups<br>show proactive task help |
| task_followups | task_followup_control | pause task followups for Review code<br>resume task followups |
| task_followups | task_followup_response | review this task followup<br>explain that task followup |
| class_changes | move_class_session | tomorrow's DBMS class moved from 9 AM to 11 AM<br>move monday's OS class to 2 PM |
| class_changes | recall_class_session | when is tomorrow's DBMS class<br>what time is monday's OS class |
| class_changes | class_session_history | show class history for tomorrow's DBMS<br>list class history for monday's OS |
| class_changes | link_class_reminder | link reminder 1 to tomorrow's DBMS class<br>link reminder 2 to monday's OS class |
| class_changes | class_reminder_updates | review class reminder updates for tomorrow's DBMS<br>apply class reminder updates for monday's OS |
| activity | activity_summary | what have i been doing today<br>show today's activity |
| activity | clear_activity | clear my activity log<br>Could you please clear my activity log |
| apps | open_app | open chrome<br>start my web browser |
| apps | open_folder | open my downloads folder<br>show my photos |
| apps | open_url | open youtube<br>go to github |
| apps | organise_folder | organise downloads<br>organize my downloads folder |
| apps | search_chrome | google best pizza near me<br>search on google for rtx 5090 price |
| attendance | add_marks | scored 20/25 in dbms cie 2<br>I got 18 out of 25 in DBMS CIE 1 |
| attendance | can_skip | how many DS classes can I skip<br>Could you please how many DS classes can I skip |
| attendance | exam_needed | what do I need in the DBMS exam for an A<br>what do I need in the DBMS exam for an O |
| attendance | holiday | no college today<br>No classes today |
| attendance | mark_all | attended all classes today<br>Could you please attended all classes today |
| attendance | mark_class | I attended data structures<br>bunked evs today |
| attendance | show_attendance | my attendance<br>show my attendance record |
| attendance | show_marks | my marks<br>show my recorded grades |
| brain | brain_thing | what do you know about catjang<br>Could you please what do you know about catjang |
| brain | brain_timeline | what am i doing<br>show my current activity |
| cognition | action | what action did you just take<br>show your most recent action |
| cognition | layers | brain layers<br>describe your cognitive layers |
| cognition | notification | what notification did you send<br>Could you please what notification did you send |
| cognition | notification_status | notification status<br>show notification decisions |
| cognition | notification_why | why did you send that notification<br>why did you not send that notification |
| cognition | reminder_retry | retry failed reminders<br>retry withheld reminders |
| cognition | question | what did you ask me<br>Could you please what did you ask me |
| cognition | reply | what did you just say<br>repeat your most recent reply |
| cognition | state | cognition status<br>show your cognition |
| cognition | telegram_message | what did you send through telegram<br>what was your last telegram message |
| college | join_class | join my class<br>connect me to my class |
| college | revision_pack | make a revision pack for DBMS<br>prepare DBMS revision notes |
| college | set_class_link | DS class link is meet.google.com/abc-defg-hij<br>Could you please DS class link is meet.google.com/abc-defg-hij |
| college | set_profile | my USN is R24AI123<br>my USN is 1RV23 |
| college | set_syllabus | data structures syllabus is in <br>Could you please data structures syllabus is in  |
| college | show_profile | what's my USN<br>show my student registration number |
| college | show_syllabus | Data Structures unit 1<br>what's in DS unit 2 |
| college | start_assignment | start the DS assignment<br>Could you please start the DS assignment |
| conversation | end | end conversation mode<br>finish our voice chat |
| conversation | start | conversation mode<br>begin a voice conversation |
| deadlines | move_deadline | my DBMS deadline moved from Friday to Monday<br>move deadline DBMS to Monday |
| deadlines | recall_deadline | when is my DBMS deadline<br>what is the due date for DBMS deadline |
| deadlines | deadline_history | show deadline history for DBMS<br>list deadline history for DBMS |
| deadlines | link_deadline_reminder | link reminder 1 to deadline DBMS<br>link reminder 2 to my deadline DBMS |
| deadlines | deadline_reminder_updates | review reminder updates for DBMS<br>apply reminder updates for DBMS |
| deadlines | add_deadline | DBMS assignment due Friday 11:59pm<br>add deadline OS lab record due 5 Oct |
| deadlines | clear_deadlines | clear my deadlines<br>Could you please clear my deadlines |
| deadlines | finish_deadline | done with DBMS assignment<br>I finished DBMS assignment |
| deadlines | list_deadlines | what's due<br>show upcoming deadlines |
| deadlines | remove_deadline | remove deadline 2<br>Could you please remove deadline 2 |
| device | change_brightness | brighten the screen<br>make the display darker |
| device | change_volume | crank up the volume<br>make it a lot louder |
| device | clear_clipboard_history | clear clipboard history<br>wipe clipboard history |
| device | close_app | kill spotify<br>terminate the chrome browser |
| device | list_clipboard_history | show clipboard history<br>show my recent copies |
| device | read_clipboard | read my clipboard<br>show the text i copied |
| device | restore_clipboard_item | copy clipboard item 3<br>restore clipboard item 2 |
| device | set_brightness | max brightness<br>screen brightness to 40 |
| device | set_mute | turn the sound off<br>silence |
| device | set_volume | volume max<br>half volume |
| device | take_screenshot | take a screenshot<br>save a capture of my screen |
| device | write_clipboard | copy hello world to clipboard<br>put Hello There on the clipboard |
| devtools | ci_status | did CI pass on catjang<br>check CI for catjang |
| devtools | list_servers | what dev servers are running<br>list active development servers |
| devtools | outdated | check outdated packages<br>which packages need updating |
| devtools | port_info | what's running on port 3000<br>Could you please what's running on port 3000 |
| devtools | stop_server | stop catjang's dev server<br>kill port 3000 |
| evening | evening_questions | ask me about my day<br>start my evening check-in |
| execution | cancel | cancel the handoff<br>cancel execution 0 |
| execution | prepare | prepare a handoff<br>create a task handover |
| execution | revise | refresh that brief<br>leave out the notes |
| execution | resume | resume the handoff<br>Could you please resume the handoff |
| execution | status | check the handoff<br>inspect my latest handover |
| files | find_files | find my resume<br>where have i stored my resume |
| files | select_found_file | select notes.txt<br>actually use resume.pdf instead |
| files | open_found_file | open 2<br>Open it |
| files | rescan_files | rescan my files<br>refresh my file index |
| files | reveal_found_file | show it in folder<br>Could you please show it in folder |
| foresight | foresight_stop | stop opening spotify by yourself<br>Could you please stop opening spotify by yourself |
| foresight | foresight_summary | how do your predictions compare<br>compare your prediction methods |
| fun | game_hours | how many hours did I game this week<br>gaming time today |
| fun | semester_wrap | semester wrap-up<br>how was my semester |
| fun | study_streak | what's my study streak<br>show my consecutive study days |
| git | commit_message | write a commit message for catjang<br>Could you please write a commit message for catjang |
| git | git_changes | what did i change in catjang today<br>what did i commit to catjang this week |
| git | git_check | any uncommitted work<br>check for unsaved git changes |
| habits | forget_habit | forget the spotify habit<br>stop suggesting spotify |
| habits | list_habits | what are my habits<br>show my learned habits |
| habits | pause_habits | pause habit suggestions<br>disable habit suggestions |
| habits | resume_habits | resume habit suggestions<br>enable habit suggestions |
| habits | why_habit | why did you suggest that<br>Could you please why did you suggest that |
| health | battery_health | battery health<br>check battery condition |
| health | disk_hogs | what's taking up space<br>what is filling my disk |
| health | pending_restart | do i need to restart<br>is a restart needed |
| health | uptime | how long has the laptop been on<br>uptime |
| insights | best_study | when do i study best<br>when am i most productive studying |
| insights | day_hours | when do i usually start<br>when do i usually stop |
| insights | session_forecast | how long will this session last<br>Could you please how long will this session last |
| insights | suggestion_score | how good are your suggestions<br>how useful are your habit suggestions |
| installers | delete_installers | delete my installers<br>remove downloaded installers |
| installers | list_installers | what installers are in my downloads<br>show downloaded installers |
| journal | open_journal | open my journal<br>open yesterday's journal |
| journal | search_journal | search my journal for viva<br>what did I write about cricket |
| journal | write_journal | create my journal<br>generate today's journal |
| learning | learning_report | learning report<br>show your learning audit |
| life | friday_feeling | how are you feeling<br>what is your mood |
| limits | list_limits | what are my app limits<br>show application time limits |
| limits | remove_limit | remove the limit on valorant<br>Could you please remove the limit on valorant |
| limits | set_limit | limit valorant to 2 hours a day<br>set a daily limit of 90 minutes for Minecraft |
| logins | list_logins | list my logins<br>show stored sign-ins |
| logins | log_in | log me in to github<br>sign in to github |
| logins | open_url | lms login<br>open my lms |
| logins | remove_login | remove my github login<br>Could you please remove my github login |
| logins | save_login | save my reva login<br>add a login for the reva portal |
| media | connect_spotify | connect spotify<br>hey friday, can you log in to my spotify account please |
| media | disconnect_spotify | disconnect spotify<br>Could you please disconnect spotify |
| media | like_song | like this song<br>add this song to my liked songs |
| media | media_next | move to the next track<br>next song |
| media | media_pause | pause the music<br>hold music playback |
| media | media_play | carry on playing<br>play |
| media | media_previous | go back to the previous track<br>previous track |
| media | now_playing | what's playing<br>identify the current song |
| media | play_collection | play my gym playlist<br>shuffle the playlist chill vibes on spotify |
| media | play_liked | play my liked songs<br>shuffle my favourite songs |
| media | play_music | play some music<br>play spotify |
| media | play_song | listen to Believer<br>play dilbara by pritam |
| media | queue_song | add believer to the queue<br>queue up kesariya by arijit singh |
| media | set_repeat | repeat this song<br>repeat the playlist |
| media | set_shuffle | shuffle<br>turn on shuffle please |
| memory | forget_all_memories | forget everything about me<br>Could you please forget everything about me |
| memory | forget_memory | forget the spotify habit<br>forget that my sister is Priya |
| memory | learned_this_week | what did you learn this week<br>what have you learned this week |
| memory | list_memories | what do you remember about me<br>show facts you remember about me |
| memory | memories_about | what do you know about ravi<br>what do you know about catjang |
| memory | remember | note buy a new charger<br>Note, call Ravi |
| memory | talked_about | what did we talk about yesterday<br>Could you please what did we talk about yesterday |
| modes | delete_mode | delete chill mode<br>delete routine work mode |
| modes | end_mode | end mode<br>leave the current mode |
| modes | list_modes | list my modes<br>show available modes |
| modes | mode_status | what mode am i in<br>which mode is active |
| modes | set_mode_quiet | make gaming mode not quiet<br>Could you please make gaming mode not quiet |
| modes | set_mode_steps | when I start study mode, open vs code, play lofi and set volume to 20<br>Could you please when I start study mode, open vs code, play lofi and set volume to 20 |
| modes | start_mode | start study mode<br>enable study mode |
| notes | add_diary | dear diary, look up why I'm so tired<br>journal: the viva went well |
| notes | add_note | save a note Buy USB-C Cable<br>save a note Make the screen less bright |
| notes | clear_notes | clear my notes<br>empty my notes inbox |
| notes | delete_note | delete note 2<br>Could you please delete note 2 |
| notes | list_notes | read my notes<br>show my saved notes |
| personality | roast_me | roast my week<br>roast me |
| personality | sarcasm_off | be serious<br>use a serious tone |
| personality | sarcasm_on | sarcasm on<br>enable sarcasm |
| power | away | I'm going out<br>Could you please I'm going out |
| power | cancel_shutdown | cancel the shutdown<br>cancel the pending shutdown |
| power | lock_pc | lock the laptop<br>secure my laptop |
| power | restart_pc | restart the laptop<br>reboot my workstation |
| power | shutdown_pc | shut down<br>power down my laptop |
| power | sleep_pc | put the laptop to sleep<br>put my computer in sleep mode |
| predict | bar_score | how good are your bar guesses<br>Could you please how good are your bar guesses |
| predict | predict_next | what will i open next<br>predict my next app |
| predict | prediction_accuracy | how good are your predictions<br>how accurate are your predictions |
| proactive | briefing | brief me<br>give me a daily briefing |
| proactive | eye_breaks | turn on eye breaks<br>enable eye rest reminders |
| proactive | nudges_off | turn off nudges<br>disable proactive nudges |
| proactive | nudges_on | turn on nudges<br>enable proactive nudges |
| proactive | pause_nudges | pause nudges<br>snooze nudges for 30 minutes |
| projects | list_projects | list my projects<br>show saved projects |
| projects | project_time | how long did i work on catjang this week<br>Could you please how long did i work on catjang this week |
| projects | remove_project | catjang is not a project<br>Could you please catjang is not a project |
| projects | reset_resume | reset resume for catjang<br>Could you please reset resume for catjang |
| projects | resume_project | pick up where i left off<br>resume catjang |
| projects | save_project | this is a project<br>save this as a project called idea lab |
| projects | set_resume | When I resume catjang, run npm run dev, run claude --continue, open VS Code and play lofi<br>Could you please When I resume catjang, run npm run dev, run claude --continue, open VS Code and play lofi |
| projects | show_resume | what does resume catjang do<br>Could you please what does resume catjang do |
| projects | suggest_resume_project | working on catjang<br>Could you please working on catjang |
| reading | add_reading | add this to my reading list<br>save this page for later |
| reading | clear_reading | clear my reading list<br>Could you please clear my reading list |
| reading | done_reading | done with reading list 1<br>Could you please done with reading list 1 |
| reading | list_reading | what's on my reading list<br>show my saved reading |
| reading | open_reading | open reading list 2<br>open item 2 from my reading list |
| reasoning | apply | apply reasoning proposal 7<br>Could you please apply reasoning proposal 7 |
| reasoning | reject | reject reasoning proposal 7<br>Could you please reject reasoning proposal 7 |
| reasoning | review | reconsider my situation<br>review your conclusions about my plans |
| reasoning | show | reasoning status<br>show your inferred conclusions |
| reflection | whats_on_your_mind | what's on your mind<br>what are you thinking about |
| reminders | cancel_all_reminders | delete all reminders<br>clear reminders |
| reminders | cancel_reminder | remove reminder 3<br>cancel reminder 1 |
| reminders | list_reminders | list reminders<br>show my scheduled reminders |
| reminders | set_reminder | set a reminder for 5pm to call mom<br>create a reminder in 10 minutes to stretch |
| routines | create_routine | create routine work mode: open chrome, close chrome and take a screenshot<br>create routine work mode: open chrome and mute |
| routines | delete_routine | delete the work mode routine<br>delete routine work mode |
| routines | list_routines | list my routines<br>show my automations |
| routines | run_routine | switch to work mode<br>start work mode |
| screen | screen_question | what's on my screen<br>describe my current display |
| spotify | connect_spotify | connect spotify<br>link my spotify account |
| spotify | disconnect_spotify | disconnect spotify<br>Could you please disconnect spotify |
| spotify | like_song | like this song<br>add this song to my liked songs |
| spotify | media_next | move to the next track<br>next song |
| spotify | media_pause | put the music on hold<br>hey friday, pause |
| spotify | media_play | carry on playing<br>play |
| spotify | media_previous | go back to the previous track<br>previous track |
| spotify | now_playing | what's playing?<br>what song is this |
| spotify | play_collection | play my gym playlist<br>shuffle the playlist chill vibes on spotify |
| spotify | play_liked | play my liked songs<br>shuffle my favourite songs |
| spotify | play_music | play some music<br>play spotify |
| spotify | play_song | listen to Believer<br>play dilbara by pritam |
| spotify | queue_song | add believer to the queue<br>queue up kesariya by arijit singh |
| spotify | set_repeat | repeat this song<br>repeat the playlist |
| spotify | set_shuffle | shuffle on<br>randomize the song order |
| stats | system_stats | system status<br>show computer resource usage |
| study | study_hours | study hours today<br>show today's study time |
| talk | talk_ask | ask me something<br>ask me a question |
| talk | talk_off | stop talking on your own<br>disable spontaneous conversation |
| talk | talk_on | you can talk freely<br>enable spontaneous conversation |
| talk | talk_pause | be quiet for 30 minutes<br>Could you please be quiet for 30 minutes |
| telegram | telegram_answer | send me the answer in telegram<br>send your last answer through telegram bot |
| telegram | telegram_file | send me answer.txt in telegram<br>send me that file through telegram |
| telegram | telegram_message | send me a "hi" through telegram<br>send me "Hi. Are you there?" through telegram |
| telegram | telegram_status | telegram status<br>check my telegram connection |
| telegram | telegram_summary | send me my learning report through telegram<br>send me my weekly summary through telegram |
| timetable | add_class | add class Networks on Wednesday 11 to 12 in room 101<br>add class Lab on friday 2 pm to 4 pm |
| timetable | add_subject | add subject OS<br>Could you please add subject OS |
| timetable | clear_timetable | clear my timetable<br>Could you please clear my timetable |
| timetable | import_timetable | read my timetable from the screen for section ii-a<br>read my timetable from the screen |
| timetable | list_subjects | list my subjects<br>show enrolled subjects |
| timetable | next_class | what's my next class<br>which lecture is next |
| timetable | remove_class | remove class DBMS on monday<br>remove class Physics |
| timetable | set_subjects | my subjects are Finance, Management and Marketing<br>Could you please my subjects are Finance, Management and Marketing |
| timetable | show_classes | what classes do i have tomorrow<br>show tomorrow's lectures |
| transforms | clipboard_transform | paste as plain text<br>paste without any formatting |
| typing | press_keys | select all<br>select the entire document |
| typing | type_text | type my usn<br>type my name please |
| typing | write_text | write a python script to rename files<br>write a commit message for catjang |
| voice | read_aloud | read this<br>speak the selected text |
| voice | speech_speed | talk faster<br>increase your speaking speed |
| voice | stop_speaking | stop reading<br>stop reading aloud |
| voice | wake_stats | how many false wakes<br>Could you please how many false wakes |
| watches | list_watches | what are you watching<br>show my active watches |
| watches | stop_watching | stop watching blender<br>cancel all watches |
| watches | watch_auto | tell me when the download finishes<br>Could you please tell me when the download finishes |
| watches | watch_battery | tell me when it's charged<br>tell me when the battery reaches 80% |
| watches | watch_foreground | tell me when it's done<br>ping me when its done |
| watches | watch_log | tell me when server.log logs an error<br>notify me when server.log logs an error |
| watches | watch_program | tell me when blender closes<br>let me know when the installer finishes |
| watches | watch_web | tell me when results.example.com/Class10 changes<br>Could you please tell me when results.example.com/Class10 changes |
| weekly | open_weekly | open my weekly summary<br>summarize my week |
| whatsapp | list_contacts | list my contacts<br>show saved whatsapp contacts |
| whatsapp | remove_contact | remove contact dad<br>Could you please remove contact dad |
| whatsapp | save_contact | save dad's number as 091234 56789<br>Could you please save dad's number as 091234 56789 |
| whatsapp | send_whatsapp | message mom on whatsapp: I'll be late<br>whatsapp mom I'll be late |
| workspace | add_goal | add goal high: Build Friday<br>add goal high: Learn cooking |
| workspace | clear | clear my goals and tasks<br>Could you please clear my goals and tasks |
| workspace | goal_state | pause goal Prepare for placements<br>resume goal Prepare for placements |
| workspace | goals | show my goals<br>what goals am i tracking |
| workspace | plan | plan task FRIDAY project: Review; Test<br>Could you please plan task FRIDAY project: Review; Test |
| workspace | priority | set goal Build Friday priority low<br>Could you please set goal Build Friday priority low |
| workspace | start_task | start task: DBMS revision<br>start task: FRIDAY project |
| workspace | step | finish task step FRIDAY project: Review finished<br>Could you please finish task step FRIDAY project: Review finished |
| workspace | task_state | complete task First project: Finished review<br>block task FRIDAY project: Waiting for feedback |
| workspace | tasks | show my tasks<br>what tasks am i tracking |
| wrapped | spotify_wrapped | my spotify wrapped<br>show my spotify listening recap |

## Saved-state routing coverage

`tests/test_stateful_command_language.py` uses temporary stores and mocked OS/integration boundaries to check:

- Routine creation, step replacement, execution and deletion; a removed name no longer runs.
- Mode step editing, quiet settings, activation, deactivation and deletion.
- Project registration, resume-step editing/inspection/reset, actual local resume routing and unregistration; project files remain present.
- Correct file-result selection/reveal, expired search results and invalid indices.
- Contact creation/update/removal, exact message contents and confirmation before sending; removed contacts do not receive a message.
- Reading-list URL case, selected-item opening/removal and invalid indices.
- Negations and payloads containing these instructions remain unchanged by paraphrase translation.

All routing tests in this file use AI_ASSIST_ONLY=true. They do not open real apps, reveal real files or send messages.

Corpus: `tests/command_action_examples.json`. Inventory and guards: `tests/command_action_support.py` and `tests/test_command_action_coverage.py`.
See [saved progress and remaining areas](COMMAND_COVERAGE_PROGRESS.md).
