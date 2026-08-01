"""Phase 2 — observability.

Every test here runs **offline**: no API key, no network, no sleeps. Phase 1 found a key-dependent
test silently skipping, so anything that could vanish in CI injects its dependencies instead — a
fake clock for the rate limiter, hand-built `Usage` objects for the cost table.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.obs import limits
from app.obs.cost import (
    InteractionLog,
    UnknownModelError,
    Usage,
    cost_usd,
    rates_for,
)
from app.obs.log import JsonFormatter, new_request_id, request_id_var
from app.obs.redact import redact

# ── redaction ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "must_not_contain"),
    [
        ("email me at ernesto@example.com please", "ernesto@example.com"),
        ("call +1 (555) 123-4567 tomorrow", "555"),
        ("card 4111 1111 1111 1111 expires soon", "4111"),
        ("reach me: First.Last+tag@sub.domain.co.uk", "First.Last+tag@sub.domain.co.uk"),
    ],
)
def test_redaction_removes_pii(raw: str, must_not_contain: str):
    assert must_not_contain not in redact(raw)


def test_redaction_keeps_the_actual_question():
    out = redact("Do you work with construction? my email is a@b.com")
    assert "construction" in out
    assert "[email]" in out


def test_redaction_truncates_so_a_paste_cannot_flood_the_log():
    out = redact("x" * 50_000, max_chars=100)
    assert len(out) < 200
    assert "truncated" in out


def test_redaction_handles_empty():
    assert redact("") == ""


# ── cost: four rates, not two ────────────────────────────────────────────────────────


def test_all_four_rates_are_priced():
    r = rates_for("claude-haiku-4-5")
    assert (r["input"], r["output"], r["cache_write"], r["cache_read"]) == (1.0, 5.0, 1.25, 0.10)


def test_cache_write_is_1_25x_and_read_is_0_1x_input():
    r = rates_for("claude-haiku-4-5")
    assert r["cache_write"] == pytest.approx(r["input"] * 1.25)
    assert r["cache_read"] == pytest.approx(r["input"] * 0.10)


def test_unknown_model_raises_rather_than_guessing():
    """A silently-wrong rate corrupts the spend cap, which is the one control that costs money."""
    with pytest.raises(UnknownModelError):
        cost_usd(Usage(input_tokens=100), "claude-does-not-exist")


def test_cached_turn_is_much_cheaper_than_uncached():
    """The production numbers from Phase 1: a 4,409-token prefix, ~150 output tokens."""
    uncached = cost_usd(Usage(input_tokens=4409, output_tokens=150), "claude-haiku-4-5")
    cached = cost_usd(Usage(input_tokens=12, output_tokens=150, cache_read_input_tokens=4409),
                      "claude-haiku-4-5")
    assert cached < uncached
    assert uncached / cached > 3.5  # measured ≈4.3x


def test_cache_write_turn_is_the_most_expensive_case():
    """Why the daily cap is budgeted against writes: with a 5-minute TTL, a low-traffic bot pays
    the write on most turns, not the cheap read."""
    write = cost_usd(Usage(input_tokens=12, output_tokens=150,
                           cache_creation_input_tokens=4409), "claude-haiku-4-5")
    read = cost_usd(Usage(input_tokens=12, output_tokens=150,
                          cache_read_input_tokens=4409), "claude-haiku-4-5")
    assert write > read
    # 12 in + 150 out + 4409 written = (12 + 750 + 5511.25) / 1e6
    assert write == pytest.approx(0.00627325, abs=1e-7)
    # 12 in + 150 out + 4409 read    = (12 + 750 +  440.90) / 1e6
    assert read == pytest.approx(0.00120290, abs=1e-7)


def test_two_rate_math_would_have_undercounted_a_cache_write():
    """Guards the actual Phase 0 trap: input+output alone ignores the cached portion entirely."""
    u = Usage(input_tokens=12, output_tokens=150, cache_creation_input_tokens=4409)
    naive = (12 * 1.0 + 150 * 5.0) / 1_000_000
    assert cost_usd(u, "claude-haiku-4-5") > naive * 5


def test_total_prompt_tokens_includes_the_cached_portion():
    """On a cache hit `input_tokens` reads as 12 — absurd until the cached part is added back."""
    assert Usage(input_tokens=12, cache_read_input_tokens=4409).total_prompt_tokens == 4421


# ── interaction log ──────────────────────────────────────────────────────────────────


def test_interaction_log_is_json_serialisable_and_priced():
    entry = InteractionLog(
        request_id="abc", model="claude-haiku-4-5", system_prompt_version="1.0",
        user_message_redacted="hi", latency_ms=1200, status="ok",
        usage=Usage(input_tokens=12, output_tokens=100, cache_read_input_tokens=4409),
    )
    d = entry.as_dict()
    json.dumps(d)  # must not raise
    assert d["cost_usd"] > 0
    assert d["usage"]["cache_read_input_tokens"] == 4409


def test_interaction_log_carries_no_raw_user_message_field():
    """The schema itself should make logging a raw message awkward, not merely discouraged."""
    fields = InteractionLog.__dataclass_fields__
    assert "user_message_redacted" in fields
    assert "user_message" not in fields


# ── rate limiter ─────────────────────────────────────────────────────────────────────


def test_client_key_prefers_forwarded_for_over_the_tcp_peer():
    """Behind Railway's router the peer is the router — using it buckets every visitor together."""
    client = limits.client_key({"x-forwarded-for": "203.0.113.9, 10.0.0.1"}, "10.0.0.1")
    assert client.key == "203.0.113.9"
    assert client.source == "x-forwarded-for"


