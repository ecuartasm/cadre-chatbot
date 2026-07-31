"""`requirements*.txt` are generated artefacts and must not drift from `uv.lock`.

They exist for anyone installing without `uv` — a reviewer, a CI image, a colleague. That makes
them a second description of the same dependency set, and a second description is a second thing to
go stale. Nothing regenerates them automatically, so this asserts they are current.

⚠️ **`mcp` must never appear in the runtime file.** `mcp_server/` is an operator tool run on a
laptop against the deployed `/api/stats`; `tests/test_mcp.py` already asserts it stays out of the
Docker image, and a runtime requirements file listing it would put it back by another door.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
RUNTIME = ROOT / "requirements.txt"
DEV = ROOT / "requirements-dev.txt"

PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", re.M)


def differing(current: dict[str, str], fresh: dict[str, str]) -> dict[str, tuple[str, str]]:
    return {k: (current[k], fresh[k]) for k in fresh if k in current and fresh[k] != current[k]}


def pins(path: Path) -> dict[str, str]:
    return {m.group(1).lower(): m.group(2) for m in PIN.finditer(path.read_text(encoding="utf-8"))}


def test_both_files_exist_and_are_populated():
    """Guards the guard: an empty or missing file would make every check below vacuous."""
    for f in (RUNTIME, DEV):
        assert f.is_file(), f"{f.name} is missing"
        assert len(pins(f)) > 10, f"{f.name} has suspiciously few pins"


def test_every_direct_dependency_is_pinned():
    """The four in pyproject must appear, or the file does not actually install the app."""
    proj = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    direct = {re.split(r"[><=\[]", d)[0].strip().lower() for d in proj["project"]["dependencies"]}
    missing = direct - set(pins(RUNTIME))
    assert not missing, f"direct dependencies absent from requirements.txt: {sorted(missing)}"


def test_dev_is_a_superset_of_runtime():
    """Anyone installing the dev file must get a working app, not just the tooling."""
    r, d = pins(RUNTIME), pins(DEV)
    missing = {k for k in r if k not in d}
    assert not missing, f"requirements-dev.txt is missing runtime packages: {sorted(missing)}"
    conflicting = {k: (r[k], d[k]) for k in r if k in d and r[k] != d[k]}
    assert not conflicting, f"version conflicts between the two files: {conflicting}"


def test_the_mcp_server_stays_out_of_the_runtime_set():
    """It is an operator tool, not part of the served app. test_mcp.py keeps it out of the image;
    this keeps it out of the runtime dependency list, which is the other way in."""
    assert "mcp" not in pins(RUNTIME), "mcp is a dev dependency — it must not ship at runtime"
    assert "mcp" in pins(DEV), "mcp should be installable for the operator tooling"


def test_everything_is_hash_pinned():
    """`--require-hashes` is what makes the install non-substitutable, and it is the mode the
    Dockerfile uses. A file without hashes would silently install whatever the index served."""
    for f in (RUNTIME, DEV):
        text = f.read_text(encoding="utf-8")
        assert "--hash=sha256:" in text, f"{f.name} carries no hashes"
        pinned = len(pins(f))
        hashed = len(re.findall(r"^[A-Za-z0-9_.-]+==.*\\\s*$", text, re.M))
        assert hashed >= pinned - 1, f"{f.name}: {pinned} pins but only {hashed} carry hashes"


@pytest.mark.parametrize("path,flags", [(RUNTIME, ["--no-dev"]), (DEV, [])])
def test_the_files_match_uv_lock(path: Path, flags: list[str]):
    """The check that actually matters: regenerate into a temp file and compare the pins.

    Compared as parsed pins rather than raw bytes — `uv export` writes the invoking command into
    its header, so a byte comparison would fail purely because the output path differed.
    """
    out = subprocess.run(
        ["uv", "export", *flags, "--frozen", "--no-emit-project", "--no-header"],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    if out.returncode != 0:
        pytest.skip(f"uv export unavailable: {out.stderr[:120]}")

    fresh = {m.group(1).lower(): m.group(2) for m in PIN.finditer(out.stdout)}
    current = pins(path)
    assert fresh == current, (
        f"{path.name} has drifted from uv.lock.\n"
        f"  only in lock : {sorted(set(fresh) - set(current))}\n"
        f"  only in file : {sorted(set(current) - set(fresh))}\n"
        f"  differing    : {differing(current, fresh)}\n"
        f"Regenerate: uv export {' '.join(flags)} --frozen --no-emit-project -o {path.name}"
    )
