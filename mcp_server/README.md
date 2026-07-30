# MCP observability server

Read-only MCP tools over the deployed Cadre chatbot, so an operator can *ask* what it has been doing
rather than curl a JSON endpoint and read it by eye.

```
MCP client (Claude Desktop, etc.)
        │  stdio
        ▼
  mcp_server/server.py  ──HTTP──▶  /api/stats
                                   /health
```

## Why it sits here and not on the request path

The obvious MCP demo is bot-as-client with a `search_cadre_knowledge` tool. Priced against this
project's real numbers, that turns every user turn into two API calls — **$0.001024 → $0.002629
(2.6×)** and roughly double the 2,398 ms p50 — to retrieve a ~5k-token corpus that is *already fully
in the prompt*.

This sits beside the request path instead. The chatbot's cost, latency, and failure modes are
unchanged, and `tests/test_mcp.py` asserts that rather than assuming it.

## Why stdio and not an HTTP endpoint on the deployment

An HTTP MCP surface on Railway would be a new **unauthenticated public endpoint exposing interaction
data**, and auth is explicitly out of scope (`CLAUDE.md`) — so there would be nothing to put in front
of it. Publishing people's messages and calling it acceptable because they are redacted is the
reasoning this project rejects everywhere else.

## What it deliberately cannot do

It reads **aggregates only** — `/api/stats` and `/health`. Never the raw interaction log, never an
individual conversation. That answers the operator's questions without republishing what anyone
typed, and it is what makes a no-auth read-only tool defensible.

It is also read-only: no tool here changes anything, spends anything, or mutates state. Both
properties are under test.

## Tools

| Tool | Answers |
|---|---|
| `bot_health()` | Is it up, which prompt version is live, is the log sink writable |
| `bot_stats()` | Turns, cost, cache hit rate, latency percentiles |
| `refusal_breakdown()` | Refusal rate **by reason**, and whether any reason is outside the corpus vocabulary |
| `spend_today()` | Spend against the daily cap |

Each reports `available: false` with a reason when the bot is unreachable or its log cannot be read —
never zeros. "No traffic" and "cannot tell" are different claims.

## Running it

```bash
# against production (the default)
uv run python mcp_server/server.py

# against a local instance
CADRE_BOT_URL=http://localhost:8000 uv run python mcp_server/server.py
```

Client config (Claude Desktop — `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "cadre-chatbot": {
      "command": "uv",
      "args": ["run", "--project", "/absolute/path/to/cadre-chatbot",
               "python", "mcp_server/server.py"],
      "env": { "CADRE_BOT_URL": "https://cadre-chatbot-production.up.railway.app" }
    }
  }
}
```

Then ask it things like *"what has the Cadre bot refused today, and why?"* or *"how close is it to
its spend cap?"*.

## Not in the deployed image

`mcp` is a dev-group dependency and `mcp_server/` is never `COPY`d into the container, so the
deployed chatbot's runtime dependency set is unchanged — the same mechanism that keeps
`scripts/scrape.py` out.
