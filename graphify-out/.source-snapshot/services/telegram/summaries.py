"""Explicitly requested Telegram reports and persistent daily/weekly delivery.

Independent of desktop notifications: gaming, being at the laptop, or having no
classes does not suppress a phone summary. No AI processes private activity data.
"""

import asyncio
import json
from datetime import datetime, timedelta

from core.config import config
from core.logger import logger
from services.telegram import capabilities, client
from services.telegram.formatting import activity_lines, section, weekly_text

state_path = config.MEMORY_DIR / "telegram_summaries.json"
RETRY_SECONDS = 300
_retry_after: dict[str, float] = {}
_delivered: dict[str, str] = {}
_busy = False


def build(kind: str, now: datetime) -> str:
    from services.activity.log import activity_log
    from services.activity import weekly
    from services.proactive import briefing

    if kind == "morning":
        return briefing.build(now, structured=True)
    if kind == "nightly":
        parts = [section("📊 Activity", activity_lines(activity_log.day_summary(now))),
                 section("⏰ Due soon", briefing._deadlines(now, structured=True))]
        return (f"🌙 FRIDAY — Nightly recap\n{now:%A, %d %B %Y}\n\n"
                + "\n\n".join(part for part in parts if part))
    if kind == "weekly":
        report = weekly.build(weekly.monday_of(now.date()), activity_log)
        body = "📈 FRIDAY — Weekly recap\n\n" + weekly_text(report)
        if getattr(config, 'LEARNING_DATA_ENABLED', False):
            from services.learning import reports
            # Ingest at the real observation time even when catching up an old cutoff.
            body += '\n\n' + reports.build(end=now)
        return body
    if kind == 'learning':
        from services.learning import reports
        return reports.build(now=now)
    raise ValueError("Unknown Telegram report")


def deliver(kind: str, now: datetime | None = None) -> None:
    if not capabilities.ready():
        raise client.TelegramError("Telegram bot and recipient are not configured")
    try:
        body = build(kind, now or datetime.now())
    except Exception as error:
        logger.warning('Telegram report build failed: %s', type(error).__name__)
        raise client.TelegramError('Report is unavailable') from None
    client.send_long(config.TELEGRAM_USER_ID, body)


def _load() -> dict:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        return (state if isinstance(state, dict) else {}) | _delivered
    except (OSError, ValueError):
        return dict(_delivered)


