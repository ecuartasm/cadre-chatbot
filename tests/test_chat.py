"""Phase 0c tests.

These deliberately do NOT call the Anthropic API. What is worth testing here is our own
plumbing — request validation, the history cap, SSE framing, and the headers that keep a
proxy from buffering. Testing the model's prose would be slow, costly, and flaky; that job
belongs to the golden-set eval in Phase 6, which asserts properties rather than strings.
"""

from __future__ import annotations

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
