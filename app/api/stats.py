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

from app.obs import spend
from app.obs.cost import UnknownModelError, rates_for
from app.obs.log import get_logger
from app.obs.sink import SINK

router = APIRouter(prefix="/api", tags=["stats"])
log = get_logger("stats")

# Bounded so a long-running instance cannot turn a status endpoint into a large file read. The
# rotation handler already caps each file at one day, so this is a second, cheaper bound.
# Ceiling on log lines parsed per request. A busy day must not turn /api/stats into a slow
# endpoint or a memory spike -- the numbers stay approximate rather than the request stalling.
MAX_LINES = 20_000


# Load today's interaction records.
#   out: (rows, unavailable_reason). rows is [] and the reason is set when there is no disk sink
#        or no file yet. NEVER raises -- a broken stats endpoint must not make the app look down.
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

    latencies = [int(r.get("latency_ms") or 0) for r in rows if r.get("status") == "ok"]

    return {
        "available": True,
        "log_sink": SINK.mode,
        "retention_days": SINK.retention_days,
        # ⚠️ `turns`/`cost` below are derived from `interactions.jsonl`, which the 7-day rotation
        # deletes. `spend` is the durable record: today's total plus one archived line per
        # completed day, which is why lifetime cost is answerable at all. The two disagree by
        # design once a log rotates, and the spend block is the one to trust for money.
        "spend": spend.status(),
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
        # ⚠️ **A mean and a count — never percentiles.** A p50/p95 describes the *shape of a
        # distribution*, which is a claim this data cannot support: the sample is small, it counts
        # `ok` turns only, and on real traffic it produced p50 == p95 over a single measurement —
        # a statistic that looks authoritative and says nothing.
        #
        # It also frames latency as an SLO to optimise, which it is not here. This bot has no
        # retrieval step — the corpus is in the cached prompt — so end-to-end latency is
        # overwhelmingly the model provider's response time. A mean is an honest summary of what
        # was observed; a percentile implies a tail worth engineering against, and that tail is not
        # ours to move.
        #
        # The latency with a real diagnosis attached is **time to first token**: if it lands close
        # to the total, a proxy buffered the stream. Only a client can measure it, so it is
        # per-turn in the playground and the eval's `--json` telemetry rather than aggregated here.
        "latency_ms": {
            "mean": round(sum(latencies) / len(latencies)) if latencies else None,
            "n": len(latencies),
            "note": (
                "mean over `ok` turns; no percentiles — the sample cannot support a distribution "
                "claim, and with no retrieval step this is the provider's response time"
            ),
        },
        "model_rates_per_mtok": _rates(rows),
    }


# Percentage helper.
#   in : part, whole
#   out: part/whole as a percentage rounded to 1dp; 0.0 when whole is 0 (no ZeroDivisionError
#        on a fresh instance with no traffic).
def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


# The price table(s) actually used by the turns in this window.
#   in : rows -- today's interaction records
#   out: {model_id: four rates}. Derived from the models seen in the log, so a day that spanned
#        a model swap reports both rather than only the currently-configured one.
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
