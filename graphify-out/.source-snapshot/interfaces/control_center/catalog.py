"""Offline capability descriptions backed by FRIDAY's production phrase registry."""
from dataclasses import dataclass
from pathlib import Path

from services.automation.command_phrases import PHRASE_GROUPS

ROOT = Path(__file__).resolve().parents[2]

# family: title, category, what it does, how to use it, requirements, guide
DESCRIPTIONS = {
    'apps': ('Apps & folders', 'Computer', 'Launch apps, websites and folders; search the web in Chrome and organize downloads.', 'Name the app or folder. Review the proposal before organizing files.', 'Installed apps; Windows desktop.', 'FEATURES.md'),
    'device': ('Sound, display & clipboard', 'Computer', 'Change volume/brightness, mute, take screenshots and manage clipboard history.', 'Give a level from 0 to 100, or ask for a relative change. Clipboard commands act on your local clipboard.', 'Windows; hardware controls depend on your device.', 'FEATURES.md'),
    'transforms': ('Clipboard transformations', 'Computer', 'Transform copied text or paste it without formatting.', 'Copy text first. For pasting, use Target app and select the destination.', 'Clipboard text and an editable destination.', 'FEATURES.md'),
    'typing': ('Typing & keyboard', 'Computer', 'Dictate text, draft writing and send keyboard shortcuts to another app.', 'Use Target app, then click the destination during the countdown. Review returned typing before applying it.', 'An open editable app; Windows input permissions.', 'FEATURES.md'),
    'stats': ('System statistics', 'Computer', 'Read CPU, memory, battery, GPU and storage usage.', 'Ask for the whole system or name the resource you want.', 'Windows; some sensors may be unavailable.', 'FEATURES.md'),
    'reminders': ('Reminders', 'Day & college', 'Create timed reminders, list upcoming items and cancel them.', 'Include what and when. List reminders before referring to an item number.', 'FRIDAY running when delivery is due; notifications enabled.', 'FEATURES.md'),
    'media': ('Media controls', 'Music', 'Control the current Windows media player and identify the playing track.', 'Start playback in your player, then ask to pause, resume, skip or go back.', 'A compatible media session.', 'FEATURES.md'),
    'spotify': ('Spotify playback', 'Music', 'Play songs, artists, albums, playlists and liked songs; queue, repeat and shuffle.', 'Connect Spotify first. Include a song, artist or playlist name.', 'Spotify account and configured connection; Premium for playback APIs.', 'PERSONAL_ASSISTANT_UPGRADES.md'),
    'conversation': ('Conversation & wake word', 'Chat & voice', 'Talk hands free, use Hey Friday and interrupt spoken replies.', 'Start FRIDAY desktop, then use its voice controls or Ctrl+Alt+C. Hey Friday: Ctrl+Alt+H; listen once: Ctrl+Alt+Space.', 'Microphone and configured speech models; desktop controller.', 'PERSONAL_ASSISTANT_UPGRADES.md'),
    'screen': ('Ask about the screen', 'Computer', 'Read visible content, explain an on-screen error or propose supervised computer steps.', 'Use Target app for a screen question. Computer steps use \\c followed by a task; approve each proposal with \\c yes.', 'Configured vision provider; screen images may go to that provider. Computer agent is typed only.', 'FEATURES.md'),
    'routines': ('Saved routines', 'Automation', 'Save named sequences of commands and run them by name.', 'Create a routine with named steps, or use Customize to edit it. Saving a routine does not run it.', 'Only supported commands can become executable steps.', 'CUSTOMIZATION_UI.md'),
    'modes': ('Study, work & gaming modes', 'Automation', 'Apply saved start steps, quiet settings and end/restore behavior.', 'Choose a mode; check which one is active. Customize edits the saved mode.', 'Saved mode configuration; quiet mode holds interruptions.', 'CUSTOMIZATION_UI.md'),
    'voice': ('Speech & read aloud', 'Chat & voice', 'Speak selected text and change reading speed.', 'Use Target app for reading a selection. Voice controls open the existing desktop speech controller.', 'Configured TTS; selected text for read this.', 'FEATURES.md'),
    'notes': ('Quick notes', 'Memory', 'Save short notes in a local inbox, read them and clear them.', 'Use note: followed by your text. Read notes before clearing the inbox.', 'Local saved notes.', 'FEATURES.md'),
    'reading': ('Reading list', 'Memory', 'Keep pages to read later and inspect saved reading.', 'Open a page first and use Target app when saving the current page.', 'A browser page or explicit URL.', 'FEATURES.md'),
    'files': ('File search & answers', 'Files & web', 'Find files by name/content, open results and answer from supported documents.', 'Search, then select a result by number. Rescan after adding files; \\d asks about files.', 'Enabled file index; supported local documents; model for generated answers.', 'FEATURES.md'),
    'installers': ('Downloads cleanup', 'Files & web', 'Find downloaded installers and offer to remove them.', 'Inspect the installer list, then explicitly request cleanup and review the confirmation.', 'Downloads folder access.', 'FEATURES.md'),
    'health': ('Computer health', 'Computer', 'Inspect battery health, uptime, restart needs and storage usage.', 'Ask a health question; unavailable hardware reports remain unavailable.', 'Windows system reporting.', 'FEATURES.md'),
    'limits': ('App time limits', 'Day & college', 'Track daily app use and warn when a limit is reached.', 'Name an app and a daily duration. Limits warn; they do not close applications.', 'Activity tracking and FRIDAY running.', 'FEATURES.md'),
    'watches': ('Watches & completion alerts', 'Automation', 'Watch application exits, charge, web changes, downloads and long-running work.', 'State the event you want to watch, then inspect or stop saved watches.', 'Relevant local app/site access; FRIDAY running.', 'FEATURES.md'),
    'deadlines': ('Assignments & deadlines', 'Day & college', 'Track due dates, exams and checked date changes.', 'Name the subject and date. Use College Schedules for structured editing; inspect reminder changes separately.', 'Saved deadlines; ambiguous names need clarification.', 'COLLEGE_SCHEDULES.md'),
    'timetable': ('Classes & subjects', 'Day & college', 'Read your timetable, next class, subjects, faculty and rooms.', 'Load or edit a timetable in College Schedules, then ask about a day or class.', 'Saved timetable and optional subject metadata.', 'COLLEGE_SCHEDULES.md'),
    'class_changes': ('Class rescheduling', 'Day & college', 'Move one dated class, inspect its history and review linked reminders.', 'Name the subject, occurrence and new time. Review proposed reminder updates before applying.', 'A uniquely identified saved class occurrence.', 'COLLEGE_SCHEDULES.md'),
    'task_followups': ('Proactive task help', 'Brain & learning', 'Offer bounded follow-ups for saved goals, blockers and tasks.', 'Inspect follow-up status, review an offer, or pause/resume help globally or by task.', 'Saved tasks; attention gates and daily budgets apply.', 'CONNECTED_BRAIN.md'),
    'college': ('College assistant', 'Day & college', 'Open classes, read student details and prepare subject revision packs.', 'Use College Schedules for timetable, assignments, exams, events and upload previews.', 'Configured student details, class links and study materials.', 'COLLEGE_SCHEDULES.md'),
    'attendance': ('Attendance & marks', 'Day & college', 'Record and inspect attendance and assessment scores.', 'Use exact subject names; include earned/total marks for a score.', 'Saved subjects and attendance/marks records.', 'FEATURES.md'),
    'personality': ('Personality', 'Chat & voice', 'Adjust serious replies, sarcasm and conversational tone.', 'Ask for a serious tone or enable sarcasm.', 'Backend available; AI for generated conversation.', 'FEATURES.md'),
    'power': ('Lock, sleep & shutdown', 'Computer', 'Request Windows power actions and cancel a scheduled shutdown.', 'Read the confirmation and approve only the requested action. Save your work first.', 'Windows; existing confirmations still apply.', 'FEATURES.md'),
    'insights': ('Study insights', 'Activity & projects', 'Summarize observed study patterns and productive times.', 'Ask after collecting some activity history; interpretations are estimates.', 'Enough local activity history.', 'FEATURES.md'),
    'devtools': ('Developer tools', 'Activity & projects', 'Inspect development servers and outdated project dependencies.', 'Register a project and ask for its development status.', 'Saved project and installed development tools.', 'FEATURES.md'),
    'habits': ('Learned habits', 'Brain & learning', 'Recognize repeated activity and manage suggestions based on it.', 'Inspect observed habits or pause/resume their suggestions. Use Habit tracker for explicit daily checklists.', 'Activity history; observations are not proof of intent.', 'FEATURES.md'),
    'projects': ('Project workspaces', 'Activity & projects', 'Register folders, resume saved workspaces and inspect project time.', 'Use Customize to register a folder and resume steps, then name the project.', 'A registered existing project folder.', 'CUSTOMIZATION_UI.md'),
    'journal': ('Daily journal', 'Memory', 'Create a journal from local activity and add your own notes.', 'Ask to create a journal or add an explicit journal entry.', 'Local journal folder and activity history.', 'FEATURES.md'),
    'weekly': ('Weekly summaries', 'Activity & projects', 'Read a weekly overview of observed activity and work.', 'Ask for your weekly summary; inspect the dates covered.', 'Local activity history.', 'FEATURES.md'),
    'study': ('Study time', 'Activity & projects', 'Report how long study activity was observed today.', 'Ask for study hours or a time period.', 'Activity categories and tracking enabled.', 'FEATURES.md'),
    'git': ('Git work status', 'Activity & projects', 'Check registered projects for uncommitted work.', 'Register the project folder first. The status command does not commit or push.', 'Git installed and a registered repository.', 'FEATURES.md'),
    'logins': ('Saved logins & campus Wi-Fi', 'Automation', 'Store sign-ins in Windows Credential Manager and assist local login.', 'Save a named login through the secure dialog; never paste a password into chat.', 'Windows Credential Manager; configured campus details for Wi-Fi.', 'FEATURES.md'),
    'whatsapp': ('WhatsApp & contacts', 'Phone & messaging', 'Prepare contact messages and file sharing for review.', 'Save contacts in Customize, name the contact and message, then review the existing approval flow.', 'WhatsApp installed/signed in; saved contact; laptop.', 'FEATURES.md'),
    'telegram': ('Telegram messages & files', 'Phone & messaging', 'Send text, selected files, saved answers and summaries to the configured private chat.', 'Check Telegram status, then explicitly request a send. File follow-ups use recent search selections.', 'Configured bot token and authorized recipient; internet.', 'TELEGRAM_UPGRADES.md'),
    'proactive': ('Briefings & notifications', 'Day & college', 'Offer briefings, breaks, completion notices and bounded proactive help.', 'Ask for a briefing; adjust nudges and eye breaks explicitly. Quiet/activity gates can defer delivery.', 'FRIDAY running; notifications enabled; local review when required.', 'PERSONAL_ASSISTANT_UPGRADES.md'),
    'talk': ('Spontaneous questions', 'Brain & learning', 'Consider a useful question or remain silent using your attention and saved context.', 'Ask for one question or control whether FRIDAY may start conversations.', 'Local reasoning configured; interruption budgets apply.', 'CONNECTED_BRAIN.md'),
    'reflection': ('Reflection', 'Brain & learning', 'Inspect FRIDAY\'s current thoughts derived from observed context.', 'Ask what is on its mind. Model interpretations remain separate from confirmed facts.', 'Local history and optional local reasoning.', 'CONNECTED_BRAIN.md'),
    'life': ('Mood & life state', 'Brain & learning', 'Describe the assistant\'s simulated mood and behavioral state.', 'Ask how FRIDAY feels; inspect the sources behind its interpretation.', 'Saved behavioral context; this is a simulated assistant state.', 'FEATURES.md'),
    'evening': ('Day check-in', 'Brain & learning', 'Consider one context-aware question about your day.', 'Request a check-in and answer naturally. It is not an unattended interview sequence.', 'Local reasoning; attention gates apply.', 'CONNECTED_BRAIN.md'),
    'foresight': ('Prediction comparisons', 'Brain & learning', 'Compare local prediction methods and their recorded results.', 'Inspect predictions and provide feedback rather than treating guesses as facts.', 'Enough observed activity and prediction outcomes.', 'PREDICTION_TRAINING.md'),
    'brain': ('Current activity awareness', 'Brain & learning', 'Report fresh app/window evidence and any task you explicitly labelled.', 'Ask what you are doing, or label your task. An app name alone does not establish intent or progress.', 'Recent local evidence; screen awareness only when enabled.', 'PERSONAL_ASSISTANT_AWARENESS.md'),
    'predict': ('Next-app predictions', 'Brain & learning', 'Guess your likely next app from observed patterns.', 'Ask for a prediction and compare it with what you actually do.', 'Local activity history.', 'PREDICTION_TRAINING.md'),
    'activity': ('Activity history', 'Activity & projects', 'Inspect app usage, visited topics and time over a selected period.', 'Ask what you did today or when you last used an app. Clearing history is an explicit operation.', 'Local activity tracking.', 'FEATURES.md'),
    'memory': ('Personal memory', 'Memory', 'Remember explicit owner facts and retrieve checked conversation context.', 'Say remember that followed by a fact, or ask what is saved. Use explicit forget controls to remove it.', 'Local memory; model interpretations do not become confirmed owner facts.', 'FEATURES.md'),
    'wrapped': ('Spotify Wrapped', 'Music', 'Summarize observed listening, songs and artists.', 'Ask for a recap and optionally name a period.', 'Spotify connection and listening history.', 'FEATURES.md'),
    'fun': ('Streaks & milestones', 'Activity & projects', 'Report study streaks and light activity milestones.', 'Ask for your streak after collecting activity over several days.', 'Recorded study activity.', 'FEATURES.md'),
    'cognition': ('Brain & executive status', 'Brain & learning', 'Inspect cognitive layers, actions, review budgets and source-based decisions.', 'Ask for brain/executive status. Optional review can be paused without changing command permissions.', 'Local cognition; background review uses configured Ollama.', 'CONNECTED_BRAIN.md'),
    'workspace': ('Goals & tracked tasks', 'Activity & projects', 'Keep explicit goals, task progress, blockers and next steps.', 'Create a named task, review it, and explicitly report progress or completion.', 'Saved local workspace; no automatic proof of task completion.', 'FEATURES.md'),
    'execution': ('Handoffs & project sessions', 'Activity & projects', 'Prepare/check handoffs and resume verified project-session checkpoints.', 'Select a saved task/project and review checkpoints before starting/resuming.', 'Registered project; source versions and existing approval rules.', 'FEATURES.md'),
    'reasoning': ('Evidence & conclusions', 'Brain & learning', 'Inspect local evidence-cited conclusions and proposed changes.', 'Read reasoning status; explicitly apply or reject a proposed effect.', 'Configured local model and bounded review budgets.', 'CONNECTED_BRAIN.md'),
    'learning': ('Learning & training audit', 'Brain & learning', 'Inspect aggregate learning quality, training reviews and verified outcomes.', 'Read the learning report or request one learning question; inspect evidence before confirming it.', 'Local learning records; optional local review model.', 'TRAINING.md'),
}

