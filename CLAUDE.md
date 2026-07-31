# CLAUDE.md — Cadre AI Support Chatbot

Onboarding for a fast, context-limited engineer. Read this before touching anything.
**Hard cap: under 250 lines.** It loads every turn, so it holds only what is needed *every* time.
Background is in `analysis/` — **don't load those into a build session**; per-phase detail is in
`reports/`.

---

## What this is

A customer-support chatbot for **Cadre AI**, an AI strategy and implementation consultancy, answering
common inbound questions so the human team can focus on high-value conversations.

**The product's defining feature is its boundary, not its coverage.** It answers a small set of
questions accurately and **refuses, then routes to `https://www.cadreai.com/contact`**, for everything
else. A confident wrong answer is a much worse failure here than "I don't know — here's who can help."
Build the refusals first.

---

## Stack

Python + FastAPI (backend) · React + Vite (frontend) · Anthropic API · deployed to Railway.

**This stack is a given** — chosen by the project owner, not derived. Don't relitigate it.

| Thing | Choice | Non-obvious detail |
|---|---|---|
| Model | `claude-haiku-4-5` | $1/$5 per MTok · 200K ctx · 64K max out. **No `effort` param** (Claude 5-family only) — confirmed via the Models API, not recalled. We use ~2% of the window. |
| Escalation model | `claude-sonnet-5` | **Only on measured evidence, and it is not a drop-in swap:** adaptive thinking on by default, and every rate is 3× — which makes scale an argument *for* Haiku, not against. The cache floor is a minimum, never a ceiling, so it does not constrain growth. |
| Token counting | `client.messages.count_tokens` | **Never `tiktoken`** — it's OpenAI's tokenizer and undercounts Claude by ~15–20%. |
| Deploy | Railway + mounted Volume | The volume is for `logs/`. Serverless is ruled out: ephemeral FS loses the logs. |
| Serving | **One deployable** | FastAPI serves the built React bundle as static files. Avoids CORS and two ways to break one deadline. |

---

## Layout

```
app/
  main.py              FastAPI app, static mount, middleware wiring, woff2 mimetype
  api/chat.py          POST /api/chat (SSE stream). `done` carries status + refusal_reason
  api/stats.py         GET /api/stats — turns, cost, cache, refusal rate BY REASON
  llm/client.py        The ONLY file importing anthropic. Also MarkerScanner, which strips the
                       refusal tag before it reaches the browser
  llm/prompt.py        System prompt builder. Versioned. See rules below.
  knowledge/loader.py  Loads + validates the KB; parses the refusal enum from it
  obs/                 sink.py, log.py, redact.py, cost.py, spend.py, limits.py — cross-cutting
content/
  raw/*.md             Byte-faithful scraped pages. Provenance. Never edited by hand.
  knowledge-base.md    Hand-curated, ~4k tokens. THE file the bot reasons over.
scripts/scrape.py      The curl-based scraper. Must stay re-runnable.
eval/golden.py         14-case golden set. See "Verification".
mcp_server/            Read-only MCP tools over /api/stats. NOT in the runtime image (dev group)
web/src/tokens.css     Design tokens — the ONLY file allowed a literal colour, size, or font
web/src/app.css        Component styles; every value a var(). No inline styles in App.jsx
web/src/fonts/         Self-hosted Inter + Inter Tight woff2 (no CDN — see "Conventions")
logs/                  JSONL, on the Railway volume. Gitignored.
docs/ai-workflow-log.md  Per-phase record of what Claude produced vs. what changed.
reports/phase-<n>-report.md  The detailed narrative per phase.
```

**Five seams, each independently replaceable:** UI → API → LLM client → knowledge layer, plus
observability cutting across. Swapping the model, editing a fact, restyling the UI, or changing where
logs go must each touch exactly one. If a change touches two, the seam is wrong.

---

## Commands

```bash
uv sync                          # dev deps are a dependency-GROUP, so plain sync installs them
uvicorn app.main:app --reload    # API at :8000
cd web && npm run build          # → served by FastAPI in prod (npm run dev for the UI dev server)
pytest && ruff check .
python scripts/scrape.py         # rebuild content/raw/ (writes content_sha256 into frontmatter)
python eval/golden.py --url <deployed>   # 14 cases, ~$0.03, paces itself around the rate limiter
uv run python mcp_server/server.py       # MCP tools over the deployed bot's observability
railway up
```

---

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
| **Contact details** | Never invent a phone number, email, or street address. `/contact` only. |
| **Security specifics** | Never assert a certification (SOC 2), retention policy, or contractual guarantee. Give the general public answer and route specifics → `/contact`. |
| **Third-party stats** | The site's "90% of AI initiatives fail" / "72% adoption" figures are imprecise. Attribute or omit. |

