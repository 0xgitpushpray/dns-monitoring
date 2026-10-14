"""DNS lookups against a specific resolver."""

from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass, field

import dns.exception
import dns.rdatatype
import dns.resolver

SYSTEM = "system"

# Record types whose values contain domain names, compared case-insensitively.
NAME_TYPES = {"CNAME", "DNAME", "MX", "NS", "PTR", "SRV"}


@dataclass
class QueryResult:
    answers: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def normalize(rtype: str, value: str) -> str:
    """Canonical form of a record value, so config values and answers compare equal.

    Raises ValueError for an invalid A/AAAA address.
    """
    value = value.strip()
    if rtype in ("A", "AAAA"):
        return str(ipaddress.ip_address(value))
    if rtype in NAME_TYPES:
        return value.lower().rstrip(".")
    return value


def _rdata_text(rdata) -> str:
    if rdata.rdtype == dns.rdatatype.TXT:
        return "".join(s.decode("utf-8", "replace") for s in rdata.strings)
    return rdata.to_text()


def _make_resolver(resolver: str, timeout: float) -> dns.resolver.Resolver:
    if resolver == SYSTEM:
        res = dns.resolver.Resolver()
    else:
        res = dns.resolver.Resolver(configure=False)
        res.nameservers = [resolver]
    # The OS config can list stale servers (e.g. from inactive network adapters),
    # so split the time budget to make sure every server gets a turn.
    res.timeout = timeout / max(1, len(res.nameservers))
    res.lifetime = timeout
    return res


def query(domain: str, rtype: str, resolver: str = SYSTEM, timeout: float = 3.0) -> QueryResult:
    """Look up `domain`/`rtype` via `resolver` (an IP address or "system")."""
    try:
        res = _make_resolver(resolver, timeout)
    except dns.exception.DNSException as exc:
        return QueryResult(error=f"resolver setup failed: {exc}")

    start = time.perf_counter()
    try:
        answer = res.resolve(domain, rtype)
    except dns.resolver.NXDOMAIN:
        error = "NXDOMAIN (domain does not exist)"
    except dns.resolver.NoAnswer:
        error = f"no {rtype} records"
    except dns.resolver.NoNameservers:
        error = "resolver returned SERVFAIL/REFUSED"
    except dns.exception.Timeout:
        error = f"timed out after {timeout:g}s"
        if resolver == SYSTEM:
            error += f" (tried {', '.join(str(ns) for ns in res.nameservers)})"
    except dns.exception.DNSException as exc:
        error = str(exc) or type(exc).__name__
    else:
        latency = (time.perf_counter() - start) * 1000
        answers = sorted({normalize(rtype, _rdata_text(r)) for r in answer})
        return QueryResult(answers=answers, latency_ms=latency)
    return QueryResult(latency_ms=(time.perf_counter() - start) * 1000, error=error)
