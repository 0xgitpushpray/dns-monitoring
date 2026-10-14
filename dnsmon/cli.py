"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from . import __version__
from .alerts import format_event, send_webhook
from .config import EXAMPLE_CONFIG, Config, ConfigError, load_config
from .models import Event
from .monitor import OK, Outcome, run_cycle
from .store import Store

DEFAULT_CONFIG = "config.toml"
MAX_ANSWER_WIDTH = 70

STATUS_COLORS = {"OK": "32", "SLOW": "33", "FAIL": "31", "MISMATCH": "31"}
LEVEL_COLORS = {"critical": "31", "warning": "33", "info": "32"}

_color = False


def paint(text: str, code: str | None) -> str:
    return f"\033[{code}m{text}\033[0m" if _color and code else text


def timestamp(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time()).strftime("%Y-%m-%d %H:%M:%S")


def truncate(text: str, width: int = MAX_ANSWER_WIDTH) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."


def print_table(headers: list[str], rows: list[list]) -> None:
    """Print aligned columns. A cell may be a plain string or a (text, ansi_color) tuple."""
    cells = [[c if isinstance(c, tuple) else (c, None) for c in row] for row in rows]
    widths = [max([len(h)] + [len(row[i][0]) for row in cells]) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)).rstrip())
    for row in cells:
        print("  ".join(paint(text.ljust(w), code) for (text, code), w in zip(row, widths)).rstrip())


def display_status(outcome: Outcome) -> str:
    if outcome.status == OK and outcome.slow:
        return "SLOW"
    return outcome.status.upper()


def print_outcomes(outcomes: list[Outcome]) -> None:
    rows = []
    for o in outcomes:
        status = display_status(o)
        detail = ", ".join(o.result.answers) if o.result.ok else o.result.error
        rows.append(
            [
                o.check.name,
                o.resolver,
                (status, STATUS_COLORS.get(status)),
                f"{o.result.latency_ms:.0f} ms",
                truncate(detail or ""),
            ]
        )
    print_table(["CHECK", "RESOLVER", "STATUS", "LATENCY", "ANSWERS / ERROR"], rows)


def print_events(events: list[Event]) -> None:
    for event in events:
        print(paint(format_event(event), LEVEL_COLORS.get(event.level)))


def print_summary(outcomes: list[Outcome]) -> None:
    counts: dict[str, int] = {}
    for o in outcomes:
        status = display_status(o)
        counts[status] = counts.get(status, 0) + 1
    parts = ", ".join(
        paint(f"{n} {status.lower()}", STATUS_COLORS.get(status)) for status, n in counts.items()
    )
    print(f"[{timestamp()}] {len(outcomes)} lookups: {parts}")


def alert(events: list[Event], config: Config) -> None:
    if config.webhook_url and events:
        send_webhook(config.webhook_url, events)


def outcome_json(o: Outcome) -> dict:
    return {
        "check": o.check.name,
        "domain": o.check.domain,
        "type": o.check.type,
        "resolver": o.resolver,
        "status": o.status,
        "slow": o.slow,
        "latency_ms": round(o.result.latency_ms, 1),
        "answers": o.result.answers,
        "error": o.result.error,
        "events": [{"level": e.level, "kind": e.kind, "message": e.message} for e in o.events],
    }


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.config)
    if path.exists() and not args.force:
        print(f"error: {path} already exists (use --force to overwrite)", file=sys.stderr)
        return 2
    path.write_text(EXAMPLE_CONFIG, encoding="utf-8")
    print(f"Wrote {path}. Edit it to list the domains you care about, then run: dnsmon check")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    with Store(config.database) as store:
        store.prune(config.retention_days)
        outcomes = run_cycle(config, store)
    events = [e for o in outcomes for e in o.events]

    if args.json:
        print(json.dumps([outcome_json(o) for o in outcomes], indent=2))
    else:
        print_outcomes(outcomes)
        if events:
            print()
            print_events(events)
    alert(events, config)
    return 0 if all(o.status == OK for o in outcomes) else 1


def cmd_watch(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    interval = args.interval or config.interval
    # Show each round immediately even when output is redirected to a log file.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    lookups = sum(len(config.resolvers_for(c)) for c in config.checks)
    print(
        f"Watching {len(config.checks)} checks ({lookups} lookups) every {interval:g}s. "
        "Press Ctrl+C to stop."
    )
    with Store(config.database) as store:
        first = True
        try:
            while True:
                started = time.monotonic()
                store.prune(config.retention_days)
                outcomes = run_cycle(config, store)
                events = [e for o in outcomes for e in o.events]
                if first:
                    print_outcomes(outcomes)
                    first = False
                print_summary(outcomes)
                print_events(events)
                alert(events, config)
                time.sleep(max(0.0, interval - (time.monotonic() - started)))
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    with Store(config.database) as store:
        if args.events:
            events = store.events(args.check, args.limit)
            if not events:
                print("No events recorded yet.")
                return 0
            rows = [
                [
                    timestamp(e.ts),
                    (e.level.upper(), LEVEL_COLORS.get(e.level)),
                    e.kind,
                    e.check,
                    e.resolver,
                    truncate(e.message, 90),
                ]
                for e in reversed(events)
            ]
            print_table(["TIME", "LEVEL", "KIND", "CHECK", "RESOLVER", "MESSAGE"], rows)
            return 0

        records = store.results(args.check, args.limit)
        if not records:
            print("No results recorded yet. Run `dnsmon check` first.")
            return 0
        rows = [
            [
                timestamp(r.ts),
                r.check,
                r.resolver,
                (r.status.upper(), STATUS_COLORS.get(r.status.upper())),
                f"{r.latency_ms:.0f} ms",
                truncate(", ".join(r.answers) if r.error is None else r.error),
            ]
            for r in reversed(records)
        ]
        print_table(["TIME", "CHECK", "RESOLVER", "STATUS", "LATENCY", "ANSWERS / ERROR"], rows)
    return 0


def positive_interval(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from None
    if seconds < 1:
        raise argparse.ArgumentTypeError("interval must be at least 1 second")
    return seconds


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONFIG,
        help=f"path to the config file (default: {DEFAULT_CONFIG})",
    )
    common.add_argument("--no-color", action="store_true", help="disable colored output")
    common.add_argument("-v", "--verbose", action="store_true", help="show debug logging")

    parser = argparse.ArgumentParser(
        prog="dnsmon",
        description="Monitor DNS records across resolvers and alert on failures and changes.",
    )
    parser.add_argument("--version", action="version", version=f"dnsmon {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("init", parents=[common], help="create an example config file")
    p.add_argument("--force", action="store_true", help="overwrite an existing config")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser(
        "check",
        parents=[common],
        help="run all checks once (exit code 1 if any fail)",
    )
    p.add_argument("--json", action="store_true", help="print results as JSON")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("watch", parents=[common], help="run checks continuously")
    p.add_argument(
        "-i", "--interval", type=positive_interval, help="seconds between rounds (overrides config)"
    )
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("history", parents=[common], help="show recorded results or events")
    p.add_argument("--check", help="only show this check (by name)")
    p.add_argument("--events", action="store_true", help="show alerts/events instead of results")
    p.add_argument("-n", "--limit", type=int, default=50, help="number of rows (default: 50)")
    p.set_defaults(func=cmd_history)

    return parser


def main(argv: list[str] | None = None) -> int:
    global _color
    args = build_parser().parse_args(argv)
    _color = not args.no_color and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
