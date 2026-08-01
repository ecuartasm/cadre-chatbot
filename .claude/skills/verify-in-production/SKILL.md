---
name: verify-in-production
description: Use after deploying to Railway, or when asked whether the bot is actually working live, or when a change passed locally and you are about to call it done. Also use when a deploy appears stuck or failed. Local green is weaker evidence than it feels — six defects in this build were found only against the deployed instance.
---

# Verifying in production

**Local green is weaker evidence than it feels.** Six defects here were invisible locally and only
appeared against the deployed instance:

| Defect | Why local passed |
|---|---|
| Dockerfile never copied `content/` | The corpus was on disk locally |
| Volume created at `/tmp`, unattached | No volume locally |
| `request_id` logged as `-` | Timing of a ContextVar reset under a real proxy |
| Rate limiter's bucketing indistinguishable | One client can't reveal a shared bucket |
| woff2 served as `application/octet-stream` | macOS registers the mimetype; slim Debian doesn't |
| A price anchor in a pricing refusal | The eval passed locally minutes earlier — the model is non-deterministic |

The last one matters most: **passing locally is not the same run as passing in production.**

## 1. Deploy, and read the state rather than the output

```bash
railway up --ci
```

Three traps, each of which cost real time during the build:

- **`"Failed to stream build logs"` does not mean the deploy failed.** The log stream dropped; the
  build usually continues. Check the service, not the command's output.
- **A 502 right after is normal** — that's the swap. It is not a crash loop unless it persists.
- **`railway deployment list` is the source of truth.** `DEPLOYING` means still building; wait for
  `SUCCESS`. Deploys took ~7 minutes early in the build and ~20 minutes later, so *do not conclude
  failure from slowness*. One sat in `DEPLOYING` behind a 502 and recovered unaided.

## 2. Check the deployed instance

```bash
./.claude/skills/verify-in-production/check.sh --wait
```

`--wait` polls until healthy — use it straight after `railway up`. It reports:

- **Identity** — prompt version, corpus sha, model. *Does the deployed thing match the repo?* A
  matching corpus sha is what proves `COPY content/` worked; that check exists because it once didn't.
- **Log sink** — if `writable` is false, every number after it is stale or missing.
- **Spend** — against the daily cap.
- **Behaviour aggregates** — turns, refusal rate by reason, cache hit rate, mean latency.
  ⚠️ No percentiles: with no retrieval step, latency is the provider's response time, and a
  p50/p95 over this sample claims a distribution shape it cannot support.

An unavailable `/api/stats` reports *why*. That is an honest "cannot tell", not "no traffic" — the two
are different claims and the endpoint refuses to conflate them.

## 3. Run the golden set — this is the step that proves behaviour

```bash
python eval/golden.py --url https://cadre-chatbot-production.up.railway.app
```

14 cases, ~$0.03, ~2 minutes. Exit 0 only if all pass, so it works as a gate.

Everything above checks that the right *code* is deployed. Only this checks that the bot still
*behaves*. It has already caught a real defect that passed locally in the same session.

If it aborts with a rate-limit message, that is **not** a content failure — it paces itself, but two
runs inside a minute will trip the 20/min limiter.

## 4. Interpreting what you see

- **Cache hit rate low on a quiet instance is expected.** The prefix TTL is 5 minutes, so the first
  turn of each window pays a *write*. A near-100% rate means the eval just ran; a low one on idle
  traffic is normal, not a fault. This is why the daily cap is budgeted against the write cost.
- **The first turn after any deploy pays a cache write** (~$0.0063 vs ~$0.0012). Expected.
- **`abandoned` turns** record `$0` because usage only arrives with the `done` event. The ledger
  under-counts by that share, deliberately — a guess does not belong in a money ledger.
- **A `refusal_reason` outside the corpus vocabulary** means the model invented a slug or the corpus
  drifted. `refusal_breakdown()` in the MCP server names them rather than averaging them into a rate.

## 5. Asking conversationally instead

The MCP server exposes the same data as tools, which is easier for open-ended questions:

```bash
uv run python mcp_server/server.py     # stdio; point an MCP client at it
```

`bot_health()` · `bot_stats()` · `refusal_breakdown()` · `spend_today()`. Read-only, aggregates only,
never the raw interaction log.

## What "verified" may and may not claim

Be precise about the difference, because the bot makes claims about Cadre's data-security posture and
overclaiming its own would be the same inconsistency:

- ✅ *"Rotation ran"* — observed once. **Not** *"7-day retention works"*, which needs the 8th day.
- ✅ *"The CSS contains `100dvh`"* — asserted by a test. **Not** *"the composer sits above the iOS
  keyboard"*, which needs a phone.
- ✅ *"The fonts load"* — HTTP 200 and correct content-type. **Not** *"it looks right"*, which needs
  eyes on the rendered page.

State what was checked, not what it implies.
