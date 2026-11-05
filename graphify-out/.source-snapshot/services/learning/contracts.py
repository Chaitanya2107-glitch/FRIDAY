"""Shared metadata-only contracts for collection, screening and model samples."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

POLICY_VERSION = "next-app-v1"
ScreeningStatus = Literal["accepted", "excluded", "quarantined", "pending"]


@dataclass(frozen=True)
class LearningRecord:
    source: str
    source_id: str
    revision: str
    event_at: datetime | None
    category: str
    status: ScreeningStatus
    reason: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Session:
    source_id: str
    at: datetime | None
    app: str | None
    seconds: float | None
    category: str = "unknown"
    origin: str = "unknown"
    status: ScreeningStatus = "accepted"
    runtime: str | None = None


@dataclass(frozen=True)
class PredictionFeedback:
    source_id: str
    at: datetime | None
    app: str
    nxt: str
    right: bool
    before: str | None = None
    available_at: datetime | None = None


@dataclass(frozen=True)
class TrainingExample:
    source_id: str
    feature_at: datetime
    label_at: datetime
    app: str
    nxt: str
    before: str | None
    source_ids: tuple[str, ...]
    weight: float = 1.0
    feedback_ids: tuple[str, ...] = ()
    feedback_at: datetime | None = None

    @property
    def row(self) -> tuple[datetime, str, str, str | None]:
        return self.feature_at, self.app, self.nxt, self.before


@dataclass(frozen=True)
class Dataset:
    examples: tuple[TrainingExample, ...]
    fingerprint: str
    reasons: dict[str, int] = field(default_factory=dict)
    policy_version: str = POLICY_VERSION


@dataclass
class SourceScan:
    records: list[LearningRecord] = field(default_factory=list)
    sessions: list[Session] = field(default_factory=list)
    feedback: list[PredictionFeedback] = field(default_factory=list)
    complete_sources: set[str] = field(default_factory=set)
    coverage: dict[str, str] = field(default_factory=dict)
