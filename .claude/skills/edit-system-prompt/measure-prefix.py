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

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

FLOOR = 4096
THIN = 4300  # a margin under this is one prose trim away from breaking caching


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    import anthropic

    from app.llm.prompt import (
        MEASURED_SYSTEM_TOKENS,
        SYSTEM_PROMPT_VERSION,
        build_system_blocks,
    )

    live = anthropic.Anthropic().messages.count_tokens(
        model="claude-haiku-4-5",
        system=build_system_blocks(),
        messages=[{"role": "user", "content": "x"}],
    ).input_tokens

    margin = live - FLOOR
    drift = live - MEASURED_SYSTEM_TOKENS

    print(f"live count_tokens      : {live:,}")
    print(f"recorded in prompt.py  : {MEASURED_SYSTEM_TOKENS:,}   (drift {drift:+,})")
    print(f"margin over the {FLOOR} floor : {margin:+,}")
    print(f"SYSTEM_PROMPT_VERSION  : {SYSTEM_PROMPT_VERSION}")
    print()

    problems = []
    if live < FLOOR:
        problems.append(
            f"BELOW THE FLOOR by {FLOOR - live}. Caching will silently stop and every turn will "
            f"cost ~6x more. Do not deploy this — add real content back, do not pad."
        )
    elif margin < THIN - FLOOR:
        problems.append(
            f"Margin is only {margin} tokens. One prose trim breaks caching, silently. "
            f"Consider whether the edit should be smaller."
        )

    if drift != 0:
        problems.append(
            f"Update MEASURED_SYSTEM_TOKENS in app/llm/prompt.py to {live} "
            f"(a test fails past 150 drift), append a line to its history comment saying WHY it "
            f"changed, and fix the 'Measured at N tokens' figure in build_system_blocks()'s "
            f"docstring."
        )
        problems.append(
            f"Bump SYSTEM_PROMPT_VERSION (currently {SYSTEM_PROMPT_VERSION}). Log lines from two "
            f"prompts are otherwise indistinguishable, which makes before/after comparison in "
            f"interactions.jsonl impossible."
        )

    if not problems:
        print("OK — nothing to update. The recorded value matches and the margin is healthy.")
        return 0

    print("TO DO:")
    for p in problems:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
