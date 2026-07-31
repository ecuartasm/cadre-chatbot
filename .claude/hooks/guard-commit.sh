#!/usr/bin/env bash
# PreToolUse guard on `git commit`.
#
# Permissions already deny the things identifiable from the *command* — force-push, hard reset,
# reading .env. This hook exists for what a permission rule cannot see: the **content** being
# committed. Both checks below are incidents this repo actually had, not hypotheticals:
#
#   1. A secret in staged content. CLAUDE.md: "Never commit a secret... if a key is ever pushed,
#      rotate it." A key reaches history through `git add -A`, not through a command anyone would
#      think to deny.
#   2. A large binary. `git add -A` swept a 9.5MB page capture into history unnoticed, because the
#      commit was run in the same breath as the add and only the result was checked.
#
# Blocks with exit 2, which returns the message to Claude rather than silently failing.
# Never blocks on its own errors: a guard that breaks the workflow when *it* is wrong is worse than
# no guard.

set -uo pipefail

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("tool_input",{}).get("command",""))
except Exception: print("")' 2>/dev/null)

# Only guard commits. Everything else passes straight through.
case "$CMD" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

command -v git >/dev/null 2>&1 || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

FAIL=""

# --- 1. Secrets in staged content -------------------------------------------------------
# Anthropic keys, generic long tokens after an api_key-ish name, and .env itself.
SECRETS=$(git diff --cached -U0 2>/dev/null | grep -nE \
  'sk-ant-[A-Za-z0-9_-]{20,}|(api[_-]?key|secret|password|token)["'"'"']?\s*[:=]\s*["'"'"'][A-Za-z0-9_-]{24,}' \
  | head -5)
if [ -n "$SECRETS" ]; then
  FAIL="${FAIL}
SECRET-SHAPED STRING IN STAGED CONTENT:
${SECRETS}
If this is a real key: unstage it, rotate the key, and do not simply remove it in a later commit."
fi

if git diff --cached --name-only 2>/dev/null | grep -qE '(^|/)\.env($|\.)'; then
  FAIL="${FAIL}
.env IS STAGED. It is gitignored for a reason; unstage it."
fi

# --- 2. Large files ---------------------------------------------------------------------
# 1MB. Big enough to never fire on source, small enough to catch a stray PDF or image.
LIMIT=1048576
BIG=$(git diff --cached --name-only --diff-filter=AM 2>/dev/null | while read -r f; do
  [ -f "$f" ] || continue
  SZ=$(wc -c < "$f" 2>/dev/null || echo 0)
  [ "$SZ" -gt "$LIMIT" ] && printf '  %s (%s KB)\n' "$f" "$((SZ / 1024))"
done)
if [ -n "$BIG" ]; then
  FAIL="${FAIL}
LARGE FILE(S) STAGED — git history is permanent, so check this is deliberate:
${BIG}
If it is reference material rather than source, gitignore it and keep an extracted summary instead."
fi

if [ -n "$FAIL" ]; then
  printf 'Blocked by .claude/hooks/guard-commit.sh%s\n\nRun `git status` and read the STAGED LIST, not just the result.\n' "$FAIL" >&2
  exit 2
fi

exit 0
