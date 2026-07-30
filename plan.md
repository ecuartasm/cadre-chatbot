# plan.md — Cadre AI Support Chatbot

Execution plan. Phases run in order and every phase ends with the same checklist — see below.

Conventions and non-negotiable rules live in `CLAUDE.md`. This file holds **sequence, scope decisions,
and the open items**.

**Repo:** `https://github.com/ecuartasm/cadre-chatbot` (private) · remote `origin` · branch `main`.

---

## Phase exit checklist — every phase, no exceptions

A phase is not done until all eight are true. This is the loop, not a formality.

1. **Tests green** — `pytest`, plus `python eval/golden.py` once the eval exists (Phase 6 onward).
2. **The phase's own exit criterion met** (stated per phase below).
3. **`docs/ai-workflow-log.md` appended** — one entry: *phase / what I asked for / what Claude produced
   / what I changed and why*. Write it now, not later.
4. **`reports/phase-<n>-report.md` written** — the detailed record of the phase: what shipped, the
   decisions and their reasoning, problems hit and how they were resolved, verification evidence with
   real numbers, what was deliberately deferred, and what comes next. The workflow log is a terse
   four-field entry; the report is the narrative a reader can reconstruct the phase from.
5. **Review the *next* phase against what this one just taught, and edit it in this file.** Not a
   formality — Phase 0's review found a missing `COPY content/` that would have shipped a bot with no
   knowledge base, and turned a vague "~2–4k token" target into a measured floor of 3,702. Ask: does
   anything I just learned change the next phase's scope, ordering, or numbers? Did this phase absorb
   work the next one still claims? Did it invalidate an assumption downstream? Write the adjustment
   into the phase itself, and record the reasoning in the report.
6. **Commit** with a descriptive message naming the phase. Small and specific beats one big commit.
7. **Push to `origin main`.** Work that only exists locally isn't safe, and the repo is the deliverable.
8. **Redeploy and verify the live URL** (every phase from 0c onward, since that's when a deployable bot
   first exists). A green local build that's broken in production is not a finished phase.

⚠️ **Do this deliberately, not automatically.** It's tempting to wire steps 6–7 into a Claude Code
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

### Phase 1 — Knowledge base · 75–95 min  *(revised after Phase 0 — see §"Phase 1 revisions")*
0. **Resolve the open gate below, first.**
1. **⚠️ Add `COPY content/ ./content/` to the Dockerfile — before anything else.** The runtime image
   currently copies only `app/` and `web/dist`. Without this line the corpus works locally and the
   deployed bot has **no knowledge base at all**: a production-only failure, invisible in every local
   test. (`scripts/` stays uncopied on purpose — the scraper is build-time tooling and has no business
   in the runtime image.)
