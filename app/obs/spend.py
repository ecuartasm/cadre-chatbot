"""Daily spend ceiling — persisted, because an in-memory counter is not a cap.

Railway restarts containers. A counter held only in memory resets on every restart, so a cap
built on one would silently never fire — and the failure mode is that it *looks* enforced. The
volume exists for state like this, so the total lives in a small JSON file reloaded at startup.

Checked **before** the model call, never after: the point is to not spend the money, not to
notice afterwards that it was spent.

Single-writer assumption: the container runs one uvicorn worker (see docker-entrypoint.sh), so
an asyncio lock suffices. Multiple workers or replicas would need Redis or a file lock — stated
here so the constraint is visible rather than implied.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.obs.log import get_logger
from app.obs.sink import SINK

log = get_logger("spend")

# $5/day, priced against the *worst* case: a cache-WRITE turn. Budget against the write rather than
# the read, because the cache TTL is 5 minutes and on low traffic most turns are the first of a
# fresh window.
#
# ⚠️ **How many turns that buys is MODEL-DEPENDENT**, and by a lot. Every Sonnet rate is 3x Haiku's,
# so the same cap is roughly a third of the traffic. `turns_remaining_estimate()` computes it from
# the active model rather than leaving a stale "~797 turns" comment to be read as current after a
# swap. See tests/test_obs.py.
DAILY_CAP_USD = float(os.getenv("DAILY_COST_CAP_USD", "5.00"))

# Log as the ceiling is approached, so the first sign of trouble is not the cap already tripped.
_ALERT_FRACTIONS = (0.5, 0.8, 1.0)

_STATE_PATH = Path(SINK.log_dir) / "spend.json" if SINK.mode == "disk" else None


def _today() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d")


@dataclass
class _State:
    date: str
    total_usd: float
    turns: int
    alerted: list[float]


def _load() -> _State:
    if _STATE_PATH and _STATE_PATH.exists():
        try:
            raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            if raw.get("date") == _today():
                return _State(
                    raw["date"], float(raw["total_usd"]), int(raw["turns"]),
                    list(raw.get("alerted", []))
                )
            # A new UTC day: roll over rather than carrying yesterday's total forward.
        except (OSError, ValueError, KeyError) as e:
            # Corrupt state must not prevent boot; starting from zero is the safe direction
            # (it under-counts, so the cap can still fire later today).
            log.warning("spend_state_unreadable", extra={"error": str(e)})
    return _State(_today(), 0.0, 0, [])


_state = _load()
_lock = asyncio.Lock()


def _persist() -> None:
    if not _STATE_PATH:
        return
    try:
        tmp = _STATE_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "date": _state.date,
                    "total_usd": round(_state.total_usd, 8),
                    "turns": _state.turns,
                    "alerted": _state.alerted,
                }
            ),
            encoding="utf-8",
        )
        # Atomic replace: a crash mid-write leaves the previous total, never a truncated file.
        tmp.replace(_STATE_PATH)
    except OSError as e:
        log.error("spend_state_unwritable", extra={"error": str(e)})


def _roll_if_new_day() -> None:
    if _state.date != _today():
        log.info(
            "spend_day_rollover",
            extra={"previous_date": _state.date, "previous_total_usd": round(_state.total_usd, 6),
                   "previous_turns": _state.turns},
        )
        _state.date, _state.total_usd, _state.turns, _state.alerted = _today(), 0.0, 0, []
        _persist()


def would_exceed_cap() -> bool:
    """Called before the model request. True means refuse the turn."""
    _roll_if_new_day()
    return _state.total_usd >= DAILY_CAP_USD


async def record(cost: float) -> None:
    async with _lock:
        _roll_if_new_day()
        _state.total_usd += cost
        _state.turns += 1

        fraction = _state.total_usd / DAILY_CAP_USD if DAILY_CAP_USD else 0.0
        for threshold in _ALERT_FRACTIONS:
            if fraction >= threshold and threshold not in _state.alerted:
                _state.alerted.append(threshold)
                log.warning(
                    "spend_threshold_crossed",
                    extra={
                        "threshold_pct": int(threshold * 100),
                        "total_usd": round(_state.total_usd, 6),
                        "cap_usd": DAILY_CAP_USD,
                        "turns": _state.turns,
                    },
                )
        _persist()


def worst_case_turn_usd() -> float:
    """A cache-WRITE turn on the active model, using the measured shape of a real turn."""
    from app.llm.client import MODEL
    from app.llm.prompt import MEASURED_SYSTEM_TOKENS
    from app.obs.cost import Usage, cost_usd

    return cost_usd(
        Usage(input_tokens=12, output_tokens=150,
              cache_creation_input_tokens=MEASURED_SYSTEM_TOKENS),
        MODEL,
    )


def status() -> dict[str, object]:
    _roll_if_new_day()
    return {
        "date": _state.date,
        "spend_today_usd": round(_state.total_usd, 6),
        "cap_usd": DAILY_CAP_USD,
        "turns_today": _state.turns,
        "pct_of_cap": round(100 * _state.total_usd / DAILY_CAP_USD, 2) if DAILY_CAP_USD else None,
        "persisted": _STATE_PATH is not None,
        # Computed from the active model, never a hardcoded figure: the same $5 buys roughly a
        # third as many turns on Sonnet as on Haiku.
        "worst_case_turn_usd": round(worst_case_turn_usd(), 6),
        "turns_remaining_estimate": int(
            max(0.0, DAILY_CAP_USD - _state.total_usd) / worst_case_turn_usd()
        ),
    }
