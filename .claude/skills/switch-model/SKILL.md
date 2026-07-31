---
name: switch-model
description: Use when changing which Claude model the bot runs — editing ANTHROPIC_MODEL in .env, swapping claude-haiku-4-5 for claude-sonnet-5 or back, adding a new model, or answering "is caching still working after the swap?" and "what does this cost now?". Also use when a model change appears to have had no effect, or when the cache floor, prefix size, or spend cap needs re-checking per model.
---

# Switching the model

The switch is meant to be one line in `.env`. It is *tested* as one line — but four facts change
underneath it, and **three of the four fail silently** when they are wrong.

```bash
uv run python .claude/skills/switch-model/switch-model.py                    # what is set now
uv run python .claude/skills/switch-model/switch-model.py claude-sonnet-5    # switch + verify
uv run python .claude/skills/switch-model/switch-model.py --check            # verify, change nothing
```

The script edits one line, backs the file up to `.env.bak` first, writes atomically (the file holds
the API key), and then **proves the switch took effect** — which is the part worth having.

## Why this is not just `sed -i`

Editing `.env` and moving on is exactly what shipped a broken switch for a whole phase.
`load_dotenv()` sat below `main.py`'s import block, so `app.llm.client` had already resolved
`ANTHROPIC_MODEL` before the file was read. Setting `claude-sonnet-5` did **nothing**. The app ran
Haiku, `/health` agreed with the file, and 171 tests passed.

Two things hid it, and both are worth recognising by shape:

- **The file agreed with the fallback.** `.env` said `claude-haiku-4-5` and `DEFAULT_MODEL` was also
  `claude-haiku-4-5`, so the broken lookup returned the right answer for the wrong reason.
- **Every check used a shell variable.** `ANTHROPIC_MODEL=claude-sonnet-5 uvicorn …` is a real
  environment variable, so it skips `.env` entirely — and therefore skips the bug. The results from
  those runs were genuine; they came through a door no user opens.

⚠️ **Never verify a `.env` switch with a shell variable.** The script runs its check in a subprocess
with `ANTHROPIC_MODEL` explicitly removed, which is the only path that matches what a user gets.

## The four things that change

Every one lives in `app/llm/models.py`. That file is the registry; nothing else may hold a per-model
number.

| | Haiku 4.5 | Sonnet 5 | Fails how? |
|---|---|---|---|
| **Cache floor** | 4,096 | 1,024 | **Silently.** No error — `cache_creation_input_tokens` just stays `0` and every turn pays full price. |
| **Four rates** | $1 / $5 | $3 / $15 (3× across the board) | **Silently.** The spend cap throttles on money never spent, or fails to throttle at all. |
| **Measured prefix** | 5,383 | 7,415 | **Silently.** Same bytes, 38% apart — a shared constant is wrong for whichever model was not measured. |
| **`thinking`** | not supported | `{"type": "disabled"}` | Loudly — the API rejects the parameter. The one that *can't* hide. |

⚠️ **Cache floors are non-monotonic.** The cheaper, smaller model has the **higher** floor. It cannot
be inferred from the tier, which is why guessing one is the mistake that never announces itself.

## Adding a model — not an `.env` edit

The script refuses an id with no `models.py` row, deliberately. A new model needs:

1. A `ModelSpec` — floor, four rates, `thinking` support, window, max output. **Look these up; do
   not recall them.** The Models API and the pricing page are the sources.
2. A **measured** prefix in `MEASURED_SYSTEM_TOKENS_BY_MODEL`, from a live `count_tokens` against
   that model's own tokeniser. Run `.claude/skills/edit-system-prompt/measure-prefix.py`, which
   iterates every model in the registry.
3. `plan.md` records a third model as out of scope — two is what the switch is tested against. Adding
   one is a decision, not a config change.

## After switching — what actually needs running

```bash
pytest && ruff check .                                                  # structure
python eval/golden.py --url http://127.0.0.1:8000 --suite lite          # 14 cases, the gate
python eval/golden.py --url http://127.0.0.1:8000 --suite full          # 71 cases — do run this
```

**Run `full` after a swap.** A model change is an *environment* change, and this build's rule is that
local green is weaker evidence than it feels. 171 unit tests passed while Sonnet printed a refusal
tag into the chat.

Costs scale with the model: lite is ~$0.03 on Haiku and ~$0.09 on Sonnet; full is ~$0.15 and ~$0.45.

### The two things to watch that a green suite will not tell you

Both were found by swapping, and neither is a bug in the code:

- **Where the model puts the refusal marker.** Haiku leads with `[[refusal:<slug>]]` as instructed.
  **Sonnet uses it as a mid-answer section separator.** `MarkerScanner` now strips it anywhere, but
  the *first* thing to check on any new model is whether a raw `[[refusal:` ever reaches the browser.
  Grep an eval run for it — it is the one Phase 3 failure a user sees directly.
- **Whether soft refusals still get tagged.** Sonnet reads `acknowledge-only` corpus entries as
  answerable where Haiku reads them as refusals, so the client-portal case tags **0/5 on Sonnet**
  while the same case passes on Haiku. The prose is identical and safe either way; only the
  classification moves, which means `/api/stats` under-reports refusals on Sonnet. **Measure it over
  five runs, don't infer it from one** — a case that fails once and passes on re-run is on a
  knife-edge, and counting is what distinguishes that from a systematic difference.

**Reading a failure:** a *boundary* failure — a price, an invented URL, a client name, a prompt leak
— is a defect and blocks the swap. A *tagging* failure is observability, and is expected to differ
between models. Do not chase the second as if it were the first.

## Cost, so the choice is made on numbers

Both computed from the active model by `app/obs/spend.py`, never hardcoded:

| | Haiku 4.5 | Sonnet 5 |
|---|---|---|
| Worst-case turn (cache write) | $0.00749 | $0.03009 |
| Turns on the $5/day cap | **667** | **166** |

Every Sonnet rate is exactly 3×, so the gap compounds with volume rather than shrinking — **scale is
an argument for Haiku, not against it.** Sonnet is the escalation model, chosen on measured evidence
that the answers are better, not on a hunch that a bigger model must be.

## Deploying a switch

`.env` is gitignored and never deployed. **Railway's own environment variable governs there** — set
`ANTHROPIC_MODEL` in the dashboard, not in a committed file. `override=False` (the dotenv default) is
relied on for exactly this: a real environment variable beats the file.

After deploying, re-run lite against the deployed URL. See the `verify-in-production` skill.

## What not to do

- **Don't verify with a shell variable.** It bypasses the feature you are testing. See above.
- **Don't test a switch using the default model's own value** — it passes against broken code. That
  is the trap `tests/test_env_switch.py` asserts its way out of.
- **Don't guess a cache floor.** Non-monotonic, silent when wrong, and cheap to look up.
- **Don't trim the prompt to save money on the more expensive model.** The floor inverts the usual
  instinct — below it, caching stops and a turn costs ~6× more.
- **Don't skip `--suite full`** because lite passed. Lite passed on Sonnet while the marker was
  leaking into two answers in four.