def test_client_key_falls_back_to_peer_when_no_header():
    assert limits.client_key({}, "198.51.100.7") == ("198.51.100.7", "peer")


def test_client_key_never_returns_empty():
    assert limits.client_key({"x-forwarded-for": "  "}, None) == ("unknown", "none")


def test_client_key_source_is_reported_so_a_silent_degradation_is_visible():
    """The point of `source`: "peer" in production means one shared bucket for every visitor, which
    from outside looks identical to a limiter that is working correctly."""
    assert limits.client_key({}, "10.0.0.1").source == "peer"
    assert limits.client_key({"x-forwarded-for": "1.2.3.4"}, "10.0.0.1").source == "x-forwarded-for"


def test_limiter_allows_up_to_the_limit_then_blocks():
    limits.reset()
    for i in range(limits.RATE_LIMIT_PER_MINUTE):
        allowed, _ = limits.check("1.1.1.1", now=1000.0 + i)
        assert allowed, f"request {i} should have been allowed"
    allowed, retry_after = limits.check("1.1.1.1", now=1000.0)
    assert not allowed
    assert retry_after >= 1


def test_limiter_window_slides(monkeypatch):
    """Injected clock — no sleeps, so this is fast and deterministic in CI."""
    limits.reset()
    for i in range(limits.RATE_LIMIT_PER_MINUTE):
        limits.check("2.2.2.2", now=1000.0 + i)
    assert not limits.check("2.2.2.2", now=1000.0)[0]
    # 61s later the whole window has expired
    assert limits.check("2.2.2.2", now=1061.0 + limits.RATE_LIMIT_PER_MINUTE)[0]


def test_limiter_at_zero_rejects_without_crashing(monkeypatch):
    """Found by a live smoke test, not by the suite: `len(bucket) >= 0` is true for an *empty*
    bucket, so the retry_after arithmetic indexed `bucket[0]` and 500'd on every request."""
    limits.reset()
    monkeypatch.setattr(limits, "RATE_LIMIT_PER_MINUTE", 0)
    allowed, retry_after = limits.check("5.5.5.5", now=1000.0)
    assert not allowed
    assert retry_after == 60


def test_limiter_at_zero_does_not_grow_the_client_dict(monkeypatch):
    """A rejected caller must not create a bucket: eviction only runs on the allowed path, so
    tracking rejections would make the limiter its own memory-exhaustion vector."""
    limits.reset()
    monkeypatch.setattr(limits, "RATE_LIMIT_PER_MINUTE", 0)
    for i in range(50):
        limits.check(f"10.0.0.{i}", now=1000.0)
    assert len(limits._hits) == 0


