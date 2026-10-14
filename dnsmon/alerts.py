"""Alert delivery."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from .models import Event

log = logging.getLogger(__name__)

# Discord rejects messages over 2000 characters.
MAX_MESSAGE = 1900


def format_event(event: Event) -> str:
    return f"[{event.level.upper()}] {event.kind} {event.check} @ {event.resolver}: {event.message}"


def send_webhook(url: str, events: list[Event], timeout: float = 10.0) -> bool:
    """POST events to a Slack- or Discord-style webhook. Returns False on failure."""
    if not events:
        return True
    text = "dnsmon alerts:\n" + "\n".join(format_event(e) for e in events)
    if len(text) > MAX_MESSAGE:
        text = text[: MAX_MESSAGE - 3] + "..."
    # Slack reads "text", Discord reads "content"; each ignores the other.
    body = json.dumps({"text": text, "content": text}).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "dnsmon"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            pass
    except (urllib.error.URLError, OSError) as exc:
        log.warning("webhook delivery failed: %s", exc)
        return False
    return True
