"""GET /api/stats — what the bot has actually done, without SSHing in to grep JSONL.

This is the part of the observability layer that makes it usable. Everything Phase 2 writes is
already in `interactions.jsonl`; this reads it back and answers the four questions worth asking:
what did it cost, is caching working, how often does it refuse, and for what reason.

**It never reports a number it cannot substantiate.** `interactions.jsonl` exists only when the log
sink is in `disk` mode, so in `stdout-only` mode there is no file — and returning `turns: 0` there
would state "no traffic" when the truth is "cannot tell". The two are reported differently, on
purpose: a zero that means "unavailable" is the same class of quiet lie as a cache that silently
never engages.

Reads the file per request rather than keeping counters in memory. At this scale that is cheaper
than the alternative and, more importantly, it survives a restart — an in-memory counter would
reset and quietly under-report, which is the same failure `spend.py` avoids by persisting.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from fastapi import APIRouter

from app.obs.cost import UnknownModelError, rates_for
from app.obs.log import get_logger
from app.obs.sink import SINK

router = APIRouter(prefix="/api", tags=["stats"])
log = get_logger("stats")

# Bounded so a long-running instance cannot turn a status endpoint into a large file read. The
# rotation handler already caps each file at one day, so this is a second, cheaper bound.
MAX_LINES = 20_000


def _read_interactions() -> tuple[list[dict], str | None]:
    """Return (rows, unavailable_reason). Never raises — a broken stats endpoint must not be the
    thing that takes the service down."""
    if SINK.mode != "disk" or not SINK.log_dir:
        return [], "log sink is stdout-only, so there is no interactions.jsonl to read"

    path = Path(SINK.log_dir) / "interactions.jsonl"
    if not path.exists():
        return [], "no interactions logged yet today"

    rows: list[dict] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    # A torn final line during a concurrent write is expected, not exceptional.
                    continue
                if len(rows) >= MAX_LINES:
                    break
    except OSError as e:
        log.warning("stats_unreadable", extra={"error": str(e)})
        return [], f"could not read the log: {type(e).__name__}"

    return rows, None


@router.get("/stats")
async def stats() -> dict[str, object]:
    rows, unavailable = _read_interactions()

    if unavailable:
        # Explicitly not zeros. "Cannot tell" and "nothing happened" are different claims.
        return {
            "available": False,
            "reason": unavailable,
            "log_sink": SINK.mode,
        }

    total = len(rows)
    status_counts = Counter(r.get("status", "unknown") for r in rows)
    refusals = Counter(
        r["refusal_reason"] for r in rows if r.get("refusal_reason")
    )

    cost = sum(float(r.get("cost_usd") or 0) for r in rows)
    out_tokens = sum(int((r.get("usage") or {}).get("output_tokens") or 0) for r in rows)

    # A turn "hit" the cache when it read a cached prefix. The first turn of every TTL window
    # writes instead, so a low rate on a quiet instance is expected rather than a fault.
    hits = sum(
        1 for r in rows if int((r.get("usage") or {}).get("cache_read_input_tokens") or 0) > 0
    )
    writes = sum(
        1 for r in rows if int((r.get("usage") or {}).get("cache_creation_input_tokens") or 0) > 0
    )

    latencies = sorted(int(r.get("latency_ms") or 0) for r in rows if r.get("status") == "ok")

    return {
        "available": True,
        "log_sink": SINK.mode,
        "retention_days": SINK.retention_days,
        "turns": total,
        "by_status": dict(status_counts),
        # The number this bot is actually judged on. A refusal rate near zero on real traffic would
        # mean the boundary is not holding, not that nobody asked anything awkward.
        "refusal_rate": _pct(sum(refusals.values()), total),
        "refusals_by_reason": dict(refusals.most_common()),
        "cost": {
            "total_usd": round(cost, 6),
            "mean_per_turn_usd": round(cost / total, 6) if total else 0.0,
            "output_tokens": out_tokens,
        },
        "cache": {
            "read_hits": hits,
            "writes": writes,
            "hit_rate": _pct(hits, total),
            "note": (
                "the first turn of each 5-minute TTL window writes rather than reads, so a low "
                "hit rate on low traffic is expected"
            ),
        },
        "latency_ms": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "n": len(latencies),
        },
        "model_rates_per_mtok": _rates(rows),
    }


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def _percentile(values: list[int], p: int) -> int | None:
    """Nearest-rank. Deliberately not interpolated — with a handful of turns an interpolated
    percentile invents precision the sample does not have."""
    if not values:
        return None
    k = max(0, min(len(values) - 1, round(p / 100 * len(values) + 0.5) - 1))
    return values[k]


def _rates(rows: list[dict]) -> dict[str, object]:
    """Echo the price table actually used, so a cost figure can be checked rather than trusted."""
    models = {r.get("model") for r in rows if r.get("model")}
    out: dict[str, object] = {}
    for m in sorted(filter(None, models)):
        try:
            out[str(m)] = rates_for(str(m))
        except UnknownModelError:
            out[str(m)] = "no price table — cost for this model is not counted"
    return out