def test_limiter_buckets_are_per_client():
    limits.reset()
    for i in range(limits.RATE_LIMIT_PER_MINUTE):
        limits.check("3.3.3.3", now=1000.0 + i)
    assert not limits.check("3.3.3.3", now=1000.0)[0]
    assert limits.check("4.4.4.4", now=1000.0)[0], "one client must not exhaust another's quota"


# ── the abandoned stream ─────────────────────────────────────────────────────────────


def _fake_stream(*chunks, raise_at_end: type[BaseException] | None = None):
    """Stands in for `stream_reply`, so this needs no API key and no network."""

    async def gen(_messages):
        for c in chunks:
            yield c
        if raise_at_end:
            raise raise_at_end()

    return gen


@pytest.mark.asyncio
async def test_abandoned_stream_still_logs(monkeypatch, caplog):
    """The criterion that motivated the `finally` block: a browser that disconnects mid-answer must
    not produce a billed turn with no record of it."""
    from app.api import chat as chat_mod
    from app.llm.client import Chunk

    monkeypatch.setattr(
        chat_mod, "stream_reply",
        _fake_stream(Chunk(type="delta", text="Cadre "), Chunk(type="delta", text="helps"),
                     raise_at_end=asyncio.CancelledError),
    )
    recorded: list[float] = []
    monkeypatch.setattr(chat_mod.spend, "record", _capture(recorded))

    caplog.set_level("INFO")
    stream = chat_mod._event_stream([{"role": "user", "content": "hi"}], "rid-abandon")
    with pytest.raises(asyncio.CancelledError):
        async for _ in stream:
            pass

    entry = _one_interaction(caplog)
    assert entry["status"] == "abandoned"
    assert entry["assistant_chars"] == 11, "the text that did stream must be accounted for"
    assert entry["error"] == "CancelledError"
    assert entry["request_id"] == "rid-abandon", (
        "proves the explicit id is load-bearing: this `finally` runs after the middleware has "
        "reset the ContextVar, so a formatter fallback would log '-'"
    )
    assert len(recorded) == 1, "an abandoned turn must still hit the spend ledger"
    # Honest about the gap: usage arrives only with `done`, so an abandoned turn records $0 while
    # the streamed tokens are really billed. Asserted so the under-count stays a known quantity.
    assert recorded == [0.0]
    assert entry["cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_completed_stream_logs_usage_and_cost(monkeypatch, caplog):
    from app.api import chat as chat_mod
    from app.llm.client import Chunk
    from app.llm.client import Usage as ClientUsage

    done = Chunk(
        type="done", stop_reason="end_turn",
        usage=ClientUsage(input_tokens=12, output_tokens=40, cache_read_input_tokens=4409),
    )
    monkeypatch.setattr(
        chat_mod, "stream_reply", _fake_stream(Chunk(type="delta", text="hello"), done)
    )
    recorded: list[float] = []
    monkeypatch.setattr(chat_mod.spend, "record", _capture(recorded))

    caplog.set_level("INFO")
    frames = [f async for f in
              chat_mod._event_stream([{"role": "user", "content": "hi"}], "rid-ok")]

    entry = _one_interaction(caplog)
    assert entry["status"] == "ok"
    assert entry["usage"]["cache_read_input_tokens"] == 4409
    assert entry["stop_reason"] == "end_turn"
    expected = cost_usd(Usage(input_tokens=12, output_tokens=40, cache_read_input_tokens=4409),
                        entry["model"])
    assert entry["cost_usd"] == pytest.approx(expected)
    assert recorded == [pytest.approx(expected)]
    assert any('"type":"done"' in f for f in frames)


@pytest.mark.asyncio
async def test_user_message_is_redacted_before_it_reaches_the_log(monkeypatch, caplog):
    """End-to-end on the path that matters: the raw message must never reach a log record."""
    from app.api import chat as chat_mod
    from app.llm.client import Chunk

    monkeypatch.setattr(chat_mod, "stream_reply", _fake_stream(Chunk(type="delta", text="ok")))
    monkeypatch.setattr(chat_mod.spend, "record", _capture([]))

    caplog.set_level("INFO")
    msg = "email me at prospect@acme.com"
    async for _ in chat_mod._event_stream([{"role": "user", "content": msg}], "rid-pii"):
        pass

    entry = _one_interaction(caplog)
    assert "prospect@acme.com" not in entry["user_message_redacted"]
    assert "prospect@acme.com" not in caplog.text
    assert "[email]" in entry["user_message_redacted"]


def _capture(sink: list[float]):
    async def record(cost: float) -> None:
        sink.append(cost)

    return record


def _one_interaction(caplog) -> dict:
    """Pull the single `interaction` record out of the captured log, as the dict it was logged as.

    Deliberately not rebuilt into an `InteractionLog`: asserting on the emitted dict tests what
    actually lands in the JSONL, and `as_dict()` adds derived fields the constructor won't take.
    """
    records = [r for r in caplog.records if r.getMessage() == "interaction"]
    assert len(records) == 1, f"expected exactly one interaction log, got {len(records)}"
    r = records[0]
    return {k: v for k, v in r.__dict__.items() if not k.startswith("_")}


# ── json log format ──────────────────────────────────────────────────────────────────


def test_formatter_emits_one_json_object_with_the_request_id():
    import logging

    token = request_id_var.set("rid-123")
    try:
        rec = logging.LogRecord("cadre.test", logging.INFO, __file__, 1, "an_event", None, None)
        rec.custom_field = "kept"  # type: ignore[attr-defined]
        out = json.loads(JsonFormatter().format(rec))
    finally:
        request_id_var.reset(token)

    assert out["event"] == "an_event"
    assert out["request_id"] == "rid-123"
    assert out["custom_field"] == "kept"
    assert out["level"] == "INFO"
    assert "ts" in out


def test_request_ids_are_unique_and_short_enough_to_quote():
    ids = {new_request_id() for _ in range(500)}
    assert len(ids) == 500
    assert all(len(i) == 16 for i in ids)


# ── request id plumbing ──────────────────────────────────────────────────────────────
#
# All three of these were found by reading a live log line, not by the suite. The id is reset in a
# `finally` that fires before the middleware's own log call and before the exception handler runs,
# so every consumer that read the ContextVar got "-" — an id matching nothing in the logs.


def test_access_log_line_carries_the_same_id_as_the_response_header():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = c.get("/api/config")
    rid = r.headers["X-Request-Id"]
    assert rid != "-"
    assert len(rid) == 16


def test_inbound_request_id_is_reused_so_a_proxy_id_survives():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = c.get("/api/config", headers={"X-Request-Id": "from-the-proxy"})
    assert r.headers["X-Request-Id"] == "from-the-proxy"


def test_a_500_returns_an_id_that_is_actually_greppable(monkeypatch):
    """The 500 body invites the user to quote this id, so it must not be the "-" placeholder.

    Breaks a real route rather than registering a throwaway one: the `StaticFiles` mount at "/" is
    a catch-all, so anything added after it is shadowed and returns 404 (see main.py's note on
    route order).
    """
    from fastapi.testclient import TestClient

    from app import main as main_mod

    def boom() -> dict:
        raise RuntimeError("deliberate — must not reach the browser")

    monkeypatch.setattr(main_mod.spend, "status", boom)

    with TestClient(main_mod.app, raise_server_exceptions=False) as c:
        r = c.get("/health", headers={"X-Request-Id": "trace-me"})

    assert r.status_code == 500
    assert r.json()["request_id"] == "trace-me"
    assert r.headers["X-Request-Id"] == "trace-me"
    assert "deliberate" not in r.text, "a stack trace must never reach the browser"
    assert "Traceback" not in r.text


# ── /api/stats (Phase 6) ─────────────────────────────────────────────────────────────


def test_stats_says_unavailable_rather_than_reporting_zeros(monkeypatch, tmp_path):
    """`turns: 0` and "cannot read the log" are different claims. Reporting the first when the
    second is true is the same class of quiet lie as a cache that silently never engages."""
    from app.api import stats as stats_mod
    from app.obs.sink import SinkStatus

    # SinkStatus is frozen on purpose, so swap the whole object rather than a field.
    monkeypatch.setattr(stats_mod, "SINK", SinkStatus("stdout-only", None, False, 7, "test"))
    rows, reason = stats_mod._read_interactions()
    assert rows == []
    assert "stdout-only" in reason


def test_stats_computes_the_numbers_it_reports(tmp_path, monkeypatch):
    from app.api import stats as stats_mod
    from app.obs.sink import SinkStatus

    rows = [
        {"status": "ok", "cost_usd": 0.001, "latency_ms": 100, "model": "claude-haiku-4-5",
         "usage": {"output_tokens": 50, "cache_read_input_tokens": 4409}},
        {"status": "refused", "refusal_reason": "no-public-pricing", "cost_usd": 0.002,
         "latency_ms": 200, "model": "claude-haiku-4-5",
         "usage": {"output_tokens": 60, "cache_creation_input_tokens": 4409}},
        {"status": "refused", "refusal_reason": "no-public-pricing", "cost_usd": 0.003,
         "latency_ms": 300, "model": "claude-haiku-4-5",
         "usage": {"output_tokens": 70, "cache_read_input_tokens": 4409}},
    ]
    path = tmp_path / "interactions.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    monkeypatch.setattr(stats_mod, "SINK", SinkStatus("disk", str(tmp_path), True, 7, "test"))
    got, reason = stats_mod._read_interactions()

    assert reason is None
    assert len(got) == 3


def test_stats_survives_a_torn_final_line(tmp_path, monkeypatch):
    """A half-written line during a concurrent append is expected, not exceptional — a status
    endpoint must not be the thing that takes the service down."""
    from app.api import stats as stats_mod
    from app.obs.sink import SinkStatus

    path = tmp_path / "interactions.jsonl"
    path.write_text('{"status":"ok"}\n{"status":"refu', encoding="utf-8")
    monkeypatch.setattr(stats_mod, "SINK", SinkStatus("disk", str(tmp_path), True, 7, "test"))

    rows, reason = stats_mod._read_interactions()
    assert reason is None
    assert len(rows) == 1


def test_stats_reports_latency_without_percentiles():
    """⚠️ **A mean and a count, never a p50/p95 — and this asserts the percentiles stay gone.**

    This replaced a test for a nearest-rank percentile helper. The helper was correct; reporting a
    *percentile* was the category error.

    A percentile claims the *shape of a distribution*, which this sample cannot support: it counts
    `ok` turns only, and on real traffic it reported p50 == p95 over a single measurement — a
    statistic that looks authoritative and says nothing. It also frames latency as a tail worth
    engineering against, and with no retrieval step that tail is the model provider's, not ours.

    A mean over `n` observed turns is an honest summary of what happened. That stays.

    The latency that IS meaningful is **time to first token** — only a client can measure it, and it
    carries a real diagnosis: if it lands close to the total, a proxy buffered the stream. It is
    surfaced per turn in the playground and in the eval's `--json` telemetry, where a single
    measurement against a known cause belongs, rather than as an aggregate implying a trend.

    Per-turn `latency_ms` on the `done` frame and in `interactions.jsonl` is untouched — one turn's
    duration is a fact about that turn.
    """
    from pathlib import Path

    from app.api import stats as stats_mod

    src = Path(stats_mod.__file__).read_text(encoding="utf-8")
    assert "_percentile" not in src, "the percentile helper is back"

    payload = src.split("return {", 1)[1]
    assert '"p50"' not in payload and '"p95"' not in payload, "percentiles reappeared"
    assert '"latency_ms"' in payload, "the mean latency should still be reported"
    assert '"mean"' in payload and '"n"' in payload