EXTRA = {
    'device': ('set volume to 30', 'set brightness to 50', 'unmute'),
    'typing': ('type Hello from Friday', 'write an email asking for leave', 'press ctrl+s'),
    'reminders': ('remind me in 10 minutes to stretch', 'cancel reminder 1'),
    'notes': ('note: Review chapter 3 tomorrow',),
    'files': ('\\f resume', '\\d what do my notes say about graphs', 'open result 1'),
    'spotify': ('play believer', 'play my focus playlist', 'shuffle my liked songs', 'queue kesariya', 'repeat this song'),
    'projects': ('resume friday',),
    'memory': ('remember that my favourite colour is green',),
    'workspace': ('start task: Review chapter 3',),
    'cognition': ('brain status', 'executive status', 'executive review off', 'executive review on', 'why did you decide that', 'development status'),
    'timetable': ('who takes my next class',),
    'college': ('open college schedules', 'show college events'),
    'screen': ('\\c help', '\\c status', '\\c stop'),
    'telegram': ('send me my weekly summary through telegram', 'send me the answer in telegram'),
}

ADDITIONS = (
    ('chat', 'AI chat & web answers', 'Chat & voice', 'Ask questions, write drafts and search the web with citations.', 'Choose a provider or use the backend default. \\s searches the web; ordinary chat uses recent history.', 'Configured provider/model; internet for online providers and web search.', 'AI_ASSISTANCE.md', ('hello Friday', 'look up graph traversal algorithms', '\\s Python tkinter documentation')),
    ('browser', 'Browser & research tasks', 'Files & web', 'Run supervised browser tasks and bounded cited research reports.', 'State a task. Review each proposed input step and approve with browser yes; browser stop cancels. Headless is explicit.', 'Installed Playwright Chromium; browser/provider configuration; internet for web tasks.', 'BROWSER_AUTOMATION.md', ('browser task search for tkinter examples', 'research graph traversal algorithms', 'browser status', 'browser yes', 'browser stop', 'research report', 'desktop task type Hello in Notepad')),
    ('phone', 'Android phone bridge', 'Phone & messaging', 'Select a paired phone, inspect notifications, preview replies and ring it.', 'Check phone status; choose a paired device. A notification reply needs its existing confirmation.', 'Paired KDE Connect device and available local bridge.', 'PERSONAL_ASSISTANT_UPGRADES.md', ('phone status', 'read my phone notifications', 'read phone notification 1', 'reply: I will call you later', 'ring my phone', 'forget my phone')),
    ('screen_watch', 'Local screen awareness', 'Computer', 'Opt in to private local screen analysis, inspect summaries and manage app access.', 'Start/resume explicitly. The visible watching badge must remain present; Screen access rules live in Customize.', 'Local vision model; enabled screen permission and visible badge. Raw captures are not saved.', 'screen-awareness.md', ('screen awareness status', 'resume screen awareness', 'pause screen awareness', 'stop watching my screen', 'screen memory', 'forget screen memory')),
    ('tracker', 'Daily habits & to-do', 'Day & college', 'Track daily habits, check-ins, streaks and explicit to-do completion.', 'Open the native tracker or use exact names after a colon. Completion is your report, not inferred progress.', 'Native tracker works offline; chat commands require backend.', 'HABITS_AND_TODO.md', ('open habit tracker', 'open daily dashboard', 'add habit: Read 20 minutes', 'check habit: Read 20 minutes', 'habit progress', 'add todo: Review notes', 'show my todos', 'complete todo: Review notes')),
    ('dj', 'Friday DJ', 'Music', 'Play mood mixes, suggest more from the current artist and save DJ preferences.', 'Connect Spotify, ask for a mood or more songs like the current one, then review preferences.', 'Configured Spotify playback connection.', 'PERSONAL_ASSISTANT_UPGRADES.md', ('play something chill', 'more songs like this', 'show my DJ preferences')),
    ('dates', 'Commitment date follow-ups', 'Day & college', 'Answer checked date questions and resolve postponed exams or commitments.', 'Name a saved commitment first, then ask a short follow-up. Supply a new date when asked; uncertain matches need clarification.', 'Saved uniquely identified commitment; short references expire after 15 minutes.', 'ORDINARY_CHAT_FOLLOWUPS.md', ('when is my robotics exam', 'when is it again', 'how many days left', 'my exam was postponed', 'follow-up status', 'never mind')),
    ('desktop', 'Desktop, Island & customization', 'Automation', 'Use desktop lifecycle/voice controls, the Dynamic Island, and native configuration editors.', 'Start FRIDAY from Overview. Use Tools to open existing controls/editors. Closing this window leaves the desktop running.', 'Windows desktop; backend for live controls; some editors also work offline.', 'TASKBAR.md', ('open college schedules', 'open habit tracker')),
)


