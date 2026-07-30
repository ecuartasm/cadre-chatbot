"""Phase 0c tests.

These deliberately do NOT call the Anthropic API. What is worth testing here is our own
plumbing — request validation, the history cap, SSE framing, and the headers that keep a
proxy from buffering. Testing the model's prose would be slow, costly, and flaky; that job
belongs to the golden-set eval in Phase 6, which asserts properties rather than strings.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

import app.api.chat as chat_module
from app.api.chat import MAX_TURNS, ChatRequest
from app.llm.client import Chunk, Usage
from app.main import app

client = TestClient(app)


# --- request validation ---------------------------------------------------------------


def test_rejects_empty_message_list():
    assert client.post("/api/chat", json={"messages": []}).status_code == 422


def test_rejects_blank_content():
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "   "}]})
    assert r.status_code == 422


def test_rejects_unknown_role():
    r = client.post("/api/chat", json={"messages": [{"role": "system", "content": "hi"}]})
    assert r.status_code == 422


def test_history_is_capped_server_side():
    """The messages array comes from the browser, so the bound has to be enforced here —
    not trusted from the client."""
    many = [{"role": "user", "content": f"m{i}"} for i in range(100)]
    parsed = ChatRequest(messages=many)
    assert len(parsed.messages) == MAX_TURNS * 2
    assert parsed.messages[-1].content == "m99"  # keeps the most recent, drops oldest


def test_overlong_content_is_truncated_not_rejected():
    long = "x" * 99_000
    parsed = ChatRequest(messages=[{"role": "user", "content": long}])
    assert len(parsed.messages[0].content) == chat_module.MAX_MESSAGE_CHARS


# --- SSE contract ---------------------------------------------------------------------


@pytest.fixture
def fake_stream(monkeypatch):
    """Replace the LLM with a deterministic two-delta stream."""

    async def _fake(messages: list[dict]) -> AsyncIterator[Chunk]:
        yield Chunk(type="delta", text="Hello ")
        yield Chunk(type="delta", text="world")
        yield Chunk(
            type="done",
            stop_reason="end_turn",
            usage=Usage(input_tokens=10, output_tokens=2, cache_read_input_tokens=7),
        )

    monkeypatch.setattr(chat_module, "stream_reply", _fake)


def test_stream_emits_deltas_then_done(fake_stream):
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    frames = [f for f in r.text.split("\n\n") if f.strip()]
    assert frames[0] == 'data: {"type":"delta","text":"Hello "}'
    assert '"type":"done"' in frames[-1]
    # Cache counters must survive to the client — cost is uncomputable without them.
    assert '"cache_read_input_tokens":7' in frames[-1]


def test_anti_buffering_headers_present(fake_stream):
    """The whole reason Phase 0c exists. Without X-Accel-Buffering a proxy can hold the
    body and deliver it in one lump, which looks like a hang and then a dump."""
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["x-accel-buffering"] == "no"
    assert "no-cache" in r.headers["cache-control"]


def test_llm_failure_surfaces_as_an_error_frame_not_a_dead_stream(monkeypatch):
    async def _boom(messages: list[dict]) -> AsyncIterator[Chunk]:
        yield Chunk(type="error", text="Something went wrong. Please try again.")

    monkeypatch.setattr(chat_module, "stream_reply", _boom)
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200  # a mid-stream failure cannot retroactively change the status
    assert '"type":"error"' in r.text


# --- prompt invariants ----------------------------------------------------------------


def test_system_prompt_is_byte_stable_across_calls():
    """Prompt caching is a prefix match: any per-call variation silently disables it."""
    from app.llm.prompt import build_system_blocks

    assert build_system_blocks() == build_system_blocks()


def test_system_prompt_carries_a_cache_breakpoint():
    from app.llm.prompt import build_system_blocks

    assert build_system_blocks()[-1]["cache_control"] == {"type": "ephemeral"}


def test_boundary_rules_are_present_in_the_prompt():
    from app.llm.prompt import build_system_blocks

    text = build_system_blocks()[0]["text"].lower()
    for rule in ("pricing", "portal", "cadreai.com/contact"):
        assert rule in text


def test_config_endpoint_leaks_no_secret():
    body = client.get("/api/config").text
    assert "sk-ant-" not in body


# --- multi-turn (Phase 4) -------------------------------------------------------------


def test_a_prior_assistant_turn_is_accepted_and_ordered():
    """Nothing had ever sent one before Phase 4 — every test used a single user message."""
    parsed = ChatRequest(
        messages=[
            {"role": "user", "content": "Do you work with construction?"},
            {"role": "assistant", "content": "Yes, construction is one of nine industries."},
            {"role": "user", "content": "What does that look like in practice?"},
        ]
    )
    assert [m.role for m in parsed.messages] == ["user", "assistant", "user"]
    assert parsed.messages[-1].content.startswith("What does that")


def test_the_cap_keeps_whole_recent_turns_not_a_severed_pair():
    """Trimming to an even count from the end preserves user/assistant alternation, so the model
    never receives a reply whose question was dropped."""
    convo = []
    for i in range(20):
        convo.append({"role": "user", "content": f"q{i}"})
        convo.append({"role": "assistant", "content": f"a{i}"})
    parsed = ChatRequest(messages=convo)

    assert len(parsed.messages) == MAX_TURNS * 2
    assert parsed.messages[0].role == "user", "history must not begin with an orphaned reply"
    assert parsed.messages[-1].role == "assistant"


def test_history_from_the_browser_carries_no_refusal_marker(fake_stream):
    """The client accumulates only visible deltas, so a prior refusal arrives untagged. This is
    the input that made the model stop tagging — pinned here so the shape is explicit."""
    r = client.post(
        "/api/chat",
        json={
            "messages": [
                {"role": "user", "content": "How much does it cost?"},
                {"role": "assistant", "content": "Cadre doesn't publish pricing."},
                {"role": "user", "content": "Just a ballpark?"},
            ]
        },
    )
    assert r.status_code == 200
    assert "[[refusal" not in r.text


def test_a_stream_that_dies_mid_marker_shows_an_error_not_a_fragment(monkeypatch):
    """The accepted trade, made explicit: text the scanner was holding when the stream failed is
    dropped rather than flushed. Showing a fragment of an answer directly above 'something went
    wrong' would read worse than showing only the error."""

    async def _dies_mid_marker(messages: list[dict]) -> AsyncIterator[Chunk]:
        # In the real path the scanner would still be holding these bytes when the error lands.
        yield Chunk(type="error", text="Something went wrong. Please try again.")

    monkeypatch.setattr(chat_module, "stream_reply", _dies_mid_marker)
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert '"type":"error"' in r.text
    assert "[[refusal" not in r.text
    assert '"type":"delta"' not in r.text


def test_done_frame_carries_status_and_refusal_reason(fake_stream):
    """Phase 6 blocker. The golden set runs against the DEPLOYED url, where interactions.jsonl sits
    on a volume it cannot read — so without these on the wire the eval could only match substrings
    in prose, which is what the refusal marker exists to avoid."""
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    done = [f for f in r.text.split("\n\n") if '"type":"done"' in f][-1]
    payload = json.loads(done[len("data: "):])
    assert payload["status"] == "ok"
    assert payload["refusal_reason"] is None
    assert "usage" in payload and "request_id" in payload
