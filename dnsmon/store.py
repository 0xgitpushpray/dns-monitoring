"""SQLite-backed history of lookup results and events."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .models import Event, Record

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    check_name TEXT NOT NULL,
    resolver TEXT NOT NULL,
    status TEXT NOT NULL,
    answers TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_results_lookup ON results (check_name, resolver, ts);
CREATE INDEX IF NOT EXISTS idx_results_ts ON results (ts);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    level TEXT NOT NULL,
    kind TEXT NOT NULL,
    check_name TEXT NOT NULL,
    resolver TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts);
"""

_RESULT_COLUMNS = "ts, check_name, resolver, status, answers, latency_ms, error"
_EVENT_COLUMNS = "level, kind, check_name, resolver, message, ts"


class Store:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def commit(self) -> None:
        self.conn.commit()

    def add(self, record: Record) -> None:
        self.conn.execute(
            f"INSERT INTO results ({_RESULT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.ts,
                record.check,
                record.resolver,
                record.status,
                json.dumps(record.answers),
                record.latency_ms,
                record.error,
            ),
        )

    def add_event(self, event: Event) -> None:
        self.conn.execute(
            f"INSERT INTO events ({_EVENT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
            (event.level, event.kind, event.check, event.resolver, event.message, event.ts),
        )

    def last(self, check: str, resolver: str) -> Record | None:
        row = self.conn.execute(
            f"SELECT {_RESULT_COLUMNS} FROM results WHERE check_name = ? AND resolver = ? "
            "ORDER BY ts DESC, id DESC LIMIT 1",
            (check, resolver),
        ).fetchone()
        return _record(row) if row else None

    def results(self, check: str | None = None, limit: int = 50) -> list[Record]:
        """Most recent results first."""
        sql = f"SELECT {_RESULT_COLUMNS} FROM results"
        params: tuple = ()
        if check:
            sql += " WHERE check_name = ?"
            params = (check,)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        return [_record(row) for row in self.conn.execute(sql, (*params, limit))]

    def events(self, check: str | None = None, limit: int = 50) -> list[Event]:
        """Most recent events first."""
        sql = f"SELECT {_EVENT_COLUMNS} FROM events"
        params: tuple = ()
        if check:
            sql += " WHERE check_name = ?"
            params = (check,)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        return [Event(*row) for row in self.conn.execute(sql, (*params, limit))]

    def prune(self, days: float) -> None:
        """Delete history older than `days` days. 0 keeps everything."""
        if days <= 0:
            return
        cutoff = time.time() - days * 86400
        with self.conn:
            self.conn.execute("DELETE FROM results WHERE ts < ?", (cutoff,))
            self.conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))


def _record(row: tuple) -> Record:
    ts, check, resolver, status, answers, latency_ms, error = row
    return Record(ts, check, resolver, status, json.loads(answers), latency_ms, error)
