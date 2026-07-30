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
