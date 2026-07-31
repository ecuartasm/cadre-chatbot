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

**One correction to the above, from a closer audit.** The *transport* for multi-turn is fine and
already tested: `test_history_is_capped_server_side` sends 100 messages and asserts the Pydantic model
keeps the last 16, and `web/src/App.jsx` posts the full array (`{ messages: next }`). What is untested
is everything downstream of that — whether the **model** uses the history correctly, and how the
Phase 3 marker behaves across turns. Those are different things, and only the second is open.

#### 4.1 The marker is missing from history — the finding that matters most

The client accumulates only `delta` text into the assistant turn, and the marker is stripped
server-side. So on a pushback turn the model is shown **its own previous refusal with no tag on it**:

```
user:      How much does an engagement cost?
assistant: Cadre doesn't publish pricing — engagements are scoped individually…   ← no [[refusal:…]]
user:      Come on, just a ballpark.
```

The risk is specific: a model that imitates its own transcript concludes the tag is optional, and
drops it — on precisely the turn where the refusal metric matters most. The boundary would still
hold in prose while the *measurement* of it silently failed, which is this project's recurring failure
shape in a new place.

Cheapest mitigation, to try first: one line in `_MARKER` — *"Tag every refusal, including when your
earlier replies in this conversation appear untagged; the tag is removed before display."* Re-injecting
the marker server-side is the fallback, and it is much worse: the server would have to reconstruct the
reason for a turn it no longer holds, which means either trusting the client or making the API
stateful. Try the prompt line, measure, and only escalate if it fails.

#### 4.2 Two scanner holes that fail in opposite directions

Found by exercising `MarkerScanner` directly rather than by reading it:

| Case | Now | Should be |
|---|---|---|
| Stream **ends** while holding a partial marker | `finish()` releases it → user sees `[[refusal:no-public-pri` | **Suppress.** The buffer is nothing *but* the broken tag, so releasing it shows the user a leak and hides no content |
| Stream **raises** while holding | `finish()` is never reached → held text silently dropped | Fine to drop (≤64 chars, and the user gets an error frame regardless) — but make it a decision with a test, not an accident |

Verified: `feed("[[refusal:no-public-pri")` then `finish()` returns the partial tag.

Realistically unreachable via `max_tokens` — truncation would have to land at output token ~10 with a
1,024 cap — so this is about correctness under a malformed reply, not a likely incident. It matters
because **the existing test looks like it covers this and does not**:
`test_an_unterminated_marker_does_not_swallow_the_reply` covers the >64-character case, where
releasing is right. The ends-while-holding case is a different code path with the opposite correct
answer.

#### 4.3 A cheap measurement worth taking while here

`cache_read_input_tokens` should stay **constant** as the conversation grows, because history sits
after the cache breakpoint. Confirming that empirically across a 4-turn conversation is the direct
evidence that the breakpoint is placed correctly — so far it has only been verified on single-turn
requests, where a misplaced breakpoint would look identical.

**Exit:** an anaphora follow-up resolves correctly against bounded history · a refusal survives at
least two rounds of pushback, **with the pushback turn logging `status="refused"` and the same
`refusal_reason`** · the two scanner edge cases are decided and tested · `cache_read` measured across a
multi-turn conversation and unchanged. Then the checklist.

### Phase 5 — React chat UI · 60–75 min

**Forward review after Phase 4.** Unlike Phase 4, this phase has real work left — but a different
split than the original line implied. Checked against `web/`:

| Item | State |
|---|---|
| Message list · streaming render · input | **Built** — `App.jsx`, 153 lines, working |
| Error states | **Built** — `isError` on the turn, red text, covers both the SSE error frame and a fetch throw |
| Single booking CTA | **Built** — footer link to `/contact` |
| `tokens.css` custom properties | **Absent** — there is no `.css` file anywhere in `web/` |
| `dvh`/`svh` shell, 16px input font | **Absent** |

So this is **restyling, not construction**, and three things constrain it:

1. **All styling is currently inline `style={{…}}` — 12 of them.** That is CSS-in-JS by another name,
   which `CLAUDE.md` explicitly rules out in favour of plain CSS with custom properties. The current
   state violates a stated convention, so extracting it is required work, not polish.

