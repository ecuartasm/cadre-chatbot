"""Link rendering, tested as BEHAVIOUR rather than as source strings.

Every other link check in this repo asserts "does the file contain X". Those catch a deletion but
not a defect: `test_bare_site_paths_resolve_through_the_allowlist` would have passed the whole time
the uppercase-scheme gap existed, because the source *did* contain everything it looked for.

`web/scripts/link-audit.mjs` runs the real matching module against ~102 cases — all 36 allowlisted
pages in both absolute and bare-path form, 20 shapes that break naive linkifiers, and 11 that must
NOT link. It exits non-zero on any failure and prints each one.

⚠️ It imports the real `links.js`. The audit's first draft kept its own copy of the regexes, because
`markdown.jsx` contains JSX and Node cannot import it. The copy went stale the moment the real
pattern changed and reported a fixed bug as still broken — which is why the patterns were split into
a plain module. A harness that copies the code under test is a mirror, not a test.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
AUDIT = ROOT / "web" / "scripts" / "link-audit.mjs"


def test_the_audit_script_exists():
    """Guards the skip below: if the file is renamed, the behavioural suite would quietly stop
    running while the node-missing skip made that look intentional."""
    assert AUDIT.is_file(), f"{AUDIT} is missing — link behaviour is no longer covered"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_link_rendering_behaves_correctly_across_every_allowlisted_page():
    r = subprocess.run(
        ["node", str(AUDIT)], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    # stdout carries the pass line and stderr each failure; surface both so a failure here names
    # the exact input rather than just an exit code.
    assert r.returncode == 0, f"\n{r.stdout}\n{r.stderr}"
    assert "checks passed" in r.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_audit_actually_fails_when_the_allowlist_is_wrong():
    """Guards the guard. An audit that cannot fail is a green light with nothing behind it, so this
    feeds it a deliberately broken allowlist and requires a non-zero exit."""
    src = (ROOT / "web" / "src" / "cadre-urls.js").read_text(encoding="utf-8")
    broken = src.replace("https://www.cadreai.com/contact'", "https://www.cadreai.com/kontact'")
    assert broken != src, "the fixture no longer matches cadre-urls.js"

    target = ROOT / "web" / "src" / "cadre-urls.js"
    original = target.read_text(encoding="utf-8")
    try:
        target.write_text(broken, encoding="utf-8")
        r = subprocess.run(
            ["node", str(AUDIT)], cwd=ROOT, capture_output=True, text=True, timeout=120
        )
        assert r.returncode != 0, "the audit passed against a corrupted allowlist"
    finally:
        target.write_text(original, encoding="utf-8")
