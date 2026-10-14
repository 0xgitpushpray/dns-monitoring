import json

import pytest

from dnsmon import cli
from dnsmon.resolver import QueryResult

CONFIG = """\
resolvers = ["1.1.1.1"]
[[checks]]
domain = "example.com"
[[checks]]
name = "pinned"
domain = "example.org"
expect = ["9.9.9.9"]
"""


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr(
        "dnsmon.monitor.query",
        lambda domain, rtype, resolver, timeout: QueryResult(["1.2.3.4"], 12.0),
    )
    monkeypatch.delenv("DNSMON_WEBHOOK_URL", raising=False)
    return path


def test_init_writes_example(tmp_path, capsys):
    path = tmp_path / "config.toml"
    assert cli.main(["init", "-c", str(path)]) == 0
    assert path.exists()
    assert cli.main(["init", "-c", str(path)]) == 2
    assert "already exists" in capsys.readouterr().err


def test_check_reports_mismatch_and_exit_code(config, capsys):
    assert cli.main(["check", "-c", str(config)]) == 1
    out = capsys.readouterr().out
    assert "example.com A" in out
    assert "MISMATCH" in out
    assert "expected [9.9.9.9], got [1.2.3.4]" in out


def test_check_json(config, capsys):
    cli.main(["check", "-c", str(config), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert [d["status"] for d in data] == ["ok", "mismatch"]
    assert data[0]["answers"] == ["1.2.3.4"]


def test_history(config, capsys):
    cli.main(["check", "-c", str(config)])
    capsys.readouterr()
    assert cli.main(["history", "-c", str(config)]) == 0
    assert "example.com A" in capsys.readouterr().out
    assert cli.main(["history", "-c", str(config), "--events"]) == 0
    assert "MISMATCH" in capsys.readouterr().out


def test_missing_config(tmp_path, capsys):
    assert cli.main(["check", "-c", str(tmp_path / "missing.toml")]) == 2
    assert "dnsmon init" in capsys.readouterr().err
