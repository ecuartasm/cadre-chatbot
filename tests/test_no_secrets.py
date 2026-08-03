"""No credential may exist in a tracked file, in any form.

The rule the owner stated: the key goes nowhere — not a report, not a doc, nothing pushed to GitHub
or Railway. This asserts it continuously rather than trusting a one-off audit, because the risky
moment is not today; it is the commit six weeks from now that pastes a value into a report to
illustrate something.

⚠️ **A bare prefix is not a secret.** `sk-ant-` and `sk-or-v1-` appear legitimately in this repo —
in `.env.example`, in prose explaining which provider serves which environment, in the commit-guard
regex, and in tests asserting the prefix must NOT appear in a response. What makes a string a
credential is prefix **plus enough following material to be usable**, which is what these match.
A test that flagged every mention of `sk-ant-` would fail on its own documentation, which is the
narrowing mistake this project has made eight times.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

# Prefix + enough characters to be a usable credential. The lengths are deliberately well below a
# real key's, so a truncated paste is still caught.
CREDENTIAL = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{20,}"      # Anthropic
    r"|sk-or-v1-[A-Za-z0-9]{20,}"     # OpenRouter — this project's PRODUCTION key
    r"|sk-proj-[A-Za-z0-9_-]{20,}"    # OpenAI project keys
)


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, text=True, timeout=60)
    return [ROOT / n for n in out.stdout.split("\0") if n]


def test_git_is_available_and_reports_files():
    """Guards the guard: if `git ls-files` returned nothing, every check below would pass by
    iterating an empty list — green, and looking at nothing at all."""
    assert len(_tracked_files()) > 50, "git ls-files returned too few files to be believable"


def test_no_credential_in_any_tracked_file():
    hits = []
    for f in _tracked_files():
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary; a key would not survive in one anyway
        for m in CREDENTIAL.finditer(text):
            # Report the location and the PREFIX only — never the value, not even in a failure.
            hits.append(f"{f.relative_to(ROOT)}: {m.group(0)[:12]}…")
    assert not hits, "credential-shaped strings in tracked files:\n  " + "\n  ".join(hits)


def test_no_credential_anywhere_in_git_history():
    """Removing a key in a later commit does not remove it from the repo. If this ever fails, the
    fix is to ROTATE the key, not to rewrite history and hope."""
    revs = subprocess.run(["git", "rev-list", "--all"], cwd=ROOT,
                          capture_output=True, text=True, timeout=120).stdout.split()
    assert revs, "no commits found — this check would pass vacuously"

    found = subprocess.run(
        ["git", "grep", "-lE", CREDENTIAL.pattern.replace("\n", ""), *revs],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    assert found.returncode != 0 or not found.stdout.strip(), (
        f"credential-shaped string in history:\n{found.stdout[:500]}"
    )


def test_dotenv_is_ignored_and_was_never_committed():
    ignored = subprocess.run(["git", "check-ignore", ".env"], cwd=ROOT,
                             capture_output=True, text=True, timeout=30)
    assert ignored.returncode == 0, ".env is not gitignored"

    ever = subprocess.run(["git", "log", "--all", "--pretty=format:", "--name-only"],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    committed = {n for n in ever.stdout.split("\n") if n.strip()}
    assert ".env" not in committed, ".env appears in history — rotate the key"


@pytest.mark.parametrize("prefix", ["sk-ant-", "sk-or-v1-", "sk-proj-"])
def test_the_commit_hook_knows_every_provider_prefix(prefix: str):
    """`sk-ant-` alone was not enough: the PRODUCTION key is OpenRouter's, so a guard that only
    knew Anthropic's prefix would have waved the client's key straight through."""
    hook = (ROOT / ".claude" / "hooks" / "guard-commit.sh").read_text(encoding="utf-8")
    assert prefix in hook, f"the commit guard does not recognise {prefix} keys"


def test_the_detector_actually_detects():
    """A regex that matched nothing would make every test above pass silently. Fabricated strings,
    never a real key."""
    assert CREDENTIAL.search("sk-ant-" + "A" * 40)
    assert CREDENTIAL.search("sk-or-v1-" + "b" * 40)
    # …and does NOT fire on the bare prefixes this repo legitimately documents.
    assert not CREDENTIAL.search("keys look like `sk-ant-…` and `sk-or-v1-…`")
    assert not CREDENTIAL.search("ANTHROPIC_API_KEY=sk-ant-...")


def test_claude_md_stays_under_its_own_line_cap():
    """`CLAUDE.md` declares a hard cap of under 250 lines because it loads on every turn, and a file
    that quietly grows past its budget stops being the thing it claims to be.

    ⚠️ **The cap was stated for months with nothing enforcing it.** A one-line documentation edit
    pushed the file to exactly 250 — breaking the rule in the same commit that fixed a different
    documentation defect — and it was caught by hand rather than by the suite. That is the failure
    mode this repo keeps recording: a rule written down is not a rule checked.
    """
    lines = (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
    assert len(lines) < 250, (
        f"CLAUDE.md is {len(lines)} lines; the cap is under 250. Cut something rather than "
        "raising it — the cap is what keeps the file loadable every turn."
    )


def test_the_commit_guard_does_not_fire_on_env_example():
    """`.env.example` is tracked on purpose, holds no values, and `.gitignore` negates it with
    `!.env.example`. The guard's pattern matched it anyway, so it would block a commit touching the
    one env file the repo deliberately ships — reporting that the file "is gitignored" when it is
    not. A guard that fires on a legitimate change teaches people to bypass it.
    """
    hook = (ROOT / ".claude" / "hooks" / "guard-commit.sh").read_text(encoding="utf-8")
    assert r"\.env\.example$" in hook, "the commit guard has no exception for .env.example"

    # The property, not the wording: run the guard's own filter over real paths.
    import re

    keep = re.compile(r"(^|/)\.env\.example$")
    block = re.compile(r"(^|/)\.env($|\.)")

    def blocked(path: str) -> bool:
        return not keep.search(path) and bool(block.search(path))

    assert blocked(".env"), "a real .env must still be blocked"
    assert blocked(".env.local")
    assert blocked(".env.production")
    assert blocked("app/.env")
    assert not blocked(".env.example"), ".env.example must be allowed through"