def _save(state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp = state_path.with_suffix(".tmp")
    temp.write_text(json.dumps(state), encoding="utf-8")
    temp.replace(state_path)


def _tracking_started(now: datetime) -> datetime | None:
    from services.learning.catalog import catalog
    value = catalog.report(now, now).get('tracking_started')
    return datetime.fromisoformat(value) if value else None


def _weekly_cutoff(period: str) -> datetime:
    return datetime.fromisoformat(period) + timedelta(days=config.TELEGRAM_WEEKLY_DAY,
                                                      hours=int(config.TELEGRAM_WEEKLY_HOUR))


def _weekly_key(period: str) -> str:
    return f'weekly:{config.TELEGRAM_USER_ID}:{period}'


def _weekly_due(now: datetime, state: dict) -> list[tuple[str, str]]:
    hour = config.TELEGRAM_WEEKLY_HOUR
    if not hour.isdigit() or not 0 <= int(hour) <= 23 or not 0 <= config.TELEGRAM_WEEKLY_DAY <= 6:
        return []
    if now.timestamp() < _retry_after.get('weekly', 0):
        return []
    try:
        started = _tracking_started(now)
    except Exception as error:
        logger.warning('Weekly learning tracking unavailable: %s', type(error).__name__)
        return []
    if started is None:
        return []
    period_start = (started - timedelta(days=started.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    pending = []
    while period_start <= now:
        period = period_start.date().isoformat()
        cutoff = _weekly_cutoff(period)
        if started <= cutoff <= now and not state.get(_weekly_key(period)):
            pending.append(('weekly', period))
        period_start += timedelta(days=7)
    return pending


def _snapshot_path():
    return state_path.with_name(state_path.stem + '_weekly_snapshots.json')


def _snapshots() -> dict:
    path = _snapshot_path()
    if not path.exists():
        return {}
    # Corrupt snapshots must not be silently regenerated with changing counts.
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Invalid weekly snapshot store')
    return value


def _save_snapshots(value: dict) -> None:
    path = _snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value), encoding='utf-8')
    temp.replace(path)


def _parts(text: str) -> list[str]:
    result = []
    while text:
        end = min(len(text), client.TEXT_LIMIT)
        if end < len(text):
            newline = text.rfind('\n', 0, end)
            if newline >= end // 2:
                end = newline + 1
        result.append(text[:end])
        text = text[end:]
    return result


def _deliver_weekly(period: str) -> None:
    key = _weekly_key(period)
    snapshots = _snapshots()
    if key not in snapshots:
        snapshots[key] = {'body': build('weekly', _weekly_cutoff(period)), 'acknowledged_parts': 0,
                          'uncertain_failure': False}
        _save_snapshots(snapshots)
    snapshot = snapshots[key]
    parts = _parts(snapshot['body'])
    for index in range(snapshot['acknowledged_parts'], len(parts)):
        # Persist ambiguity before the network call. A crash after acknowledgement
        # but before saving may repeat that chunk; exactly-once is not promised.
        snapshot['uncertain_failure'] = True
        _save_snapshots(snapshots)
        client.send(config.TELEGRAM_USER_ID, parts[index])
        snapshot['acknowledged_parts'] = index + 1
        snapshot['uncertain_failure'] = False
        _save_snapshots(snapshots)


def due(now: datetime) -> list[tuple[str, str]]:
    from services.activity import weekly

    state, found = _load(), []
    for kind, hour in (("morning", config.TELEGRAM_BRIEFING_HOUR),
                       ("nightly", config.TELEGRAM_NIGHTLY_HOUR),
                       ("weekly", config.TELEGRAM_WEEKLY_HOUR)):
        if kind == 'weekly' and getattr(config, 'LEARNING_DATA_ENABLED', False):
            found.extend(_weekly_due(now, state))
            continue
        if not hour.isdigit() or not 0 <= int(hour) <= 23 or now.hour < int(hour):
            continue
        if kind == "weekly" and now.weekday() != config.TELEGRAM_WEEKLY_DAY:
            continue
        period = weekly.monday_of(now.date()).isoformat() if kind == "weekly" else now.date().isoformat()
        if state.get(kind) != period and now.timestamp() >= _retry_after.get(kind, 0):
            found.append((kind, period))
    return found


async def tick(now: datetime) -> None:
    global _busy
    if _busy or not capabilities.ready():
        return
    _busy = True
    try:
        for kind, period in due(now):
            try:
                if kind == 'weekly' and getattr(config, 'LEARNING_DATA_ENABLED', False):
                    await asyncio.to_thread(_deliver_weekly, period)
                else:
                    await asyncio.to_thread(deliver, kind, now)
            except Exception as error:
                # No marker on failure: retry after five minutes. Exception text
                # could contain private content, so log only the error type.
                _retry_after[kind] = now.timestamp() + RETRY_SECONDS
                logger.warning("Telegram %s summary failed: %s", kind, type(error).__name__)
                if kind == 'weekly':
                    break  # preserve catch-up order and the five-minute retry delay
                continue
            _delivered[kind] = period
            if kind == 'weekly' and getattr(config, 'LEARNING_DATA_ENABLED', False):
                _delivered[_weekly_key(period)] = period
            try:
                _save(_load())
            except OSError as error:
                # A successful send must not repeat every minute if disk writes
                # fail. Keep a process-local marker and report persistence failure.
                logger.warning("Telegram summary delivery state could not be saved: %s", type(error).__name__)
            _retry_after.pop(kind, None)
            logger.debug("Telegram %s summary delivered for %s", kind, period)
    finally:
        _busy = False
