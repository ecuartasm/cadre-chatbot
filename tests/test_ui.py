"""Phase 5 — UI conventions, guarded at the source level.

`CLAUDE.md`'s verification section covers the knowledge layer and the API and says nothing about the
UI, so these two rules would otherwise be review-time glances that decay the first time someone adds
a quick `style={{ color: '#666' }}`. They are cheap to assert and expensive to rediscover.

Deliberately source inspection, not a browser test. Rendering React in CI would mean jsdom, a runner
for a second language, and a slow suite — for rules that are entirely about what the source is
allowed to contain. The things a browser *would* catch (does the font load, does it work at 375px)
are verified by hand and recorded in the phase report.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).parent.parent / "web" / "src"
APP = WEB / "App.jsx"
TOKENS = WEB / "tokens.css"
APP_CSS = WEB / "app.css"

# Any hex literal that is not black or white. Black/white are allowed nowhere but tokens.css either,
# but they are what the rule is *about*, so failures name the real problem rather than a near-miss.
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")

# Comments explain *why* a colour is banned, so they necessarily name it. Scan declarations only,
# or every one of these rules fails on its own rationale.
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.M)


def code(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def test_the_stylesheets_are_actually_imported():
    """Without this, Vite builds cleanly and applies nothing — the state the repo was in before
    Phase 5, when there was no CSS entry point at all."""
    main = code(WEB / "main.jsx")
    assert "./tokens.css" in main
    assert "./app.css" in main


def test_no_inline_styles_in_the_component():
    """`style={{…}}` is CSS-in-JS by another name, which CLAUDE.md rules out in favour of plain CSS
    with custom properties."""
    assert "style={{" not in code(APP)


def test_no_colour_literals_outside_the_token_file():
    """A literal here is a value that cannot be restyled from one place, which is the entire point
    of the token layer."""
    for path in (APP, APP_CSS):
        found = HEX.findall(code(path))
        assert not found, f"{path.name} contains colour literals {found}; put them in tokens.css"


def test_text_is_black_and_no_grey_body_text():
    """A requester requirement, not a preference. The pre-Phase-5 UI was the counter-example: five
    inline colours, none of them black — #666 twice, #999 twice, #b00."""
    tokens = code(TOKENS)
    assert "--text: var(--black)" in tokens
    assert "--black: #0b0707" in tokens, "black is Cadre's own primary black, not merely dark"

    # The specific greys that were removed must not come back anywhere in web/src.
    for path in WEB.rglob("*"):
        if path.suffix not in (".css", ".jsx"):
            continue
        text = code(path)
        for grey in ("#666", "#999", "#ddd", "#333", "grey", "gray"):
            assert grey not in text, f"{path.name} reintroduces grey ({grey}) — text must be black"


def test_error_colour_is_the_one_deliberate_exception():
    """Colour carries meaning here: an error must not read as an answer. Recorded as an exception
    to the black rule so it is a decision rather than a leak."""
    assert "--text-error: var(--cadre-red)" in code(TOKENS)
    assert ".message--error" in code(APP_CSS)


def test_ios_viewport_and_input_font_rules():
    """Both are iOS-specific and both fail silently on a desktop browser: `vh` puts the composer
    under the keyboard, and an input under 16px triggers focus auto-zoom."""
    css = code(APP_CSS)
    assert "100dvh" in css, "vh does not track iOS Safari's toolbars or keyboard"
    assert "100svh" in css, "svh fallback for browsers without dvh"
    assert "font-size: var(--size-input)" in css
    assert "--size-input: 1rem" in code(TOKENS), "16px minimum"


def test_fonts_are_self_hosted_and_the_files_exist():
    """Declaring a font that was never loaded falls back to Arial SILENTLY — it looks approximately
    right to whoever wrote it. The @font-face and the bytes must both be present."""
    tokens = code(TOKENS)
    assert "@font-face" in tokens
    assert "fonts.googleapis" not in tokens and "gstatic" not in tokens, (
        "fonts must be self-hosted: this project is one deployable with no runtime external "
        "dependency, and the bot discusses Cadre's data-security posture"
    )
    for name in ("inter-latin-var.woff2", "inter-tight-latin-var.woff2"):
        f = WEB / "fonts" / name
        assert f.is_file(), f"{name} is declared but not present"
        assert f.stat().st_size > 10_000, f"{name} looks truncated ({f.stat().st_size} bytes)"


@pytest.mark.parametrize("token", ["--font-body", "--font-display", "--radius-pill", "--bg"])
def test_component_styles_consume_tokens(token: str):
    assert token in code(APP_CSS)


def test_the_multi_turn_loop_was_not_refactored():
    """Phase 4's requirement. The client must accumulate only visible delta text and post the whole
    array back — storing raw frames instead would put the refusal marker into history."""
    app = code(APP)
    assert "JSON.stringify({ messages: next })" in app, "history must still be sent whole"
    assert "copy[copy.length - 1].content + evt.text" in app, "deltas must still accumulate"


def test_woff2_mimetype_is_registered_explicitly():
    """Found on the deployed URL, not locally: `StaticFiles` reads the stdlib mimetypes database,
    which is seeded from the host OS. macOS knows `.woff2`, the slim Debian image does not — so the
    same code served `font/woff2` locally and `application/octet-stream` in production. Browsers
    honour the `format('woff2')` hint regardless, so nothing looked broken."""
    import mimetypes

    import app.main  # noqa: F401 — importing registers the type

    assert mimetypes.guess_type("x.woff2")[0] == "font/woff2"