2. ✅ **The design-token dependency is RESOLVED — no longer a blocker.** It was real: the step needs a
   real browser, which rules me out as much as a naive page fetch. It was settled from two sources
   rather than the approximation originally planned:
   - The site is **Webflow**, which declares its tokens as CSS custom properties in the served
     stylesheet rather than only computing them. Fetching it yielded the real declared values —
     colours, fonts, weights, spacing, radii — saved to `analysis/brand-tokens-extracted.txt`.
   - The requester supplied a full-page screenshot, which corrected how those tokens are actually
     *used* (see the table below). Declared values alone would have produced a red-headed, blue-buttoned
     widget that matched no page on the site.

3. **Phase 4 added a functional requirement this phase must not break.** `App.jsx` accumulates only
   visible `delta` text into the assistant turn and posts the whole array back. Multi-turn correctness
   depends on both halves. A restyling pass that touches the accumulation logic — or "tidies" it into
   storing raw frames — would put the refusal marker into history and undo Phase 4. Treat
   `sendMessage` as behaviour under test, not layout.

4. ⚠️ **The fonts are not loaded, and nothing in this plan said so.** `Inter` and `Inter Tight` appear
   nowhere in `web/` — not in `index.html`, not in `package.json`, no `@font-face`. Writing
   `font-family: 'Inter Tight'` would **silently fall back to Arial**: no error, no warning, and a
   widget that looks approximately right to whoever wrote it. That is this project's signature failure
   mode, so it gets a decision rather than a default.

   **Self-host the woff2 files** (~4 files, ~160KB) rather than linking Google Fonts. Two reasons, and
   the second is the real one: the project is deliberately *one deployable* with no runtime external
   dependency — the corpus is committed, the app never fetches the web — and a CDN font would be the
   only third-party request on the page. This bot answers questions about Cadre's data-security
   posture; a widget that phones a third party while doing so is the same kind of inconsistency as
   logging raw user messages. Fallback stack stays `Inter, Arial, sans-serif`, matching the site's own
   declaration.

   *Good outcome:* the fallback is honest either way. *Bad outcome to avoid:* declaring Inter, shipping
   Arial, and reporting it as brand-matched.

5. **There is no CSS entry point at all.** `main.jsx` imports only React and `App.jsx`; no stylesheet is
   wired in. `tokens.css` needs an explicit import, or it will build cleanly and apply nothing.

6. **Both conventions need a durable guard, not a review-time glance.** "No inline styles" and "text is
   black" are exactly the rules that decay the first time someone adds a quick `style={{ color: '#666' }}`.
   A cheap source-level test — assert `web/src/App.jsx` contains no `style={{` and no non-black hex
   literal outside `tokens.css` — makes both permanent. `CLAUDE.md`'s verification section covers the
   knowledge layer and the API but says nothing about the UI, which is why this has to be stated here.

#### What the site actually looks like — corrected from a screenshot

The declared tokens were right; **my reading of how they are used was wrong**, and only a screenshot
showed it. Extracting `h1{color:var(--cadre-red)}` from a 470KB minified stylesheet, I concluded red
was the heading colour and proposed blue for interactive elements. Both wrong:

| | I inferred from CSS | What the page actually does |
|---|---|---|
| Headings | red | **Black.** Red appears as a *word-level* accent — "AI **Confidence**", "Find. Prepare. **Implement.**" |
| Interactive elements | `--cadre-blue` | **Black pills, white text, `→` suffix** — "Talk to an AI Strategist →" |
| `--cadre-blue` #08749b | primary interactive | **Essentially absent** from the homepage. Declared, barely used |
| Background | white | **Warm sand `#faf9f6`**, not white. This is the dominant surface |

So **black is the brand's own interactive and heading colour.** The requester's instruction below is
not a divergence from Cadre's design — it is the closest match to it.

Rest of the visual language, for the widget to sit inside rather than beside:

- **Cards** — white fill on the sand background, large radii (~1–1.5rem, matching the CSS), a hairline
  border and a very soft shadow. Airy, generous padding.
- **Buttons** — fully-rounded black pills, white label, `→` suffix. One dark testimonial card inverts
  this: black surface, white text.
