"""
services/automation/command_tools.py

The system actions FRIDAY can take, described as native AI tools. When no local
rule matches a command, services/automation/intent.py sends these to a cheap
model, which either calls one or more of them or replies with text (= chat).

Tool names and argument names match the action dicts that intent._execute()
runs, so a tool call becomes an action with no translation — except folders,
which the model picks by name and which are turned into real paths here.

TO ADD AN ACTION:
  1. Handle it in intent._execute()
  2. Describe it in build_tools() below
"""

from providers.base_provider import Tool, ToolCall

COMMAND_ROUTER_PROMPT = (
    "You are F.R.I.D.A.Y's command router, running on the user's Windows laptop. "
    "If the user's message asks you to do something on the computer, call the matching "
    "tool — several tools, in order, if they ask for several things. Only do what they "
    "explicitly asked for: never add actions or targets they didn't name. If it's a "
    "question or conversation instead, don't call any tool: reply with just the word CHAT."
)


def _object(properties: dict | None = None, required: list[str] | None = None) -> dict:
    schema = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = required
    return schema


def _level(what: str) -> dict:
    return _object(
        {"level": {"type": "integer", "minimum": 0, "maximum": 100, "description": f"{what} in percent"}},
        ["level"],
    )


def _delta(what: str) -> dict:
    return _object(
        {"delta": {"type": "integer", "description": f"Percentage points to change the {what} by; negative lowers it"}},
        ["delta"],
    )


def _number(what: str) -> dict:
    return _object(
        {"number": {"type": "integer", "minimum": 1, "description": f"The {what} number, as shown in the list"}},
        ["number"],
    )


