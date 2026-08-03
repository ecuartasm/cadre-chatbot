#!/usr/bin/env python3
"""Measure the assembled system prefix and report what bookkeeping needs updating.

Run after ANY edit to app/llm/prompt.py. It exists because the failure it guards is silent: below
claude-haiku-4-5's 4,096-token minimum cacheable prefix, caching stops with no error and no warning,
and every turn costs ~6x more forever.

Reports rather than edits. The values it names are ones a human should change deliberately.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo root, three levels up from .claude/skills/<name>/. Computed rather than hardcoded so the
# script works whatever directory it is invoked from.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

THIN_MARGIN = 200  # a margin under this is one prose trim away from breaking caching


# Measure the assembled prefix against every model in the registry and report what to update.
#   out: exit code -- 0 when every model clears its floor with margin, 1 when something needs
#        attention (below the floor, or drifted from the recorded value).
# ⚠️ Counts against Anthropic DIRECTLY: count_tokens 404s through a gateway, and the SDK reads
# ANTHROPIC_BASE_URL itself, so measuring through OpenRouter would silently fail.
def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    import anthropic

    from app.llm.models import MODELS
    from app.llm.prompt import (
        MEASURED_SYSTEM_TOKENS_BY_MODEL,
        SYSTEM_PROMPT_VERSION,
        build_system_blocks,
    )

    client = anthropic.Anthropic()
    blocks = build_system_blocks()
    problems: list[str] = []
    stale: dict[str, int] = {}

    print(f"SYSTEM_PROMPT_VERSION  : {SYSTEM_PROMPT_VERSION}\n")

    # Every model, not just the active one. The two tokenise the same prompt very differently
    # (6,054 vs 8,336 — a 38% gap), so measuring only the current one leaves the other silently
    # stale and its floor test asserting a number that no longer describes anything.
    for mid, spec in MODELS.items():
        live = client.messages.count_tokens(
            model=mid, system=blocks, messages=[{"role": "user", "content": "x"}]
        ).input_tokens
        recorded = MEASURED_SYSTEM_TOKENS_BY_MODEL.get(mid)
        margin = live - spec.cache_floor
        drift = live - recorded if recorded is not None else None

        drift_s = "not recorded" if drift is None else f"drift {drift:+,}"
        print(f"  {mid:20} live {live:>6,} · floor {spec.cache_floor:>5,} · "
              f"margin {margin:>+6,} · {drift_s}")

        if live < spec.cache_floor:
            problems.append(
                f"{mid}: BELOW THE FLOOR by {spec.cache_floor - live}. Caching stops silently and "
                f"every turn costs ~6x more. Do not deploy — add real content back, do not pad."
            )
        elif margin < THIN_MARGIN:
            problems.append(
                f"{mid}: margin is only {margin} tokens. One prose trim breaks caching, silently."
            )
        if drift is None or drift != 0:
            stale[mid] = live

    print()
    if stale:
        pairs = ", ".join(f'"{m}": {n}' for m, n in stale.items())
        problems.append(
            f"Update MEASURED_SYSTEM_TOKENS_BY_MODEL in app/llm/prompt.py to {{{pairs}}} "
            f"(a test fails past 150 drift), append a line to the history comment saying WHY it "
            f"changed, and fix the 'Measured at N tokens' figure in build_system_blocks()."
        )
        problems.append(
            f"Bump SYSTEM_PROMPT_VERSION (currently {SYSTEM_PROMPT_VERSION}) — log lines from two "
            f"prompts are otherwise indistinguishable."
        )

    if not problems:
        print("OK — nothing to update. Every model matches its record and clears its floor.")
        return 0

    print("TO DO:")
    for p in problems:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
