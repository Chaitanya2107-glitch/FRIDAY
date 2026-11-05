"""Explicit whole-request paraphrases, grouped for executable coverage and docs.

Only command syntax belongs here. Never substitute synonyms inside user data.
Parameterized requests continue through the existing feature-specific parsers.
"""

PHRASE_GROUPS = {
    "apps": {
        "open chrome": ("start my web browser", "bring up google chrome"),
        "organise downloads": ("organize my downloads folder", "sort out my downloads folder"),
    },
    "device": {
        "read my clipboard": ("show the text i copied", "read the current copied text"),
        "show clipboard history": ("show my recent copies", "list recently copied items"),
        "take a screenshot": ("save a capture of my screen", "take a screen capture"),
    },
    "transforms": {
        "paste as plain text": ("paste without any formatting", "paste unformatted text"),
        "make my clipboard uppercase": ("capitalize everything in my clipboard", "convert copied text to uppercase"),
    },
    "typing": {
        "select all": ("select the entire document", "highlight everything"),
        "undo": ("reverse my last edit", "undo my last change"),
        "new tab": ("create a fresh browser tab", "open another browser tab"),
    },
    "stats": {
        "system status": ("show computer resource usage", "check overall pc performance"),
        "battery": ("show remaining battery", "how much charge remains"),
    },
    "reminders": {
        "list reminders": ("show my scheduled reminders", "what reminders are pending"),
    },
    "media": {
        "what's playing": ("identify the current song", "name the playing track"),
        "pause the music": ("hold music playback", "pause whatever is playing"),
    },
    "spotify": {
        "connect spotify": ("link my spotify account", "set up my spotify connection"),
        "shuffle on": ("randomize the song order", "play songs in random order"),
        "shuffle off": ("restore normal song order", "stop randomizing songs"),
    },
    "conversation": {
        "conversation mode": ("begin a voice conversation", "start a voice chat"),
        "end conversation mode": ("finish our voice chat", "close this conversation"),
    },
    "screen": {
        "what's on my screen": ("describe my current display", "tell me what is visible on my display"),
    },
    "routines": {
        "list my routines": ("show my automations", "what automations have i saved"),
    },
    "modes": {
        "list my modes": ("show available modes", "what modes are available"),
        "what mode am i in": ("which mode is active", "check my current mode"),
        "start study mode": ("enable study mode", "begin a study session"),
        "end mode": ("leave the current mode", "disable the current mode"),
    },
    "voice": {
        "read this": ("speak the selected text", "read the highlighted text aloud"),
        "stop reading": ("stop reading aloud", "stop your speech"),
        "talk faster": ("increase your speaking speed", "speed up your reading"),
        "talk slower": ("decrease your speaking speed", "slow your reading down"),
        "normal speed": ("restore normal speaking speed", "use your usual speaking speed"),
    },
    "notes": {
        "read my notes": ("show my saved notes", "what notes have i saved"),
        "clear my notes": ("empty my notes inbox", "erase all my notes"),
    },
    "reading": {
        "what's on my reading list": ("show my saved reading", "what have i saved to read"),
        "add this to my reading list": ("save this page for later", "bookmark this for reading"),
    },
    "files": {
        "rescan my files": ("refresh my file index", "rebuild my file index"),
        "find my resume": ("where have i stored my resume", "track down my resume"),
    },
    "installers": {
        "what installers are in my downloads": ("show downloaded installers", "list setup files in downloads"),
        "delete my installers": ("remove downloaded installers", "clean out my downloaded installers"),
    },
    "health": {
        "battery health": ("check battery condition", "how healthy is my battery"),
        "do i need to restart": ("is a restart needed", "does my laptop need a reboot"),
        "what's taking up space": ("what is filling my disk", "find what uses my storage"),
    },
    "limits": {
        "what are my app limits": ("show application time limits", "which apps have time limits"),
    },
    "watches": {
        "what are you watching": ("show my active watches", "what changes are you monitoring"),
    },
    "deadlines": {
        "what's due": ("show upcoming deadlines", "which assignments are due"),
    },
    "timetable": {
        "what classes do i have tomorrow": ("show tomorrow's lectures", "what is my class schedule tomorrow"),
        "what's my next class": ("which lecture is next", "what class comes next"),
        "list my subjects": ("show enrolled subjects", "which subjects am i taking"),
    },
    "class_changes": {
        "when is tomorrow's dbms class": ("what time is tomorrow's dbms class", "when is my tomorrow's dbms class"),
    },
    "task_followups": {
        "show task followups": ("show proactive task help", "proactive task help"),
    },
    "college": {
        "join my class": ("connect me to my class", "open my online lecture"),
        "make a revision pack for DBMS": ("prepare DBMS revision notes", "build a DBMS revision pack"),
        "what's my USN": ("show my student registration number", "tell me my university seat number"),
    },
    "attendance": {
        "my attendance": ("show my attendance record", "check class attendance"),
        "my marks": ("show my recorded grades", "show my assessment scores"),
    },
    "personality": {
        "be serious": ("use a serious tone", "disable sarcasm"),
        "sarcasm on": ("enable sarcasm", "bring back the jokes"),
    },
    "power": {
        "lock the laptop": ("secure my laptop", "lock my workstation"),
        "put the laptop to sleep": ("put my computer in sleep mode", "suspend my laptop"),
        "restart the laptop": ("reboot my workstation", "restart this device"),
        "shut down": ("power down my laptop", "switch my computer off"),
        "cancel the shutdown": ("cancel the pending shutdown", "abort the scheduled shutdown"),
    },
    "insights": {
        "when do i study best": ("when am i most productive studying", "show my best study time"),
    },
    "devtools": {
        "what dev servers are running": ("list active development servers", "show running development servers"),
        "check outdated packages": ("which packages need updating", "check for old dependencies"),
    },
    "habits": {
        "what are my habits": ("show my learned habits", "what patterns do you see in my habits"),
        "pause habit suggestions": ("disable habit suggestions", "stop suggesting my habits"),
        "resume habit suggestions": ("enable habit suggestions", "start suggesting habits again"),
    },
    "projects": {
        "list my projects": ("show saved projects", "what projects have i saved"),
    },
    "journal": {
        "create my journal": ("generate today's journal", "create my daily journal"),
    },
    "weekly": {
        "open my weekly summary": ("summarize my week", "give me this week's overview"),
    },
    "study": {
        "study hours today": ("show today's study time", "how much studying have i done today"),
    },
    "git": {
        "any uncommitted work": ("check for unsaved git changes", "show my uncommitted changes"),
    },
    "logins": {
        "list my logins": ("show stored sign-ins", "which accounts have saved logins"),
    },
    "whatsapp": {
        "list my contacts": ("show saved whatsapp contacts", "who can i message on whatsapp"),
    },
    "telegram": {
        "telegram status": ("check my telegram connection", "is my telegram bot connected"),
    },
    "proactive": {
        "brief me": ("give me a daily briefing", "bring me up to date"),
        "turn off nudges": ("disable proactive nudges", "stop proactive reminders"),
        "turn on nudges": ("enable proactive nudges", "resume proactive reminders"),
        "turn on eye breaks": ("enable eye rest reminders", "remind me to rest my eyes"),
        "turn off eye breaks": ("disable eye rest reminders", "stop eye rest reminders"),
    },
    "talk": {
        "stop talking on your own": ("disable spontaneous conversation", "stop starting conversations"),
        "you can talk freely": ("enable spontaneous conversation", "you may start conversations"),
        "ask me something": ("ask me a question", "start a question for me"),
    },
    "reflection": {
        "what's on your mind": ("what are you thinking about", "share your current thoughts"),
    },
    "life": {
        "how are you feeling": ("what is your mood", "tell me how you feel"),
    },
    "evening": {
        "ask me about my day": ("start my evening check-in", "let's review my day"),
    },
    "foresight": {
        "how do your predictions compare": ("compare your prediction methods", "show prediction comparisons"),
    },
    "brain": {
        "what am i doing": ("show my current activity", "what am i working on right now"),
    },
    "predict": {
        "what will i open next": ("predict my next app", "which app will i use next"),
    },
    "activity": {
        "what have i been doing today": ("show today's activity", "give me my activity for today"),
    },
    "memory": {
        "what do you remember about me": ("show facts you remember about me", "what facts have you saved about me"),
    },
    "wrapped": {
        "my spotify wrapped": ("show my spotify listening recap", "give me my music recap"),
    },
    "fun": {
        "what's my study streak": ("show my consecutive study days", "how many days is my study streak"),
    },
    "cognition": {
        "brain layers": ("describe your cognitive layers", "show your brain architecture"),
        "what did you just say": ("repeat your most recent reply", "remind me of your last answer"),
        "what action did you just take": ("show your most recent action", "which action did you last perform"),
    },
    "workspace": {
        "show my goals": ("what goals am i tracking", "list my saved objectives"),
        "show my tasks": ("what tasks am i tracking", "show my saved task progress"),
    },
    "execution": {
        "prepare a handoff": ("create a task handover", "save a handover for my current task"),
        "check the handoff": ("inspect my latest handover", "show the handover status"),
    },
    "reasoning": {
        "reasoning status": ("show your inferred conclusions", "what conclusions have you drawn"),
        "reconsider my situation": ("review your conclusions about my plans", "reassess my current situation"),
    },
    "learning": {
        "learning report": ("show your learning audit", "show the training data report"),
    },
}

PHRASE_ALIASES = {
    phrase: canonical
    for commands in PHRASE_GROUPS.values()
    for canonical, aliases in commands.items()
    for phrase in aliases
}
