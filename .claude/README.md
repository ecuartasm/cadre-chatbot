# `.claude/` — Claude Code configuration for this repo

One of each: a subagent, two commands, and a hook. Each earns its place against something this
project actually hit, rather than existing to fill a slot.

## Subagent — `agents/kb-updater.md`

Detects drift between the committed corpus and the live cadreai.com, then **proposes** changes. It
never writes `content/knowledge-base.md` itself.

That restriction is the point. The corpus is the product, every fact must be traceable to a
`content/raw/` file, and the one time a fact entered this project unverified — "Bill Lyons, CEO of
Griffin Funding" — the company name was fabricated upstream and survived because a plausible-looking
corroboration made the *pairing* look checked. A subagent that could write the corpus directly would
reintroduce exactly that path.

## Commands — `commands/`

- **`/update-kb`** — the full corpus-refresh loop, five stages: **detect** (kb-updater) → **draft** a
  candidate file, re-verifying each fact against `content/raw/` → **🚦 approve** via an explicit
  question, with anything negative-knowledge asked separately and defaulting to reject → **back up
  and apply** → **verify** (tests, redeploy, golden set).

  Two properties worth keeping if this is ever edited. The subagent still has **no Write tool** — the
  drafting moved to the main session rather than granting it write access, so the guarantee stays
  structural. And the backup at stage 4 is **verified with `cmp` before the corpus is overwritten**: a
  backup that fails silently converts "I can undo this" from a fact into an assumption.
- **`/log-decision`** — append a decision to `docs/ai-workflow-log.md` while it is fresh. Reconstructing
  "what I changed and why" at the end of a phase defeats the purpose of keeping the log.

## Hook — `hooks/guard-commit.sh` (PreToolUse on Bash)

Guards `git commit` against two things a **permission rule cannot see**, because permissions match on
the command and these are properties of the *content*:

| Check | The incident behind it |
|---|---|
| Secret-shaped strings in staged content, and `.env` staged | `CLAUDE.md`: "Never commit a secret… if a key is ever pushed, rotate it." A key arrives via `git add -A`, not via a command anyone would deny |
| Any staged file over 1 MB | `git add -A && git commit` in one breath swept a 9.5 MB page capture into history unnoticed — only the *result* was checked, not the staged list |

Blocks with exit 2 so the reason reaches Claude. It never blocks on its own errors — not a git repo,
no git, unparseable input all pass through, because a guard that breaks the workflow when *it* is
wrong is worse than no guard.

Verified against six paths: non-commit passthrough · clean commit allowed · staged secret blocked ·
staged `.env` blocked · 2 MB file blocked · outside a repo, allowed.

## What is deliberately NOT a hook

**Auto-commit/push on `Stop`.** `Stop` fires after *every* assistant turn, not at phase boundaries, so
it would produce dozens of commits per phase with generated messages — the opposite of "small,
frequent commits with descriptive messages" — and could publish a broken intermediate state or a
secret before `.gitignore` was right. Hooks are for guardrails; taking outward-facing actions on your
behalf is not a guardrail. See the note in `plan.md`'s phase-exit checklist.
