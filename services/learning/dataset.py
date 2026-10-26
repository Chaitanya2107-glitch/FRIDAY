"""Derive natural-user next-app examples without crossing rejected observations.

``label_at`` is when the first settled destination observation became available
(its first session end), independently of later same-app chunks.
Feature time always uses the first source observation. Forecast confirmation
records can arrive later and must never retrospectively change hour/day features.
"""

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from services.learning.contracts import Dataset, POLICY_VERSION, PredictionFeedback, Session, TrainingExample

SYSTEM_APPS = {"idle", "system", "lockapp", "logonui", "shellexperiencehost", "searchhost", "shellhost"}


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _reason(session: Session, now: datetime, minimum: float) -> str:
    if not session.source_id:
        return "missing_identity"
    if session.status != "accepted":
        return "screening_rejected"
    if not isinstance(session.at, datetime):
        return "invalid_time"
    if not isinstance(session.seconds, (float, int)) or isinstance(session.seconds, bool) or not math.isfinite(session.seconds) or session.seconds < 0:
        return "invalid_duration"
    try:
        if session.at > now or session.at + timedelta(seconds=session.seconds) > now:
            return "future_time"
    except (TypeError, OverflowError):
        return "invalid_time"
    if not isinstance(session.app, str) or not session.app.strip():
        return "invalid_app"
    if session.category in {"system", "idle"} or session.app.casefold() in SYSTEM_APPS:
        return "system_or_idle"
    if session.origin not in {"user", "requested"}:
        return "unknown_origin" if session.origin == "unknown" else "automatic_origin"
    if session.seconds < minimum:
        return "short_session"
    return ""


@dataclass
class _Group:
    at: datetime
    end: datetime
    settled_at: datetime
    app: str
    runtime: str | None
    ids: list[str]


def build_examples(sessions: Iterable[Session], feedback: Iterable[PredictionFeedback], now: datetime,
                   min_seconds: float = 5, max_gap_seconds: float = 60) -> Dataset:
    """Consume original chronological order; invalid records are boundaries, never removed bridges."""
    if not math.isfinite(min_seconds) or min_seconds <= 0 or not math.isfinite(max_gap_seconds) or max_gap_seconds < 0:
        raise ValueError("Invalid next-app policy timing")
    reasons: Counter = Counter()
    segments: list[list[_Group]] = []
    segment: list[_Group] = []
    sessions = tuple(sessions)
    identity_counts = Counter(session.source_id for session in sessions)
    for session in sessions:
        reason = _reason(session, now, min_seconds)
        if identity_counts[session.source_id] > 1:
            reason = "duplicate_identity"
        if reason:
            reasons[reason] += 1
            segment = []
            continue
        end = session.at + timedelta(seconds=session.seconds)
        if segment:
            previous = segment[-1]
            gap = (session.at - previous.end).total_seconds()
            boundary = ("runtime_boundary" if session.runtime != previous.runtime else
                        "chronology_boundary" if gap < 0 else
                        "unobserved_gap" if gap > max_gap_seconds else "")
            if boundary:
                reasons[boundary] += 1
                segment = []
        if not segment:
            segment = []
            segments.append(segment)
        if segment and segment[-1].app == session.app:
            segment[-1].end = end
            segment[-1].ids.append(session.source_id)
        else:
            segment.append(_Group(session.at, end, end, session.app, session.runtime, [session.source_id]))

    forecasts = {f.source_id: f for f in feedback if f.source_id}
    examples = []
    for segment in segments:
        for index in range(len(segment) - 1):
            source, target = segment[index:index + 2]
            before = segment[index - 1].app if index else None
            snapshots = []
            for item in forecasts.values():
                if (item.app, item.before) != (source.app, before):
                    continue
                if not isinstance(item.at, datetime) or not isinstance(item.available_at, datetime):
                    continue
                try:
                    if source.at <= item.at <= source.end and item.at < target.at and item.at <= item.available_at <= now:
                        snapshots.append(item)
                except TypeError:
                    continue
            snapshots.sort(key=lambda item: (item.at, item.source_id))
            matched = [item for item in snapshots if item.right and item.nxt == target.app]
            # The activity observation was available independently of feedback.
            # A late confirmation must not change an earlier fold's features.
            feature_at = source.at
            ids = tuple(source.ids + target.ids)
            # The first source and target records anchor this observed switch.
            # Extending either app with title/dwell chunks adds audit links only.
            identity = _digest([POLICY_VERSION, source.ids[0], target.ids[0]])
            examples.append(TrainingExample(identity, feature_at, target.settled_at, source.app, target.app,
                                            before, ids, 3.0 if matched else 1.0,
                                            tuple(item.source_id for item in matched),
                                            min((item.available_at for item in matched), default=None)))
    recipe = [POLICY_VERSION, min_seconds, max_gap_seconds,
              [(e.source_id, e.source_ids, e.feature_at.isoformat(), e.label_at.isoformat(), e.app, e.nxt, e.before,
                e.weight, e.feedback_ids, e.feedback_at.isoformat() if e.feedback_at else None) for e in examples]]
    return Dataset(tuple(examples), _digest(recipe), dict(reasons))
