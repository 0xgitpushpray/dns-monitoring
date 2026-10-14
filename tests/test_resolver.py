import dns.exception
import dns.resolver
import pytest

from dnsmon.resolver import normalize, query


@pytest.mark.parametrize(
    "rtype, value, expected",
    [
        ("A", " 1.2.3.4 ", "1.2.3.4"),
        ("AAAA", "2001:0DB8::0001", "2001:db8::1"),
        ("CNAME", "WWW.Example.com.", "www.example.com"),
        ("MX", "10 Mail.Example.com.", "10 mail.example.com"),
        ("TXT", "v=spf1 -all", "v=spf1 -all"),
    ],
)
def test_normalize(rtype, value, expected):
    assert normalize(rtype, value) == expected


def test_normalize_rejects_bad_address():
    with pytest.raises(ValueError):
        normalize("A", "not-an-ip")


@pytest.mark.parametrize(
    "exc, message",
    [
        (dns.resolver.NXDOMAIN(), "NXDOMAIN"),
        (dns.resolver.NoAnswer(), "no A records"),
        (dns.resolver.NoNameservers(), "SERVFAIL"),
        (dns.exception.Timeout(), "timed out after 2s"),
    ],
)
def test_query_errors_are_reported(monkeypatch, exc, message):
    def boom(self, *args, **kwargs):
        raise exc

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", boom)
    result = query("example.com", "A", "1.1.1.1", timeout=2)
    assert not result.ok
    assert message in result.error
    assert result.answers == []
