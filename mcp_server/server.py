"""MCP server over the Cadre chatbot's observability layer.

Four read-only tools so an operator can *ask* what the bot has been doing — "what did it refuse
today, and why?" — instead of curling a JSON endpoint and reading it by eye.

**Why this and not `search_cadre_knowledge`.** The obvious MCP demo is bot-as-client with a
retrieval tool. Priced against the real numbers, that turns every user turn into two API calls:
$0.001024 → $0.002629 (2.6x) and roughly double the 2,398 ms p50 — to retrieve a ~5k-token corpus
already fully in the prompt. This sits *beside* the request path instead, so the chatbot's cost and
latency are unchanged and there is no new way for it to break.

**Why stdio and not an HTTP endpoint on the deployment.** An HTTP MCP surface on Railway would be a
new *unauthenticated public endpoint exposing interaction data*, and auth is explicitly out of scope
(CLAUDE.md), so there would be nothing to put in front of it. Serving people's messages publicly and
calling it acceptable because they are redacted is the reasoning this project rejects everywhere
else.

**What it deliberately cannot do.** It reads `/api/stats` and `/health` — aggregates — and never the
raw interaction log. That answers the operator's questions without republishing what anyone typed.
The MCP layer inherits the product's own discipline: report what can be substantiated, decline the
rest. It is read-only; there is no tool here that changes anything.

Run:
    CADRE_BOT_URL=https://cadre-chatbot-production.up.railway.app uv run python mcp_server/server.py
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from mcp.server.mcpserver import MCPServer

DEFAULT_URL = "https://cadre-chatbot-production.up.railway.app"
BOT_URL = os.getenv("CADRE_BOT_URL", DEFAULT_URL).rstrip("/")
TIMEOUT_S = 20

mcp = MCPServer(
    name="cadre-chatbot-observability",
    instructions=(
        "Read-only observability for the Cadre AI support chatbot. Reports aggregates only — "
        "never the contents of individual conversations. Use refusal_breakdown() to see what the "
        "bot declined to answer and why; that is the number this bot is judged on."
    ),
)


def _get(path: str) -> dict:
    """Fetch a JSON endpoint. Returns an `error` dict rather than raising, so a tool call reports
    an unreachable bot as a fact instead of a stack trace."""
    try:
        req = urllib.request.Request(f"{BOT_URL}{path}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code} from {path}", "url": BOT_URL}
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return {"error": f"{type(e).__name__}: {e}", "url": BOT_URL}


@mcp.tool(
    description=(
        "Is the Cadre chatbot up, which system-prompt version is live, and is its log sink "
        "writable. Use this first when something looks wrong."
    )
)
def bot_health() -> dict:
    health = _get("/health")
    if "error" in health:
        return {"reachable": False, **health}

    config = _get("/api/config")
    sink = health.get("log_sink", {})
    return {
        "reachable": True,
        "url": BOT_URL,
        "status": health.get("status"),
        "environment": health.get("environment"),
        "model": health.get("model"),
        "system_prompt_version": config.get("system_prompt_version"),
        "corpus_sha256": (config.get("corpus") or {}).get("sha256"),
        "log_sink": {
            "mode": sink.get("mode"),
            "writable": sink.get("writable"),
            "retention_days": sink.get("retention_days"),
        },
        # Not decoration: an unwritable sink means every number the other tools report is stale or
        # missing, and that should be visible before the numbers are trusted.
        "note": (
            "log_sink.writable must be true for the other tools to have data to read"
            if not sink.get("writable")
            else None
        ),
    }


@mcp.tool(
    description=(
        "Traffic, cost, cache efficiency and latency for the Cadre chatbot today. Returns "
        "available=false with a reason when the log cannot be read, rather than reporting zeros."
    )
)
def bot_stats() -> dict:
    stats = _get("/api/stats")
    if "error" in stats:
        return {"available": False, **stats}
    # Passed through as-is when available: /api/stats is already explicit about the difference
    # between "no traffic" and "cannot tell", and flattening that here would lose it.
    return stats


@mcp.tool(
    description=(
        "How often the Cadre chatbot refused to answer, broken down by reason. This is the number "
        "the bot is judged on: it is designed to refuse pricing, portal URLs, podcast content, "
        "security specifics and off-topic requests. A reason that looks like a knowledge gap "
        "rather than a designed boundary is the signal that the corpus needs work."
    )
)
def refusal_breakdown() -> dict:
    stats = _get("/api/stats")
    if "error" in stats:
        return {"available": False, **stats}
    if not stats.get("available"):
        return {"available": False, "reason": stats.get("reason")}

    by_reason = stats.get("refusals_by_reason", {}) or {}
    designed = {
        "no-public-pricing", "no-public-portal-access", "no-episode-content",
        "security-specifics-not-public", "off-topic", "clients-anonymised",
        "no-public-client-size", "no-public-company-figures", "no-public-engagement-count",
        "no-public-contact-details", "no-published-timeline", "events-not-verified",
        "not-disclosed", "unattributed-third-party-stat", "ambiguous-article-dates",
        "pillar-count-ambiguous",
    }
    unexpected = sorted(set(by_reason) - designed)

    return {
        "available": True,
        "turns": stats.get("turns"),
        "refusal_rate_pct": stats.get("refusal_rate"),
        "by_reason": by_reason,
        "by_status": stats.get("by_status"),
        "unexpected_reasons": unexpected,
        "interpretation": (
            "every refusal reason is a designed boundary from the corpus"
            if not unexpected
            else f"reasons not in the corpus vocabulary: {unexpected}"
        ),
    }


@mcp.tool(
    description=(
        "Spend so far today against the Cadre chatbot's daily cap, and how close it is to "
        "throttling. The cap is enforced before the model call, so reaching it stops spending "
        "rather than reporting it after the fact."
    )
)
def spend_today() -> dict:
    health = _get("/health")
    if "error" in health:
        return {"available": False, **health}

    spend = health.get("spend") or {}
    pct = spend.get("pct_of_cap")
    return {
        "available": True,
        "date_utc": spend.get("date"),
        "spend_usd": spend.get("spend_today_usd"),
        "cap_usd": spend.get("cap_usd"),
        "pct_of_cap": pct,
        "turns_today": spend.get("turns_today"),
        "persisted": spend.get("persisted"),
        "note": (
            "the ledger under-counts abandoned turns, whose token usage never arrives — "
            "see reports/phase-2-report.md"
        ),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