def build_tools(app_names: list[str], folder_names: list[str]) -> list[Tool]:
    apps = ", ".join(app_names)
    app = _object(
        {"app_name": {"type": "string", "description": f"The app's name. Known apps: {apps}"}},
        ["app_name"],
    )
    folder = _object(
        {"folder": {"type": "string", "enum": folder_names, "description": "Which of the user's folders"}},
        ["folder"],
    )
    return [
        Tool("open_app", "Open (launch) an app.", app),
        Tool("close_app", "Close an app that's running.", app),
        Tool("search_chrome", "Search Google in Chrome.", _object(
            {"query": {"type": "string", "description": "What to search for"}}, ["query"])),
        Tool("open_url", "Open a website in Chrome.", _object(
            {"url": {"type": "string", "description": "The address, e.g. youtube.com"}}, ["url"])),
        Tool("open_folder", "Open one of the user's folders in File Explorer.", folder),
        Tool("organise_folder",
             "Tidy a folder by moving its files into subfolders by type. FRIDAY asks the user first.",
             folder),
        Tool("set_volume", "Set the system volume to an exact level.", _level("Volume")),
        Tool("change_volume", "Turn the system volume up or down.", _delta("volume")),
        Tool("set_mute", "Mute or unmute the system sound.", _object(
            {"mute": {"type": "boolean", "description": "true to mute, false to unmute"}}, ["mute"])),
        Tool("set_brightness", "Set the screen brightness to an exact level.", _level("Brightness")),
        Tool("change_brightness", "Make the screen brighter or dimmer.", _delta("brightness")),
        Tool("take_screenshot", "Save a screenshot to the Pictures folder.", _object()),
        Tool("read_clipboard", "Show the text currently on the clipboard.", _object()),
        Tool("write_clipboard", "Copy some text to the clipboard.", _object(
            {"text": {"type": "string", "description": "The exact text to copy"}}, ["text"])),
        Tool("list_clipboard_history", "Show recently copied items.", _object()),
        Tool("restore_clipboard_item", "Copy an item from the clipboard history back to the clipboard.",
             _number("clipboard history item")),
        Tool("clear_clipboard_history", "Forget the clipboard history.", _object()),
        Tool("media_play", "Resume the music or video that's paused in the open player.", _object()),
        Tool("media_pause", "Pause the music or video that's playing.", _object()),
        Tool("media_next", "Skip to the next song or track.", _object()),
        Tool("media_previous", "Go back to the previous song or track.", _object()),
        Tool("now_playing", "Say which song is playing.", _object()),
        Tool("play_music", "Start music: resume the open player, or open Spotify and play.", _object()),
        Tool("play_song", "Play a specific song or artist.", _object(
            {"query": {"type": "string", "description": "The song and/or artist, e.g. dilbara by pritam"}},
            ["query"],
        )),
        Tool("play_collection", "Play an artist, an album or one of the user's playlists on Spotify.", _object(
            {
                "kind": {"type": "string", "enum": ["artist", "album", "playlist"]},
                "query": {"type": "string", "description": "Its name, e.g. arijit singh, divide, gym"},
                "shuffle": {"type": "boolean", "description": "true to play it shuffled"},
            },
            ["kind", "query"],
        )),
        Tool("play_liked", "Play the user's liked songs on Spotify.", _object(
            {"shuffle": {"type": "boolean", "description": "true to play them shuffled"}})),
        Tool("set_shuffle", "Turn Spotify's shuffle on or off.", _object(
            {"on": {"type": "boolean", "description": "true for on, false for off"}}, ["on"])),
        Tool("set_repeat", "Set Spotify's repeat mode.", _object(
            {"mode": {"type": "string", "enum": ["track", "context", "off"],
                      "description": "track = this song, context = the playlist/album, off"}},
            ["mode"],
        )),
        Tool("queue_song", "Add a song to the Spotify queue, to play after the current one.", _object(
            {"query": {"type": "string", "description": "The song and/or artist"}}, ["query"])),
        Tool("like_song", "Add the song playing on Spotify to the liked songs, or remove it.", _object(
            {"like": {"type": "boolean", "description": "true to like it, false to unlike it"}}, ["like"])),
        Tool("find_files", "Find files on the user's computer by name or by what's inside them.", _object(
            {"query": {"type": "string", "description": "What the file is or contains, e.g. resume, rent agreement"}},
            ["query"],
        )),
        Tool("connect_spotify", "Log in to Spotify so FRIDAY can control it.", _object()),
        Tool("type_text", "Type exact words into the app the user is using (dictation).", _object(
            {"text": {"type": "string", "description": "Exactly the words to type"}}, ["text"])),
        Tool("write_text",
             "Write something (an email, message, paragraph, code) and type it into the app the user is using.",
             _object({"request": {"type": "string",
                                  "description": "What to write, e.g. an email asking my boss for Friday off"}},
                     ["request"])),
        Tool("press_keys", "Press a key or shortcut in the app the user is using.", _object(
            {
                "keys": {"type": "string", "description": "e.g. enter, ctrl+s, alt+tab, page down"},
                "times": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            ["keys"],
        )),
        Tool("system_stats", "Report how the computer is doing: CPU, memory, battery, GPU, disk.", _object(
            {
                "part": {"type": "string", "enum": ["cpu", "memory", "battery", "gpu", "disk"],
                         "description": "Only this part. Leave out for everything."},
                "top": {"type": "boolean", "description": "Also name the apps using the most"},
            },
        )),
        Tool("set_reminder", "Set a reminder.", _object(
            {"message": {
                "type": "string",
                "description": 'The reminder in words starting with "remind me", including when, '
                               'e.g. "remind me in 10 minutes to call mom" or "remind me at 5pm to leave"',
            }},
            ["message"],
        )),
        Tool("list_reminders", "Show the upcoming reminders.", _object()),
        Tool("cancel_reminder", "Cancel one reminder.", _number("reminder")),
        Tool("cancel_all_reminders", "Cancel every reminder.", _object()),
    ]


def tool_call_to_action(call: ToolCall, folder_paths: dict[str, str]) -> dict:
    """Turn a tool call into the action dict intent._execute() runs."""
    arguments = dict(call.arguments)
    if "folder" in arguments:
        path = folder_paths.get(str(arguments.pop("folder")).lower())
        if path:
            arguments["path"] = path  # an unknown folder leaves "path" out, so the action is ignored
    return {**arguments, "type": "system", "action": call.name}
