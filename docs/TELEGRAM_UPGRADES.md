# FRIDAY on Telegram

Restart FRIDAY once after installing these changes. Send `/h` (or `/help`) for
the full command guide, grouped by feature, with examples. `/start` shows the
same guide. These examples use your configured private chat with FRIDAY.

| Message | Result |
| --- | --- |
| `/h` | Show all command categories, slash shortcuts and request examples. |
| `/! /sleep` | Sleep immediately, without a confirmation question. |
| `/! /send notes.pdf` | Find and upload the file without asking first. |
| `/! type hello` | Type `hello` into the active laptop window immediately. |
| `/cc right-arrow` | Press the right arrow once. |
| `/cc enter` | Press Enter once. |
| `/cc ctrl+s` | Press Ctrl+S once. |
| `brain status` | Reply with the laptop's local brain status in Telegram. |
| `executive status` | Reply with local executive review status. |
| `notification status` | Reply with local notification delivery status. |
| `reasoning status` | Reply with local facts and reasoning proposals. |
| `brief me` | Reply with the structured daily briefing. |
| `send me my weekly summary through telegram` | Deliver the structured weekly report. |

`/!` applies to the command following it in the same message. Sending `/!` alone
shows usage and does not enable a mode. Your next ordinary command uses its usual
confirmations. Both `/! /restart` and `/! restart the laptop` work.

`/cc` acts on the window currently focused on the laptop. It accepts Enter, Tab,
Escape, arrows, function keys and supported combinations such as `alt+tab`.
Hyphenated arrows (`left-arrow`, `right-arrow`, `up-arrow`, `down-arrow`) and
spaced names (`right arrow`) both work. Invalid names return usage without
pressing anything.

Private diagnostic replies and `/!` require your direct chat with FRIDAY. The
bot still checks the configured Telegram user, ignores forwarded commands, and
honors `/lockdown`. Existing remote clipboard, saved-login, computer-agent and
local-only mutation restrictions still apply. Laptop and Telegram pending
confirmations stay separate.

## Offline commands

Messages sent while FRIDAY or the laptop is offline run in order when FRIDAY
returns and the network is available. Commands requiring confirmation ask when
they run; use `/! <command>` to execute them without that question.

Telegram stores unseen messages for **up to 24 hours**. Once FRIDAY receives an
update, it saves it locally before advancing Telegram's offset. Received pending
commands survive a restart; duplicate fetched updates do not run again.

If FRIDAY stops during an execution, it cannot always tell whether the action
finished. It reports the interrupted command and leaves it for you to check
instead of repeating a potentially completed action. An old queued `yes` cannot
approve a newly issued confirmation question.

## Briefings and reports

Daily, nightly, weekly and learning reports have emoji headings, blank lines
between sections, and bullet points. Empty optional sections are omitted.
Reminders, classes and upcoming deadlines appear as individual items. Weekly
reports separate each day and explain changes relative to the previous week.
Long answers continue across multiple messages instead of losing their end.
Spoken laptop briefings retain their existing wording.

Illustrative daily layout:

```text
☀️ FRIDAY — Daily briefing
Tuesday, 27 October 2026
Good morning.

🌤️ Weather
• Clear, 24°.

📚 Classes
• 10:00 am DBMS in A

⏰ Due soon
• DBMS assignment — tomorrow

🔔 Reminders
• 05:00 PM — Call mom

🔋 Laptop
• Battery 80%, charging.
```

The existing delivery hours are unchanged. They use the laptop's local time.
Reference: [Telegram update retention and offsets](https://core.telegram.org/bots/api#getting-updates).
