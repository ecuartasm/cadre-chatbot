"""`.env` must actually drive the model. Regression test for a silent, total failure.

`load_dotenv()` lived in `app/main.py` below its import block. Python runs imports first, so
`app.llm.client` had already resolved `MODEL = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)` by the
time `.env` was read — and setting `ANTHROPIC_MODEL=claude-sonnet-5` in `.env` did nothing at all.

⚠️ **Why it survived a whole model-switch phase:** the two paths agreed by coincidence. `.env` said
`claude-haiku-4-5` and `DEFAULT_MODEL` was also `claude-haiku-4-5`, so the broken lookup returned
the right answer for the wrong reason. Every Sonnet check had used a shell variable
(`ANTHROPIC_MODEL=claude-sonnet-5 uvicorn ...`), which skips `.env` and therefore skips the bug.

That is the trap this file exists to avoid, so the test below **asserts its fixture differs from
`DEFAULT_MODEL`**. A test written with the default value would pass against the broken code.

These run in a subprocess on purpose: the parent pytest process imported `app.llm.client` long ago,
so its `MODEL` is already resolved and cannot demonstrate anything about import order.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.llm.models import DEFAULT_MODEL, MODELS

ROOT = Path(__file__).parent.parent

# Any specced model that is NOT the fallback. If this ever equals DEFAULT_MODEL the test is
# vacuous — see the module docstring — so it is asserted below rather than assumed.
OTHER_MODEL = next(m for m in sorted(MODELS) if m != DEFAULT_MODEL)


def _resolve_with_dotenv(tmp_path: Path, dotenv_body: str, code: str) -> str:
    """Run `code` in a fresh interpreter whose cwd holds `.env`, with no inherited override."""
    (tmp_path / ".env").write_text(dotenv_body, encoding="utf-8")

    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_MODEL"}
    env["PYTHONPATH"] = str(ROOT)
    # A key is never needed: the client builds its SDK object lazily, so importing it is safe.
    env.setdefault("ANTHROPIC_API_KEY", "test-not-a-real-key")

    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90,
    )
    assert r.returncode == 0, f"subprocess failed:\n{r.stderr}"
    return r.stdout.strip()


def test_the_fixture_is_not_the_default():
    """Guards the guard. With the fixture equal to `DEFAULT_MODEL`, every test below passes against
    the broken code — which is exactly how the original bug hid."""
    assert OTHER_MODEL != DEFAULT_MODEL
    assert len(MODELS) >= 2, "the .env switch cannot be tested with only one specced model"


def test_a_model_set_only_in_dotenv_reaches_the_client(tmp_path: Path):
    """The property the user actually asked for: edit `.env`, get that model."""
    out = _resolve_with_dotenv(
        tmp_path,
        f"ANTHROPIC_MODEL={OTHER_MODEL}\n",
        "from app.llm import client; print(client.MODEL)",
    )
    assert out == OTHER_MODEL, (
        f".env asked for {OTHER_MODEL} and the client resolved {out!r}. `.env` is being read after "
        "app.llm.client resolves ANTHROPIC_MODEL — see app/__init__.py."
    )


def test_the_whole_per_model_stack_follows_dotenv(tmp_path: Path):
    """Not just the id — the prefix size, the cache floor, and the output ceiling all move with it.

    Asserted together because the id switching while the floor stayed on the old model's value is
    the *silent* half of this bug: caching would fail with the counters simply reading 0.
    """
    out = _resolve_with_dotenv(
        tmp_path,
        f"ANTHROPIC_MODEL={OTHER_MODEL}\n",
        "from app.llm import client;"
        "from app.llm.prompt import MEASURED_SYSTEM_TOKENS as M, CACHE_FLOOR_TOKENS as F;"
        "print(client.MODEL, M, F, client.MAX_TOKENS)",
    )
    model_id, measured, floor, max_tokens = out.split()
    spec = MODELS[OTHER_MODEL]

    assert model_id == OTHER_MODEL
    assert int(floor) == spec.cache_floor, "the cache floor did not follow the model"
    assert int(measured) > int(floor), "the measured prefix must clear the floor it is paired with"
    assert int(max_tokens) <= spec.max_output


def test_importing_main_does_not_re_resolve_the_model(tmp_path: Path):
    """`/health` reports the model. It must read the client's value rather than resolving
    ANTHROPIC_MODEL a second time — a private copy agreed with the real one only by coincidence."""
    out = _resolve_with_dotenv(
        tmp_path,
        f"ANTHROPIC_MODEL={OTHER_MODEL}\n",
        "import app.main as m; from app.llm import client;"
        "print(m.health()['model'], client.MODEL)",
    )
    reported, actual = out.split()
    assert reported == actual == OTHER_MODEL, "/health disagrees with the model actually in use"


def test_a_real_environment_variable_still_beats_dotenv(tmp_path: Path):
    """Railway sets config through its dashboard, not a committed file. `override=False` is the
    dotenv default and is relied on here: the deployed environment must win."""
    (tmp_path / ".env").write_text(f"ANTHROPIC_MODEL={OTHER_MODEL}\n", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["ANTHROPIC_MODEL"] = DEFAULT_MODEL
    env.setdefault("ANTHROPIC_API_KEY", "test-not-a-real-key")

    r = subprocess.run(
        [sys.executable, "-c", "from app.llm import client; print(client.MODEL)"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == DEFAULT_MODEL


def test_dotenv_is_loaded_by_the_package_not_by_an_entry_point():
    """Structural, and worth pinning: any entry point that loads `.env` itself reintroduces the
    ordering bug for every *other* entry point (pytest, eval/golden.py, mcp_server, scripts).

    ⚠️ Parsed with `ast`, not `in`. The first version of this test matched the word `load_dotenv()`
    inside `main.py`'s own comment *explaining* why it must not call it — a test that failed on
    correct code, and the eighth time in this build an assertion was narrower than the property it
    stood for. The property is "does not CALL it", which is a syntax question.
    """
    import ast

    assert "load_dotenv()" in (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")

    tree = ast.parse((ROOT / "app" / "main.py").read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "load_dotenv" not in called, (
        "app/main.py must not call load_dotenv() — below its imports it runs too late, and above "
        "them it only fixes this one entry point. It belongs in app/__init__.py."
    )


@pytest.mark.parametrize("model_id", sorted(MODELS))
def test_every_specced_model_can_be_selected_from_dotenv(tmp_path: Path, model_id: str):
    out = _resolve_with_dotenv(
        tmp_path, f"ANTHROPIC_MODEL={model_id}\n",
        "from app.llm import client; print(client.MODEL)",
    )
    assert out == model_id
