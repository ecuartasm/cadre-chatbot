# CLAUDE.md — Cadre AI Support Chatbot

Onboarding for a fast, context-limited engineer. Read this before touching anything.

**Hard cap: this file stays under 250 lines.** It is loaded on every turn, so it holds only what is
needed *every* time. Deep background lives in `analysis/` — **do not load those files into a build
session.** They are 190KB of reasoning that has already been distilled into this file and `plan.md`.
If something here seems arbitrary, the "why" is in `analysis/ANALYSIS.md`; read it as a human, then
come back.

---

## What this is

A customer-support chatbot for **Cadre AI**, an AI strategy and implementation consultancy. It answers
common inbound questions from prospective and existing clients so the human team can focus on
high-value conversations.

**The product's defining feature is its boundary, not its coverage.** It answers a small set of
questions accurately and **refuses, then routes to `https://www.cadreai.com/contact`**, for everything
else. A confident wrong answer is a much worse failure here than "I don't know — here's who can help."
Build the refusals first.

---

## Stack

Python + FastAPI (backend) · React + Vite (frontend) · Anthropic API · deployed to Railway.

**This stack is a given** — chosen by the project owner, not derived. Don't relitigate it. It suits
the work: async middleware for the logging layer, Pydantic for request validation, and the Anthropic
SDK on the shortest path.