- **Type** — Inter Tight for headings, heavy weight and tight tracking; Inter for body.
- **Spacing is generous.** The page breathes; sections are far apart. A cramped widget would read as
  foreign even with the right colours.
- **The FAQ section is the closest analogue on the site to what we are building** — "Common questions,
  straight answers", a two-column list with hairline rules, black text, `+` affordances. When a layout
  choice is ambiguous, match that section.

One deliberate divergence, stated so it is not mistaken for an oversight: the site *does* use grey for
supporting copy. Ours will not (below). Their grey sits under large marketing headlines; ours would be
small functional reading text, where grey costs legibility for nothing.

#### Requester decision — text is black

**Stated directly, and it is a requirement rather than a preference: text in the chatbot must be
black.** The current UI is the counter-example that prompted it — five inline colours, none of them
black: `#666` twice, `#999` twice, and `#b00` for errors. Grey-on-white body text is exactly the
"looks designed, reads worse" default this replaces.

- **Black is `--colors--primary-black: #0b0707`**, Cadre's own declared primary black, so the widget
  matches the site rather than merely being dark. Use literal `#000` instead only if the requester
  wants it.
- **No grey body text anywhere.** That includes the placeholder line, the footer, and the latency
  readout — the things currently at `#666`/`#999`. If something needs de-emphasis, use size or
  weight, not a lighter colour.
- **Two deliberate exceptions**, both functional rather than decorative, to confirm rather than
  assume: the **error state** (currently `#b00`) carries meaning that black would erase, and
  `--cadre-red` is the brand's own error-ish colour; and the **`/contact` link**, where an
  undifferentiated black link stops reading as clickable. Everything else is black.

**Exit:** no inline `style={{…}}` left in `App.jsx`, **guarded by a test** · `tokens.css` exists, is
imported, and components consume variables never literals · **all message and interface text renders
black — no grey body text**, also guarded · Inter/Inter Tight **self-hosted and actually loading**
(verified in the browser, not assumed from the CSS) · shell in `dvh`/`svh` and input font ≥16px (both
iOS-specific: `vh` sits under the keyboard, <16px triggers focus auto-zoom) · usable at 375px wide ·
streaming still visible · CTA present · **the multi-turn probes still pass unchanged**. Then the
checklist.

**Not in scope, so it does not creep in:** no component library, no CSS framework, no dark mode, no
animation beyond what streaming already implies, no redesign of the conversation model. This is a
styling pass over a working UI.

### Phase 6 — Eval + P2 + polish · 60–75 min

**Forward review after Phase 5.** Two of the four listed items are already done, verified against the
repo:

| Listed item | State |
|---|---|
| Split the JSONL streams | **Done in Phase 2** — `log.py` routes to `app`/`interactions`/`errors` by a `stream` extra |
| Confirm logs land on the volume | **Done in Phase 2** — `/health` probes by writing a file; state survived a confirmed container replacement |
| `/api/stats` | **Not built.** No `stats` route exists |
| 13-case golden set | **Not built.** `eval/` does not exist |

So the phase is the eval plus `/stats`, not four things. That is still a full phase — the eval is the
harder half and has been deferred through five phases.

#### ⛔ Blocker found in the audit: refusal state never reaches the wire

`CLAUDE.md` specifies the golden set asserts *"the expected `status`/`refusal_reason` in the log"*, and
the exit criterion is that the eval runs **against the deployed URL**. Those two requirements are
currently incompatible:

- The `done` SSE frame carries `stop_reason`, `usage`, and `request_id` — **not** `status` and **not**
  `refusal_reason`.
- `interactions.jsonl` lives on the Railway volume, and reading it needs `railway ssh` with a
  registered key (see the Phase 2 report §9, where this was already hit).

So a remote eval cannot assert the one property Phases 3 and 4 exist to produce. It would be reduced to
matching substrings in prose — exactly what `CLAUDE.md`'s verification rule rules out, and what the
marker was built to avoid.

**Fix, and it belongs first in this phase:** put `status` and `refusal_reason` on the `done` frame.
They are facts about the caller's own turn, and the slugs are derived from the public corpus, so
nothing internal is exposed. It also makes the eval's remote and local modes assert *the same thing*
rather than two different weakenings of it.

