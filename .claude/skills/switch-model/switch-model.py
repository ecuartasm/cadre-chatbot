#!/usr/bin/env python3
"""Switch ANTHROPIC_MODEL in .env, then prove the switch actually took effect.

The proving half is the point. Editing `.env` is one line of sed; the reason this script exists is
that the edit silently did nothing for an entire phase, and nothing in the app said so:

  - `load_dotenv()` used to run after `app.llm.client` had already resolved ANTHROPIC_MODEL, so the
    file was read too late and the app kept the default model.
  - It was invisible because `.env` and DEFAULT_MODEL held the SAME value, so the broken lookup
    returned the right answer for the wrong reason.
  - Every check had used a shell variable (`ANTHROPIC_MODEL=... uvicorn`), which bypasses `.env`
    and therefore bypasses the bug.

So verification here always runs in a SUBPROCESS with the shell variable explicitly removed, which
is the only path that reflects what a user editing `.env` will actually get.

Usage:
    switch-model.py                 # show current state and what is available
    switch-model.py <model-id>      # switch to it, verify, report cost + next steps
    switch-model.py --check         # verify the current .env without changing anything

Reports rather than assumes. It will not switch to a model that has no `models.py` row, and it will
not stay quiet about a prefix that fails to clear the new model's cache floor.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# The file this script edits. Holds the API key, which is why nothing here ever prints its
# contents -- only the single line being changed.
ENV_PATH = ROOT / ".env"
KEY = "ANTHROPIC_MODEL"

sys.path.insert(0, str(ROOT))

THIN_MARGIN = 200  # a margin under this is one prose trim away from silently losing caching

G, Y, R, B, DIM, OFF = "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[2m", "\033[0m"


def ok(m: str) -> str:
    return f"{G}✓{OFF} {m}"


def warn(m: str) -> str:
    return f"{Y}!{OFF} {m}"


def bad(m: str) -> str:
    return f"{R}✗{OFF} {m}"


# --- .env handling -------------------------------------------------------------------
#
# Rewrites ONE line and leaves every other byte alone. The file holds the API key, so it is never
# regenerated from parsed values, never printed, and never written non-atomically.


# Read the currently configured model from .env.
#   out: the model id, or None when the key is absent
def read_env_model() -> str | None:
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{KEY}=") and not stripped.startswith("#"):
            return stripped.split("=", 1)[1].strip()
    return None


# Rewrite the ANTHROPIC_MODEL line in place.
#   in : new_model -- the model id to set
#   out: path of the backup written first
# Line-by-line rewrite, never a regenerate: every other line -- including the key -- is copied
# through untouched.
def write_env_model(new_model: str) -> Path:
    """Replace the ANTHROPIC_MODEL line in place. Returns the backup path."""
    original = ENV_PATH.read_text(encoding="utf-8")
    # Sibling path, not `with_suffix` — on a dotfile named `.env` that yields `.env.env.bak`.
    backup = ENV_PATH.parent / ".env.bak"  # `.env.*` is gitignored
    shutil.copy2(ENV_PATH, backup)

    lines = original.splitlines(keepends=True)
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{KEY}=") and not line.strip().startswith("#"):
            newline = "\n" if line.endswith("\n") else ""
            lines[i] = f"{KEY}={new_model}{newline}"
            found = True
            break
    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(f"{KEY}={new_model}\n")

    tmp = ENV_PATH.parent / ".env.tmp"
    tmp.write_text("".join(lines), encoding="utf-8")
    tmp.replace(ENV_PATH)  # atomic: a crash mid-write cannot truncate the file holding the key
    return backup


# --- verification --------------------------------------------------------------------


# Prove the change took effect, through the SAME path a real run uses.
#   out: what the app resolves -- model, floor, rates, recorded prefix
# ⚠️ Runs in a SUBPROCESS with the shell variable REMOVED. A shell variable bypasses .env
# entirely, which is exactly how the "editing .env does nothing" bug stayed hidden for a phase.
def resolve_via_dotenv() -> dict[str, object]:
    """What the app ACTUALLY resolves, in a fresh interpreter with the shell override removed.

    Not importable in-process: this module may already have `app.llm.client` loaded, and its MODEL
    is resolved once at import. Only a subprocess can answer the question honestly.
    """
    code = (
        "import json;"
        "from app.llm import client;"
        "from app.llm.prompt import MEASURED_SYSTEM_TOKENS as M, CACHE_FLOOR_TOKENS as F,"
        " SYSTEM_PROMPT_VERSION as V;"
        "from app.obs.spend import worst_case_turn_usd, DAILY_CAP_USD;"
        "print(json.dumps({'model': client.MODEL, 'measured': M, 'floor': F, 'version': V,"
        " 'max_tokens': client.MAX_TOKENS, 'thinking': client.model_info()['thinking'],"
        " 'window': client.model_info()['context_window'],"
        " 'worst_turn': worst_case_turn_usd(), 'cap': DAILY_CAP_USD}))"
    )
    env = {k: v for k, v in os.environ.items() if k != KEY}
    env["PYTHONPATH"] = str(ROOT)
    env.setdefault("ANTHROPIC_API_KEY", "unused-import-only")

    r = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        return {"error": r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "failed"}
    import json

    return json.loads(r.stdout.strip())


# Count the assembled prefix against the live API.
#   in : model_id
#   out: token count, or None when there is no key or a gateway is configured (count_tokens
#        404s through one), so the check degrades to "unmeasured" rather than to a false pass.
def live_prefix_tokens(model_id: str) -> int | None:
    """Count the real prefix against the real tokeniser. The recorded number is per-model and the
    two models differ by 38% on identical bytes, so a swap without this is a guess."""
    try:
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH)
        import anthropic

        from app.llm.prompt import build_system_blocks

        client = anthropic.Anthropic()
        return client.messages.count_tokens(
            model=model_id,
            system=build_system_blocks(),
            messages=[{"role": "user", "content": "x"}],
        ).input_tokens
    except Exception as e:  # noqa: BLE001 — reported, never fatal; the offline checks still run
        print(f"    {DIM}(live count unavailable: {type(e).__name__}){OFF}")
        return None


# Build the human-readable verdict.
#   in : state -- what the app resolved; live -- measured token count or None
#   out: lines to print. Flags a margin under THIN_MARGIN, and a drift between the live count
#        and the recorded one.
def report(state: dict[str, object], live: int | None) -> list[str]:
    """Print the state and return the list of problems that should block a deploy."""
    from app.llm.models import MODELS

    problems: list[str] = []
    if "error" in state:
        print(bad(f"the app could not resolve a model: {state['error']}"))
        return ["the app does not start with this .env"]

    model = str(state["model"])
    measured, floor = int(state["measured"]), int(state["floor"])
    margin = measured - floor

    print(f"  {B}resolved model{OFF}   {model}")
    print(f"  prompt           v{state['version']} · {measured:,} tokens")
    print(f"  cache floor      {floor:,} · margin {margin:+,}")
    print(f"  max_tokens       {state['max_tokens']:,} · window {int(state['window']):,}")
    print(f"  thinking         {state['thinking']}")

    turns = int(float(state["cap"]) / float(state["worst_turn"]))
    print(f"  worst-case turn  ${float(state['worst_turn']):.5f} "
          f"→ {turns:,} turns on the ${float(state['cap']):.2f} cap")

    file_says = read_env_model()
    if file_says and file_says != model:
        problems.append(
            f".env says {file_says!r} but the app resolved {model!r} — the file is being read too "
            f"late, or a shell variable is overriding it. See app/__init__.py."
        )
        print(bad(f".env says {file_says} · app resolved {model}"))
    else:
        print(ok(".env is what the app actually uses"))

    if margin <= 0:
        problems.append(
            f"the prefix ({measured:,}) is BELOW {model}'s cache floor ({floor:,}). Caching will "
            f"fail silently — no error, the cache counters just stay 0, and every turn costs ~6x."
        )
        print(bad(f"below the cache floor by {-margin:,}"))
    elif margin < THIN_MARGIN:
        print(warn(f"margin is only {margin:,} — one prose trim from losing caching silently"))
    else:
        print(ok(f"clears the floor by {margin:,}"))

    if live is not None:
        drift = live - measured
        if drift:
            problems.append(
                f"MEASURED_SYSTEM_TOKENS_BY_MODEL[{model!r}] records {measured:,} but the live "
                f"count is {live:,} ({drift:+,}). Update app/llm/prompt.py."
            )
            print(bad(f"recorded {measured:,} · live {live:,} ({drift:+,})"))
        else:
            print(ok(f"live count matches the record ({live:,})"))

    missing = [m for m in MODELS if m not in _recorded_models()]
    if missing:
        problems.append(f"no measured prefix recorded for: {', '.join(missing)}")

    return problems


# Which models have a measured prefix recorded in prompt.py.
#   out: set of model ids. A model in the registry but missing here cannot be switched to
#        safely -- its prefix has never been measured against its floor.
def _recorded_models() -> set[str]:
    from app.llm.prompt import MEASURED_SYSTEM_TOKENS_BY_MODEL

    return set(MEASURED_SYSTEM_TOKENS_BY_MODEL)


# CLI entry point.
#   args: <model-id> to switch, or none to report the current state without changing anything
#   out: exit code -- 0 when the switch is verified, 1 when it is not.
# Refuses to switch to a model with no spec: an unspecced model has no cache floor and no price
# table, and would run with another model's numbers.
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model", nargs="?", help="model id to switch to")
    ap.add_argument("--check", action="store_true", help="verify current .env, change nothing")
    args = ap.parse_args()

    from app.llm.models import DEFAULT_MODEL, MODELS

    if not ENV_PATH.exists():
        print(bad(f"no .env at {ENV_PATH}"))
        return 1

    current = read_env_model()
    print(f"\n{B}Available{OFF} (from app/llm/models.py — the registry, not a guess)")
    for mid in sorted(MODELS):
        spec = MODELS[mid]
        mark = " ← current" if mid == current else ""
        default = " (default)" if mid == DEFAULT_MODEL else ""
        print(f"  {mid:20} floor {spec.cache_floor:>5,} · "
              f"${spec.rates['input']:.2f}/${spec.rates['output']:.2f} per MTok{default}{mark}")

    if args.model and args.model not in MODELS:
        print(f"\n{bad(f'{args.model!r} has no row in app/llm/models.py.')}")
        print("    Adding a model is NOT just an .env edit — it needs a ModelSpec (cache floor,")
        print("    four rates, thinking support, window) and a measured prefix for its tokeniser.")
        print("    Guessing a cache floor is the one mistake that fails silently.")
        return 1

    if args.model and args.model != current:
        backup = write_env_model(args.model)
        print(f"\n{ok(f'.env: {current} → {args.model}')}  {DIM}(backup: {backup.name}){OFF}")
    elif args.model:
        print(f"\n{ok(f'already set to {args.model}')}")

    print(f"\n{B}Verifying through the .env path{OFF} "
          f"{DIM}(subprocess, shell override removed){OFF}")
    state = resolve_via_dotenv()
    live = live_prefix_tokens(str(state.get("model"))) if "error" not in state else None
    problems = report(state, live)

    print(f"\n{B}Next{OFF}")
    if problems:
        print(bad("do not deploy — fix these first:"))
        for p in problems:
            print(f"    - {p}")
    else:
        print("  1. pytest && ruff check .")
        print("  2. python eval/golden.py --url http://127.0.0.1:8000 --suite lite")
        print(f"     {DIM}a model swap is an environment change, so run --suite full too{OFF}")
        print("  3. watch for: a leaked [[refusal:...]] tag in any answer, and the refusal")
        print("     tagging rate — models place and apply the marker differently")
    print()
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
