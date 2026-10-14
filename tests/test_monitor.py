import pytest

from dnsmon.config import Check, Config
from dnsmon.models import Record
from dnsmon.monitor import FAIL, MISMATCH, OK, evaluate, run_cycle
from dnsmon.resolver import QueryResult
from dnsmon.store import Store

CHECK = Check(name="site", domain="example.com", type="A")
PINNED = Check(name="pinned", domain="example.com", type="A", expect=("1.2.3.4",))


def ok(*answers, latency=10.0):
    return QueryResult(answers=sorted(answers), latency_ms=latency)


def failed(error="NXDOMAIN"):
    return QueryResult(latency_ms=5.0, error=error)


def prev(status, answers=(), latency=10.0):
    return Record(0.0, "site", "1.1.1.1", status, list(answers), latency, None)


def kinds(events):
    return [e.kind for e in events]


def test_first_ok_result_is_quiet():
    status, events = evaluate(CHECK, "1.1.1.1", ok("1.2.3.4"), None, 500)
    assert status == OK
    assert events == []


def test_first_failure_alerts():
    status, events = evaluate(CHECK, "1.1.1.1", failed(), None, 500)
    assert status == FAIL
    assert kinds(events) == ["FAIL"]
    assert events[0].level == "critical"
    assert "NXDOMAIN" in events[0].message


def test_repeated_failure_alerts_once():
    _, events = evaluate(CHECK, "1.1.1.1", failed(), prev(FAIL), 500)
    assert events == []


def test_recovery():
    status, events = evaluate(CHECK, "1.1.1.1", ok("1.2.3.4"), prev(FAIL), 500)
    assert status == OK
    assert kinds(events) == ["RECOVERED"]


def test_answer_change():
    _, events = evaluate(CHECK, "1.1.1.1", ok("5.6.7.8"), prev(OK, ["1.2.3.4"]), 500)
    assert kinds(events) == ["CHANGED"]
    assert events[0].message == "[1.2.3.4] -> [5.6.7.8]"


def test_unchanged_is_quiet():
    _, events = evaluate(CHECK, "1.1.1.1", ok("1.2.3.4"), prev(OK, ["1.2.3.4"]), 500)
    assert events == []


def test_mismatch_against_expected():
    status, events = evaluate(PINNED, "1.1.1.1", ok("6.6.6.6"), prev(OK, ["1.2.3.4"]), 500)
    assert status == MISMATCH
    assert kinds(events) == ["MISMATCH"]
    assert "expected [1.2.3.4], got [6.6.6.6]" in events[0].message


def test_matching_expected():
    status, _ = evaluate(PINNED, "1.1.1.1", ok("1.2.3.4"), None, 500)
    assert status == OK


@pytest.mark.parametrize(
    "previous, alerts",
    [
        (None, True),
        (prev(OK, ["1.2.3.4"], latency=10), True),
        (prev(OK, ["1.2.3.4"], latency=900), False),
        (prev(FAIL, latency=3000), True),
    ],
)
def test_slow_alerts_on_transition(previous, alerts):
    _, events = evaluate(CHECK, "1.1.1.1", ok("1.2.3.4", latency=800), previous, 500)
    assert ("SLOW" in kinds(events)) == alerts


def test_run_cycle_records_and_detects_changes(tmp_path):
    config = Config(
        checks=[CHECK, Check(name="mail", domain="example.com", type="MX")],
        resolvers=["1.1.1.1", "8.8.8.8"],
        database=tmp_path / "db.sqlite",
    )
    answers = {"A": ok("1.2.3.4"), "MX": ok("10 mail.example.com")}
    calls = []

    def fake_query(domain, rtype, resolver, timeout):
        calls.append((domain, rtype, resolver))
        return answers[rtype]

    with Store(config.database) as store:
        first = run_cycle(config, store, fake_query)
        assert len(first) == 4
        assert len(calls) == 4
        assert all(o.status == OK and not o.events for o in first)

        answers["A"] = ok("9.9.9.9")
        second = run_cycle(config, store, fake_query)
        changed = [(o.check.name, o.resolver) for o in second if o.events]
        assert changed == [("site", "1.1.1.1"), ("site", "8.8.8.8")]

        assert len(store.results(limit=100)) == 8
        assert [e.kind for e in store.events()] == ["CHANGED", "CHANGED"]
