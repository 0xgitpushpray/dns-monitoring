"""Loading and validating the TOML configuration file."""

from __future__ import annotations

import ipaddress
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import dns.rdatatype

from .resolver import SYSTEM, normalize

WEBHOOK_ENV = "DNSMON_WEBHOOK_URL"

TOP_LEVEL_KEYS = {
    "interval",
    "timeout",
    "latency_warn_ms",
    "resolvers",
    "database",
    "retention_days",
    "webhook_url",
    "checks",
}
CHECK_KEYS = {"name", "domain", "type", "expect", "resolvers"}

EXAMPLE_CONFIG = """\
# dnsmon configuration

# Seconds between rounds of checks in `dnsmon watch`.
interval = 60

# Per-query timeout in seconds.
timeout = 3.0

# Flag answers slower than this many milliseconds.
latency_warn_ms = 500

# Resolvers to query. "system" uses the DNS servers configured in your OS.
resolvers = ["system", "1.1.1.1", "8.8.8.8"]

# SQLite file holding the results history (relative to this file).
database = "dnsmon.db"

# Delete history older than this many days (0 keeps everything).
retention_days = 30

# Optional Slack- or Discord-compatible webhook that receives alerts.
# Can also be set with the DNSMON_WEBHOOK_URL environment variable.
# webhook_url = "https://hooks.slack.com/services/..."

[[checks]]
domain = "example.com"
type = "A"

[[checks]]
name = "Cloudflare DNS"
domain = "one.one.one.one"
type = "A"
# Alert when the answers differ from this list.
expect = ["1.1.1.1", "1.0.0.1"]

[[checks]]
domain = "gmail.com"
type = "MX"

[[checks]]
domain = "google.com"
type = "NS"
# Query only these resolvers for this check.
resolvers = ["1.1.1.1"]
"""


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Check:
    name: str
    domain: str
    type: str
    expect: tuple[str, ...] | None = None
    resolvers: tuple[str, ...] | None = None


@dataclass
class Config:
    checks: list[Check]
    resolvers: list[str] = field(default_factory=lambda: [SYSTEM])
    interval: float = 60
    timeout: float = 3.0
    latency_warn_ms: float = 500
    database: Path = Path("dnsmon.db")
    retention_days: float = 30
    webhook_url: str | None = None

    def resolvers_for(self, check: Check) -> list[str]:
        return list(check.resolvers or self.resolvers)


def load_config(path: str | Path) -> Config:
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path} (run `dnsmon init` to create one)") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from None
    if os.environ.get(WEBHOOK_ENV):
        data["webhook_url"] = os.environ[WEBHOOK_ENV]
    return parse_config(data, base_dir=path.parent)


def parse_config(data: dict[str, Any], base_dir: Path = Path(".")) -> Config:
    _reject_unknown(data, TOP_LEVEL_KEYS, "config")

    raw_checks = data.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise ConfigError("at least one [[checks]] entry is required")
    checks = [_parse_check(raw, i) for i, raw in enumerate(raw_checks, 1)]
    names = [c.name for c in checks]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ConfigError(f"duplicate check names: {', '.join(dupes)}")

    database = Path(_string(data, "database", "dnsmon.db", "config"))
    if not database.is_absolute():
        database = base_dir / database

    webhook = data.get("webhook_url") or None
    if webhook is not None and (
        not isinstance(webhook, str) or not webhook.startswith(("http://", "https://"))
    ):
        raise ConfigError("'webhook_url' must be an http:// or https:// URL")

    return Config(
        checks=checks,
        resolvers=_resolvers(data.get("resolvers", [SYSTEM]), "config"),
        interval=_number(data, "interval", 60, 1, "config"),
        timeout=_number(data, "timeout", 3.0, 0.1, "config"),
        latency_warn_ms=_number(data, "latency_warn_ms", 500, 0, "config"),
        database=database,
        retention_days=_number(data, "retention_days", 30, 0, "config"),
        webhook_url=webhook,
    )


def _parse_check(raw: Any, index: int) -> Check:
    where = f"checks[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: must be a table")
    _reject_unknown(raw, CHECK_KEYS, where)

    domain = raw.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        raise ConfigError(f"{where}: 'domain' is required")
    domain = domain.strip()

    rtype = _string(raw, "type", "A", where).strip().upper()
    try:
        dns.rdatatype.from_text(rtype)
    except dns.rdatatype.UnknownRdatatype:
        raise ConfigError(f"{where}: unknown record type {rtype!r}") from None

    name = _string(raw, "name", f"{domain} {rtype}", where).strip()

    expect = None
    if "expect" in raw:
        values = raw["expect"]
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ConfigError(f"{where}: 'expect' must be a list of strings")
        try:
            expect = tuple(sorted({normalize(rtype, v) for v in values}))
        except ValueError as exc:
            raise ConfigError(f"{where}: invalid value in 'expect': {exc}") from None

    resolvers = None
    if "resolvers" in raw:
        resolvers = tuple(_resolvers(raw["resolvers"], where))

    return Check(name=name, domain=domain, type=rtype, expect=expect, resolvers=resolvers)


def _resolvers(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: 'resolvers' must be a non-empty list of strings")
    result = []
    for item in value:
        item = item.strip()
        if item.lower() == SYSTEM:
            result.append(SYSTEM)
            continue
        try:
            result.append(str(ipaddress.ip_address(item)))
        except ValueError:
            raise ConfigError(
                f"{where}: resolver {item!r} must be an IP address or \"system\""
            ) from None
    return result


def _string(data: dict, key: str, default: str, where: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{where}: '{key}' must be a string")
    return value


def _number(data: dict, key: str, default: float, minimum: float, where: str) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where}: '{key}' must be a number")
    if value < minimum:
        raise ConfigError(f"{where}: '{key}' must be at least {minimum:g}")
    return value


def _reject_unknown(data: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown setting(s): {', '.join(unknown)}")
