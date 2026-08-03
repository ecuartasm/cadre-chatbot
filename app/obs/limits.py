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

That header is **client-spoofable in principle**, so this limiter is a courtesy control against
ordinary abuse and accidental loops, *not* a security boundary. The real money backstop is the
daily spend cap in `spend.py`, which no header can influence.

Measured on Railway rather than assumed: sending an invented `X-Forwarded-For` did **not** create a
fresh bucket, so the edge router does not let a client control the left-most entry. Two things
follow. The code's trust model is unchanged — it would honour a spoofed header if some future proxy
passed one through, which is why the caveat above stands. But on this deployment the bucketing is
genuinely per-visitor, confirmed by `client_key_source="x-forwarded-for"` in the production log
rather than inferred from the limit tripping at 21 requests (which a single shared bucket would also
have produced).
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import NamedTuple

# 20/min is generous for a human exploring and still bounds a runaway client. Deliberately not
# tight:
# a limit that locks out a curious visitor costs more than it saves on a demo.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))
# Window length in seconds. SLIDING, not a fixed calendar minute: timestamps older than this are
# discarded before every count, so "20/min" means 20 in any rolling 60s, never 40 across a boundary.
WINDOW_S = 60.0

# Bounded so a flood of unique (or spoofed) IPs cannot grow this without limit — the limiter itself
# must not become the memory-exhaustion vector.
MAX_TRACKED_CLIENTS = 10_000

# client key -> deque of request timestamps inside the window. PROCESS MEMORY, so buckets are
# per-worker and are lost on restart; a second replica would have its own. Stated here rather than
# discovered later -- it is the reason the app runs --workers 1.
_hits: defaultdict[str, deque[float]] = defaultdict(deque)


class ClientKey(NamedTuple):
    """The bucket a request counts against, plus **where the key came from**.

    `source` exists because the difference between the two cases is invisible from outside and has
    opposite consequences. If the key is a per-visitor address, the limiter protects the service. If
    it silently degraded to the router's address, every visitor shares one bucket and the first
    scraper to trip it locks out everyone — while the endpoint looks perfectly healthy.

    Only the source is logged, never the address: an IP in a 7-day log is data this app has no
    reason to keep, and the source alone answers the operational question.
    """

    key: str
    source: str  # 'x-forwarded-for' | 'peer' | 'none'


def client_key(headers: dict[str, str], peer: str | None) -> ClientKey:
    """Left-most X-Forwarded-For entry, falling back to the TCP peer."""
    xff = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For") or ""
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return ClientKey(first, "x-forwarded-for")
    if peer:
        return ClientKey(peer, "peer")
    return ClientKey("unknown", "none")


# Record a request and decide whether it is allowed.
#   in : key -- the bucket identifier from client_key()
#        now -- injectable clock (seconds, monotonic). Tests pass it so they need no sleeps.
#   out: (allowed: bool, retry_after_seconds: int). retry_after is 0 when allowed, and otherwise
#        the exact time until the OLDEST request in the bucket expires -- not a guessed backoff.
#   side effect: appends `now` to the bucket when allowed, and evicts idle buckets past the cap.
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


# Drop buckets with no activity inside the window. Called only on the ALLOWED path, once the dict
# exceeds MAX_TRACKED_CLIENTS -- so a rejected flood cannot drive eviction work.
#   in : now -- current monotonic time
#   out: None (mutates _hits in place)
def _evict_idle(now: float) -> None:
    for k in [k for k, v in _hits.items() if not v or now - v[-1] >= WINDOW_S]:
        del _hits[k]


# Clear every bucket. Test-only -- there is no production path that resets the limiter.
def reset() -> None:
    """Test helper."""
    _hits.clear()
