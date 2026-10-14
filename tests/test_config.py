from pathlib import Path

import pytest

from dnsmon.config import EXAMPLE_CONFIG, ConfigError, load_config, parse_config
from dnsmon.resolver import SYSTEM


def test_example_config_is_valid(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(EXAMPLE_CONFIG, encoding="utf-8")
    config = load_config(path)
    assert len(config.checks) == 4
    assert config.database == tmp_path / "dnsmon.db"
    assert config.resolvers == [SYSTEM, "1.1.1.1", "8.8.8.8"]


def test_defaults():
    config = parse_config({"checks": [{"domain": "example.com"}]})
    check = config.checks[0]
    assert check.name == "example.com A"
    assert check.type == "A"
    assert check.expect is None
    assert config.resolvers == [SYSTEM]
    assert config.interval == 60
    assert config.webhook_url is None


def test_expect_is_normalized():
    config = parse_config(
        {
            "checks": [
                {"domain": "a.com", "type": "mx", "expect": ["10 MX.Example.COM."]},
                {"domain": "b.com", "type": "AAAA", "expect": ["2001:0db8:0000::0001"]},
            ]
        }
    )
    assert config.checks[0].type == "MX"
    assert config.checks[0].expect == ("10 mx.example.com",)
    assert config.checks[1].expect == ("2001:db8::1",)


def test_per_check_resolvers():
    config = parse_config(
        {
            "resolvers": ["8.8.8.8"],
            "checks": [{"domain": "a.com"}, {"domain": "b.com", "resolvers": ["1.1.1.1"]}],
        }
    )
    assert config.resolvers_for(config.checks[0]) == ["8.8.8.8"]
    assert config.resolvers_for(config.checks[1]) == ["1.1.1.1"]


def test_absolute_database_path_kept(tmp_path):
    db = tmp_path / "x.db"
    config = parse_config({"database": str(db), "checks": [{"domain": "a.com"}]}, Path("elsewhere"))
    assert config.database == db


def test_webhook_env_override(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[[checks]]\ndomain = "a.com"\n', encoding="utf-8")
    monkeypatch.setenv("DNSMON_WEBHOOK_URL", "https://hooks.example.com/x")
    assert load_config(path).webhook_url == "https://hooks.example.com/x"


@pytest.mark.parametrize(
    "data, message",
    [
        ({}, "at least one"),
        ({"checks": [{"type": "A"}]}, "'domain' is required"),
        ({"checks": [{"domain": "a.com", "type": "BOGUS"}]}, "unknown record type"),
        ({"checks": [{"domain": "a.com", "typo": 1}]}, "unknown setting"),
        ({"interval": 1, "intervall": 2, "checks": [{"domain": "a.com"}]}, "unknown setting"),
        ({"resolvers": ["not-an-ip"], "checks": [{"domain": "a.com"}]}, "IP address"),
        ({"resolvers": [], "checks": [{"domain": "a.com"}]}, "non-empty"),
        ({"checks": [{"domain": "a.com", "expect": ["999.1.1.1"]}]}, "invalid value"),
        ({"checks": [{"domain": "a.com"}, {"domain": "a.com"}]}, "duplicate check names"),
        ({"interval": 0, "checks": [{"domain": "a.com"}]}, "at least 1"),
        ({"timeout": "3", "checks": [{"domain": "a.com"}]}, "must be a number"),
        ({"webhook_url": "ftp://x", "checks": [{"domain": "a.com"}]}, "http"),
    ],
)
def test_invalid_config(data, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(data)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="dnsmon init"):
        load_config(tmp_path / "nope.toml")


def test_bad_toml(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("checks = [", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(path)
