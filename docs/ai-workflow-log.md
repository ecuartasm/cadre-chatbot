# AI workflow log

One entry per phase, appended **at the end of that phase** — never reconstructed later, which is the
whole point. Four fields, always the same:

- **Asked for** — what I directed Claude Code to do
- **Produced** — what it generated
- **Changed** — what I corrected, rejected, or rewrote, **and why**
- **Verified** — how I confirmed it actually works

---

## Phase 0b — `CLAUDE.md` + `plan.md`

**Asked for:** distil ~190KB of analysis into a self-contained `CLAUDE.md` (conventions + the
non-negotiable knowledge-base rules) and a phased `plan.md` (sequence, scope decisions with reasons,
open items).

**Produced:** both files. `CLAUDE.md` at 205 lines under a self-declared 250-line cap; `plan.md` with
phases 0a–8, scope in/out tables, the gate, and the open case-study verification gate.

**Changed:** rejected the initial instinct to `@`-import the analysis documents into `CLAUDE.md`. They
total ~190KB and would be reloaded on every turn for content needed only while curating the corpus. The
decision recorded in the analysis was the opposite — distil, don't import — so `CLAUDE.md` restates the
rules in compressed form and the analysis stays out of build-session context entirely.

**Verified:** line count under the stated cap; every claim about model IDs, pricing, and the prompt-cache
floor cross-checked against the Anthropic API reference rather than recalled.

---

## Phase 0a — Deploy skeleton

**Asked for:** `uv`/Python 3.12 toolchain, minimal FastAPI app, Railway config, `.claude/settings.json`,
this log, then deploy.

**Produced:** `pyproject.toml`, `app/main.py` (`/health` + an honest `/` placeholder), `railway.toml`,
`tests/test_health.py`, `.env.example`, `.claude/settings.json`.

**Changed:**
1. **`ModuleNotFoundError: No module named 'app'`** on first `pytest` run — the repo root wasn't on
   `sys.path`. Fixed with `pythonpath = ["."]` in `[tool.pytest.ini_options]` rather than adding a
   packaging step, since this is an app and not an installable library.
2. **Swapped `httpx` → `httpx2`** in the dev deps. Starlette 1.3 emits
   `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated`. Taking the
   warning seriously now is cheaper than carrying it through every later phase's test output.
3. **`/health` reports key *presence*, never validity.** The obvious implementation calls the API to
   confirm the key works; that would mean a billed request on every Railway healthcheck. It returns
   `anthropic_key_configured: bool` instead.
4. **Rewrote `.env`.** The copied file came from another project — it carried `NEXT_PUBLIC_APP_URL`,
   `APP_SECRET`, `APP_USERNAME`/`APP_PASSWORD`, and an `ANTHROPIC_MODEL` pointing at a Sonnet model,
   which contradicts the locked decision (`claude-haiku-4-5`). Values were also quoted, which survives
   `python-dotenv` but not a raw `set -a; . ./.env`. Stripped quotes, dropped the stale vars, preserved
   the key.

**Verified:** `pytest` 3/3 green with no warnings · `ruff check` clean · booted `uvicorn` locally and
curled `/health` and `/` · grepped both responses for `sk-ant-` (0 occurrences) · confirmed the key
still authenticates after the `.env` rewrite using the free `/v1/models` endpoint, so the check cost no
tokens.

---

## Phase 1 — Knowledge base

**Asked for:** resolve the case-study gate from literal page text; write a byte-faithful scraper;
curate a corpus clearing Haiku 4.5's 4,096-token cache floor; add a read-once loader and the
`kb-updater` subagent.

**Produced:** `scripts/scrape.py` (36 pages, `content_sha256` frontmatter), `content/raw/*.md`,
`content/knowledge-base.md` (4,028 tokens), `app/knowledge/loader.py`, `.claude/agents/kb-updater.md`,
`/update-kb`, `/log-decision`, 14 corpus tests.

