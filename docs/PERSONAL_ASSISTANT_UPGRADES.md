# Phone bridge, interruptible conversation and Friday DJ

These are the three personal-assistant upgrades approved on 2026-10-26.
The original desktop robot and appearance remain unchanged.

## Android phone bridge

KDE Connect supplies the paired Windows/Android connection. The official Windows
26.08.2 package was installed through winget, and the owner paired the Android
app and enabled notification access. Keep KDE Connect running on both devices.
If you move its Windows installation, `KDECONNECT_DIR` can identify its folder.

Use these in the command bar or by voice:

- **“Phone status”** or **“list phones”** shows paired, reachable devices.
- **“Use phone <name or device ID>”** selects one when several are connected.
- **“Read my phone notifications”** lists up to ten shared notifications.
- **“Read phone notification 2”** selects and reads that item.
- **“Read that notification”** rereads the selected item.
- **“Reply that I’ll call in ten minutes.”** previews the selected sender/app
  and exact draft. **“Yes”** submits it; **“no”** cancels. Another turn cancels
  pending confirmation, and confirmation/notification context expires after two minutes.
- **“Ring my phone”** submits KDE Connect's ring request.
- **“Forget my phone”** clears Friday's device choice and notification context;
  KDE Connect pairing remains intact.

With one reachable paired device, explicit selection is unnecessary. Notifications
need Android notification access and KDE Connect's notification plugin. Replies are
available only when the notification exposes a direct-reply action. Friday rechecks
the selected device, bus/service lifetime and notification contents before submission.
KDE Connect has no atomic compare-and-reply operation; a notification can still change
after the final read. Submission is not a messaging-app delivery acknowledgement.
Failed submissions are not automatically retried.

Phone notification text/drafts bypass chat history, chat models, search, learning,
speech caches and transcript logs. Temporary selection/drafts stay in bounded RAM.
Private desktop responses also disable Telegram toast mirroring, use redacted
notification records, and omit phone drafts from command-bar suggestion training.
Requested spoken responses use your existing TTS settings, including the online
voice when available; the private flag controls storage/mirroring, not the TTS provider.
These commands are laptop-only; Telegram cannot read or confirm them. KDE Connect
and Android retain their own notifications under their own settings. No background
Friday notification reader or new network API port is added.

“Find my phone” retains its existing file-search meaning; use **“ring my phone”**
for the device control.

## Interruptible conversation

Start with **“let’s talk”**, the conversation menu, or **Ctrl+Alt+C**. During a reply:

- **“Wait, change that to tomorrow.”** stops speech and retains the correction.
- **“Hold on.”** stops speech and leaves Friday listening for your next turn.
- **“Hey Friday, <your next request>”** is another explicit interruption cue.

Regular quiet turns need no wake phrase. The microphone capture starts before
reply generation, so it also covers the first streamed sentence. It shares the
ordinary microphone lock and stop controls; capture is not enabled outside an
explicit conversation session. “Bye”, the conversation toggle and silence end
the session. Typing instead discards pending voice input.

Interruptions use the installed speech model and lexical checks against Friday's
own words. There is no acoustic echo cancellation. Headphones improve reliability;
background speech and recognition errors can still cause missed/false cues. Recognition
checks run approximately once per second during playback, plus transcription latency.
The Windows speech fallback stops at its next word callback; Edge/Piper use existing
generation checks. A pure spoken interruption stops output, not a previously completed
external action. Corrections retain existing ambiguity, confirmation and date-edit rules.

Old queued/streamed speech retains its original generation and cannot adopt the
generation of a newer turn. Capture epochs fence stop/rearm races. Audio is bounded,
held in memory and discarded on cancellation; local transcript logging is disabled.

## Friday DJ

Use the existing **“connect Spotify”** flow if needed. Playback requires Spotify
Premium, a permitted connected account and an available playback device.

- **“Play something chill.”** starts a bounded mood mix.
- **“Give me energetic music.”** changes to an energetic mix.
- **“Switch to a relaxed mood.”** uses the chill mood.
- **“Switch the mood.”** cycles through chill, focus, energetic, happy and sleep.
- **“More songs like this.”** queues up to five other tracks from the current
  track's primary artist. This is artist-based discovery, not acoustic similarity.
- **“For chill music use my Evening Walk playlist.”** saves a named playlist.
- **“For focus music search for piano instrumental.”** saves a search preference.
- **“Show my DJ preferences.”** shows saved choices.
- **“Forget my chill music preference.”** removes one.

An explicit saved playlist/query takes priority. Otherwise Friday checks your
playlists for the mood and uses a bounded catalog search. Track mixes contain
up to eight distinct valid tracks. Playlist playback uses its context URI rather
than fetching somebody else's playlist contents. Ordinary song titles such as
“Happy” retain their normal song-search meaning. Mentioning a mood in conversation
does not start music, and bare “more like this” does not change the queue.

Preferences persist in `memory/spotify_dj.json`. Each request resolves current
preferences/current playback afresh. Queue failures report confirmed progress
and stop further additions; uncertain writes are not automatically repeated.
Playback can succeed even if saving the last requested mood fails, and that
storage failure is reported separately.

This uses existing Spotify scopes, track search, playlist playback and queue
endpoints. Recommendations, audio features/analysis and artist-top-tracks are
not required. Current API references: [Spotify's 2026 changes](https://developer.spotify.com/documentation/web-api/references/changes/february-2026)
and [queue endpoint](https://developer.spotify.com/documentation/web-api/reference/add-to-queue).
Phone setup: [official KDE Connect downloads](https://kdeconnect.kde.org/download.html).

## Loading and checking the update

Exit the taskbar widget and reopen the usual FRIDAY shortcut to reload both
desktop and backend code. The original robot is preserved.

Focused checks live in `tests/test_phone_bridge.py`, `test_phone_transport.py`,
`test_conversation_input.py` and `test_spotify_dj.py`. Installed-integration
readiness is checked by `tasks/probe_assistant_upgrades.py`; it does not read
notification contents, capture audio, ring, reply or play music. Final source
and test evidence is recorded in `tasks/assistant-upgrades-verification.json`.

Final validation: 5,638 full-suite checks passed with 13 existing opt-in skips;
498 focused checks passed. The desktop/backend were reloaded together on
2026-10-27. Live health, request/response schemas, private phone-status and DJ
preference reads passed; the microphone was off. Voice echo quality and actual
notification replies/playback still require normal owner use; the checks did not
read notification contents, record audio, ring, send a reply or start music.
