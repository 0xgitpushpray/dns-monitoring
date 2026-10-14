import time

from dnsmon.models import Event, Record
from dnsmon.store import Store


def test_last_returns_latest_per_check_and_resolver(tmp_path):
    with Store(tmp_path / "db.sqlite") as store:
        store.add(Record(1.0, "a", "1.1.1.1", "ok", ["1.2.3.4"], 10.0))
        store.add(Record(2.0, "a", "1.1.1.1", "fail", [], 20.0, "timed out"))
        store.add(Record(3.0, "a", "8.8.8.8", "ok", ["5.6.7.8"], 30.0))
        store.commit()

        latest = store.last("a", "1.1.1.1")
        assert latest.status == "fail"
        assert latest.error == "timed out"
        assert store.last("a", "8.8.8.8").answers == ["5.6.7.8"]
        assert store.last("b", "1.1.1.1") is None


def test_history_filters_and_orders(tmp_path):
    with Store(tmp_path / "db.sqlite") as store:
        for i in range(5):
            store.add(Record(float(i), "a" if i % 2 else "b", "system", "ok", [], 1.0))
        store.add_event(Event("warning", "CHANGED", "a", "system", "x", ts=1.0))
        store.add_event(Event("critical", "FAIL", "b", "system", "y", ts=2.0))
        store.commit()

        assert [r.ts for r in store.results(limit=3)] == [4.0, 3.0, 2.0]
        assert [r.ts for r in store.results(check="a")] == [3.0, 1.0]
        assert [e.kind for e in store.events()] == ["FAIL", "CHANGED"]
        assert [e.kind for e in store.events(check="a")] == ["CHANGED"]


def test_prune(tmp_path):
    now = time.time()
    with Store(tmp_path / "db.sqlite") as store:
        store.add(Record(now - 10 * 86400, "a", "system", "ok", [], 1.0))
        store.add(Record(now, "a", "system", "ok", [], 1.0))
        store.add_event(Event("info", "RECOVERED", "a", "system", "old", ts=now - 10 * 86400))
        store.commit()

        store.prune(0)
        assert len(store.results()) == 2

        store.prune(7)
        assert len(store.results()) == 1
        assert store.events() == []


def test_persists_across_connections(tmp_path):
    path = tmp_path / "sub" / "db.sqlite"
    with Store(path) as store:
        store.add(Record(1.0, "a", "system", "ok", ["x"], 1.0))
        store.commit()
    with Store(path) as store:
        assert store.last("a", "system").answers == ["x"]