**Changed:**
1. **The gate overturned the analysis, not the other way round.** The literal page shows clients ARE
   anonymised (8× "Non-Disclosed Company") AND individuals ARE named — both at once, so the research
   note's original line was correct and the adversarial review's "correction" was the error.
   "Griffin Funding" appears nowhere; the company name was fabricated. Count is 8, not 9.
2. **Rejected the first curated draft at 3,517 tokens** — 192 below the floor. Rejected the second at
   +31 margin too: clearing by one paragraph means any later edit breaks caching silently. Added the
   nine per-industry value propositions (real content scenario 1 needed and lacked) rather than padding.
3. **`tests/conftest.py` added after finding the live `count_tokens` test was silently skipping** — no
   `.env` load in the test process meant the assertion guarding this phase's central number never ran,
   while the suite reported green.
4. Dropped an unused `KNOWLEDGE_SHA256` import and rewrapped 8 long docstring lines rather than
   suppressing the lint.
5. Switched content extraction from shell `grep` to Python after two regexes failed on complexity and
   one hung for 120s.

**Verified:** 34 tests · ruff clean · 36/36 pages scraped · prefix 4,415 vs 4,096 floor confirmed by
live `count_tokens` · **corpus sha identical local ↔ deployed** (proves `COPY content/` worked) ·
**`cache_read=4409` on the second production call** · all three refusals hold on the live bot with no
number, no invented URL, and no guest characterisation.

---

## Phase 2 — Observability, cost accounting, and limits

**Asked for:** structured request logging that survives a restart, four-rate cost accounting, PII
redaction, a persisted daily spend cap, and per-IP rate limiting — with every failure mode loud.

**Produced:** `app/obs/{sink,log,redact,cost,spend,limits}.py`, `docker-entrypoint.sh`, a rewritten
`app/api/chat.py`, request-context middleware and a catch-all exception handler in `app/main.py`, and
32 tests in `tests/test_obs.py`.

**Changed:**
1. **Wrote `sink.py` first, before any logging code.** The recurring defect in this build has been
   silence — the cache floor, the missing `COPY content/`, the skipped test, the volume mount path.
   Python's logging handlers swallow I/O errors by design, so an unwritable volume shows up as an
   empty directory nobody checks. `resolve_sink()` probes by *actually writing a file* (`os.access`
   lies under mounts) and raises in production rather than degrading quietly.
2. **The Railway volume was created at `/tmp` and unattached** despite `--mount-path /data`. Caught
   only by running `railway volume list` instead of trusting the create output. Fixed with
   `volume update -m /data` plus an attach.