| Thing | Choice | Non-obvious detail |
|---|---|---|
| Model | `claude-haiku-4-5` | $1/$5 per MTok · 200K ctx · 64K max out. **No `effort` param** (that's Claude 5-family only); uses legacy `budget_tokens` if you ever enable thinking — you won't, this is a grounded FAQ bot. |
| Escalation model | `claude-sonnet-5` | Only if quality gaps show up. **Not a drop-in swap:** it runs adaptive thinking by default at `effort: high`. Both must be explicitly turned down or latency collapses. |
| Token counting | `client.messages.count_tokens` | **Never `tiktoken`** — it's OpenAI's tokenizer and undercounts Claude by ~15–20%. |
| Deploy | Railway + mounted Volume | The volume is for `logs/`. Serverless is ruled out: ephemeral FS loses the logs. |
| Serving | **One deployable** | FastAPI serves the built React bundle as static files. Avoids CORS and two ways to break one deadline. |

---

## Layout

```
app/
  main.py              FastAPI app, static mount, middleware wiring
  api/chat.py          POST /api/chat (SSE stream), GET /api/stats
  llm/client.py        Anthropic calls behind ONE interface — the only file that imports anthropic
  llm/prompt.py        System prompt builder. Versioned. See rules below.
  knowledge/loader.py  Loads + validates content/knowledge-base.md
  obs/                 log.py, cost.py, limits.py — the cross-cutting layer
content/
  raw/*.md             Byte-faithful scraped pages. Audit trail. Committed. Never edited by hand.
  knowledge-base.md    Hand-curated. ~2–4k tokens. THE file the bot reasons over.
scripts/scrape.py      The curl-based scraper. Committed — it must be re-runnable.
eval/golden.py         13-case eval. See "Verification".
web/                   React + Vite source
logs/                  JSONL, on the Railway volume. Gitignored.
docs/ai-workflow-log.md  Per-phase record of what Claude produced vs. what changed.
```

**Five seams, each independently replaceable:** UI → API → LLM client → knowledge layer, plus
observability cutting across all of them. Swapping the model, editing a fact, restyling the UI, or
changing where logs go must each touch exactly one seam. If a change touches two, the seam is wrong.

---

## Commands

```bash
uv sync                        # or: pip install -r requirements.txt
uvicorn app.main:app --reload  # API at :8000
cd web && npm run dev          # UI dev server
cd web && npm run build        # → served by FastAPI in prod

python scripts/scrape.py       # rebuild content/raw/ (writes content_sha256 into frontmatter)
python eval/golden.py --url http://localhost:8000   # or --url <deployed>
pytest

railway up
```

---

## Knowledge-base rules — NON-NEGOTIABLE

The bot's corpus is scraped once at build time, committed, and served statically. **The running app
never searches the web.** This is deliberate: it makes the knowledge boundary explicit, the eval
deterministic, and the demo immune to network failure. It also avoids a name collision — an unrelated
New York real-estate fintech is also called "Cadre."

### Never state these. There is no public source for any of them.

| Topic | Correct behavior |
|---|---|
| **Pricing** — any number, range, or "rough idea" | Engagements are scoped individually → `/contact`. Never infer from client size or case-study savings. |
| **Client portal access** | Confirm it exists and what it tracks. **Never invent a login URL, subdomain, onboarding flow, or support email.** Access is arranged through the client's Cadre team → `/contact`. |
| **Podcast episode content** | May name a show, guest, company, date, link. **Never summarize, quote, or infer what a guest said.** A title is not a conclusion: "Is MCP Actually Broken?" does not mean anyone said it is. These are real, identifiable people — this is worse than inventing a price. |
| **Client size** | No revenue band, employee band, or deal minimum is published. Answer by *segment and industry fit*, never by number → `/contact`. |
| **Headcount / revenue** | Sources conflict; revenue figures were founder projections. Say "a growing team" or omit. |
| **Case-study client names** | ⚠️ **Blocked until verified.** See "Open gate" in `plan.md`. Metrics are *reported past results*, never guarantees. |
| **Engagement duration** | The "45-day AI Transformation Intensive" is *one named offering*, never a general answer to "how long does this take" → `/contact`. |
| **Contact details** | Never invent a phone number, email, or street address. `/contact` only. |
| **Security specifics** | Never assert a certification (SOC 2), retention policy, or contractual guarantee. Give the general public answer and route specifics → `/contact`. |
| **Third-party stats** | The site's "90% of AI initiatives fail" / "72% adoption" figures are imprecise. Attribute or omit. |

**Every refusal routes to `https://www.cadreai.com/contact`, phrased as helpful routing — never as
failure. One exception:** off-topic requests (coding help, weather, general LLM use) get a one-line
decline naming what the bot *can* help with and **deliberately no `/contact` link** — that person is
not a lead. Log it as `refusal_reason: 'off-topic'`.

### Curation rules

- **`content/raw/` is byte-faithful and never hand-edited.** It is the provenance record. If a fact
  isn't traceable to a raw file, it doesn't go in the curated KB.
- **Never restate a fact without its caveat.** If carrying the caveat is awkward, omit the fact.
- Every curated entry carries `disclosure: answerable | acknowledge-only | refuse` and, when not
  `answerable`, a `refusal_reason`. **Refusals are structural, not just prompt text.**
- Target ~2–4k tokens. **Count it with `count_tokens`; don't estimate.**

---

## System prompt rules

Lives in `app/llm/prompt.py`, versioned (`SYSTEM_PROMPT_VERSION`), logged per turn. Sections: persona
· grounding rule · escalation policy · conversion behavior · format rules · anti-hallucination
guardrails.

⚠️ **The prompt must be byte-stable.** Prompt caching is a prefix match, so **no timestamps, no
`request_id`, no session id, no per-user string anywhere in the system block.** Anything dynamic goes
in `messages`. One changed byte invalidates the cache and silently triples the cost of every turn.

**Caching:** put `cache_control: {"type": "ephemeral"}` on the **last system block** (render order is
`tools` → `system` → `messages`, so one breakpoint covers the whole prefix).

⚠️ **Haiku 4.5's minimum cacheable prefix is 4,096 tokens** — above the KB's target size. Below the
floor, caching **fails silently**: no error, `cache_creation_input_tokens` just stays `0` forever.
Floors are non-monotonic across models (512 on Opus 5, 1,024 on Sonnet 5, 4,096 on Haiku 4.5), so this
is not guessable. **Measure it, then decide** — see `plan.md` Phase 3.

---

## Conventions

- **`app/llm/client.py` is the only file that imports `anthropic`.** Everything else talks to the
  interface. That's what makes the model swappable.
- **Cost math needs four rates, not two:** input, output, cache-write (~1.25× input), cache-read
  (~0.1× input). A `cost_usd` computed as `tokens × one_rate` is wrong the moment caching engages, and
  it makes the daily spend cap throttle on money never spent.
- **Log `user_message_redacted`, never the raw message.** Strip emails and phone numbers before
  writing. **Retention: 7 days**, enforced by the rotation handler config — the config *is* the
  policy. The bot discusses Cadre's data-security posture; its own logging must not be the
  counterexample.
- **Bound conversation history server-side.** The `messages` array arrives from the browser, so cap it
  (8 turns, or a token budget) in the Pydantic model. Don't trust the client.
- **Every log line carries `request_id`**, set by middleware and threaded through.
- **Secrets:** API key server-side only. Never in the React bundle — Vite inlines anything prefixed
  `VITE_` at build time. `.env` is gitignored before the first commit.
- Styling: **plain CSS with custom properties** as design tokens. No CSS-in-JS, no fully-skinned
  component kit. Headless primitives are fine. (Owner's decision, like the stack.)
- Chat UI: shell height in **`dvh`/`svh`, not `vh`** (iOS Safari keyboard covers `vh`), and input
  `font-size: 16px` minimum (anything less triggers focus auto-zoom on iOS).

---

## Verification

- **The golden set asserts properties, not strings.** The model is non-deterministic; substring
  matching on prose produces false failures on correct behavior. Assert *grounding present* for
  answers and *absence* for refusals (no number, no URL-shaped string, no quoted claim) plus the
  expected `status`/`refusal_reason` in the log. **Refusals are far more testable than answers.**
- 13 cases: 6 scenarios · 3 required refusals · 2 coverage (getting-started, case-studies) · 2
  multi-turn (anaphora follow-up, refusal-then-pushback).
- Unit-test the knowledge layer (deterministic). Integration-test the API error path. **Don't test the
  LLM itself.**
- One assertion that `usage.cache_read_input_tokens > 0` across two identical-prefix requests.

---

## Out of scope — deliberately

Don't build these. Each is a recorded decision, with the trigger that would reverse it in `plan.md`.

**RAG / vector DB** (corpus is ~2–4k tokens and stable — prompt-stuffing plus a cached prefix is
cheaper *and* simpler) · **auth / real portal access** (the bot explains how, it doesn't implement it)
· **live CRM or calendar booking** (link out) · **cross-session chat persistence** · **admin CMS** ·
**i18n** (English only) · **voice** · **OTel/Prometheus/Grafana** (JSONL + `/stats` is the MVP tier).

**And never:** invent pricing, invent a portal URL, summarize podcast content, or name a case-study
client before the gate in `plan.md` closes.

---

## Working agreement

**Repo:** `https://github.com/ecuartasm/cadre-chatbot` (private) · `origin` · `main`.

**Follow `plan.md` phase by phase, and run its phase-exit checklist every time.** In short: tests green
→ phase exit criterion met → `docs/ai-workflow-log.md` appended → **`reports/phase-<n>-report.md`
written** → **commit** → **push to `origin main`** → **review the next phase against what this one taught** →
**commit** → **push** → redeploy and verify the live URL. All eight, every phase. `plan.md` has the
full version.

- **The forward-review step earns its place.** Phase 0's review caught that the Dockerfile never copied
  `content/`, which would have deployed a bot with an empty knowledge base while every local test
  passed. Treat it as a real check: what did this phase teach that changes the next one's scope,
  ordering, or numbers?

- **Two records per phase, and they are not the same thing.** `docs/ai-workflow-log.md` is a terse
  four-field entry (asked for / produced / changed / verified). `reports/phase-<n>-report.md` is the
  detailed narrative: what shipped and why, problems and resolutions, verification evidence with actual
  numbers, what was deferred, what's next. Write the report from the phase's own evidence — measured
  values, real commit hashes, actual test counts — never from recollection.

- **Push at the end of every phase, without exception.** Work that exists only locally isn't safe, and
  the repo *is* the deliverable. Don't batch several phases into one push.
- **Write the workflow-log entry as you go**, not at the end — reconstructing "what I changed and why"
  from memory defeats the entire purpose of keeping it.
- **The gate:** the bot must answer all six scenarios on the deployed URL before MCP or observability
  P2 begins. Non-negotiable regardless of time available.
- Small, descriptive commit messages that name the phase. Never `git push --force`.
- **Never commit a secret.** `.env` is gitignored; check `git status` before every commit. If a key is
  ever pushed, rotate it — don't just remove the file in a later commit.
- When something in this file or `plan.md` looks wrong, say so and fix it rather than working around it.
  These two files are the contract, and a wrong contract should be corrected, not tolerated.
