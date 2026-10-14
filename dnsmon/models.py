"""Data types shared between the monitor and the store."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Record:
    """One lookup result as persisted in the history database."""

    ts: float
    check: str
    resolver: str
    status: str
    answers: list[str]
    latency_ms: float
    error: str | None = None


@dataclass
class Event:
    """Something worth alerting on: a failure, a change, a recovery..."""

    level: str  # "critical", "warning" or "info"
    kind: str  # FAIL, MISMATCH, CHANGED, SLOW, RECOVERED
    check: str
    resolver: str
    message: str
    ts: float = field(default_factory=time.time)
