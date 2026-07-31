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

# A JSONL series, one line per completed day. `spend.json` is a single overwritten record, so
# without this every daily total is destroyed at the next rollover.
_HISTORY_PATH = Path(SINK.log_dir) / "spend-history.jsonl" if SINK.mode == "disk" else None


def _today() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d")


@dataclass
class _State:
    date: str
    total_usd: float
    turns: int
    alerted: list[float]


def _archived_dates() -> set[str]:
    if not _HISTORY_PATH or not _HISTORY_PATH.exists():
        return set()
    try:
        return {
            json.loads(line)["date"]
            for line in _HISTORY_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    except (OSError, ValueError, KeyError):
        return set()


def _archive(date: str, total_usd: float, turns: int) -> None:
    """Append one finished day to `spend-history.jsonl` before its total is discarded.

    `spend.json` holds a single record — today's — and overwrites it. Without this, every daily
    total is destroyed at the next rollover and "what has this cost so far?" has no answer beyond
    the current day.

    Idempotent by date: two processes both starting after midnight would otherwise each archive
    yesterday, double-counting it in any sum over the file.

    ⚠️ **Deliberately NOT subject to the 7-day rotation.** That retention rule is a privacy policy
    about logged user messages; a date, a dollar figure and a turn count contain no personal data,
    and a cost history that deletes itself weekly cannot answer the question it exists for. One
    line per day — 365 lines a year.
    """
    if not _HISTORY_PATH or date in _archived_dates():
        return
    try:
        with _HISTORY_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "date": date,
                "total_usd": round(total_usd, 8),
                "turns": turns,
            }) + "\n")
    except OSError as e:
        log.error("spend_history_unwritable", extra={"error": str(e), "date": date})


def _load() -> _State:
    if _STATE_PATH and _STATE_PATH.exists():
        try:
            raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            if raw.get("date") == _today():
                return _State(
                    raw["date"], float(raw["total_usd"]), int(raw["turns"]),
                    list(raw.get("alerted", []))
                )
            # A new UTC day. ⚠️ This is the path a RESTART takes, and it used to discard the
            # previous day's total in silence — `_roll_if_new_day()` logs the rollover, but it
            # only fires in a process that is still running when midnight passes. Every restart
            # (local dev, every Railway redeploy) came through here instead, so in practice the
            # rollover was never recorded at all: `spend_day_rollover` appeared in no log file.
            _archive(str(raw["date"]), float(raw["total_usd"]), int(raw["turns"]))
            log.info(
                "spend_day_rollover",
                extra={"previous_date": raw["date"],
                       "previous_total_usd": round(float(raw["total_usd"]), 6),
                       "previous_turns": int(raw["turns"]), "via": "restart"},
            )
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


def _state_file_is_stale() -> bool:
    """True when `spend.json` on disk still carries a date other than today's.

    ⚠️ Checked against the FILE, not `_state` — `_load()` already returns today's date after a
    rollover, so comparing `_state.date` to today would never fire and this whole guard would be
    dead code that looked correct.
    """
    if not _STATE_PATH or not _STATE_PATH.exists():
        return False
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8")).get("date") != _today()
    except (OSError, ValueError):
        return False


# `_load()` returns a fresh state on rollover but cannot persist it — `_persist` reads the module
# global, which is not bound until `_state = _load()` above. Left unwritten, `spend.json` keeps
# yesterday's date until the first turn is recorded, so every restart in between re-logs
# `spend_day_rollover` and reads as several rollovers rather than one.
if _state_file_is_stale():
    _persist()


def _roll_if_new_day() -> None:
    """The path a LONG-RUNNING process takes across midnight. The restart path is in `_load()`;
    both must archive, or the total survives only when the process happens to outlive the day."""
    if _state.date != _today():
        _archive(_state.date, _state.total_usd, _state.turns)
        log.info(
            "spend_day_rollover",
            extra={"previous_date": _state.date, "previous_total_usd": round(_state.total_usd, 6),
                   "previous_turns": _state.turns, "via": "live"},
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


def history(limit: int = 30) -> list[dict[str, object]]:
    """Completed days, oldest first. Today is not in here — it is still in `spend.json`."""
    if not _HISTORY_PATH or not _HISTORY_PATH.exists():
        return []
    try:
        rows = [
            json.loads(line)
            for line in _HISTORY_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, ValueError):
        log.warning("spend_history_unreadable")
        return []
    return sorted(rows, key=lambda r: str(r.get("date")))[-limit:]


def status() -> dict[str, object]:
    _roll_if_new_day()
    past = history()
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
        # Completed days. `spend.json` keeps only today, so without this the answer to "what has
        # this cost so far?" is lost at every rollover.
        "history_days": len(past),
        "lifetime_usd": round(
            sum(float(r.get("total_usd", 0)) for r in past) + _state.total_usd, 6
        ),
        "lifetime_turns": sum(int(r.get("turns", 0)) for r in past) + _state.turns,
        "recent_days": past[-7:],
    }
