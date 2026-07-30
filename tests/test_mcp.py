"""Phase 7 — the MCP observability server.

Offline. The tools are thin readers over `/api/stats` and `/health`, so what is worth testing is the
shape they return and — more importantly — what they refuse to do:

- report numbers when the bot is unreachable (they must say so, not return zeros)
- read the raw interaction log (they must not be able to)
- ship inside the runtime image (it must stay out)

The last one is the reason this phase was re-aimed at all: MCP had to be additive, so "the deployed
chatbot is unchanged" is a property under test rather than an intention.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "mcp_server"))

import server as mcp_server  # noqa: E402


def _payload(result) -> dict:
    """Pull the JSON a tool returned out of the MCP result envelope."""
    content = result[1] if isinstance(result, tuple) else result.content
    if isinstance(content, dict):
        return content
    text = content[0].text if isinstance(content, list) else content.content[0].text
    return json.loads(text)


@pytest.mark.asyncio
async def test_all_four_tools_are_registered():
    tools = await mcp_server.mcp.list_tools()
    assert {t.name for t in tools} == {
        "bot_health", "bot_stats", "refusal_breakdown", "spend_today"
    }


@pytest.mark.asyncio
async def test_every_tool_describes_itself():
    """The description is the whole interface — an MCP client picks a tool from it and nothing
    else, so an undescribed tool is an unusable one."""
    for t in await mcp_server.mcp.list_tools():
        assert t.description and len(t.description) > 60, f"{t.name} is under-described"


@pytest.mark.asyncio
async def test_an_unreachable_bot_is_reported_not_papered_over(monkeypatch):
    """The failure that matters. Returning zeros here would state "no traffic" when the truth is
    "cannot reach it" — the same quiet lie /api/stats itself refuses to tell."""
    monkeypatch.setattr(
        mcp_server, "_get", lambda path: {"error": "URLError: connection refused", "url": "x"}
    )

    health = _payload(await mcp_server.mcp.call_tool("bot_health", {}))
    assert health["reachable"] is False
    assert "error" in health

    for name in ("bot_stats", "refusal_breakdown", "spend_today"):
        got = _payload(await mcp_server.mcp.call_tool(name, {}))
        assert got["available"] is False, f"{name} claimed availability with no bot to read"


@pytest.mark.asyncio
async def test_refusal_breakdown_flags_a_reason_outside_the_corpus(monkeypatch):
    """A slug the corpus does not define means either the model invented one or the vocabulary
    drifted. Either way an operator should see it named, not averaged into a rate."""
    monkeypatch.setattr(mcp_server, "_get", lambda path: {
        "available": True, "turns": 10, "refusal_rate": 30.0,
        "refusals_by_reason": {"no-public-pricing": 2, "made-up-slug": 1},
        "by_status": {"ok": 7, "refused": 3},
    })
    got = _payload(await mcp_server.mcp.call_tool("refusal_breakdown", {}))
    assert got["unexpected_reasons"] == ["made-up-slug"]
    assert "made-up-slug" in got["interpretation"]


@pytest.mark.asyncio
async def test_a_healthy_breakdown_says_so_plainly(monkeypatch):
    monkeypatch.setattr(mcp_server, "_get", lambda path: {
        "available": True, "turns": 102, "refusal_rate": 45.1,
        "refusals_by_reason": {"no-public-pricing": 22, "off-topic": 4},
        "by_status": {"ok": 49, "refused": 46, "abandoned": 7},
    })
    got = _payload(await mcp_server.mcp.call_tool("refusal_breakdown", {}))
    assert got["unexpected_reasons"] == []
    assert "designed boundary" in got["interpretation"]


@pytest.mark.asyncio
async def test_stats_unavailable_is_passed_through_not_flattened(monkeypatch):
    """`/api/stats` already distinguishes "no traffic" from "cannot tell"; re-wrapping it here
    would throw that distinction away."""
    monkeypatch.setattr(mcp_server, "_get", lambda path: {
        "available": False, "reason": "log sink is stdout-only", "log_sink": "stdout-only"
    })
    got = _payload(await mcp_server.mcp.call_tool("bot_stats", {}))
    assert got["available"] is False
    assert "stdout-only" in got["reason"]


def test_the_server_never_reads_the_raw_interaction_log():
    """The deliberate limitation. Aggregates answer the operator's questions without republishing
    what anyone typed, which is why this can be a read-only tool with no auth in front of it."""
    src = (ROOT / "mcp_server" / "server.py").read_text(encoding="utf-8")
    for forbidden in ("interactions.jsonl", "user_message", "user_message_redacted"):
        assert forbidden not in src, f"the MCP server must not touch {forbidden}"

    # Word-boundary, or `open(` matches `urlopen(` — the same substring mistake the URL check in
    # eval/golden.py made. The property is "reads no local files", not "contains no 'open'".
    for call in (r"\bopen\(", r"\bPath\(", r"\bpathlib\b", r"\bos\.listdir\b"):
        assert not re.search(call, src), f"the MCP server must not do local file I/O ({call})"


def test_every_tool_is_read_only():
    """No tool here changes anything. An MCP server an operator points a model at should not be
    able to spend money or mutate state."""
    src = (ROOT / "mcp_server" / "server.py").read_text(encoding="utf-8")
    assert "urllib.request.Request(" in src
    # A POST/PUT/DELETE would need a method= argument or data= payload.
    assert "method=" not in src and "data=" not in src


def test_mcp_stays_out_of_the_runtime_image():
    """The property that made this phase additive rather than a risk: the deployed chatbot is
    unchanged. `mcp` is in the dev group, which `uv export --no-dev` excludes, and `mcp_server/`
    is never COPYd."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    runtime, _, rest = pyproject.partition("[project.optional-dependencies]")
    assert "mcp>=" not in runtime, "mcp must not be a runtime dependency"
    assert "mcp>=" in rest, "mcp should be declared in the dev group"

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "mcp_server" not in dockerfile, "mcp_server/ must not be copied into the image"
    assert "--no-dev" in dockerfile
