---
description: Re-scrape cadreai.com, propose corpus updates, get explicit approval, then apply and verify
argument-hint: (optional) substring to limit which pages are re-scraped
allowed-tools: Bash, Read, Write, Edit, Grep, Glob, Task, AskUserQuestion
---

Refresh the knowledge-base corpus from the live site and take it all the way to a deployed, verified
change — **with an explicit approval gate in the middle that must not be skipped.**

Scope: $ARGUMENTS (empty = all 36 pages; otherwise pass through as `--only <substring>`)

Five stages. Do not merge them, and do not proceed past stage 3 without a real answer.

---

## 1. Detect — delegate to the `kb-updater` subagent

Run the **kb-updater** subagent. It carries the full procedure and the boundary rules, and the work is
context-heavy (36 pages of markdown in, a short diff out) — exactly what a separate context window is
for.

It has **no Write tool**, deliberately. That is a hard guarantee rather than an instruction it could
drift from: an unattended agent writing straight to the corpus is the Griffin Funding failure
automated and repeated on every refresh. Do not "helpfully" grant it Write to make this smoother.

Report its output: `PAGES CHANGED / PROPOSED EDITS / 🔴 NEEDS REVIEW / NOISE / TOKEN IMPACT`.

**If nothing changed, say so and stop.** A no-op is a valid and useful result.

## 2. Draft — you build the candidate, verifying as you go

Write `content/knowledge-base.proposed.md`: a **complete candidate file**, not a patch.

This is a second check, not transcription. For every proposed change, open the backing
`content/raw/*.md` yourself and confirm the text is genuinely on the page. The Griffin Funding error
survived because a plausible external corroboration validated a pairing the source never made — you
are the reader who goes back to the literal page.

Carry every `disclosure` tag and `refusal_reason` through unchanged unless the change is explicitly
about one. Then show the diff:

```bash
git diff --no-index content/knowledge-base.md content/knowledge-base.proposed.md
```

## 3. 🚦 Approve — ask, and mean it

**Use AskUserQuestion. Never infer approval from anything earlier in the conversation.**

Put in the question what actually changes: sections touched, facts added or removed, and the token
delta against the 4,096 floor.

- **Anything flagged 🔴 gets its own question, and the default is reject.** Pricing, portal access,
  client names, headcount, revenue, engagement counts, security claims, contact details. Never bundle
  one of these into a batch approval.
- Ordinary factual and cosmetic changes may be approved as a single batch.

If the answer is no or partial: apply only what was approved, or delete the proposed file and stop.
**State plainly what you did not apply.**

## 4. Back up, then apply — and update the number that guards the floor

Only after approval. **Back up first, and confirm the backup landed before overwriting anything** — a
backup step that fails silently is worse than none, because it converts "I can undo this" from a fact
into an assumption.

```bash
mkdir -p content/backups
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="content/backups/knowledge-base-$STAMP.md"

cp content/knowledge-base.md "$BACKUP"
cmp -s content/knowledge-base.md "$BACKUP" \
  || { echo "BACKUP FAILED — not overwriting the corpus"; exit 1; }
echo "backed up to $BACKUP ($(wc -c < "$BACKUP") bytes)"

mv content/knowledge-base.proposed.md content/knowledge-base.md
```

Tell the user the backup path. **To undo, at any point before or after deploy:**

```bash
cp content/backups/knowledge-base-<STAMP>.md content/knowledge-base.md && railway up --ci
```

`content/backups/` is gitignored on purpose. Git is the durable history — this is the immediate undo,
and it works even when the corpus had uncommitted edits at the time, which is exactly when git would
not have saved you. Committing copies of a file git already versions would just be noise.

```bash
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
import anthropic; from app.llm.prompt import build_system_blocks
print(anthropic.Anthropic().messages.count_tokens(model='claude-haiku-4-5',
  system=build_system_blocks(), messages=[{'role':'user','content':'x'}]).input_tokens)"
```

Update `MEASURED_SYSTEM_TOKENS` in `app/llm/prompt.py` to that number. A test fails if it drifts by
more than 150, and that test is the only thing between a trimmed corpus and **silently** disabled
caching at ~6× the per-turn cost. **If the new number is under ~4,200, stop and say so prominently.**

## 5. Verify — the corpus is baked into the image, so an edit is inert until you redeploy

```bash
pytest && ruff check .        # the loader re-validates its markers and re-parses the 16-slug enum
railway up --ci               # WITHOUT this the live bot still serves the old corpus
python eval/golden.py --url https://cadre-chatbot-production.up.railway.app
```

Confirm `/api/config` reports the new `corpus.sha256`. The first turn after a redeploy pays a cache
**write** (~$0.0063) rather than a read — expected, not a regression.

Then append a `docs/ai-workflow-log.md` entry: what changed, what was approved, what was rejected.
**Do not commit or push without asking** — the corpus is the product, and committing it deserves the
same deliberateness as approving it.
