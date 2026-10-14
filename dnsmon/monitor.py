"""Running checks and turning results into events."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .config import Check, Config
from .models import Event, Record
from .resolver import QueryResult, query
from .store import Store

OK = "ok"
FAIL = "fail"
MISMATCH = "mismatch"

QueryFn = Callable[[str, str, str, float], QueryResult]


@dataclass
class Outcome:
    check: Check
    resolver: str
    result: QueryResult
    status: str
    slow: bool
    events: list[Event]


def classify(check: Check, result: QueryResult) -> str:
    if not result.ok:
        return FAIL
    if check.expect is not None and list(check.expect) != result.answers:
        return MISMATCH
    return OK


def evaluate(
    check: Check,
    resolver: str,
    result: QueryResult,
    previous: Record | None,
    latency_warn_ms: float,
) -> tuple[str, list[Event]]:
    """Classify a result and compare it with the previous one for the same check/resolver.

    Events fire on transitions only, so a check that stays broken alerts once,
    not on every round.
    """
    status = classify(check, result)
    events: list[Event] = []

    def emit(level: str, kind: str, message: str) -> None:
        events.append(Event(level, kind, check.name, resolver, message))

    prev_status = previous.status if previous else None
    if status != prev_status:
        if status == FAIL:
            emit("critical", "FAIL", f"lookup failed: {result.error}")
        elif status == MISMATCH:
            emit(
                "critical",
                "MISMATCH",
                f"expected {_fmt(check.expect)}, got {_fmt(result.answers)}",
            )
        elif previous is not None:
            emit("info", "RECOVERED", f"back to normal: {_fmt(result.answers)}")
    elif status != FAIL and result.answers != previous.answers:
        emit("warning", "CHANGED", f"{_fmt(previous.answers)} -> {_fmt(result.answers)}")

    if result.ok and result.latency_ms > latency_warn_ms:
        was_fast = (
            previous is None
            or previous.status == FAIL
            or previous.latency_ms <= latency_warn_ms
        )
        if was_fast:
            emit(
                "warning",
                "SLOW",
                f"answered in {result.latency_ms:.0f} ms (threshold {latency_warn_ms:g} ms)",
            )

    return status, events


def run_cycle(config: Config, store: Store, query_fn: QueryFn | None = None) -> list[Outcome]:
    """Run every check against its resolvers once, record the results, return outcomes."""
    query_fn = query_fn or query
    jobs = [(check, r) for check in config.checks for r in config.resolvers_for(check)]
    with ThreadPoolExecutor(max_workers=min(16, len(jobs))) as pool:
        results = list(
            pool.map(lambda job: query_fn(job[0].domain, job[0].type, job[1], config.timeout), jobs)
        )

    now = time.time()
    outcomes = []
    for (check, resolver), result in zip(jobs, results):
        previous = store.last(check.name, resolver)
        status, events = evaluate(check, resolver, result, previous, config.latency_warn_ms)
        store.add(
            Record(now, check.name, resolver, status, result.answers, result.latency_ms, result.error)
        )
        for event in events:
            store.add_event(event)
        slow = result.ok and result.latency_ms > config.latency_warn_ms
        outcomes.append(Outcome(check, resolver, result, status, slow, events))
    store.commit()
    return outcomes


def _fmt(values) -> str:
    return "[" + ", ".join(values) + "]" if values else "[]"