*Check while doing it:* the frontend ignores unknown fields on `done`, so this must not change what
`App.jsx` stores in history — Phase 4's constraint still applies.

#### ⚠️ The eval nearly trips its own rate limiter

13 cases is **16 HTTP requests** — 11 single-turn, plus 2 for anaphora and 3 for refusal-then-pushback
— against a 20/min limit. It fits with **4 requests of margin**, which is not enough to rely on:

- one retried case, one extra pushback turn, or two runs inside a minute all trip it;
- the failure does **not** look like a rate limit. The limiter returns a readable SSE error frame on
  HTTP 200, so the eval sees a well-formed response whose text is wrong, and reports a *content*
  failure. A confusing false negative on the one tool meant to be trustworthy.

Pace the runner (a short delay between cases is enough at this size) **and** have it detect
`reason: "rate-limited"` explicitly and abort with that message rather than scoring it as a wrong
answer.

#### `/api/stats` must not report zeros it cannot substantiate

`/stats` reads `interactions.jsonl`, which only exists when `SINK.mode == "disk"`. In `stdout-only`
mode there is no file — and returning `{"turns": 0, "cost": 0}` there would state "no traffic" when the
truth is "cannot tell". Report the sink mode and an explicit unavailable, the way `/health` already
does for `log_sink`.

**Three things Phase 5 and earlier changed about how to build it:**

1. **The properties to assert already exist as structured fields**, which is new. `refusal_reason`
   (Phase 3) and `status="refused"` (Phase 4) mean a refusal case asserts
   `status == "refused" and refusal_reason == "no-public-pricing"` — an exact match on a closed enum,
   not a substring search over prose. `CLAUDE.md`'s "assert properties, not strings" is now cheap
   rather than aspirational. Assert the *absence* checks on the answer text (no digit-shaped price, no
   URL that is not `/contact`, no quoted guest claim) and everything else on the log line.

2. **The two multi-turn cases already have a working harness.** Phase 4's probe script drives real
   conversations while storing only the visible (marker-stripped) assistant text, exactly as the
   browser does. Rewrite it into `eval/golden.py` rather than starting over — and keep that fidelity,
   because storing raw frames instead is what would mask the very regression the pushback case exists
   to catch.

3. **`/stats` should read the refusal fields, not just count turns.** The interesting number this bot
   can now report is *refusal rate by reason* — which is also the evidence for the corpus-size
   question raised earlier: if real questions are being refused with `no-public-*` reasons that the
   site does in fact answer, the corpus has a gap. That turns "should the KB be bigger?" from an
   intuition into a measurement.

**Also fold in:** the visual sign-off Phase 5 could not do (§7 of its report) — hierarchy, spacing,
and the 375px layout still need a human's eyes on the deployed URL.

**The 13 cases**, from `CLAUDE.md`, with what each asserts. Refusals are the easier half — an exact
match on a closed enum — which is why they carry the weight:

| # | Case | Asserts |
|---|---|---|
| 1–6 | The six brief scenarios | `status == "ok"`, grounding present, no invented URL |
| 7 | Pricing | `refused` + `no-public-pricing`, **and no digit-shaped price in the text** |
| 8 | Portal login URL | `refused` + `no-public-portal-access`, **no URL other than `/contact`** |
| 9 | Podcast episode content | `refused` + `no-episode-content`, **no quoted or paraphrased guest claim** |
| 10 | Getting started | `status == "ok"`, routes to `/contact` |
| 11 | Case studies | `status == "ok"`, **no client name**, metrics framed as past results |
| 12 | Anaphora follow-up (2 turns) | turn 2 resolves against history, `status == "ok"` |
| 13 | Refusal-then-pushback (3 turns) | **every** turn `refused` with the *same* reason — the case that caught Phase 4's defect |

Case 13 is the one to write first. It is the only case in the set that has already found a real
regression, and it is the one a weaker assertion would silently pass.

