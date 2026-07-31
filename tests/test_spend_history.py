"""Daily spend totals must survive the rollover that discards them.

`spend.json` holds exactly ONE record — today's — and overwrites it. Before `spend-history.jsonl`
existed, every daily total was destroyed at the next UTC rollover, so "what has this bot cost?"
had no answer beyond the current day.

⚠️ **The rollover was not merely unrecorded — it was never even logged.** `_roll_if_new_day()` does
log it, but only fires in a process still running when midnight passes. Every RESTART took the
`_load()` path instead, which read yesterday's total into a local and dropped it. Local dev and
every Railway redeploy go through that path, which is why `spend_day_rollover` appeared in no log
file in this project's entire history despite several day boundaries passing.

Run in subprocesses with their own LOG_DIR: `spend.py` resolves its paths and loads its state at
import, so an in-process test would be examining state that was fixed before the fixture existed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

YESTERDAY = '{"date": "2020-01-01", "total_usd": 1.2345, "turns": 300, "alerted": [0.5]}'


def _run(log_dir: Path, code: str) -> str:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["LOG_DIR"] = str(log_dir)
    env.setdefault("ANTHROPIC_API_KEY", "test-not-a-real-key")
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=90,
    )
    assert r.returncode == 0, r.stderr
    # The logger also writes JSON to stdout, so the rollover line lands above whatever the snippet
    # printed. Take the LAST line — a naive `r.stdout` parse picks up the log record instead and
    # fails with a confusing JSONDecodeError about the wrong object entirely. Snippets that print
    # nothing are legitimate (the restart tests only care about the side effect on disk).
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else ""


def test_a_finished_day_is_archived_before_its_total_is_discarded(tmp_path: Path):
    (tmp_path / "spend.json").write_text(YESTERDAY, encoding="utf-8")

    out = _run(
        tmp_path, "from app.obs import spend; import json; print(json.dumps(spend.history()))"
    )
    rows = json.loads(out)

    assert len(rows) == 1, "the previous day was dropped instead of archived"
    assert rows[0]["date"] == "2020-01-01"
    assert rows[0]["total_usd"] == 1.2345
    assert rows[0]["turns"] == 300


def test_today_starts_from_zero_even_though_the_total_was_kept(tmp_path: Path):
    """Archiving must not become carrying-forward — the cap is a DAILY ceiling, and a total that
    accumulated across days would trip it permanently on day two."""
    (tmp_path / "spend.json").write_text(YESTERDAY, encoding="utf-8")

    out = _run(
        tmp_path, "from app.obs import spend; print(spend._state.total_usd, spend._state.turns)"
    )
    total, turns = out.split()
    assert float(total) == 0.0
    assert int(turns) == 0


def test_restarting_repeatedly_archives_the_day_exactly_once(tmp_path: Path):
    """Two processes starting after midnight would each see a stale file. Without dedup, the day
    is written twice and every sum over the file double-counts it."""
    (tmp_path / "spend.json").write_text(YESTERDAY, encoding="utf-8")

    for _ in range(3):
        _run(tmp_path, "from app.obs import spend; spend.history()")

    lines = [
        line for line in (tmp_path / "spend-history.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1, f"archived {len(lines)} times; must be idempotent by date"


def test_the_rollover_is_logged_once_not_once_per_restart(tmp_path: Path):
    """`spend.json` is rewritten with today's date immediately, so a second restart sees a current
    file and stays quiet. Otherwise the log reads as several rollovers when only one day ended."""
    (tmp_path / "spend.json").write_text(YESTERDAY, encoding="utf-8")

    for _ in range(3):
        _run(tmp_path, "from app.obs import spend; spend.history()")

    app_log = (tmp_path / "app.jsonl").read_text(encoding="utf-8")
    assert app_log.count('"event":"spend_day_rollover"') == 1

    on_disk = json.loads((tmp_path / "spend.json").read_text(encoding="utf-8"))
    assert on_disk["date"] != "2020-01-01", "the stale date was left on disk"


def test_status_reports_lifetime_across_archived_days(tmp_path: Path):
    (tmp_path / "spend.json").write_text(YESTERDAY, encoding="utf-8")
    (tmp_path / "spend-history.jsonl").write_text(
        '{"date": "2019-12-30", "total_usd": 2.0, "turns": 100}\n'
        '{"date": "2019-12-31", "total_usd": 3.0, "turns": 200}\n',
        encoding="utf-8",
    )

    out = _run(
        tmp_path, "from app.obs import spend; import json; print(json.dumps(spend.status()))"
    )
    s = json.loads(out)

    # 2.0 + 3.0 archived, plus 1.2345 archived on this boot, plus 0.0 today.
    assert s["history_days"] == 3
    assert s["lifetime_usd"] == 6.2345
    assert s["lifetime_turns"] == 600
    assert s["spend_today_usd"] == 0.0, "today must not inherit the archive"


def test_history_survives_the_seven_day_log_rotation(tmp_path: Path):
    """The 7-day retention rule is a PRIVACY policy about logged user messages. A date, a dollar
    figure and a turn count carry no personal data, and a cost history that deletes itself weekly
    cannot answer the question it exists for — so this file must not be a rotating handler."""
    from app.obs import sink  # noqa: F401  (import guard: the module must exist)

    src = (ROOT / "app" / "obs" / "log.py").read_text(encoding="utf-8")
    assert "spend-history" not in src, (
        "spend-history.jsonl must not be attached to a TimedRotatingFileHandler"
    )