2. Write + run `scripts/scrape.py` → `content/raw/*.md` with `url`/`title`/`date`/**`content_sha256`**
   frontmatter. Check `robots.txt` and `/terms-of-service`; polite delay; real user-agent. Podcasts:
   **landing pages only, metadata only, no transcription.**
3. Hand-curate `content/knowledge-base.md` around the six scenarios.
   **⚠️ Target 3,700–4,300 tokens — not the old "~2–4k".** Measured in Phase 0: the fixed prompt
   scaffolding (persona + grounding + boundary + format) is **394 tokens**, and Haiku 4.5's cache floor
   is **4,096**, so the KB must supply **≥3,702 tokens** or prompt caching silently never engages. A 2k
   KB would land at ~2.4k and quietly cost ~10× more per turn forever. Aim ~4,000 for margin without
   padding for its own sake — if the honest corpus comes in short, that is a finding to record, not a
   reason to pad.
4. Encode negative knowledge via `disclosure` / `refusal_reason` — not prose.
5. **Add `app/knowledge/loader.py`** — the knowledge-layer seam `CLAUDE.md` already names. Reads and
   validates the curated file **once at import/startup, never per request.** Re-reading per request
   would risk a byte-different prefix and silently kill the cache.
6. Ship `.claude/agents/kb-updater.md` + `.claude/commands/update-kb.md`.
7. **Update the Phase 0c tests that assert on the hardcoded facts** — `test_boundary_rules_are_present_in_the_prompt`
   and the byte-stability test. Byte-stability matters *more* now that the prompt is file-backed.
8. **Smoke-check the three required refusals against the deployed bot** (pricing, portal login, podcast
   content) — pulled forward from Phase 6. Phase 0 verified three behaviors by hand in one command; a
   real corpus multiplies what can regress, and these three assert *absence*, which is the cheapest
   thing to check reliably. The full 13-case golden set stays in Phase 6.
9. **Record the measured numbers** in the table under Phase 3 — the cache measurement now happens here,
   for free, because this is where the KB lands.

Scrape and curate are separable → **run the scrape as a subagent** while curating. Phase 0 confirmed the
shape of the argument: ~35+ pages of HTML in, a small curated file out — context-heavy input with a
small output is exactly what subagents are for. Same agent becomes `kb-updater`.

**Exit:** the slice's hardcoded facts are replaced by the real corpus, the deployed bot answers from it,
`cache_read_input_tokens > 0` on a second identical-prefix request, the three refusals hold, and
`/update-kb` proposes a diff without writing it. Then the checklist.

### Phase 2 — Observability P0+P1 · 75–95 min  *(re-analysed after Phase 1 — was 45–60)*

The estimate grew because the analysis below found two failure modes the original three-line spec would
have shipped: a container that cannot write to its own log volume, and a cost tracker blind to abandoned
streams. Both are silent. That is now this project's recurring theme — the cache floor, the missing
`COPY content/`, and a skipped test were all silent — so each item below names how it fails *loudly*.

#### 2.1 🔴 First: the volume, and the permission collision

**Decided 2026-07-29: attach the volume and build P0+P1 as specified.** The paid-infrastructure
deferral from earlier is lifted for this specifically — log storage is a few MB, and deferring it would
push the permission collision below to the end of the build, which is the late-discovery pattern this
project keeps getting caught by. `USER root` fallback is a judgement call to be made on first deploy and
recorded, not escalated.

`railway volume add -m /data` — the mount path is ours to choose, so `LOG_DIR=/data/logs` is fine.
**But a volume mounts at runtime and shadows whatever the image had at that path, and a fresh mount is
`root:root`.** The container runs as `appuser` (uid 10001, chosen deliberately in Phase 0c), so it
**cannot write to `/data`**. Logging handlers routinely swallow I/O errors, so the likely symptom is not
a crash — it is an empty log directory nobody notices.

Resolution, in order of preference:
1. **Root entrypoint that fixes ownership, then drops privileges.** `chown -R appuser /data/logs` as
   root, then `exec` uvicorn as `appuser`. Verify which tool exists in `python:3.12-slim` —
   `setpriv`/`runuser` (util-linux) are likely, `gosu` is not installed. **Verify on deploy; do not
   assume.**
2. If no privilege-drop tool is available, `USER root` with a one-line comment stating the trade-off is
   better than a silently unwritable volume. Say which was chosen and why.

**Fail loudly:** at startup, write-test `LOG_DIR` and **raise** if it fails — same pattern as the corpus
loader. An observability layer that cannot observe must not boot quietly.

#### 2.2 🔴 Abandoned streams are invisible to cost tracking

`usage` only arrives at the **end** of a stream (`get_final_message()`). If the browser disconnects
mid-answer — user closes the tab, navigates away, loses signal — that turn produces **no usage, no log
line, and no cost counted** while Anthropic still bills the tokens generated. On a public URL that is
both a cost leak and a hole in the numbers.

**Required:** wrap the generator so a `GeneratorExit`/`CancelledError` writes an `InteractionLog` with
`status: 'abandoned'`, the deltas counted so far, and `usage: partial`. Estimate output tokens from
accumulated text via `count_tokens` rather than recording zero. Add a test that cancels a stream
mid-flight and asserts a log line was still written.

#### 2.3 Where the daily spend counter lives — a decision, not a default

An in-memory counter resets on every container restart, and Railway restarts containers. A cap that
resets silently is not a cap. **Persist it to the volume** as a small JSON file
(`/data/logs/spend.json`: `{date, total_usd, turns}`), reloaded at startup, rewritten per turn. The
volume exists for exactly this. State the single-worker assumption in a comment — concurrent writers
would need a lock, and §2.1's single worker is what makes the simple version correct.

#### 2.4 Four-rate price table, with real numbers to test against

Phase 0 measured `cache_read=0`, so a two-rate table would have looked correct. Phase 1 production shows
a **4,409-token cache write on call 1 and a 4,409-token read on call 2**:

| Rate | Multiplier | Haiku 4.5 |
|---|---|---|
| input | 1× | $1.00 / MTok |
| output | — | $5.00 / MTok |
| cache **write** | 1.25× input | $1.25 / MTok |
| cache **read** | 0.1× input | $0.10 / MTok |

Measured: **$0.00119/turn cached · $0.00516 uncached · $0.00551 on a cache-write turn.**

⚠️ **Budget against the *write* cost, not the read cost.** The cache TTL is 5 minutes, so on a
low-traffic demo most turns are the first of a fresh window — i.e. writes, the *most* expensive case.
The cheap $0.00119 figure only dominates under sustained traffic. Test: a cached turn must cost ~4×
less than an uncached one, computed from the table with no API call.

#### 2.5 Size the cap from the measurement, not a round number

`DAILY_COST_CAP_USD=5.00` was set arbitrarily in Phase 0. At the worst-case $0.00551/turn that is
**~900 turns/day**; at the cached rate, ~4,200. Keep $5 — generous for a demo, and a real ceiling
against a scraper — but put that arithmetic in a comment so the number is a decision.

#### 2.6 Errors must be SSE frames, not bare HTTP status codes

The endpoint returns `text/event-stream`. A `429` or a cap-exceeded `503` returns JSON instead, and the
Phase 0c frontend's `if (!res.ok) throw` turns that into *"Couldn't reach the server (HTTP 429)."*
Technically correct, useless to a user.

**Required:** rate-limit and cap rejections return **200 with a single SSE `{"type":"error"}` frame**
naming which limit was hit ("I'm at capacity for today" vs "too many requests, try in a minute"). The
frontend already renders error frames — no UI change needed, which is why this is cheap.

#### 2.7 Keep blocking file I/O off the event loop

`RotatingFileHandler` does synchronous writes; called from an async handler it blocks the loop on every
line and on every rotation. Use stdlib **`QueueHandler` + `QueueListener`**: the request thread enqueues,
a background thread writes. ~10 lines, no dependency.

#### 2.8 Surface `request_id` and log health

- Return `request_id` in the SSE `done` frame and as a response header, so a user reporting a bad answer
  can quote something greppable.
- Extend `/health` with `log_sink_writable` and `spend_today_usd`. A broken volume then shows up in the
  probe instead of requiring a shell.

#### 2.9 Implementation notes

- **stdlib `logging` + a small JSON formatter, not `structlog`.** ~20 lines against a new dependency;
  runtime deps stay at 4.
- **Redaction is a tested pure function** — email and phone patterns — not an inline regex at the call site.
- **All Phase 2 tests run offline.** Inject a fake clock and a fake counter; assert on the price table
  arithmetic rather than a live call. Phase 1 found a key-dependent test skipping silently, and CI
  without a key would repeat that.
- Retention stays **7 days**, enforced by `TimedRotatingFileHandler(when="D", backupCount=7)` — the
  config *is* the policy.

**Exit:** volume attached and **write-verified from inside the running container** · a log line survives
a redeploy · `/health` reports `log_sink_writable: true` · an abandoned stream still produces a log line ·
cached and uncached turns cost what the table predicts · a 429 arrives as a readable SSE error frame.
Then the checklist.

### Phase 3 — System prompt refinement · 45–70 min  *(re-estimated after Phase 2 — see below)*
Phase 0c already shipped `app/llm/prompt.py` versioned, frozen, and sectioned: persona · grounding ·
refusal boundary · format rules, with the `cache_control` breakpoint attached. **What is left is only
what 0c did not need:**

- **Make refusals structural, not just prose.** *Decision taken before the phase: the model emits a
  machine-readable marker; the server parses it.* Three mechanisms were weighed — a marker, a second
  classification call, and a heuristic over the answer text. The marker wins: ~10 extra output tokens
  against a second billed call (+13%/turn) or a substring match over prose, which CLAUDE.md's own
  verification rule already rules out as untrustworthy.

  Concretely:
  - The prompt instructs: open a refusal with `[[refusal:<slug>]]` and nothing before it.
  - `stream_reply` buffers the leading bytes until the marker either matches or provably cannot,
    sets `status="refused"` and `refusal_reason`, and **strips the marker before the first delta
    reaches the client.** The marker must never appear in the UI — assert this in a test, because it
    is the one failure a user would actually see.
  - **A missing marker must not be read as "not a refusal."** The model will sometimes forget. When
    the marker is absent the turn logs `status="ok"` and `refusal_reason=null` as it does today, so
    the metric under-reports rather than mislabels — and the gap is greppable via the `/contact`
    link. Stated here so the number is read correctly rather than trusted blindly.
  - Cost of the buffer: a few tens of bytes of first-chunk delay. Measure the TTFT effect and record
    it in the table below; if it is visible, that is a real trade to name, not to hide.

- **Validate the reason vocabulary against the corpus — do not author a new list.** The corpus's
  NEGATIVE KNOWLEDGE table is already the authoritative set of **15** slugs, plus `off-topic`
  documented separately in "How to refuse" = **16**. `loader.py` currently asserts only 3 of them in
  `REQUIRED_MARKERS`. Parse the table's `refusal_reason` column at load time and treat it as the
  closed enum, so a slug the model invents is rejected rather than silently written to the log. This
  is the ordinary case of the project's rule that the corpus is the source of truth: a hand-copied
  list in Python would be a second place for the vocabulary to drift.

- **Conversion behavior** — guide toward booking a strategy call where it is natural, without being
  pushy. Deliberately absent from 0c so the slice couldn't be accused of being a lead-gen funnel before
  it could answer anything.
- Re-verify byte-stability and re-measure after the edits.

**Why the estimate tripled from 15–25 min.** The original figure covered prompt prose only. It now
includes marker parsing in the streaming path, the leak test, the enum validation in the loader, and
the conversion section. On the Phase 2 precedent (45–60 estimated, ~95 actual) the honest range is
45–70.

**Measurements — the open question here was answered in Phase 1:**

| Metric | Phase 0c (3 hardcoded facts) | After Phase 1 corpus | After Phase 3 | Floor / target |
|---|---|---|---|---|
| Fixed scaffolding | 394 tokens | 387 tokens | 842 tokens | — |
| Curated KB | 124 tokens | **4,028** tokens | 4,028 tokens | ≥3,702 |
| **Full system block** | **511 tokens** | **4,415** tokens | **4,870** tokens | **≥4,096** |
| `cache_read_input_tokens` (2nd call) | **0** ❌ | **4,409** ✅ | **4,807** ✅ | `>0` |
| Time to first token — answer | 0.74s | — | **0.85s** | — |
| Time to first token — refusal | — | — | **1.11s** | — |

The two TTFT rows are the marker's cost, measured rather than assumed. A refusal is ~0.26s slower
to first visible character because the model emits ~10 marker tokens before any prose. That is
inherent to a marker approach, not scanner overhead — the buffer only holds while those tokens are
being produced, and an answer (no marker) releases on the first character. Accepted: a quarter of a
second on the refusal path buys a refusal metric that does not depend on matching substrings in
prose.

The branch was taken in Phase 1: the corpus was grown past the floor with real content (nine
per-industry value propositions scenario 1 needed and lacked), not padding, clearing 4,096 by 319
tokens. Caching is live and verified in production. **Phase 3 therefore re-verifies rather than
discovers** — the only cell left is time-to-first-token, which is cheap to fill during the phase's own
verification pass.

**Forward review after Phase 2 — three things changed:**

1. **Prompt edits are now measurable instead of eyeballed.** `interactions.jsonl` records token counts,
   cache write/read split, cost, latency, and `stop_reason` per turn. So the working loop for this
   phase is *edit → send the probes → read the log*, not *edit → read the answers and form an
   impression*. A boundary that got looser shows up as fewer refusals; a prompt that grew shows up as a
   larger `total_prompt_tokens` — both readable, neither guessed.

   **To be exact about what "the probes" means: there is no runner yet.** `eval/` does not exist, and
   the 13-case golden set is Phase 6 (see step 1 of the checklist, and the Phase 6 scope line). Phase 3
   sends the six scenarios plus the three required refusals **by hand** against a local server and reads
   `interactions.jsonl`. That is enough to tune a prompt and is honest about what it is; it is not a
   regression suite, and Phase 3 must not be recorded as if it had one.

2. **`refusal_reason` is emitted on every interaction line and never set — it is always `null`.**
   Verified in the production log: `refusal_reason=null` on a real turn. `_guard_frame` sets it on the
   separate `turn_rejected` line, but that covers rate-limit and spend-cap rejections, not a
   knowledge-boundary refusal. `status` has the same hole: `'refused'` is listed as a valid value in
   `cost.py` but is only ever set to `ok`/`error`/`abandoned`.

   So the one metric this phase most needs in order to tune the boundary — *how often does the bot
   refuse, and for which reason* — is not measurable yet, which is why the marker decision moved into
   this phase's first bullet rather than staying an afterthought. Without it, "refusals are structural"
   is a claim about the prompt with no evidence behind it.

3. **Two hard constraints inherited from Phase 2, both silent if violated:**
   - The system prefix must stay **≥ 4,096 tokens**. Trimming prose during refinement is exactly the
     edit that would slip under it, and caching then stops with **no error** — cost quietly rises ~6×.
     The Phase 1 floor test guards this; run it after *every* prompt edit, not once at the end.
   - **`SYSTEM_PROMPT_VERSION` must be bumped on every change.** Log lines from two different prompts
     are otherwise indistinguishable, which makes the before/after comparison in point 1 impossible.
     Any change to the prompt also invalidates the cached prefix, so expect the first turn after a
     deploy to bill a cache **write** ($0.00627, not $0.00120) — that is normal, not a regression.

**Exit:**

- `status="refused"` and a `refusal_reason` from the closed 16-slug enum appear in `interactions.jsonl`
  for each of the three required refusals.
- **The `[[refusal:…]]` marker appears nowhere in the streamed output** — asserted by a test, since this
  is the only failure in the phase a user would see directly.
- A slug outside the enum is rejected rather than logged.
- **Off-topic behaves as the documented exception:** a one-line decline, naming what the bot *can* help
  with, **no `/contact` link**, logged as `refusal_reason: off-topic`. It is the only refusal that does
  not route, so it is the one most likely to be got wrong by a prompt edit aimed at the other fifteen.
- Conversion behaviour present without being pushy.
- Prefix re-measured **≥ 4,096** and `cache_read > 0` still true after every edit.
- `SYSTEM_PROMPT_VERSION` bumped; the TTFT cell filled, including any cost of the marker buffer.

Then the checklist.

### Phase 4 — Multi-turn behaviour · 30–40 min  *(rewritten — original scope already shipped)*

**Forward review after Phase 3: every line of this phase's original scope is already built and
verified, and so is its exit criterion.** Checked against the repo rather than assumed:

| Original scope | Where it actually shipped |
|---|---|
| SSE endpoint | Phase 0c, rewritten in Phase 2 |
| Provider behind the one-file interface | `app/llm/client.py`, still the only `anthropic` importer |
| `cache_control` on the last system block | Phase 0c; re-measured in 1 and 3 |
| Server-side history cap in the Pydantic model | Phase 2 — `MAX_TURNS = 8` |
| Error handling wired into observability | Phase 2 — tokens, cost, latency, cache counters per turn |
| **Exit:** `cache_read > 0` on the 2nd identical-prefix request | Verified in Phases 1, 2 **and** 3 (`cache_read=4807`) |

Executing it as written would be theatre. What the phase name promised but never covered is
**multi-turn**, and there the coverage is zero: no test sends a prior assistant turn, and nothing
exercises anaphora or pushback. That is the real gap, and it is the more interesting one.

- **Anaphora.** "Do you work with construction?" → "What does that look like?" The second question is
  meaningless without the first, and history arrives from the client — so this exercises the bound in
  `ChatRequest` as well as the model.
- **Refusal-then-pushback.** The highest-value untested behaviour in the product: after a refusal,
  "come on, just a ballpark" / "I won't hold you to it". A boundary that holds once and folds under
  mild social pressure is not a boundary, and Phase 3's marker now makes the second turn's outcome
  *measurable* — the pushback turn should log `refused` with the same reason, not `ok`.
- **Error taxonomy with the scanner in the path.** One small hole found while writing Phase 3: if the
  stream raises while `MarkerScanner` is holding bytes, `finish()` is never reached and the held text
  is dropped. Bounded at 64 characters and the user sees the error frame regardless, so it is close to
  harmless — but it should be a deliberate decision rather than an accident.

**Exit:** an anaphora follow-up resolves correctly against bounded history · a refusal survives at
least two rounds of pushback, with the second turn logging `status="refused"` and the same
`refusal_reason` · the scanner's behaviour on a mid-hold stream error is decided and tested. Then the
checklist.

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

## ✅ Gate RESOLVED — 2026-07-29, Phase 1

**Method:** `content/raw/case-studies.md`, fetched by the committed scraper. Literal on-page text,
not an AI-mediated summary. Content hash `65b6b8ed31…`.

**Findings — all three prior claims were wrong in some way:**

| Question | Answer from the page |
|---|---|
| Are clients anonymised? | **Yes — 8 occurrences of `Non-Disclosed Company`.** No client company is named anywhere. |
| Are individuals named? | **Yes.** Zac Davis · Bridget Hirsch · Jennifer · Bryce Baker · Bill Lyons, each after a quote, with a role (e.g. "CEO & Founder"). |
| Is it "Bill Lyons, CEO, Griffin Funding"? | **No. "Griffin Funding" appears zero times.** The company name was fabricated somewhere in the research chain. |
| How many case studies? | **8**, not 9. |

**Consequences for curation:**

1. **The corpus names no client company.** There is nothing to name — every one is "Non-Disclosed
   Company". That is now a *fact about the page*, not a cautious assumption.
2. **Individual names + roles may be quoted verbatim** if a testimonial is used, because they are
   literally on a public page. Prefer omitting them: no scenario asks who said what, and a name is
   the highest-cost thing to get wrong. **Never pair a name with a company** — that pairing is exactly
   the fabrication found here.
3. **Say 8 if asked.** Take metrics from the page, framed as reported past results.

**The methodology lesson, worth more than the finding.** The chain was: research asserted a
name+company → adversarial review noticed an apparent self-contradiction and "corrected" the *right*
line → a web search confirmed Bill Lyons really is Griffin Funding's CEO, which made the fabricated
pairing look *verified*. **The external corroboration succeeded while validating a claim the source
never made.** Only reading the literal page settled it. This is the argument for the byte-faithful
scraper, stated in a way no abstract reasoning about provenance could have produced.

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