@dataclass(frozen=True)
class Capability:
    key: str
    title: str
    category: str
    description: str
    how: str
    requires: str
    guide: str
    examples: tuple[str, ...]


def capabilities() -> tuple[Capability, ...]:
    items = []
    for family, commands in PHRASE_GROUPS.items():
        metadata = DESCRIPTIONS[family]
        examples = list(commands)
        examples.extend(EXTRA.get(family, ()))
        examples.extend(alias for aliases in commands.values() for alias in aliases)
        items.append(Capability(family, *metadata, tuple(dict.fromkeys(examples))))
    items.extend(Capability(*row) for row in ADDITIONS)
    return tuple(sorted(items, key=lambda item: (item.category, item.title)))


CAPABILITIES = capabilities()
CATEGORIES = ('All capabilities', *sorted({item.category for item in CAPABILITIES}))
GUIDES = {
    'CONTROL_CENTER.md': 'Start here · Control center',
    'FEATURES.md': 'Everything FRIDAY can do',
    'COMMAND_LANGUAGE.md': 'Command wording & shortcuts',
    'COMMAND_FEATURE_COVERAGE.md': 'Command family reference',
    'AI_ASSISTANCE.md': 'AI providers & language',
    'COLLEGE_SCHEDULES.md': 'College schedules & uploads',
    'HABITS_AND_TODO.md': 'Habits & to-do',
    'CUSTOMIZATION_UI.md': 'Contacts, routines, projects & modes',
    'BROWSER_AUTOMATION.md': 'Browser automation & research',
    'screen-awareness.md': 'Screen awareness & privacy',
    'PERSONAL_ASSISTANT_UPGRADES.md': 'Phone bridge, interruptions & DJ',
    'PERSONAL_ASSISTANT_AWARENESS.md': 'Personal activity awareness',
    'CONNECTED_BRAIN.md': 'Connected brain & questions',
    'DEVELOPMENT_AWARENESS.md': 'Development awareness',
    'ORDINARY_CHAT_FOLLOWUPS.md': 'Postponements & follow-ups',
    'COMMITMENT_TOPIC_FOLLOWUPS.md': 'Commitment date questions',
    'TELEGRAM_UPGRADES.md': 'Telegram setup & commands',
    'TRAINING.md': 'Training & learning reviews',
    'PREDICTION_TRAINING.md': 'Prediction verification',
    'TASKBAR.md': 'Taskbar, voice & lifecycle',
    'architecture.md': 'How FRIDAY is built',
    'current_state.md': 'Implementation status & limits',
    'island': 'Dynamic Island & native integrations',
}


def search(query: str = '', category: str = 'All capabilities') -> list[Capability]:
    words = query.casefold().split()
    return [item for item in CAPABILITIES if category in ('All capabilities', item.category)
            and all(word in ' '.join((item.title, item.category, item.description, item.how,
                                     item.requires, *item.examples)).casefold() for word in words)]


def read_guide(key: str) -> str:
    if key not in GUIDES:
        raise ValueError('Choose a guide from the list.')
    path = ROOT / 'island' / 'README.md' if key == 'island' else ROOT / 'docs' / key
    return path.read_text(encoding='utf-8-sig')
