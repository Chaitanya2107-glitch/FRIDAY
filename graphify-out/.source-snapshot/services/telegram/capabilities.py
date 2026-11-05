"""Runtime facts about Telegram, shared by chat, voice and direct status replies."""

from core.config import config
from services.telegram import client


def ready() -> bool:
    return client.enabled() and bool(config.TELEGRAM_USER_ID)


def schedule_text() -> str:
    parts = []
    for label, hour in (("daily briefing", config.TELEGRAM_BRIEFING_HOUR),
                        ("nightly recap", config.TELEGRAM_NIGHTLY_HOUR)):
        if hour.isdigit() and 0 <= int(hour) <= 23:
            parts.append(f"{label} at {int(hour):02d}:00")
    hour, day = config.TELEGRAM_WEEKLY_HOUR, config.TELEGRAM_WEEKLY_DAY
    if hour.isdigit() and 0 <= int(hour) <= 23 and 0 <= day <= 6:
        weekday = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[day]
        parts.append(f"weekly recap on {weekday} at {int(hour):02d}:00")
    return "; ".join(parts) + " (laptop local time, while FRIDAY is running)" if parts else "Scheduled summaries are off."


def prompt_section() -> str:
    # Configuration facts are safe to send to an AI; tokens, recipient IDs and
    # file contents never belong in the prompt. Configured is not a live health check.
    if not ready():
        return "\n\nTelegram capability: FRIDAY has a Telegram bot integration, but it is not configured " \
               "with both a bot token and recipient. Explain setup rather than claiming it is connected."
    return ("\n\nTelegram capability: You, FRIDAY, have an integrated Telegram bot configured for Boss. "
            "You can deliver text messages, files and summaries to Boss through it; do not say you lack Telegram access. "
            "Actual sends are performed by the command service, not by this chat response. "
            "Suggest 'send me \"hi\" through telegram' or 'send me a message through telegram saying <text>' for literal messages; "
            "'send me <file name> through telegram', 'send me that file through telegram' "
            "after a file search/selection, 'send me the answer in telegram' to forward the last saved reply "
            "exactly as written, 'send me my weekly summary through telegram', or "
            "'send me my learning report through telegram' for aggregate learning data quality. "
            "'Telegram status' checks connectivity. " + schedule_text() + ". "
            "Never claim something was sent unless the command result confirms it. "
            "Do not invent file paths, recipients, delivery results or schedule changes.")


def status() -> tuple[bool, str]:
    if not ready():
        return False, "I have a Telegram bot integration, but it needs TELEGRAM_BOT_TOKEN and TELEGRAM_USER_ID configured."
    try:
        bot = client.call("getMe")
        if not bot.get("is_bot"):
            raise client.TelegramError("Bot identity could not be verified")
    except client.TelegramError:
        return False, "My Telegram bot is configured, but I couldn't reach it just now. Try again in a moment."
    return True, "Yes, Boss — my Telegram bot is connected. I can send you text messages, files, briefings and recaps. " + schedule_text() + "."
