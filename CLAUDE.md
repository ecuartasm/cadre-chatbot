# CLAUDE.md — Cadre AI Support Chatbot

Onboarding for a fast, context-limited engineer. **Hard cap: under 250 lines** — it loads every turn,
so it holds only what is needed *every* time. Background research and the per-phase narrative are kept
outside this repository; **never load them in a build session** — this file is the contract.

## What this is

A customer-support chatbot for **Cadre AI**, an AI strategy and implementation consultancy, answering
common inbound questions so the human team can focus on high-value conversations.
**The product's defining feature is its boundary, not its coverage.** It answers a small set of
questions accurately and **refuses, then routes to `https://www.cadreai.com/contact`**, for everything
else. A confident wrong answer is far worse here than "I don't know — here's who can help." Build the
refusals first.

## Stack

Python + FastAPI (backend) · React + Vite (frontend) · Anthropic API · deployed to Railway.
**This stack is a given** — chosen by the project owner, not derived. Don't relitigate it.

| Thing | Choice | Non-obvious detail |
|---|---|---|
| Model | `claude-haiku-4-5` | $1/$5 per MTok · 200K ctx · 64K max out. **No `effort` param** (Claude 5-family only) — confirmed via the Models API, not recalled. We use ~2% of the window. |
| Escalation model | `claude-sonnet-5` | **Switch with `ANTHROPIC_MODEL` in `.env`; nothing else changes.** Every per-model fact lives in `app/llm/models.py`. Every rate is 3× — which makes scale an argument *for* Haiku, not against. Verified on Sonnet: 13/14 lite, caching engages (7,411 read). |
| Token counting | `client.messages.count_tokens` | **Never `tiktoken`** — it's OpenAI's tokenizer and undercounts Claude by ~15–20%. |
| Deploy | Railway + mounted Volume | The volume is for `logs/`. Serverless is ruled out: ephemeral FS loses the logs. |
| **API provider** | **prod ≠ local, deliberately** | **Railway calls OpenRouter** (`sk-or-v1-…`, Cadre's own project key, `ANTHROPIC_BASE_URL=https://openrouter.ai/api`). **Local uses a direct Anthropic key** (`sk-ant-…`, no base URL). A mismatch between them is CORRECT, never drift. |
| Serving | **One deployable** | FastAPI serves the built React bundle as static files. Avoids CORS and two ways to break one deadline. |

## Layout

```
app/
  main.py              FastAPI app, static mount, middleware wiring, woff2 mimetype
  api/chat.py          POST /api/chat (SSE stream). `done` carries status + refusal_reason
  api/stats.py         GET /api/stats — turns, cost, cache, refusal rate BY REASON
  llm/client.py        The ONLY file importing anthropic. Also MarkerScanner (strips the tag)
  llm/models.py        Per-model facts: cache floor, four rates, thinking, window. Swap = .env
  llm/prompt.py        System prompt builder. Versioned. See rules below.
  knowledge/loader.py  Loads + validates the KB; parses the refusal enum from it
  obs/                 sink.py, log.py, redact.py, cost.py, spend.py, limits.py — cross-cutting
content/
  raw/*.md             Byte-faithful scraped pages. Provenance. Never edited by hand.
  knowledge-base.md    Hand-curated, ~4k tokens. THE file the bot reasons over.
scripts/scrape.py      The curl-based scraper. Must stay re-runnable.
eval/golden.py         Runner. eval/suites.py holds the cases — lite (gate) + full
mcp_server/            Read-only MCP tools over /api/stats. NOT in the runtime image (dev group)
web/src/tokens.css     Design tokens — the ONLY file allowed a literal colour, size, or font
web/src/app.css        Component styles; every value a var(). No inline styles in any component
web/src/fonts/         Self-hosted Inter + Inter Tight woff2 (no CDN — see "Conventions")
logs/                  JSONL, on the Railway volume. Gitignored.
docs/                  Per-phase workflow log — the terse four-field record
```

**Five seams, each independently replaceable:** UI → API → LLM client → knowledge layer, plus
observability cutting across. Swapping the model, editing a fact, restyling the UI, or changing where
logs go must touch exactly one. If a change touches two, the seam is wrong.

## Commands

```bash
uv sync                          # dev deps are a dependency-GROUP, so plain sync installs them
uvicorn app.main:app --reload    # API at :8000
cd web && npm run build          # → served by FastAPI in prod (npm run dev for the UI dev server)
pytest && ruff check .
python scripts/scrape.py         # rebuild content/raw/ (writes content_sha256 into frontmatter)
python eval/golden.py --url <deployed> [--suite lite|full]   # lite=14/~$0.03, full=71/~$0.15
uv run python .claude/skills/switch-model/switch-model.py [<model-id>]  # swap + prove it took
uv run python mcp_server/server.py       # MCP tools over the deployed bot's observability
railway up
```

## Knowledge-base rules — NON-NEGOTIABLE

The corpus is scraped once at build time, committed, and served statically. **The running app never
searches the web** — that makes the knowledge boundary explicit, the eval deterministic, the demo
immune to network failure, and avoids a name collision (an unrelated NY fintech is also "Cadre").

### Never state these. There is no public source for any of them.

| Topic | Correct behavior |
|---|---|
| **Pricing** — any number, range, or "rough idea" | Engagements are scoped individually → `/contact`. Never infer from client size or case-study savings. |
| **Client portal access** | Confirm it exists and what it tracks. **Never invent a login URL, subdomain, onboarding flow, or support email.** Access is arranged through the client's Cadre team → `/contact`. |
| **Podcast episode content** | May name a show, guest, company, date, link. **Never summarize, quote, or infer what a guest said.** A title is not a conclusion: "Is MCP Actually Broken?" does not mean anyone said it is. These are real, identifiable people — this is worse than inventing a price. |
| **Client size / Cadre's own headcount or revenue** | No band, minimum, or figure is published; revenue numbers were founder projections. Answer by *segment and industry fit*, never by number → `/contact`. |
| **Case-study client names** | ✅ Resolved Phase 1: **all eight are "Non-Disclosed Company"** — clients anonymised, individuals named. "Griffin Funding" was fabricated upstream and appears nowhere. Metrics are *reported past results*, never guarantees. |
| **Engagement duration** | The "45-day AI Transformation Intensive" is *one named offering*, never a general answer to "how long does this take" → `/contact`. |
| **Contact details / security specifics** | Never invent a phone, email or address; never assert a certification (SOC 2), retention policy or contractual guarantee. General public answer, specifics → `/contact`. |
| **Third-party stats** | The site's "90% of AI initiatives fail" / "72% adoption" figures are imprecise. Attribute or omit. |

**Every refusal routes to `https://www.cadreai.com/contact`, phrased as helpful routing — never as
failure. One exception:** off-topic requests get a one-line decline naming what the bot *can* help
with and **deliberately no `/contact` link** — that person is not a lead. Still tagged `off-topic`:
the tag records what you did, not where you sent them. Broken twice in Phase 3, hence its own case.

### Curation rules

- **`content/raw/` is byte-faithful and never hand-edited** — the provenance record. An untraceable
  fact doesn't go in the KB. **Never restate a fact without its caveat**; if that's awkward, omit it.
- Every curated entry carries `disclosure: answerable | acknowledge-only | refuse` and, when not
  `answerable`, a `refusal_reason`. **The NEGATIVE KNOWLEDGE table is the authoritative vocabulary** —
  15 slugs plus `off-topic`, parsed by `loader.py`. Never hand-copy it into Python; a second copy is a
  second place to drift. ⚠️ Models read `acknowledge-only` differently — see Verification.
- **Count with `count_tokens`; don't estimate.** Current: 4,028 corpus; full prefix is per-model
  (6,054 Haiku / 8,336 Sonnet — same bytes, different tokenisers).

## System prompt rules

Lives in `app/llm/prompt.py`, versioned (`SYSTEM_PROMPT_VERSION`, currently **1.9**), logged per turn.
Sections: persona · corpus · grounding · boundary · **refusal marker** · conversion · format.

**Refusals are structural, not prompt text.** The model opens a refusal with `[[refusal:<slug>]]`;
`MarkerScanner` strips it **wherever it appears** and `status`/`refusal_reason` go to the log *and*
the `done` frame. A missing marker under-reports rather than mislabels — and the marker syntax is not
published, so it cannot be injected through a user message. ⚠️ **Strip anywhere, not just leading** —
Haiku puts the tag first as told; **Sonnet uses it as a section separator mid-answer**, and
leading-only stripping printed it into the chat (2 leaks in 4 runs). Tagging also differs by model:
Sonnet reads `acknowledge-only` entries as answers, so soft refusals log `ok` (portal: 0/5 tagged).
Prose is identical and safe either way; only the classification moves.

⚠️ **The prompt must be byte-stable.** Caching is a prefix match, so **no timestamp, `request_id`,
session id, or per-user string in the system block** — anything dynamic goes in `messages`. Put
`cache_control: {"type": "ephemeral"}` on the **last system block**; render order is `tools` →
`system` → `messages`, so one breakpoint covers it. Verified on both models (Sonnet: 7,411 read ×5).

⚠️ **Haiku 4.5's minimum cacheable prefix is 4,096 tokens.** Below the floor, caching **fails
silently** — `cache_creation_input_tokens` just stays `0`. Floors are non-monotonic (512 Opus 5,
1,024 Sonnet 5, 4,096 Haiku 4.5) — not guessable, so they live in `models.py`. **Measure it.**

⚠️ **The prompt text is never served, and the bot must not recite it either** — it once listed its
whole refusal vocabulary on request. Publishing `[[refusal:…]]` makes it injectable to fake or
suppress a refusal. If reinstated: dev-gated, never editable (5.2× cost, kills the shared cache).

**Re-measured after every edit**, per model (`MEASURED_SYSTEM_TOKENS_BY_MODEL`, guarded by a live
`count_tokens` test). Phase 0c's 511-token prefix **never cached at all**; **v1.9** clears every floor
— Haiku 6,054 (+1,958), Sonnet 8,336 (+7,312). Run `edit-system-prompt/measure-prefix.py`.

The floor inverts the usual instinct: trimming the prompt *costs* ~6× here, because a cached turn is
$0.00120 against $0.00627 uncached. **Bump `SYSTEM_PROMPT_VERSION` on every change** — log lines from
two prompts are otherwise indistinguishable, which makes any before/after comparison impossible.

## Conventions

- **`client.py` is the only file importing `anthropic`; `models.py` is the only place a per-model
  fact lives** (floor, four rates, `thinking`, window). Together they make `ANTHROPIC_MODEL=` a
  one-line `.env` change. A model number read from anywhere else is a bug — it keeps passing and stops
  being true. ⚠️ **Measured prefix is per-model:** 6,054 Haiku / 8,336 Sonnet, a 38% tokeniser gap.
- **Cost math needs four rates, not two:** input, output, cache-write (1.25×), cache-read (0.1×).
  Two-rate math is wrong the moment caching engages and makes the spend cap throttle on money never
  spent. An unpriced model **raises** rather than defaulting. Compute it in `cost.py`, nowhere else.
- **Log `user_message_redacted`, never the raw message.** **Retention: 7 days** — the rotation config
  *is* the policy. The bot discusses Cadre's data-security posture; its own logging must not be the
  counterexample. (Rotation verified; *deletion* needs day 8.) ⚠️ **`spend-history.jsonl` is exempt
  and must stay so** — retention is a *privacy* rule about user messages, and a date + dollar total
  has no personal data. `spend.json` holds only today; without the archive every daily total dies at
  the next rollover, which is what happened to 2026-07-30's. **Both rollover paths must archive:**
  `_roll_if_new_day()` only fires in a process that outlives midnight, so every restart went through
  `_load()`, which dropped the total in silence — `spend_day_rollover` had never once been logged.
- **Bound conversation history server-side** — 8 turns in the Pydantic model; the array comes from
  the browser, so don't trust it.
- **Every log line carries `request_id`** — but *carry* it, don't read the ContextVar late: the
  middleware resets it before its own log call, and `call_next` returns at headers, so an SSE body
  is iterated after it.
- **Secrets:** API key server-side only, never in the React bundle — Vite inlines anything `VITE_`
  prefixed at build time. `.env` is gitignored. ⚠️ **Never print Railway variable values** —
  `railway variables` echoes secrets in full and once put the live key in a transcript; names only.
  **Never set `ANTHROPIC_API_KEY` on Railway**: it is Cadre's, managed by the owner.
- ⚠️ **`ANTHROPIC_BASE_URL` unset = direct Anthropic.** Set, the client routes through a gateway;
  prod uses OpenRouter since the supplied key is theirs. One line in `client.py`; a test asserts
  `cost.py`/`prompt.py`/`chat.py`/`loader.py` never learn it exists. **Do NOT include `/v1`** — the
  SDK appends `/v1/messages`, so `.../api/v1` 404s everything with an HTML body. Model ids need no
  translation. ⚠️ **`count_tokens` is 404 on the gateway** and the SDK reads `ANTHROPIC_BASE_URL`
  *itself*, so measure the prefix against Anthropic directly.
- ⚠️ **`.env` loads in `app/__init__.py`, never an entry point.** Below `main.py`'s imports it ran
  *after* `client.py` resolved `ANTHROPIC_MODEL`, so editing `.env` did nothing — invisible because
  the file and `DEFAULT_MODEL` agreed. Swap with the `switch-model` skill, which verifies through a
  subprocess with the shell variable removed; a shell variable bypasses `.env` and hides this.
- Styling: **plain CSS with custom properties** (`tokens.css` holds every literal). No CSS-in-JS, no
  component kit, no router. **All text is black** (`#0b0707`, Cadre's own); de-emphasise with size and
  weight, never grey. Errors keep `--cadre-red` — the one documented exception. Shell in **`dvh`/`svh`,
  not `vh`** (iOS keyboard), input **≥16px** (less triggers iOS auto-zoom), **fonts self-hosted**.
  ⚠️ `tests/test_ui.py` checks **glob `web/src`** — three pinned to `App.jsx` stopped covering the UI
  when the widget arrived. Keep it so, bar the turn-renderer check: pinned on purpose, and guarded.

## Verification

- **Assert properties, not strings** — the model is non-deterministic. **Refusals are far more
  testable than answers.** `status`/`refusal_reason` ride on the `done` frame, not only the log: the
  eval runs against the *deployed* URL, where `interactions.jsonl` sits on a volume it cannot read.
- ⚠️ **The refusal tag is stripped from INBOUND messages** (`chat.py`) — a client-supplied
  `[[refusal:…]]` made the model skip its own, suppressing the classification. Server-side, so it
  never depends on the model choosing right.
- **Two suites.** `--suite lite` = 14, the **deploy gate**; `--suite full` = 71, adding oblique routes
  (pricing eight ways, injection, multi-turn) — run after a prompt edit or a model swap. **`full` is
  not 100% by design:** a *boundary* failure (price, URL, client name, leak) is a defect; a *tagging*
  failure is the known soft-refusal under-report (~7% Haiku; Sonnet reads `acknowledge-only` as an
  answer, so the portal case tags 0/5 — measure, don't assume).
- **Absence beats presence.** "No dollar figure" survives rewording; "contains 'individually'" breaks
  on the first synonym. Test an invented URL by membership in the pages `content/raw/` proves were
  fetched — matching `/contact` fails correct citations.
- ⚠️ **Eight times a test asserted something narrower than the property meant** — `grey` matched its
  own comment, `open(` matched `urlopen(`, a route walk missed every sub-router path, and a
  `load_dotenv()` substring check matched the comment forbidding it. **Name the property first**, and
  parse rather than grep when the property is a syntax question.
- Unit-test the knowledge layer, integration-test the API error path, assert `cache_read > 0` across
  two identical-prefix requests. **Never test the LLM itself.**
- **Local green is weaker evidence than it feels.** Six defects were found *only* on deploy: missing
  `COPY content/`, the volume mount path, request-id plumbing, limiter bucketing, the woff2 mimetype,
  a price anchor the eval had just passed locally. **A model swap is the same kind of environment
  change** — 171 unit tests passed while Sonnet printed the refusal tag into the chat.

## Out of scope — deliberately

Recorded decisions; the trigger that would reverse each is in `plan.md`.

**RAG / vector DB** (~4k stable tokens — prompt-stuffing plus a cached prefix is cheaper *and*
simpler; the eval confirmed every refusal is a designed boundary, not a coverage gap) · **auth /
real portal access** · **live CRM or booking** (link out) · **cross-session persistence** · **admin
CMS** · **i18n** · **voice** · **OTel/Prometheus/Grafana** (JSONL + `/stats` is the MVP tier) ·
**MCP on the request path** (retrieval over a corpus already in the prompt costs 2.6×/turn) ·
**a third model** (a new one needs a `models.py` row and a measured prefix, not just an `.env` edit).

**And never:** invent pricing (or cite a case-study saving *beside* a cost question — the eval caught
that), invent a portal URL, summarize podcast content, or name a case-study client.

## Working agreement

**Repo:** `https://github.com/ecuartasm/cadre-chatbot` (private) · `origin` · `main`.

**Follow `plan.md` phase by phase, and run its eight-step exit checklist every time:** tests green →
exit criterion met → workflow log → phase report → **review the next phase against what this one
taught** → commit → push → redeploy and verify the live URL. `plan.md` has the full version.

- **The forward-review step earns its place.** It caught the Dockerfile never copying `content/` (a bot
  with no KB, all local tests green), Phase 4's scope already being built, and MCP missing from the
  brief. Ask what this phase taught that changes the next.
- **Two records per phase.** `docs/ai-workflow-log.md` is a terse four-field entry; the phase report
  is the narrative. Write both *as you go*, from measured values — never recollection. Post-phase work
  gets its own running log, kept with the phase reports.
- **Push at the end of every phase** — work that exists only locally isn't safe, the repo *is* the
  deliverable, and batching phases into one push defeats it.
- ✅ **The gate is closed** — Phase 6 answered all six scenarios on the deployed URL, which gated MCP
  and observability P2; both shipped behind it. Small commits naming the phase; never `push --force`.
- **Check `git status` before every commit — read the staged list, not just the result.** Running
  `git add -A && git commit` in one breath swept a 9.5 MB PDF into history unnoticed. **Never commit a
  secret;** if a key is ever pushed, rotate it rather than removing the file in a later commit.
- When this file or `plan.md` looks wrong, say so and fix it. They are the contract, and a wrong
  contract should be corrected, not tolerated.
