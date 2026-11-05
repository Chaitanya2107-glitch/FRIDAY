# Telegram bot — design

Date: 2026-09-28 · Status: approved in chat, being built

## Goal

Control FRIDAY from the phone and get its notifications there while away from
the laptop. First of three sub-projects (next: auto-sessions + summaries; later:
"tell me when it's done", send-to-laptop, notes inbox). No server of our own, no
ngrok: the bot polls Telegram (outbound only), so nothing on the laptop is exposed.
Works only while the laptop is on and FRIDAY is running.

## Architecture

Runs inside the backend (API process), started from `interfaces/api/app.py`'s
lifespan like the network watcher. Off entirely unless `TELEGRAM_BOT_TOKEN` is set.
No new dependency — `httpx` talks to the Bot API.

- `services/telegram/client.py` — the Bot API calls (getUpdates, sendMessage,
  sendPhoto, sendDocument, answerCallbackQuery, file download), plus the two
  things other modules need without importing the bot: `mirror()` (notification
  → Telegram when away) and the lockdown switch.
- `services/telegram/bot.py` — the poll loop and message handling.

## Behaviour

**Notifications out.** `show_toast` (every backend notification: nudges, briefing,
class warnings, reminders, FRIDAY ONLINE/OFFLINE, battery) also calls `mirror()`,
which sends to Telegram when the user has been idle ≥ `TELEGRAM_AWAY_MINUTES`
(default 10). Notification buttons become inline buttons; a tap goes through
`services/proactive/buttons.respond` with the same one-time token.

**Commands in.** Text goes through the command bar's path (`routes/chat.chat`), so
commands, AI chat, memory and FRIDAY's existing yes/no confirmations all work.
- Reply carries text/keys to type → the bot asks "Type this into <window>? yes/no" first.
- `take a screenshot` → the screenshot is sent back as a photo.
- Voice note → decoded and transcribed by the local Whisper, then handled as text.
- `send me my/the <file>` or `/send <file>` → best file-search hit, "Send <name> (<size>)? yes/no",
  then uploaded (Telegram's limit: 50 MB). No hit → handled as normal chat.
- `/status` → online/offline, battery, foreground app, active mode, idle time.
- `/lockdown` → remote control off (notifications still arrive). Only
  "unlock telegram" said/typed **at the laptop** turns it back on.

## Security

0. `.env` is tracked by git (committed before `.gitignore`) → `git rm --cached .env`
   so the bot token never enters git.
1. Only `TELEGRAM_USER_ID` is answered; everyone else is ignored (logged). Until it's
   set, the bot's only reply is "Your Telegram ID is N — add TELEGRAM_USER_ID=N to .env".
2. Forwarded messages are never run.
3. Messages older than 2 minutes or sent before FRIDAY started (queued while it was
   off) are not run: "That came in while I was offline — send it again."
4. Clipboard reading/history and saved logins are refused from Telegram
   (`intent.remote_request` context flag; checked where those actions run).
5. The token never appears in logs (errors log the method name, not the URL).
6. Telegram bot chats are not end-to-end encrypted: screenshots/files/replies pass
   through Telegram's servers, only when asked for.
7. User's side: turn on Telegram two-step verification.

## Errors

Offline → the loop waits for `network.online`. A failed Telegram call is logged and
retried with backoff; it never crashes the backend or blocks the laptop
notification. Voice that can't be transcribed → "Couldn't make that out — try typing it."

## Testing

`tests/test_telegram.py` with a fake Bot API: strangers and forwards ignored, the
setup reply, stale messages dropped, away rule for mirroring, button taps via
`buttons.respond`, yes/no before typing and file sending, lockdown blocks commands
and buttons, clipboard refused remotely, screenshot sent as a photo. Then one real run.

## Not in this project

Auto-sessions/summaries, weekly summary, shutdown/lock commands (FRIDAY has none
today), a cloud server or database sync.
