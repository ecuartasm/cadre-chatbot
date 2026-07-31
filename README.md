# Cadre AI — Support Chatbot

A customer-support chatbot for [Cadre AI](https://www.cadreai.com), an AI strategy and
implementation consultancy. It answers common inbound questions so the human team can spend its time
on the conversations that need a person.

**The defining feature is the boundary, not the coverage.** It answers a small set of questions
accurately and refuses everything else, routing to
[cadreai.com/contact](https://www.cadreai.com/contact). A confident wrong answer would be far worse
here than "I don't have that — here's who does," so the refusals were built first and are tested
harder than the answers.

```
Q: What industries do you work in?          → answered from the curated corpus
Q: How much does an engagement cost?        → refused · no-public-pricing · routed to /contact
Q: What's the client portal login URL?      → the portal is confirmed, the URL is never invented
Q: Write me a Python script.                → declined in one line, no contact link (not a lead)
```

---

## Quick start

```bash
uv sync                                  # dev dependencies are a group; plain sync installs them
cp .env.example .env                     # then add your ANTHROPIC_API_KEY
cd web && npm ci && npm run build && cd ..
uvicorn app.main:app --reload            # http://127.0.0.1:8000
```

| URL | |
|---|---|
| `/` | Chat, plus a **Playground** tab showing per-turn tokens, cache, cost and latency |
| `/chat-widget` | A Cadre-styled demo page with the bot as a floating widget |
| `/health` | Liveness, model, endpoint, log sink, spend |
| `/api/stats` | Turns, cost, cache hit rate, **refusal rate by reason** |

---

## How it works

```
React (Vite)  ──►  FastAPI  ──►  Anthropic Messages API
                      │
                      ├── knowledge layer   content/knowledge-base.md, loaded once at startup
                      └── observability     JSONL logs · cost · spend cap · rate limit
```

**Five seams, each independently replaceable.** Swapping the model, editing a fact, restyling the UI
or changing where logs go should touch exactly one. If a change touches two, the seam is wrong.

### The knowledge boundary is deliberate

The corpus is scraped once at build time, hand-curated, and committed. **The running app never
searches the web.** That makes the boundary explicit, the eval deterministic, and the demo immune to
network failure — and avoids a name collision, since an unrelated NY fintech is also called "Cadre".

Every curated entry carries a `disclosure` tag (`answerable` / `acknowledge-only` / `refuse`) and,
where it applies, a `refusal_reason` drawn from a **closed vocabulary of 16 slugs parsed out of the
corpus itself** — never hand-copied into Python, because a second copy is a second thing to drift.

### Refusals are structural, not prose

The model opens a refusal with `[[refusal:<slug>]]`. The server strips the marker before it reaches
the browser and puts `status` and `refusal_reason` on the log *and* the `done` frame.

That is what makes *"how often does it refuse, and why"* a number you can query rather than an
impression you form. The marker is stripped from **inbound** messages too, so a user cannot forge or
suppress a classification.

---

## Configuration

Everything is environment variables; see [`.env.example`](.env.example).

| | |
|---|---|
| `ANTHROPIC_MODEL` | `claude-haiku-4-5` (default) or `claude-sonnet-5` — **swap with one line** |
| `ANTHROPIC_BASE_URL` | Optional. Unset = Anthropic directly. Set = route through a compatible gateway |
| `DAILY_COST_CAP_USD` | Hard ceiling, checked **before** the model call |
| `RATE_LIMIT_PER_MINUTE` | Per-IP, read from `X-Forwarded-For` |
| `LOG_DIR`, `LOG_RETENTION_DAYS` | The rotation config **is** the retention policy |

### Switching models

```bash
uv run python .claude/skills/switch-model/switch-model.py claude-sonnet-5
```

Every per-model fact — cache floor, four price rates, `thinking` support, context window — lives in
`app/llm/models.py`. The script edits `.env` and then **proves the change took effect**, in a
subprocess with the shell variable removed, because that is the only path matching what a user gets.

Both models were run head-to-head over the full 71-case suite; the comparison with per-request
telemetry is in [`reports/models-test.md`](reports/models-test.md). Haiku wins on cost and
first-token latency with no boundary difference, so it is the default.

---

## Testing

```bash
pytest && ruff check .                                        # 249 tests
python eval/golden.py --url http://127.0.0.1:8000 --suite lite   # 14 cases — the deploy gate
python eval/golden.py --url http://127.0.0.1:8000 --suite full   # 71 cases — after a prompt edit
node web/scripts/link-audit.mjs                               # 102 link-rendering checks
```

The eval runs against a **URL**, not an import, so it can be pointed at production. `lite` is the
deploy gate; `full` adds the oblique routes — pricing asked eight ways, prompt injection, multi-turn
pressure.

**Assert properties, not strings.** The model is non-deterministic, so `"contains no dollar figure"`
survives rewording where `"contains 'individually'"` breaks on the first synonym.

`full` is **not expected to be 100%**. A *boundary* failure — a price, an invented URL, a client name
— is a defect. A *tagging* failure, where it refuses correctly in prose but logs `ok`, is known
under-reporting concentrated in soft refusals.

---

## Observability

Three JSONL streams under `LOG_DIR`, rotated daily with 7-day retention:

| Stream | |
|---|---|
| `interactions.jsonl` | One record per turn — usage, cost, latency, status, refusal reason |
| `app.jsonl` | Request lifecycle, every line carrying its `request_id` |
| `errors.jsonl` | Failures, with tracebacks that never reach the browser |
| `spend-history.jsonl` | One line per completed day — exempt from rotation, since a cost history that deletes itself weekly answers nothing |

**The user's message is never logged raw**, only a redacted form. The bot discusses Cadre's own
data-security posture; its logging must not be the counterexample.

**Cost is computed from four rates, not two** — input, output, cache-write (1.25×), cache-read
(0.1×). Two-rate maths is wrong the moment caching engages, and would make the spend cap throttle on
money that was never spent.

---

## Layout

```
app/
  main.py              FastAPI app, static mount, middleware, cache headers
  api/chat.py          POST /api/chat — SSE stream; `done` carries status + refusal_reason
  api/stats.py         GET /api/stats — turns, cost, cache, refusal rate by reason
  llm/client.py        The only module importing `anthropic`. Also MarkerScanner
  llm/models.py        Per-model facts: cache floor, four rates, thinking, window
  llm/prompt.py        System prompt builder — versioned, measured, logged per turn
  knowledge/loader.py  Loads and validates the corpus; parses the refusal enum from it
  obs/                 sink · log · redact · cost · spend · limits
content/
  raw/*.md             Byte-faithful scraped pages. Provenance. Never hand-edited
  knowledge-base.md    The curated corpus the bot reasons over
web/src/               React: chat, playground, widget, mockup, shared hooks
eval/                  golden.py (runner) · suites.py (14 lite + 71 full)
mcp_server/            Read-only MCP tools over /api/stats. Not in the runtime image
reports/               Per-phase reports · TECHNICAL-REPORT.md · models-test.md
```

---

## Deployment

One deployable: FastAPI serves the built React bundle as static files, so there is no CORS
configuration and no second thing to break.

```bash
railway up
python eval/golden.py --url <deployed-url> --suite lite   # the gate
```

**Local green is weaker evidence than it feels.** Six defects in this build were found *only*
against the deployed instance — a missing `COPY content/`, the volume mount path, request-id
plumbing, limiter bucketing, a woff2 mimetype, and a price anchor the eval had passed locally
minutes earlier.

⚠️ **`/api/stats` is unauthenticated.** It serves redacted messages and cost data, which is fine
while the service is reachable only when you want it to be. Putting it behind auth is the trigger
for a permanently-public deployment.

---

## Documentation

| | |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | The working contract — conventions, hard rules, the things that fail silently |
| [`plan.md`](plan.md) | Phase-by-phase plan with exit criteria and recorded decisions |
| [`reports/TECHNICAL-REPORT.md`](reports/TECHNICAL-REPORT.md) | The full technical account, including §16 on post-phase work |
| [`reports/models-test.md`](reports/models-test.md) | Haiku 4.5 vs Sonnet 5, measured over 172 requests |
| [`docs/ai-workflow-log.md`](docs/ai-workflow-log.md) | Terse per-phase record of how the work was done |

---

## What is deliberately out of scope

RAG or a vector database (~4k stable tokens — prompt-stuffing with a cached prefix is cheaper *and*
simpler) · auth and real portal access · live CRM or booking · cross-session persistence · an admin
CMS for the corpus · i18n · voice · OTel/Prometheus/Grafana · MCP on the request path.

Each has a recorded trigger in `plan.md` that would reverse it.

**And never:** invent pricing, invent a portal URL, summarise podcast content, or name a case-study
client.

---

## A note on what this project is really about

The interesting failures here were not in the product — they were in the *checking*.

An `.env` switch that did nothing while every test passed. A spend rollover that was never once
logged. An eval reporting "zero boundary failures" while having no check for the invented page paths
the bot was producing. A link-audit harness that copied the regex it was meant to test, and reported
a fixed bug as still broken.

The through-line is in [`reports/TECHNICAL-REPORT.md`](reports/TECHNICAL-REPORT.md) §16.9: **a guard
pinned to one filename stops covering what it was for, and reports green while doing it.** Nine times
in this build a test asserted something narrower than the property it stood for. The habit that
catches them is naming the property first, in words, before writing the assertion.
