# plan.md — Cadre AI Support Chatbot

Execution plan. Phases run in order and every phase ends with the same checklist — see below.

Conventions and non-negotiable rules live in `CLAUDE.md`. This file holds **sequence, scope decisions,
and the open items**.

**Repo:** `https://github.com/ecuartasm/cadre-chatbot` (private) · remote `origin` · branch `main`.

---

## Phase exit checklist — every phase, no exceptions

A phase is not done until all seven are true. This is the loop, not a formality.

1. **Tests green** — `pytest`, plus `python eval/golden.py` once the eval exists (Phase 6 onward).
2. **The phase's own exit criterion met** (stated per phase below).
3. **`docs/ai-workflow-log.md` appended** — one entry: *phase / what I asked for / what Claude produced
   / what I changed and why*. Write it now, not later.
4. **`reports/phase-<n>-report.md` written** — the detailed record of the phase: what shipped, the
   decisions and their reasoning, problems hit and how they were resolved, verification evidence with
   real numbers, what was deliberately deferred, and what comes next. The workflow log is a terse
   four-field entry; the report is the narrative a reader can reconstruct the phase from.
5. **Commit** with a descriptive message naming the phase. Small and specific beats one big commit.
6. **Push to `origin main`.** Work that only exists locally isn't safe, and the repo is the deliverable.
7. **Redeploy and verify the live URL** (every phase from 0c onward, since that's when a deployable bot
   first exists). A green local build that's broken in production is not a finished phase.

⚠️ **Do this deliberately, not automatically.** It's tempting to wire steps 5–6 into a Claude Code
`Stop` hook, but there is no "phase finished" event to hook — `Stop` fires after *every* assistant
turn, so it would produce dozens of commits per phase with generated messages, which is the opposite of
"small, frequent commits with descriptive messages." Worse, an auto-push can publish a broken
intermediate state or a secret before `.gitignore` is right. **A `/ship-phase` command that runs this
checklist on demand is the correct mechanism; a hook is not.** Hooks are for guardrails (block writes to
`.env`, block `git push --force`), not for taking outward-facing actions on your behalf.

---

## The thesis in four lines

1. The corpus is small and stable, so **stuff it into the system prompt with a cached prefix** — no RAG.
2. **Scrape once, commit, serve statically.** The running app never searches the web.
3. **The boundary is the product.** Refusals get built first, and they're structural (a `disclosure`
   field), not just prompt wording.
4. **Ship a working bot at ~hour 2, then deepen it.** Never build a layer with nothing calling it.

---

## Scope: in

| In scope | Why |
|---|---|
| Single-page chat UI, streaming, mobile-usable, on-brand via CSS tokens | The minimum bar is a bot a real client could plausibly use |
| `POST /api/chat` — SSE stream, curated KB in a cached system prompt | The core |
| Curated KB covering the six scenarios + explicit negative knowledge | The corpus *is* the product |
| Grounded refusals → `/contact`, encoded as data (`disclosure`) | Scenario 6, and the differentiator |
| One clear CTA: book a strategy call | The bot exists for lead capture, not just Q&A |
| Error handling: timeout, retry, rate limit, empty response, safe fallback | A public URL with a billed key |
| Observability P0+P1+P2: structured JSON → stdout + rotating JSONL, error tracking with stack traces, per-turn tokens/cost, `/api/stats` | Answers "what does a turn cost?" and "why did it fail on the host but not locally?" — both real questions here |
| Per-IP rate limit + hard daily spend cap | Public URL, real billed key, live from day one |
| 13-case golden-set eval | Cheapest meaningful test of a non-deterministic feature |
| Committed `curl` scraper | Must be re-runnable for corpus maintenance |
| MCP layer (one pattern, one tool) | Deliberate extension — **built last, behind the gate** |

## Scope: out — and the trigger that would reverse each

| Cut | Why | What would change my mind |
|---|---|---|
| **RAG / vector DB / embeddings** | Corpus is ~2–4k tokens and stable. RAG adds infra, latency, an embedding step, and a whole failure surface (chunking, retrieval precision) for negative benefit at this size. Prompt-stuffing with a cached prefix is cheaper *and* simpler. | Curated context stops fitting comfortably in the prompt, **or** answer precision degrades because too much irrelevant context is injected. Then: keyword/section selection first, embeddings only if that isn't enough. |
| **Auth / real portal access** | The bot *explains how* to reach the portal; implementing it is a different product. | Never, for this brief. |
| **Live CRM / calendar booking** | Link out. Scheduling integration is out of proportion to the value. | The bot needs to take a real *action* — which is also the trigger for tool-use generally. |
| **Cross-session chat persistence** | In-memory per-session is enough. Named as a scaling step: Postgres keyed by conversation. | Users need to resume conversations, or analytics needs history. |
| **Multi-agent orchestration** | Overkill for FAQ-shaped support. | — |
| **Admin CMS for the KB** | It's a markdown file in git. That's better for an MVP: diffable, reviewable, revertable. | Non-technical staff need to edit it. |
| **i18n / voice / analytics dashboards** | Named and dropped. English only. | — |
| **OTel / Prometheus / Grafana** | JSONL + `/stats` is right at this size. | Logs outgrow flat files. |
| **Real pricing numbers** | Not public, engagement-specific. Inventing one is the single worst failure available. | Cadre publishes pricing. |

