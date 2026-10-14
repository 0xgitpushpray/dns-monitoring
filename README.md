# dnsmon

[![tests](https://github.com/0xgitpushpray/dns-monitoring/actions/workflows/tests.yml/badge.svg)](https://github.com/0xgitpushpray/dns-monitoring/actions/workflows/tests.yml)

A lightweight DNS monitoring tool you run locally. It checks DNS records against a set of resolvers and alerts you when a lookup fails, the answers change, the records stop matching what you expect, or a resolver gets slow.

```
$ dnsmon check
CHECK           RESOLVER  STATUS    LATENCY  ANSWERS / ERROR
example.com A   system    OK        21 ms    104.20.23.154, 172.66.147.243
example.com A   1.1.1.1   OK        43 ms    104.20.23.154, 172.66.147.243
Cloudflare DNS  1.1.1.1   OK        41 ms    1.0.0.1, 1.1.1.1
gmail.com MX    8.8.8.8   OK        39 ms    10 alt1.gmail-smtp-in.l.google.com, 20 alt2.gmail-smtp-in.l.google....
mysite.com A    8.8.8.8   MISMATCH  44 ms    203.0.113.99

[CRITICAL] MISMATCH mysite.com A @ 8.8.8.8: expected [203.0.113.10], got [203.0.113.99]
```

## Features

- **Any record type**: A, AAAA, CNAME, MX, NS, TXT, SOA, SRV, CAA and more.
- **Multiple resolvers**: compare your OS resolver (`system`) with public ones like `1.1.1.1` and `8.8.8.8`, or your own DNS servers. Queries run in parallel.
- **Change detection**: get alerted when an answer differs from the previous lookup, which helps catch hijacked records, unexpected migrations or propagation.
- **Expected values**: pin the records that must not change and get a critical alert on any mismatch.
- **Latency tracking**: flag resolvers that answer slower than a threshold.
- **Low-noise alerts**: events fire on state changes only. A check that stays down alerts once, then again when it recovers.
- **History**: every result and event is stored in a local SQLite file you can browse with `dnsmon history`.
- **Webhook alerts**: optionally send alerts to Slack or Discord.
- **Script-friendly**: `dnsmon check` exits with code `1` when something is wrong, and `--json` prints machine-readable output.

## Install

You need Python 3.11 or newer.

```bash
git clone https://github.com/0xgitpushpray/dns-monitoring.git
cd dns-monitoring
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e .
```

## Quick start

```bash
dnsmon init          # writes an example config.toml
# edit config.toml to list the domains you care about
dnsmon check         # run every check once
dnsmon watch         # keep checking every `interval` seconds (Ctrl+C to stop)
dnsmon history       # recent results
dnsmon history --events            # alerts only
dnsmon history --check "mysite.com A" -n 20
```

All commands accept `-c path/to/config.toml` (default: `config.toml` in the current folder) and `--no-color`. You can also run the tool as `python -m dnsmon`.

## Configuration

```toml
interval = 60                 # seconds between rounds in `dnsmon watch`
timeout = 3.0                 # per-lookup timeout in seconds
latency_warn_ms = 500         # answers slower than this are flagged SLOW
resolvers = ["system", "1.1.1.1", "8.8.8.8"]
database = "dnsmon.db"        # history file, relative to the config file
retention_days = 30           # 0 keeps history forever
# webhook_url = "https://hooks.slack.com/services/..."

[[checks]]
domain = "example.com"        # name defaults to "example.com A"
type = "A"

[[checks]]
name = "My website"
domain = "mysite.com"
type = "A"
expect = ["203.0.113.10"]     # alert if the answers differ from this set

[[checks]]
domain = "mysite.com"
type = "MX"
resolvers = ["1.1.1.1"]       # override the resolvers for this check
```

| Setting | Default | Description |
| --- | --- | --- |
| `interval` | `60` | Seconds between rounds of checks in `watch` mode. |
| `timeout` | `3.0` | Lookup timeout in seconds. |
| `latency_warn_ms` | `500` | Latency above which a result is flagged `SLOW`. |
| `resolvers` | `["system"]` | IPv4/IPv6 addresses of DNS servers, or `"system"` for the OS-configured ones. |
| `database` | `dnsmon.db` | SQLite file for history. |
| `retention_days` | `30` | How long to keep history. `0` keeps everything. |
| `webhook_url` | none | Slack/Discord webhook for alerts. The `DNSMON_WEBHOOK_URL` environment variable overrides it. |

Per check: `domain` (required), `type` (default `A`), `name`, `expect`, and `resolvers`.

Values in `expect` are compared after normalization: IP addresses are canonicalized, and domain names are compared without case or the trailing dot. MX records include their priority, as in `"10 mail.example.com"`. TXT values are written without surrounding quotes.

Unknown settings are rejected, so typos don't get silently ignored.

## Events

| Kind | Level | When |
| --- | --- | --- |
| `FAIL` | critical | A lookup failed: NXDOMAIN, no records, SERVFAIL/REFUSED or a timeout. |
| `MISMATCH` | critical | The answers don't match `expect`. |
| `CHANGED` | warning | The answers differ from the previous lookup. |
| `SLOW` | warning | The lookup took longer than `latency_warn_ms`. |
| `RECOVERED` | info | A failing or mismatching check is healthy again. |

Events are printed to the console, stored in the database and sent to the webhook if one is configured.

## Running it in the background

**Continuously**: leave `dnsmon watch` running in a terminal, or redirect it to a log:

```bash
dnsmon watch -c /path/to/config.toml >> dnsmon.log 2>&1
```

**On a schedule**: run `dnsmon check` periodically. Each run compares against the stored history, so change detection works across runs.

- Linux/macOS (cron, every 5 minutes):
  ```
  */5 * * * * cd /path/to/dns-monitoring && .venv/bin/dnsmon check --no-color >> dnsmon.log 2>&1
  ```
- Windows (Task Scheduler, every 5 minutes):
  ```powershell
  schtasks /Create /SC MINUTE /MO 5 /TN dnsmon /TR "C:\path\to\dns-monitoring\.venv\Scripts\dnsmon.exe check -c C:\path\to\dns-monitoring\config.toml"
  ```

## Troubleshooting

**The `system` resolver is slow or times out while public resolvers are fine.** Your OS may list stale DNS servers, for example from VPN or virtual network adapters. On a timeout, dnsmon shows which servers it tried. Listing your real DNS server IPs in `resolvers` instead of `"system"` gives you clean measurements.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests don't touch the network. CI runs them on Linux and Windows with Python 3.11 to 3.13.

## License

[MIT](LICENSE)
