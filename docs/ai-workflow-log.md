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