---

## Phases

Estimates are for **sequencing and risk-ordering, not rationing** — build time is not a constraint
here. Total ≈9–11.5h before debugging and deploy retries.

### Phase 0a — Deploy skeleton · 30 min
✅ **Already done:** `git init`, `.gitignore` (`.env` excluded before the first commit), private repo
`ecuartasm/cadre-chatbot` created and pushed.

Remaining: `uv`/requirements, hello-world FastAPI, deploy to Railway, attach the Volume, run `/init` and
rewrite what it generates, commit `.claude/settings.json`, create `docs/ai-workflow-log.md`.
**Exit:** the public Railway URL returns 200, and the exit checklist above passes.

### Phase 0b — `CLAUDE.md` + `plan.md` · 60 min, protected
✅ **Done** — both written and pushed (commit `d86f9f6`). **Deliberately separated from the deploy** so a
Railway snag couldn't eat the time for the two documents the brief asks for by name.
Revisit at the end of Phase 6 to tighten, not to rewrite.

### Phase 0c — End-to-end vertical slice · 45–60 min ⭐
Three hardcoded facts → minimal system prompt → streaming `POST /api/chat` → unstyled React chat box →
**deployed and answering questions on the public URL.**

This is the most important phase in the plan. It proves the riskiest unknown — **SSE streaming through
Railway to a React client** — at hour two instead of hour five, and from here on a stop at any point
leaves something that works.
**Exit:** you can type a question into the deployed URL and watch tokens stream back. Then the checklist.