**Every refusal routes to `https://www.cadreai.com/contact`, phrased as helpful routing — never as
failure. One exception:** off-topic requests get a one-line decline naming what the bot *can* help
with and **deliberately no `/contact` link** — that person is not a lead. Still tagged `off-topic`:
the tag records what you did, independent of where you send them. Broken twice in Phase 3, which is
why it has its own golden-set case.

### Curation rules

- **`content/raw/` is byte-faithful and never hand-edited** — the provenance record. A fact not
  traceable to a raw file doesn't go in the curated KB.
- **Never restate a fact without its caveat.** If carrying the caveat is awkward, omit the fact.
- Every curated entry carries `disclosure: answerable | acknowledge-only | refuse` and, when not
  `answerable`, a `refusal_reason`. **The NEGATIVE KNOWLEDGE table is the authoritative vocabulary** —
  15 slugs plus `off-topic`, parsed at load time by `loader.py`. Never hand-copy that list into Python;
  a second copy is a second place for it to drift.
- **Count with `count_tokens`; don't estimate.** Current: 4,028 corpus / 5,050 full prefix.

---

## System prompt rules

Lives in `app/llm/prompt.py`, versioned (`SYSTEM_PROMPT_VERSION`, currently **1.3**), logged per turn.
Sections: persona · corpus · grounding · boundary · **refusal marker** · conversion · format.

**Refusals are structural, not prompt text.** The model opens a refusal with `[[refusal:<slug>]]`;
`MarkerScanner` strips it before the first delta reaches the browser, and `status`/`refusal_reason`
go to the log *and* the `done` frame. A missing marker under-reports rather than mislabels.

⚠️ **The prompt must be byte-stable.** Caching is a prefix match, so **no timestamp, `request_id`,
session id, or per-user string anywhere in the system block** — anything dynamic goes in `messages`.
Put `cache_control: {"type": "ephemeral"}` on the **last system block**; render order is `tools` →
`system` → `messages`, so one breakpoint covers the whole prefix. Confirmed empirically: `cache_read`
held constant at 4,948 across a 3-turn conversation while the prompt grew 4,964 → 5,206.

⚠️ **Haiku 4.5's minimum cacheable prefix is 4,096 tokens.** Below the floor, caching **fails
silently** — no error, `cache_creation_input_tokens` just stays `0`. Floors are non-monotonic (512 on
Opus 5, 1,024 on Sonnet 5, 4,096 on Haiku 4.5), so this is not guessable. **Measure it.**

**Measured, and re-measured after every prompt edit** (`MEASURED_SYSTEM_TOKENS` in `prompt.py`, guarded
by a live `count_tokens` test):

| | Prefix | Margin over 4,096 |
|---|---|---|
| Phase 0c — 3 hardcoded facts | 511 | **−3,585** ❌ caching never engaged |
| Phase 1 — curated corpus | 4,415 | +319 |
| Phase 3 — refusal marker + conversion | 4,870 | +774 |
| Phase 6 — prompt **v1.3** (current) | **5,050** | **+954** |

The floor inverts the usual instinct: trimming the prompt *costs* ~6× here, because a cached turn is
$0.00120 against $0.00627 uncached. **Bump `SYSTEM_PROMPT_VERSION` on every change** — log lines from
two prompts are otherwise indistinguishable, which makes any before/after comparison impossible.

---

## Conventions

- **`app/llm/client.py` is the only file that imports `anthropic`.** That's what makes the model
  swappable.
- **Cost math needs four rates, not two:** input, output, cache-write (1.25× input), cache-read
  (0.1× input). Two-rate math is wrong the moment caching engages and makes the spend cap throttle on
  money never spent. An unpriced model **raises** rather than defaulting.
- **Log `user_message_redacted`, never the raw message.** **Retention: 7 days**, enforced by the
  rotation config — the config *is* the policy. The bot discusses Cadre's data-security posture; its
  own logging must not be the counterexample. (Rotation verified 2026-07-31; 7-day *deletion* needs
  the 8th day and remains unverified — say so rather than claiming "retention confirmed".)
- **Bound conversation history server-side** — 8 turns in the Pydantic model. The array arrives from
  the browser; don't trust the client.
- **Every log line carries `request_id`** — but *carry* it, don't read it from the ContextVar late.
  The middleware resets it before its own log call and before the exception handler, and `call_next`
  returns when headers are ready, so an SSE body is iterated after the reset.
- **Secrets:** API key server-side only. Never in the React bundle — Vite inlines anything prefixed
  `VITE_` at build time. `.env` is gitignored before the first commit.