3. **Rejected `slowapi`** (the plan's choice) for ~30 lines. It rejects by raising a JSON 429, but
   this endpoint serves `text/event-stream`, so the frontend's `if (!res.ok) throw` would render
   that as "Couldn't reach the server (HTTP 429)" — accurate and useless. Rejections now arrive as
   readable SSE frames on HTTP 200.
4. **Three request-id defects, all found by reading one live log line rather than by the suite.**
   `request_id_var.reset(token)` sits in a `finally` that fires before the middleware's own log call
   and before the exception handler runs, so both logged `-`. Worse, `call_next` returns when the
   *headers* are ready, so an SSE body is iterated after the reset — meaning the interaction log,
   the one record Phase 2 exists to produce, would have lost its id on every streaming turn. The id
   is now carried explicitly in `InteractionLog.as_dict()`, in the access-log call, and on
   `request.state` for the exception handler. Verified live: an abandoned stream logged
   `request_id=59e7707ac79b4546`, not `-`.
5. **`RATE_LIMIT_PER_MINUTE=0` produced a 500 on every request.** `len(bucket) >= 0` is true for an
   *empty* bucket, so the retry-after arithmetic indexed `bucket[0]` and raised `IndexError`. A
   plausible kill-switch value was a hard crash, and the degenerate case had no test. It now returns
   a rejection without touching `_hits` — which also closes an unbounded-growth path, since
   `defaultdict` created an entry per rejected caller while eviction only ran on the allowed path.
6. **Corrected two wrong cost figures I had written into comments and tests.** I priced the
   worst-case turn at $0.00551 — the cache-write component alone, with the output cost dropped. The
   real figure is $0.00627, so the `$5/day` cap is ~795 turns, not ~900. The daily-cap rationale in
   `spend.py` had been quoting the understated number.
7. **Made the abandoned-turn accounting honest.** A comment claimed abandoned turns are charged;
   they are not, because `usage` only arrives with the `done` event, so the ledger under-counts by
   the abandoned share. Inventing a figure from `assistant_chars` would put a guess in a money
   ledger, so the gap is documented, bounded by the rate limiter, and greppable
   (`status="abandoned"` with `cost_usd=0` and non-zero `assistant_chars`).
8. **Moved dev dependencies from `[project.optional-dependencies]` to `[dependency-groups]`.**
   CLAUDE.md documents plain `uv sync` then `pytest`, but `uv sync` installs groups and skips
   extras — so a fresh clone following the documented command would have got no test dependencies.
   The suite only passed locally because of an earlier manual install. `uv export --no-dev` still
   keeps them out of the runtime image.
9. **Set `asyncio_mode = "strict"` and made unknown pytest markers an error.** An async test with no
   marker is collected and never awaited, which is Phase 1's silent-skip failure wearing a different
   hat. Three async tests failed loudly on the missing plugin instead.

**Verified:** 66 tests · ruff clean · cache **write** 4,409 then **read** 4,409 across two turns ·
logged costs match the rate table to the cent by hand ($0.00596425 write, $0.0009439 read) ·
`spend.json` total equals the exact sum of both turns · the pasted email appears nowhere under the
log directory · a client disconnect at 2s produced `status="abandoned"`, `error="CancelledError"`,
333 streamed chars and a real request id · a rate-limited call returned HTTP 200,
`content-type: text/event-stream`, `Retry-After: 60` and a readable error frame.

**Found during the production verification, after the phase commit:** the rate limiter tripped at
request 21 as designed, but that observation could not distinguish per-visitor bucketing from a single
shared bucket keyed on Railway's router — one client would trip either at 21. The discriminating test
came back ambiguous too, and the two readings have opposite consequences (a shared bucket means the
first scraper locks out every visitor while `/health` stays green). Nothing in Phase 2's own logging
told them apart, which is a gap in the deliverable found only by trying to use it. `client_key()` now
returns `(key, source)` and logs the **source** — not the address, since an IP in a 7-day log is data
this app has no reason to keep. Production then answered it in one line:
`client_key_source="x-forwarded-for"`. Bucketing is per-visitor; the earlier ambiguity was Railway's
edge refusing to let a client control the left-most entry, which also makes `limits.py`'s
"client-spoofable" caveat stricter than this deployment's reality. Both facts are now recorded in the
module docstring as measured rather than assumed.

---

## Phase 3 — System prompt refinement

**Asked for:** make refusals structural rather than prose, populate `refusal_reason` in the logs, add
conversion behaviour, and re-verify the cache floor.

**Produced:** `MarkerScanner` in `app/llm/client.py`, `_MARKER` + `_CONVERSION` sections in
`app/llm/prompt.py` (version 1.0 → 1.1), a corpus-derived `REFUSAL_REASONS` enum in
`app/knowledge/loader.py`, validation in `app/api/chat.py`, and 39 tests in `tests/test_refusal.py`.

**Changed:**
1. **The vocabulary is parsed from the corpus, not written in Python.** The NEGATIVE KNOWLEDGE table
   already defines 15 slugs and `off-topic` is documented separately — 16 total. A hand-copied list
   would be a second source of truth for the same thing, so a slug renamed in the table would keep
   validating against a stale copy and the logs would quietly disagree with the corpus they describe.
2. **Two live probe failures on off-topic, found by running it, not by the tests.** First the bot
   *answered* a Python question and appended a disclaimer: the off-topic rule was a sub-clause about
   the contact link, so the model obeyed the "no link" half and answered anyway. Promoted it to a
   hard rule — "do NOT answer it, even though you easily could". Second, it then declined correctly
   but logged `status="ok"`, because "not routing to /contact" read as "not a refusal". Told it
   explicitly that an off-topic decline takes the tag. Only then did all ten probes classify right.
3. **Measured the marker's latency cost instead of assuming it.** TTFT is 0.85s for an answer and
   1.11s for a refusal. The ~0.26s is the model emitting ~10 marker tokens before any prose — inherent
   to the approach, not scanner overhead. Recorded in `plan.md` as an accepted trade.
4. **The prefix grew 4,415 → 4,870**, so margin over the 4,096 floor improved from 319 to 774. Every
   edit was re-measured with live `count_tokens`; the three-step history is in `prompt.py`.
5. **`InteractionLog.refusal_reason` had been dead since Phase 2** — declared, emitted, never set.
   Same for `status="refused"`. Both are now populated, which is what makes the refusal rate a real
   number rather than a field that always reads `null`.
6. **A procedural error of mine, recorded because the evidence looked like an app bug.** I deleted a
   live `interactions.jsonl` while the server held it open, so writes went to the unlinked inode and
   the file appeared never to be created. Standard Unix behaviour for any long-running writer; the
   app was fine. Re-ran against a clean server rather than trusting the first read.

**Verified:** 106 tests · ruff clean · all ten probes classify correctly (4 answers, 6 refusals) ·
`no-public-pricing`, `no-public-portal-access`, `no-episode-content`, `security-specifics-not-public`
and `off-topic` all recorded from real turns · **the `[[refusal:` marker appears in none of the ten
answers** · off-topic declines with no `/contact` link · no invented slug reached the log ·
`cache_read=4807` on the second turn, so the larger prefix still caches.

---

## Phase 4 — Multi-turn behaviour

**Asked for:** verify anaphora and refusal-then-pushback across turns, decide the two `MarkerScanner`
edge cases, and confirm `cache_read` is unaffected by growing history.

**Produced:** a `_MARKER` instruction to keep tagging across turns (prompt 1.1 → 1.2), a narrowed
`MarkerScanner.finish()` plus an earlier release path in `feed()`, and 9 tests across
`tests/test_refusal.py` and `tests/test_chat.py`.

**Changed:**
1. **Measured before fixing, and the predicted failure was real.** Ran the pushback conversation
   against 1.1 first rather than pre-emptively patching. Turn 1 logged `refused/no-public-pricing`;
   turns 2 and 3 refused *in prose* — "I don't have a ballpark to give" — and logged `status="ok"`.
   The boundary held; the measurement of it did not.
2. **It was inconsistent, which is worse than a uniform failure.** The portal pushback kept its tag
   while the pricing pushback dropped it twice. From the data you would conclude pushback rarely
   triggers a refusal, which is precisely backwards. Cause is the one predicted in the Phase 4
   forward review: the marker is stripped before display, so the model's own transcript shows its
   earlier refusals untagged and it infers the tag is optional.
3. **The prompt line fixed it; the server-side fallback was not needed.** All three pushback turns
   now log `refused/no-public-pricing`. Re-injecting the marker into history would have meant either
   trusting the client or making the API stateful, so it stayed the fallback it was planned as.
4. **My first `finish()` fix was too broad and the existing invariant test caught it.** Suppressing
   anything that *starts* with `[[refusal:` threw away the whole reply for `[[refusal:bad slug]]body`
   — a closed-but-malformed tag with real content after it. Moved the decision into `feed()`: a `]]`
   that fails the slug pattern can never become a valid marker, so release immediately. That also
   makes the end-of-stream suppression provably narrow, since anything still held there is
   guaranteed to contain no `]]`.
5. **The mid-stream-error drop is now a decision with a test**, not inherited behaviour. Held text is
   discarded rather than flushed: showing a fragment of an answer directly above "something went
   wrong" reads worse than showing only the error.
6. **`cache_read` confirmed constant across a growing conversation** — 4,948 on every turn while the
   prompt grew 4,964 → 5,079 → 5,206. Direct evidence the breakpoint is placed correctly, which
   single-turn tests could never have shown: a misplaced breakpoint looks identical on turn one.

**Verified:** 115 tests · ruff clean · pushback resisted across three escalating turns with no
number, no range, and no invented URL · all three logged `refused` with the same reason · anaphora
resolved "that" to construction correctly and stayed `ok` · no marker leaked in any turn · prefix
4,870 → 4,954, margin over the floor now 858.

---

## Phase 5 — React chat UI

**Asked for:** replace inline styles with plain CSS custom properties carrying Cadre's brand, make all
text black, self-host the fonts, and make it work on a phone — without breaking Phase 4.

**Produced:** `web/src/tokens.css`, `web/src/app.css`, two self-hosted woff2 files, a rewritten
`App.jsx` with no inline styles, CSS wired into `main.jsx`, and 12 tests in `tests/test_ui.py`.

**Changed:**
1. **Tokens are Cadre's real declared values, not approximations.** The site is Webflow, which emits
   its design tokens as CSS custom properties in the served stylesheet, so fetching it gave the actual
   palette, fonts, weights, spacing and radii. The requester's screenshot then corrected how those
   tokens are *used* — which mattered, because reading the CSS alone I had concluded headings were red
   and buttons blue. They are black. A widget built from the declared values alone would have matched
   no page on the site.
2. **Fonts are self-hosted, and that was a decision rather than a default.** Inter and Inter Tight
   appeared nowhere in `web/` — writing `font-family: 'Inter Tight'` would have fallen back to Arial
   silently and looked approximately right. Chose the two variable woff2 files (71KB, latin subset)
   over a Google Fonts link because the project is deliberately one deployable with no runtime
   external dependency, and a bot that answers questions about Cadre's data-security posture should
   not be the page making a third-party request.
3. **One text colour, and de-emphasis by size and weight only.** The old UI had five inline colours
   and none of them was black. `--text` is now `--black` (#0b0707, Cadre's own primary black) with a
   single documented exception: the error state keeps `--cadre-red`, because there colour carries
   meaning that black would erase.
4. **Both conventions are guarded by tests rather than review.** "No inline styles" and "text is
   black" decay the first time someone adds a quick `style={{ color: '#666' }}`. The tests scan
   comment-stripped source — the first version failed on its own rationale, since a comment explaining
   why grey is banned necessarily contains the word.
5. **Kept `send` verbatim.** Phase 4 established that the client must accumulate only visible delta
   text and post the whole array back; a restyle that tidied that into storing raw frames would put
   the refusal marker into history. A test now asserts both halves survive.
6. **Fixed stale copy while there.** The header still said "Phase 0c vertical slice: three hardcoded
   facts, unstyled" and the footer "knowledge is limited to three facts in this phase" — both untrue
   since Phase 1 and both visible to any visitor.

**Verified:** 127 tests · ruff clean · both woff2 served at HTTP 200 with `font/woff2` · the built
CSS retains the whole token layer (checked after a loose grep reported zeros — Vite keeps a space
after the colon, so the first check was a formatting artefact, not a break) · no grey hex survives
anywhere in `web/src` · **the multi-turn probes reproduce exactly** — three pushback turns still
`refused/no-public-pricing`, anaphora still `ok`, no marker leaked.

---

## Phase 6 — Golden set + /api/stats

**Asked for:** the 13-case golden set asserting properties not strings, `/api/stats`, and both run
against the deployed URL.

**Produced:** `eval/golden.py` (14 cases), `app/api/stats.py`, `status` + `refusal_reason` on the
`done` SSE frame, and 6 tests.

**Changed:**
1. **Fixed a blocker the audit found before writing any eval code.** `CLAUDE.md` says the golden set
   asserts `status`/`refusal_reason` *in the log*, while the exit criterion says it runs against the
   **deployed** URL — and `interactions.jsonl` sits on a volume behind `railway ssh`. Both fields now
   ride on the `done` frame, so remote and local runs assert the same thing instead of two different
   weakenings of it.
2. **The eval found a real defect on the deployed bot that it had passed locally.** Case 13 turn 1
   volunteered *"$420,000 saved in a single area"* inside a pricing refusal. The bot did not state a
   price and caveated the figure correctly as another company's result — and it is still wrong, because
   `CLAUDE.md` says never infer from case-study savings and a large number beside a cost question
   invites the reader to do that inference. The non-determinism is the tell: the same case passed
   locally minutes earlier, so the behaviour was on a knife-edge rather than reliably safe. Prompt 1.3
   forbids any currency figure in a cost answer; savings stay fine when the question is about results.
3. **Case 11 was a defect in my test, not in the bot.** I had forbidden any Cadre URL that is not
   `/contact`, which failed a *correct* answer for linking `/case-studies`. The check that matters is
   whether a URL was **invented**, so it now asserts membership in the set of pages `content/raw/`
   proves were fetched — a stronger test than the one it replaces, since it still catches a portal
   subdomain or a support address but no longer punishes correct citation.
4. **Paced the runner and made it abort on a rate-limit frame.** 16 requests against a 20/min limiter
   is four of margin, and the limiter returns a readable frame on HTTP 200 — so an unpaced run would
   report a *content* failure for a well-formed rejection, sending someone hunting a bug that is not
   there.
5. **`/api/stats` reports "cannot tell" rather than zero.** There is no `interactions.jsonl` in
   stdout-only mode, and `turns: 0` there would state "no traffic" when the truth is "unavailable" —
   the same class of quiet lie as a cache that never engages. Percentiles are nearest-rank, not
   interpolated: with a handful of turns, interpolation invents precision the sample lacks.
6. **Added a 14th case for off-topic.** Not in `CLAUDE.md`'s 13, but it is the one refusal that
   deliberately does *not* route to `/contact`, so a prompt edit aimed at the other fifteen slugs
   breaks it silently — which is exactly what happened twice in Phase 3.

**Verified:** 133 tests · ruff clean · 14/14 locally before the fixes, 12/14 against production which
is what found them · `/api/stats` reports refusal rate by reason, cache hit rate and cost from real
traffic · the corpus-size question answered from evidence (see the report).

---

## Phase 7 — MCP over the observability layer

**Asked for:** an MCP integration. The audit changed what that should mean before any code was
written.

**Produced:** `mcp_server/server.py` (4 read-only tools, stdio), `mcp_server/README.md`, 9 tests, and
the `mcp` SDK in the dev group only.

**Changed:**
1. **Re-aimed the phase rather than building what the plan said.** MCP appears nowhere in the brief —
   zero mentions — and the brief's own tips say "cut scope aggressively" and "we're watching those
   decisions closely". The planned shape (`bot as MCP client` with `search_cadre_knowledge`) would
   have turned every turn into two API calls: **$0.001024 → $0.002629, 2.6x**, plus roughly double
   the 2,398 ms p50, to retrieve a corpus already fully in the prompt. Priced it, put three options
   to the requester, and built the one that sits *beside* the request path.
2. **Transport decided before any code, and for a boundary reason not a convenience one.** stdio,
   not an ASGI sub-app: an HTTP MCP endpoint on Railway would be a new unauthenticated public
   surface exposing interaction data, and auth is out of scope, so nothing could go in front of it.
3. **The server reads aggregates only and cannot read the raw log** — asserted by a test, not
   promised in a comment. That limitation is what makes a no-auth read-only tool defensible.
4. **Did not guess the SDK.** My prior was `mcp.server.fastmcp.FastMCP`; the installed SDK has no
   such module. Inspected `mcp.server.mcpserver.MCPServer` and its real `.tool()` signature before
   writing anything.
5. **A test asserted a substring where it meant a property — again.** `"open(" not in src` matched
   `urlopen(`. Same mistake as the `grey` comment check in Phase 5 and the `/contact` URL check in
   Phase 6: three times now, always narrower or broader than the property actually cared about.
   Fixed with word boundaries, and the comment names the pattern so the next one is spotted faster.

**Verified:** 142 tests · ruff clean · all four tools called successfully against the **deployed**
instance (prompt 1.3, corpus sha `96cd2fffaf6d`, 102 turns, 45.1% refusal rate, `unexpected_reasons:
[]`) · `uv export --no-dev` contains no `mcp` and the Dockerfile never copies `mcp_server/`, so the
runtime image is unchanged · **the golden set still passes 14/14 against production**, confirming the
request path was untouched.

---

## Phase 8 — Post-submission health check (part 1 of 2)

**Asked for:** the post-submission health check — re-hit the live URL, confirm spend, volume, and that
nothing has drifted.

**Produced:** the Phase 8 report with part 1 complete and part 2 specified, plus a recorded
baseline for the checks that cannot run yet.

**Changed:**
1. **Split the phase rather than faking its headline result.** Its sharpest purpose is verifying the
   two code paths that have never executed — log rotation and the daily spend rollover — and both fire
   only at UTC midnight. It is currently 17:04 UTC, ~7h short, and the deployed instance still reports
   `spend.date: 2026-07-30`. Reporting "rotation verified" would be false; reporting "rotation did not
   fire" would be true and misleading, since it has not had the chance. Neither belongs in a report, so
   part 1 is what is checkable now and part 2 is scheduled with exact commands and expected values.
2. **Captured the baseline after the eval run, not before**, so tomorrow's numbers compare against a
   known state rather than a moving one: 136 turns, $0.186995, `spend.date: 2026-07-30`.
3. **Used the Phase 7 MCP server as the method**, which is what its forward review said it would be —
   the four tools are exactly the four questions this phase asks.

**Verified:** `bot_health` reachable, prompt 1.3, corpus sha `96cd2fffaf6d`, sink writable ·
`refusal_breakdown` 119 turns, 46.2%, `unexpected_reasons: []` · `spend_today` $0.161 of $5.00 (3.22%) ·
`bot_stats` 89.1% cache hit, p50 2,418 ms · **golden set 14/14 against the deployed URL** · volume
attached at `/data`, Ready, 91 MB of 5,000 MB. Nothing has drifted since Phase 7.

---

## Phase 8 part 2 + the two open documentation items

**Asked for:** finish what was left — the midnight checks, `CLAUDE.md`, and a hook.

**Produced:** Phase 8 report completed with part 2 results, a tightened `CLAUDE.md` (249 lines, back
under its own cap), `.claude/hooks/guard-commit.sh` wired as a PreToolUse hook, and `.claude/README.md`.

**Changed:**
1. **Both midnight paths verified.** Spend rollover fired eagerly — `/health` alone triggers it, so it
   rolled to 2026-07-31 with $0.00 and 0 turns before any traffic. Log rotation fired lazily.
2. **My own test criterion for rotation was wrong, and would have raised a false alarm.** The plan said
   "still 136 turns tomorrow → rotation did not fire". At 00:25 it read 136 — but `turns_today` was 0,
   and `TimedRotatingFileHandler` rolls on the next *emit*, not on a timer. The criterion conflated
   "broken" with "not yet triggered". The discriminating test is to write one record: turns went
   136 → **1**, not 137, so the file rolled. **Fourth instance of asserting a substring/proxy where I
   meant a property**, and the worst shape yet because it was falsifiable in the wrong direction.
3. **`CLAUDE.md` had not been touched since Phase 1** — a miss I recorded rather than quietly fixed.
   Phase 6's exit criteria said "both documents tightened" and I had only ever updated `plan.md`.
   Updated the Layout, the 13→14 case count, the four measured prefix sizes, the resolved case-study
   gate, and six deployed-only defects; then **cut it back under its own 250-line cap** by trimming
   prose rather than raising the cap, since the file says to fix such things rather than work around
   them.
4. **The hook guards what permissions cannot see.** The deny list already covers force-push, hard
   reset, and reading `.env` — all identifiable from the command. Both incidents this repo actually had
   were *content* problems: a secret arriving via `git add -A`, and a 9.5 MB PDF swept into history
   because only the result was checked. Verified against six paths including its own failure modes.

**Verified:** rotation and rollover both confirmed on the deployed instance · 142 tests · ruff clean ·
`CLAUDE.md` 249 lines · hook blocks a staged secret, a staged `.env`, and a 2 MB file, and passes
through a clean commit, a non-commit command, and being run outside a git repo.

---

## Phase 9 — Playground tab

**Asked for:** a second tab that runs inference and shows tokens, cost, latency and everything else
relevant, with the system prompt in a scrollable window at the end.

**Produced:** `web/src/Shell.jsx`, `Playground.jsx`, `markdown.jsx`, an extended `/api/config`,
`cost_usd` + `latency_ms` on the `done` frame, and 9 new test functions.

**Changed:**
1. **The prompt window was cut, and the reasoning reversed my own.** I first asked whether the prompt
   was *secret* — it is not — and called exposure defensible. The right question is what publishing it
   *enables*: the `[[refusal:…]]` syntax becomes injectable through a user message to fake or suppress
   a refusal, corrupting the field this bot is judged on, and the exact wording of every rule is a map
   of the seams between them. Replaced with metadata; a later pass also dropped the per-section
   breakdown, since naming a `marker` section is a smaller version of the same leak.
2. **Almost nothing needed instrumenting.** The `done` frame already carried the token counters,
   status and refusal_reason; `App.jsx` had been timing first-token since Phase 0c and discarding it.
   Only `cost_usd`, `latency_ms` and the prompt metadata were genuinely missing.
3. **Computed latency and cost once rather than once per consumer.** The `done` frame is emitted
   before the `finally` that logs, so the obvious implementation reports 1,948 ms on screen beside
   1,949 ms in the log for the same turn. Verified they now agree exactly: 2278 / 0.006826 in both.
4. **Corrected a claim I had put in two documents.** "`tests/test_ui.py` scans a file list" was wrong
   — it is a mix, one check globs and seven were hardcoded to `App.jsx`. Put the playground in a new
   file and those seven would have kept passing while covering nothing. All seven now parametrise over
   every component, with an assertion that the glob is non-empty.
5. **Two follow-on changes from the requester using the running app:** user turns align right, and
   inline markdown renders as real formatting — the model writes `**bold**` constantly despite
   `_FORMAT` asking for plain prose, and we were showing the asterisks. Written as a 44-line tokeniser
   returning React elements, never HTML: `dangerouslySetInnerHTML` would be an injection vector for
   model output. Frontend dependencies remain two.
6. **Two more instances of asserting a substring where I meant a property**, bringing the build total
   to six. One of them *passed* while testing almost nothing — the prompt-leak test walked
   `app.routes` and missed every sub-router path.

**Verified:** 155 tests · ruff clean · frame and log agree exactly on latency and cost · no GET route
returns the prompt text, checked against the OpenAPI schema · no rate constants in the component · the
golden set 14/14 against production at the time of the Phase 9 deploy. **Not verified:** visual
sign-off, and the §5 changes have never been deployed — Railway is disconnected by request and the
deploy is deferred to the end.