**Exit:** `status` and `refusal_reason` present on the `done` frame · `eval/golden.py` runs the 13
cases **against the deployed URL** and is green, per-case results recorded here · the runner aborts
loudly on a rate-limit frame rather than scoring it as a wrong answer · `/api/stats` reports turns,
cost, cache-hit rate and **refusal rate by reason**, and says "unavailable" rather than zero when it
cannot read the log · the corpus-size question answered from eval evidence rather than intuition ·
Phase 5's visual sign-off obtained · both documents tightened. Then the checklist.

**This phase closes the GATE.** *"The bot must answer all six scenarios on the public URL"* — cases 1–6
against the deployed URL are exactly that, so a green eval is the gate's evidence rather than a
separate exercise.

### 🚦 GATE — before Phase 7 or observability P2 extras
**The bot must answer all six scenarios on the public URL.** If it doesn't, finish the core: MCP drops
and observability stops at P1, regardless of remaining time. Within P2 the cut order is rollups →
file-split → **`/stats` last** (it's the only part that makes the layer usable without SSHing in to grep
JSONL, and it's what Phase 8 reads).

### Phase 7 — MCP over the observability layer · 60–75 min  *(re-aimed — see the audit below)*

**Audit before starting — three facts that change what this phase should be.**

**1. MCP appears nowhere in the brief.** Zero mentions of "MCP" or "Model Context Protocol" in
`analysis/Cadre-chatbot-insturctions.md`. What the brief asks for is a chatbot handling six scenarios,
a deployed URL, a repo, `CLAUDE.md` and `plan.md` — all delivered and verified as of Phase 6. This
phase is self-imposed scope.

**2. The brief's most emphatic tips point the other way.** Two entries in the Tips table:

> **Cut scope aggressively. 3 working features > 8 broken ones.**
> **Make your scope decisions explicit in plan.md.**

and in "What to Build": *"You decide what's in scope. **We're watching those decisions closely.**"*
So the scope decision here is itself part of what is being evaluated — which means an unjustified
eighth feature costs more than it adds, and a well-argued cut is a positive rather than a gap.

**3. The originally planned shape would make the product measurably worse.** `bot as MCP client`
calling `search_cadre_knowledge(query)` turns every turn into an agentic loop: call 1 stops at
`tool_use`, call 2 continues with the `tool_result`. Measured against the current numbers:

| | Today | With a tool round trip |
|---|---|---|
| Cost / turn | $0.001024 | **$0.002629** (2.6×) |
| Latency (p50) | 2,398 ms | **roughly double** |
| What retrieval finds | — | text that was already fully in context |

The corpus is ~4k tokens and is *already in the prompt*. Retrieval over material the model has
already read is ceremony, and here it is ceremony that costs 2.6× and halves the responsiveness of
the thing the brief actually asked for.

**Therefore the question is not "how do we build this" but "where does MCP belong, if anywhere".**
Three defensible answers, and the decision is recorded below rather than settled mid-build:

- **(a) MCP over the observability layer** — expose `/api/stats` and the interaction log as an MCP
  server, so Cadre's team could point an MCP client at it and ask *"what did the bot refuse today, and
  why?"*. Additive: it sits beside the request path rather than inside it, so it cannot slow or break
  the chatbot. Uses the Phase 2 and Phase 6 work rather than duplicating it. Demonstrates the same
  protocol fluency without paying 2.6× on every user turn.
- **(b) Cut it, and record the reasoning** — the brief rewards exactly this, and the reasoning above
  is the artifact. Cheapest, and leaves the verified system untouched.
- **(c) Build it as originally planned** — accepted cost: 2.6× per turn, ~2× latency, and a new
  failure mode on the request path of a system that currently passes 14/14 in production.

**DECISION: (a) — MCP over the observability layer.** The chatbot's request path is not touched, so
cost stays at $0.001024/turn and p50 at 2,398 ms. What MCP gains us is a real capability rather than a
demonstration: the observability built in Phases 2 and 6 becomes something Cadre's team can *ask
questions of* — "what did the bot refuse today, and why?" — instead of something you read by curling
a JSON endpoint.

#### Transport decision, made before starting

**stdio, running locally, reading the deployed instance over HTTP.** Not an ASGI sub-app on the
deployment, and the reason is a boundary rather than a convenience:

- An HTTP MCP endpoint on the Railway app would be a **new unauthenticated public surface exposing
  interaction data**. `CLAUDE.md` puts auth explicitly out of scope, so there would be nothing to put
  in front of it. Shipping a public endpoint that serves redacted user messages, and calling it fine
  because they are redacted, is precisely the reasoning this project rejects elsewhere.
- stdio is also what an MCP client (Claude Desktop and similar) actually expects for an operator tool,
  and it puts the server where the operator already is.

**The server reads `/api/stats` and `/health` only — never the raw interaction log.** That is a real
limitation and it is the right one: aggregates answer the operator's questions without republishing
what people typed. The MCP layer therefore inherits the product's own discipline — it answers what it
can substantiate and declines what is not safe to expose.

#### Structure

`mcp_server/` at the repo root, **not** copied into the runtime image, with the `mcp` SDK in the dev
dependency group. The deployed chatbot's runtime dependency count stays at 4, and `uv export --no-dev`
already excludes the group — same mechanism that keeps `scripts/scrape.py` out of the image.

Tools, kept few and answerable:

| Tool | Answers |
|---|---|
| `bot_health()` | Is it up, which prompt version, is the log sink writable |
| `bot_stats()` | Turns, cost, cache hit rate, latency percentiles |
| `refusal_breakdown()` | Refusal rate **by reason** — the number this bot is judged on |
| `spend_today()` | Spend against the daily cap |

#### Exit

`mcp_server/` runs and a client can call all four tools against the **deployed** instance · the tools
report "unavailable" rather than zeros when `/api/stats` says so, matching the endpoint's own honesty ·
the runtime image is unchanged — verified by confirming the deployed dependency count and that
`mcp_server/` is absent from the container · **the golden set still passes 14/14**, which should be
trivially true since the request path is untouched, and is worth confirming precisely because it should
be. Then the checklist.

**Not in scope:** exposing the raw interaction log, any write/mutating tool, auth, or a hosted MCP
endpoint. A read-only operator tool is the whole of it.

### Phase 8 — Post-submission health check · 20–25 min  *(re-estimated — see below)*
The public URL sits unattended with a live billed key for ≥24h after submission. Re-hit it, read
`/api/stats` for error rate and spend-to-date, confirm the Railway service and volume are still
attached, confirm the daily cap has headroom.

**Forward review after Phase 7 — this is now cheaper and more thorough than when it was written.**

- **The MCP server is the tool for this.** `bot_health()`, `bot_stats()`, `refusal_breakdown()` and
  `spend_today()` are exactly the four questions this phase asks, and they can be asked
  conversationally rather than by curling and reading JSON. That is the phase's method now; the curl
  path remains the fallback if the MCP client is not to hand.
#### The real reason this phase matters: two code paths have never executed

Everything else in the system has run in production many times. **Two have not, and both fire only at
UTC midnight** — so a check run ≥24h after submission is the first and only opportunity to see either
work:

| Path | Where | What it does |
|---|---|---|
| Log rotation | `log.py` — `when="midnight", backupCount=7` | Rolls `interactions.jsonl`, deletes the 8th-oldest. **The retention policy *is* this config**, so until it fires, retention is a claim rather than a behaviour |
| Daily spend rollover | `spend.py` — `_roll_if_new_day()` | Resets the ledger to 0 for the new UTC day. Until it fires, the cap has only ever counted upward |

Neither can be checked early: they are date-triggered, not traffic-triggered.

**Both are observable from outside — no SSH needed.** This was the open question, and the answer is
clean:

- `/api/stats` reads **today's** `interactions.jsonl`. As of writing it reports **119 turns**. If
  rotation fires, tomorrow it reports **~0** (only the new day's traffic). **If it still reports 119,
  rotation did not fire** and retention is silently not being enforced.
- `/health` reports `spend.date` and `spend_today_usd`, currently **2026-07-30 / $0.161139**. After
  rollover it should read the new date with spend near **0**. A stale date means `_roll_if_new_day()`
  did not run and the cap is counting a second day against the first day's total.

Record both numbers **before** finishing today, so tomorrow's reading has something to compare
against. Baseline captured: **119 turns, $0.161139, date 2026-07-30.**

*Checked while auditing, so it is not a worry:* rotation is **restart-safe**. `TimedRotatingFileHandler`
computes `rolloverAt` from the existing file's `st_mtime`, not from process start, so a Railway
redeploy before midnight does not skip a rollover — the first write after the missed time triggers it.
Frequent redeploys therefore cannot defeat retention.

**Stated honestly, because it would be easy to overclaim:** this verifies rotation *happens*. It does
**not** verify 7-day deletion, which needs the 8th day. Retention beyond "the mechanism runs" stays
unverified, and should be reported that way rather than as "retention confirmed".

- **Re-run the golden set once against the deployed URL.** ~$0.03, and it is the difference between
  "it was working when I left it" and "it is working now". Note the first turn will pay a cache
  **write** ($0.00627) rather than a read, since the TTL will have long expired — expected, not a
  regression.

**Two items carried in rather than dropped:**

1. **Phase 5's visual sign-off.** Hierarchy, spacing, and the 375px layout still need a human's eyes
   on the rendered page. Recorded in `reports/phase-5-report.md` §7 as explicitly unverified.
2. **Deploy times degraded during Phases 6–7** — ~20 minutes, and one deployment sat in `DEPLOYING`
   behind a 502 before recovering on its own. Not acted on, because nothing is broken and the cause
   is on Railway's side, but worth a look if it persists.

**Exit:** the four MCP tools answer against the live URL · **rotation fired** (`/api/stats` turns
dropped from the 119 baseline) · **the spend ledger rolled over** (`/health` shows the new UTC date
with spend near 0) · the golden set is green · spend has headroom against the cap · the volume is
still attached · anything found is recorded, including "nothing changed", which is itself the result.

**If a check fails, that is the phase's output, not a reason to extend it.** A 15-minute health check
that finds a broken rotation has done its job; fixing it is a new piece of work with its own
verification, not something to fold in silently.

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

---

## Open items — as of 2026-07-30 17:30 UTC

All eight phases are complete and deployed. Four things remain, none of them blocking a working
system. Recorded here rather than left in a conversation, since this file is where the open items
live.

| # | Item | Status |
|---|---|---|
| 1 | **Phase 8 part 2** — did rotation and the spend rollover fire? | ✅ **Both fired**, verified 2026-07-31 00:25 UTC. See `reports/phase-8-report.md` §4 |
| 2 | **Phase 5 visual sign-off** — hierarchy, spacing, 375px | ⏳ **Open** — needs a human's eyes; I cannot see the rendered page |
| 3 | **Tighten `CLAUDE.md`** | ✅ Done — refreshed and cut back under its own 250-line cap (249) |
| 4 | **Add a guardrail hook to `.claude/`** | ✅ Done — `hooks/guard-commit.sh`, verified against six paths |

**One item remains, and it is the one I cannot do.**

**On (1):** exact commands and the meaning of each outcome are in `reports/phase-8-report.md` §4.
Baseline to compare against: **136 turns · $0.186995 · `spend.date: 2026-07-30`**. If `/api/stats`
still reports 136 tomorrow, rotation did not fire and retention is silently unenforced — the most
valuable finding this phase could produce.

**On (3) — this is a miss of mine.** Phase 6's exit criteria said "both documents tightened". I
updated `plan.md` continuously but **`CLAUDE.md` has not been touched since Phase 1**, and it is now
stale in specific ways: the Layout section omits `mcp_server/`, `tokens.css` and `app.css`; it says
"13-case eval" in two places where the set is **14** (off-topic was added in Phase 6); and it records
none of the four measured prefix sizes or the prompt reaching v1.3. Phase 6 was marked complete
without this. It is documentation rather than function, but `CLAUDE.md` is one of the two files the
brief names explicitly.

**On (4):** `.claude/` has a subagent (`kb-updater`) and two commands (`/update-kb`, `/log-decision`)
but no hooks — `settings.json` carries only `$schema` and `permissions`. Note this file already argues
*against* one hook (auto-commit on `Stop`, which fires per turn rather than per phase). Guardrails fit
cleanly though: block writes to `.env`, block `git push --force`. Both are rules this project already
states and currently relies on the operator to honour.
