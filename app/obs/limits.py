"""Per-IP rate limiting.

**Deviation from plan.md, recorded deliberately.** The plan specified `slowapi`; this is ~30
lines instead, for two reasons.

First, `slowapi` rejects by *raising*, which produces a JSON 429. This endpoint serves
`text/event-stream`, and the frontend's `if (!res.ok) throw` would surface that as "Couldn't
reach the server (HTTP 429)" — accurate and useless. Plan §2.6 requires rejections to arrive as
readable SSE error frames; checking inline makes that the natural shape instead of something to
work around.

Second, it would be a 5th runtime dependency for a sliding window over a dict.

**The client IP is not `request.client.host`.** Behind Railway's edge router that is *the
router*, so every visitor shares one bucket and the first scraper to trip it locks out everyone.
The left-most `X-Forwarded-For` entry is the originating client.

That header is **client-spoofable**. This limiter is a courtesy control against ordinary abuse
and accidental loops, *not* a security boundary. The real money backstop is the daily spend cap
in `spend.py`, which no header can influence.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque

# 20/min is generous for a human exploring and still bounds a runaway client. Deliberately not
# tight:
# a limit that locks out a curious visitor costs more than it saves on a demo.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))
WINDOW_S = 60.0

# Bounded so a flood of unique (or spoofed) IPs cannot grow this without limit — the limiter itself
# must not become the memory-exhaustion vector.
MAX_TRACKED_CLIENTS = 10_000

_hits: defaultdict[str, deque[float]] = defaultdict(deque)


def client_key(headers: dict[str, str], peer: str | None) -> str:
    """Left-most X-Forwarded-For entry, falling back to the TCP peer."""
    xff = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For") or ""
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return peer or "unknown"


def check(key: str, *, now: float | None = None) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds). `now` is injectable so tests need no sleeps."""
    if RATE_LIMIT_PER_MINUTE <= 0:
        # Taken literally: zero requests per minute allowed, i.e. a kill switch. Handled here,
        # before `_hits` is touched, for two reasons. The `>=` test below is true for an *empty*
        # bucket when the limit is 0, so the retry_after arithmetic would index `bucket[0]` and
        # raise IndexError — a 500 on every request. And `_hits[key]` on a defaultdict creates an
        # entry even for a rejected caller, while eviction only runs on the allowed path, so a
        # rejected flood would grow the dict without bound.
        return False, int(WINDOW_S)

    t = now if now is not None else time.monotonic()
    bucket = _hits[key]

    while bucket and t - bucket[0] >= WINDOW_S:
        bucket.popleft()

    if len(bucket) >= RATE_LIMIT_PER_MINUTE:
        # Safe to index: the limit is >= 1 (checked at the top of this function), so reaching it
        # means the bucket holds at least one timestamp.
        retry_after = int(WINDOW_S - (t - bucket[0])) + 1
        return False, max(retry_after, 1)

    bucket.append(t)

    if len(_hits) > MAX_TRACKED_CLIENTS:
        _evict_idle(t)

    return True, 0


def _evict_idle(now: float) -> None:
    for k in [k for k, v in _hits.items() if not v or now - v[-1] >= WINDOW_S]:
        del _hits[k]


def reset() -> None:
    """Test helper."""
    _hits.clear()