### Phase 1 — Knowledge base · 60–75 min
0. **Resolve the open gate below, first.**
1. Write + run `scripts/scrape.py` → `content/raw/*.md` with `url`/`title`/`date`/**`content_sha256`**
   frontmatter. Check `robots.txt` and `/terms-of-service`; polite delay; real user-agent. Podcasts:
   **landing pages only, metadata only, no transcription.**
2. Hand-curate `content/knowledge-base.md` around the six scenarios. **Count the tokens.**
3. Encode negative knowledge via `disclosure` / `refusal_reason` — not prose.
4. Ship `.claude/agents/kb-updater.md` + `.claude/commands/update-kb.md`.

Scrape and curate are separable → **run the scrape as a subagent** while curating. It's context-heavy
input with a small output, which is exactly what subagents are for. Same agent becomes `kb-updater`.
**Exit:** the slice's hardcoded facts are replaced by the real KB and `/update-kb` proposes a diff
without writing it. Then the checklist.

### Phase 2 — Observability P0+P1 · 45–60 min
`request_id` middleware · JSON logger dual-sunk to stdout + rotating JSONL (redaction on, **7-day**
retention in the handler config) · **four-rate** price table + cost helper · per-IP rate limit with a
real `key_func` · daily spend cap checked **before** the model call · exception handler returning a
safe fallback, never a stack trace.

⚠️ **The rate limit needs a custom `key_func`.** `slowapi`'s default reads `request.client.host`, which
behind Railway's router is *the router* — so every visitor shares one bucket and the first scraper locks
out everyone. Read the left-most `X-Forwarded-For` entry, fall back to `request.client.host`. Note that
a forwarded header is spoofable, which is why the **daily cap is the real money backstop.**
**Exit:** write a log line, redeploy, confirm it survived — the volume-persistence check lives here, not
in Phase 0, because only now is there something real to write. Then the checklist.

### Phase 3 — System prompt · 30–45 min
Persona · grounding rule · escalation policy driven by `disclosure` · conversion behavior · format
rules · anti-hallucination guardrails. Own versioned module. **Frozen** — no timestamps or ids.

⚠️ **Then measure the cache prefix and decide.** Run `count_tokens` over the assembled system block
and record the number here in `plan.md`:

> **Measured system-prompt + KB tokens: `___`** (fill in during Phase 3)
> - **≥ 4,096** → caching engages on Haiku 4.5. Assert it and move on.
> - **< 4,096** → either grow the curated KB to ~4.5k so the prefix clears the floor, **or** accept no
>   caching as a stated decision with the number attached. Both defensible; assuming is not.

**Exit:** the number is written down here and the branch is taken deliberately. Then the checklist.

### Phase 4 — Chat API + LLM client · 60–75 min
SSE endpoint · provider behind the one-file interface · prompt assembly with `cache_control` on the last
system block · server-side history cap in the Pydantic model · full error handling wired into
observability (tokens, cost, latency, cache counters per turn). Read the generated code; add the tests.
**Exit:** `cache_read_input_tokens > 0` on the second identical-prefix request. Then the checklist.

### Phase 5 — React chat UI · 60–75 min
Message list · streaming render · input · error states · single booking CTA. Extract real design tokens
from cadreai.com via DevTools (**computed styles — not an AI page fetch**, which can't see them) into
`tokens.css` custom properties; components consume the variables, never literals. `dvh`/`svh` for the
shell, 16px minimum input font.
**Exit:** usable on a phone, streaming visible, CTA present. Then the checklist.

### Phase 6 — Eval + P2 + polish · 60–75 min
The 13-case golden set (properties, not strings) · split the JSONL streams · build `/api/stats` · test
**on the deployed URL** · confirm logs land on the volume · tighten both documents.
**Exit:** eval green against the deployed URL, per-case results recorded below. Then the checklist.

### 🚦 GATE — before Phase 7 or observability P2 extras
**The bot must answer all six scenarios on the public URL.** If it doesn't, finish the core: MCP drops
and observability stops at P1, regardless of remaining time. Within P2 the cut order is rollups →
file-split → **`/stats` last** (it's the only part that makes the layer usable without SSHing in to grep
JSONL, and it's what Phase 8 reads).

### Phase 7 — MCP integration · 60–90 min
One pattern, one tool: **bot as MCP client**, exposing `search_cadre_knowledge(query)`. Decide the
transport (ASGI sub-app vs. second process) **before starting**, not mid-build. Wire tool calls into
observability so the logs capture agentic steps.

Be honest about what this is: for a 2–4k-token corpus, tool-based retrieval is **a demonstration of the
mechanism, not a performance need** — prompt-stuffing stays simpler and more deterministic. It's the
same design fork as the RAG cut, reached from the other side.

### Phase 8 — Post-submission health check · 15 min
The public URL sits unattended with a live billed key for ≥24h after submission. Re-hit it, read
`/api/stats` for error rate and spend-to-date, confirm the Railway service and volume are still
attached, confirm the daily cap has headroom.

---

## 🔴 Open gate — resolve at the top of Phase 1

**Do not curate any case-study client or individual name until this is settled.**

The two research documents in `analysis/` disagree with each other. One states the rule *"clients are
anonymized as 'Non-Disclosed Company'"*; the other names a specific client and CEO for the same case
study. A live spot-check found the named person is real and the match is plausible — but **three
captures of that page produced three different attribution strings**, and the page was never read
byte-faithfully.

**Action:** scrape `/case-studies` with the real scraper and read the literal text. Then:
- Anonymized on the page → strip every name; present outcomes and metrics only.
- Genuinely named → keep the exact on-page wording, nothing inferred.

Metrics are always *reported past results*, never guarantees or projections. Note also that the case
count itself is unconfirmed (one source says 8, another 9) — take it from the scrape.

**Why this is a gate and not a nice-to-have:** every other refusal in this project is a *silence*.
This one would be an *assertion* — a specific, checkable, false claim about a real company. That is the
worst failure the bot can produce.

---

## Verification log

Fill in during Phases 3 and 6.

| Case | Asserts | Result |
|---|---|---|
| 1 · What Cadre does / industries | grounding present | |
| 2 · Book a call | `/contact` present, CTA | |
| 3 · Portal access | acknowledges, **no invented URL** | |
| 4 · AI Maturity Index | grounding present | |
| 5a · LLM selection | grounding present | |
| 5b · Data security | general answer + routes specifics | |
| 6 · Unanswerable | refuses, routes | |
| R1 · Pricing | **no number**, `refusal_reason` | |
| R2 · Portal login | **no URL**, `refusal_reason` | |
| R3 · Podcast content | **no quote/summary**, `refusal_reason` | |
| C1 · How to get started | grounding present | |
| C2 · Case studies | **no client name** while gate open | |
| M1 · Anaphora follow-up | resolves referent | |
| M2 · Refusal then pushback | **holds the refusal** | |
| — · Prompt cache | `cache_read_input_tokens > 0` | |

---

## Known limitations

Written down deliberately rather than discovered later.

- **The corpus is a snapshot.** It does not track cadreai.com. `kb-updater` + `/update-kb` is the
  maintenance path, and it **proposes** — it never auto-merges. That constraint comes from this
  project's own history: the disputed attribution above originated in an unreviewed AI research pass.
  An unattended agent committing to `knowledge-base.md` is that same failure, automated.
- **Prompt injection is mitigated, not solved.** The KB lives in `system` and user text only ever
  appears in a `user` turn; the boundary is phrased as a fact about the bot ("you have no pricing
  information") rather than an instruction ("don't reveal pricing"), which is harder to argue out of.
  Two eval cases probe it. A determined attacker may still get the persona to slip.
- **Scenario 5b (data security) is a labeled, general answer**, not a sourced one — the only public
  source is a generic privacy policy, which doesn't answer what a B2B buyer means by the question.
  Specifics route to `/contact`. This is a deliberate downgrade, not an oversight.
- **In-memory state:** the daily spend counter and conversation history reset on redeploy. Acceptable
  for this deployment, and stated rather than hidden.
- **Single worker** — the in-process rate limiter and spend counter assume it. Redis if that changes.