- Styling: **plain CSS with custom properties** (`tokens.css` is the only file allowed a literal). No
  CSS-in-JS, no component kit. **All text is black** (`#0b0707`, Cadre's own); de-emphasise with size
  and weight, never a lighter grey. Errors keep `--cadre-red` — the one documented exception.
- Chat UI: shell in **`dvh`/`svh`, not `vh`** (iOS keyboard covers `vh`), input `font-size: 16px`
  minimum (less triggers iOS focus auto-zoom). **Fonts are self-hosted** — one deployable, no CDN.

---

## Verification

- **The golden set asserts properties, not strings.** The model is non-deterministic, so substring
  matching on prose gives false failures on correct behaviour. **Refusals are far more testable than
  answers** — an exact match on a closed enum beats any guess about wording.
- **`status` and `refusal_reason` ride on the `done` SSE frame, not only in the log** — the eval runs
  against the *deployed* URL, where `interactions.jsonl` is on a volume it cannot read.
- **14 cases:** 6 scenarios · 3 required refusals · 2 coverage · 2 multi-turn · **plus off-topic**,
  the one refusal that gets *no* `/contact` link, so edits aimed elsewhere break it silently.
- **Absence beats presence.** "Contains no dollar figure" survives rewording; "contains the word
  'individually'" breaks on the first synonym. An invented URL is tested by membership in the pages
  `content/raw/` proves were fetched — not by matching `/contact`, which fails correct citations.
- ⚠️ **Four times here a test asserted a substring where it meant a property** — `grey` matched its own
  explanatory comment, the URL check flagged a correct link then a bolded one, `open(` matched
  `urlopen(`, and the rotation check couldn't tell "broken" from "not yet triggered". **Name the
  property first, then find the expression for it.**
- Unit-test the knowledge layer, integration-test the API error path, assert
  `cache_read_input_tokens > 0` across two identical-prefix requests. **Don't test the LLM itself.**
- **Local green is weaker evidence than it feels.** Six defects here were found *only* on the deployed
  environment: missing `COPY content/`, the volume mount path, request-id plumbing, the limiter's
  bucketing, the woff2 mimetype, and a price anchor the eval passed locally.

---

## Out of scope — deliberately

Don't build these. Each is a recorded decision, with the trigger that would reverse it in `plan.md`.

**RAG / vector DB** (~4k stable tokens — prompt-stuffing plus a cached prefix is cheaper *and*
simpler; the eval confirmed every refusal is a designed boundary, not a coverage gap) · **auth /
real portal access** · **live CRM or booking** (link out) · **cross-session persistence** · **admin
CMS** · **i18n** · **voice** · **OTel/Prometheus/Grafana** (JSONL + `/stats` is the MVP tier) ·
**MCP on the request path** (retrieval over a corpus already in the prompt costs 2.6×/turn).

**And never:** invent pricing (or cite a case-study saving *beside* a cost question — the eval caught
that), invent a portal URL, summarize podcast content, or name a case-study client.

---

## Working agreement

**Repo:** `https://github.com/ecuartasm/cadre-chatbot` (private) · `origin` · `main`.

**Follow `plan.md` phase by phase, and run its eight-step exit checklist every time:** tests green →
exit criterion met → workflow log → phase report → **review the next phase against what this one
taught** → commit → push → redeploy and verify the live URL. `plan.md` has the full version.

- **The forward-review step earns its place.** It caught the Dockerfile never copying `content/` (a bot
  with no knowledge base, all local tests green), that Phase 4's stated scope was already built, and
  that MCP was absent from the brief entirely. Ask what this phase taught that changes the next one.

- **Two records per phase.** `docs/ai-workflow-log.md` is a terse four-field entry (asked for /
  produced / changed / verified); `reports/phase-<n>-report.md` is the narrative. Write both from the
  phase's own evidence — measured values, real hashes, actual counts — never from recollection, and
  write them *as you go*.
- **Push at the end of every phase.** Work that exists only locally isn't safe, and the repo *is* the
  deliverable. Don't batch phases into one push.
- ✅ **The gate is closed** — Phase 6 answered all six scenarios on the deployed URL, which gated MCP
  and observability P2. Both have now shipped behind it. Small commit messages naming the phase; never
  `git push --force`.
- **Check `git status` before every commit — read the staged list, not just the result.** Running
  `git add -A && git commit` in one breath swept a 9.5 MB PDF into history unnoticed. **Never commit a
  secret;** if a key is ever pushed, rotate it rather than removing the file in a later commit.
- When something in this file or `plan.md` looks wrong, say so and fix it rather than working around it.
  These two files are the contract, and a wrong contract should be corrected, not tolerated.
