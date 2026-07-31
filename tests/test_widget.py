"""The `/chat-widget` demo: a Cadre-styled mockup with the bot as a floating widget.

Two classes of guard here, and only one of them is about code quality.

**Safety.** The page is built to look like a real company's marketing site. That is defensible as a
local demo and stops being defensible the moment it is mistakable for the real thing, so the demo
banner and the absence of credential fields are asserted rather than trusted. An unguarded
requirement lasts until someone tidies it away.

**Single implementation.** The widget must reuse `useChat()` and `renderInline()`. A second SSE
parser or a second link renderer would be a second thing to keep correct, and the two would drift —
which is the whole reason the hook was extracted rather than copied.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).parent.parent / "web" / "src"
ENTRY_HTML = Path(__file__).parent.parent / "web" / "chat-widget" / "index.html"
MOCKUP = WEB / "Mockup.jsx"
WIDGET = WEB / "Widget.jsx"
WIDGET_CSS = WEB / "widget.css"
WIDGET_MAIN = WEB / "widget-main.jsx"

_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_LINE = re.compile(r"^\s*//.*$", re.M)


def code(path: Path) -> str:
    """Source with comments stripped. Comments explain *why* a thing is banned and therefore name
    it — scanning them makes a rule fail on its own rationale, which has happened here before."""
    return _LINE.sub("", _BLOCK.sub("", path.read_text(encoding="utf-8")))


# ── safety ───────────────────────────────────────────────────────────────────────────


def test_the_demo_banner_is_present():
    """The page imitates a real company. Someone landing on it out of context must be told, at
    every viewport, that this is not cadreai.com."""
    src = code(MOCKUP)
    assert "mk-demo" in src, "no demo banner element"
    assert "not the real Cadre AI website" in src.replace("\n", " ").replace("  ", " ") or (
        "not" in src and "real Cadre AI website" in src
    ), "the banner must say plainly that this is not the real site"


def test_the_banner_is_not_dismissible_or_position_fixed():
    """A dismissible notice is a notice that is not there, and `position: fixed` is hidden by some
    mobile browsers' UI. It has to be in the document flow."""
    css = code(WIDGET_CSS)
    block = css.split(".mk-demo {", 1)
    assert len(block) == 2, "no .mk-demo rule"
    rule = block[1].split("}", 1)[0]
    assert "position: fixed" not in rule
    assert "display: none" not in rule
    assert "onClick" not in code(MOCKUP).split("mk-demo", 1)[1][:400], "banner must not be closable"


@pytest.mark.parametrize("path", sorted(WEB.glob("*.jsx")) + [ENTRY_HTML])
def test_no_credential_fields_anywhere(path: Path):
    """A page imitating a real company that also collects credentials is phishing-shaped whatever
    the intent behind it. "Log in" is a link to the real contact page; there is no form.

    Checked across every component, not just the mockup — the rule is about the product, not about
    one file."""
    src = code(path).lower()
    for banned in ('type="password"', "type='password'", "autocomplete=\"current-password\""):
        assert banned not in src, f"{path.name} contains a credential field ({banned})"
    for banned in ("password", "signin", "sign-in"):
        assert banned not in src, f"{path.name} mentions {banned!r} — no auth surface on this page"


def test_every_mockup_link_comes_from_the_allowlist():
    """Links are resolved through `CADRE_URLS`, never written as literals, so a link on this page
    cannot point somewhere `content/raw/` has not vouched for — the same property the chat renderer
    holds. A typo becomes a visible `undefined`, not a plausible dead URL."""
    src = code(MOCKUP)
    assert "CADRE_URLS" in src, "the mockup must resolve links through the allowlist"
    literal_hrefs = re.findall(r'href="(https?://[^"]*)"', src)
    assert not literal_hrefs, f"hardcoded URLs bypass the allowlist: {literal_hrefs}"


def test_the_demo_page_is_not_indexable():
    """It should not turn up in a search for Cadre AI."""
    assert 'name="robots"' in ENTRY_HTML.read_text(encoding="utf-8")
    assert "noindex" in ENTRY_HTML.read_text(encoding="utf-8")


# ── single implementation ────────────────────────────────────────────────────────────


def test_the_widget_reuses_the_shared_conversation_engine():
    """No second SSE parser. If this fails, the widget has grown its own `fetch` loop and the two
    will drift — the frame buffering and the `done` frame shape have both moved twice already."""
    src = code(WIDGET)
    assert "useChat" in src, "the widget must call useChat()"
    assert "/api/chat" not in src, "the widget must not issue its own request"
    assert "getReader" not in src and "TextDecoder" not in src, "no second stream reader"


def test_the_widget_renders_assistant_text_through_the_shared_renderer():
    """Otherwise links, bold and the refusal-marker handling behave differently in the widget than
    on the full page — the same prose formatted two ways.

    The turn markup itself now lives in `Turn.jsx`, shared with the chat view, because two copies
    meant a rule could regress in one while the other kept the suite green. So the widget must
    *delegate* rather than render turns itself."""
    src = code(WIDGET)
    assert "Turn" in src, "the widget must render turns through the shared component"
    assert "renderInline" not in src, "the widget must not format prose itself — Turn.jsx does"
    assert "renderInline(message.content)" in code(WEB / "Turn.jsx")


def test_there_is_exactly_one_sse_parser_in_the_codebase():
    """The property the extraction exists to hold, asserted directly rather than implied.

    ⚠️ **This test found a defect it was not aimed at.** It was written to stop the new widget
    growing its own reader; on first run it reported `Playground.jsx` as a second one — a
    byte-identical copy of the loop in `App.jsx`, sitting there unnoticed since Phase 9. The wire
    format then moved to `sse.js` and both callers were rewired onto it.

    Scanned by `getReader()`, which is the call that starts consuming a body — a search for
    "fetch" would match every caller and prove nothing about parsing.
    """
    readers = [p.name for p in sorted(WEB.glob("*.js*")) if "getReader()" in code(p)]
    assert readers == ["sse.js"], f"expected one stream reader, found {readers}"


# ── accessibility and mobile ─────────────────────────────────────────────────────────


def test_the_widget_is_operable_by_keyboard():
    """Focus in on open, back to the launcher on close, Escape closes. Without the return, closing
    the panel drops a keyboard user at the top of the document every time."""
    src = code(WIDGET)
    assert "aria-expanded" in src, "the launcher must announce its state"
    assert 'role="dialog"' in src
    assert "'Escape'" in src, "Escape must close the panel"
    assert "launcherRef.current?.focus()" in src, "focus must return to the launcher on close"
    assert "inputRef.current?.focus()" in src, "focus must move into the panel on open"


def test_the_transcript_is_announced():
    src = code(WIDGET)
    assert 'role="log"' in src and 'aria-live="polite"' in src


def test_the_panel_survives_the_ios_keyboard():
    """Both fail silently on a desktop browser: `vh` does not track the iOS keyboard, and an input
    under 16px triggers focus auto-zoom."""
    css = code(WIDGET_CSS)
    panel = css.split(".wg-panel {", 1)[1].split("}", 1)[0]
    assert "svh" in panel, "panel height must use svh, not vh"
    assert re.search(r"\b\d+vh\b", panel) is None, "raw vh does not track the iOS keyboard"
    composer = css.split(".wg-input {", 1)[1].split("}", 1)[0]
    assert "font-size: var(--size-input)" in composer, "16px minimum, or iOS zooms on focus"


def test_reduced_motion_is_respected():
    """Smooth-scrolling a streaming transcript is continuous motion for as long as the answer
    takes — exactly what the setting exists to suppress. Shared by all three transcript views via
    `useScrollToEnd`, so it cannot be present in one and forgotten in another."""
    assert "prefers-reduced-motion" in code(WEB / "useScrollToEnd.js")
    assert "useScrollToEnd" in code(WIDGET), "the widget must use the shared hook"


# ── build wiring ─────────────────────────────────────────────────────────────────────


def test_the_entry_html_is_a_bare_mount_point():
    """`web/chat-widget/index.html` sits outside `web/src/`, where the no-inline-styles and
    no-literal-colour globs look. Keeping it to a mount point plus a script tag means there is
    nothing there for those rules to miss."""
    html = ENTRY_HTML.read_text(encoding="utf-8")
    assert "<style" not in html, "styling belongs in web/src/, where the guards can see it"
    assert 'style="' not in html
    assert '<div id="root">' in html


def test_the_widget_entry_imports_every_stylesheet_it_uses():
    """It reuses `.message`, `.message--error` and `.caret` from app.css rather than restating
    them, so app.css is not optional here."""
    src = code(WIDGET_MAIN)
    for sheet in ("./tokens.css", "./app.css", "./widget.css"):
        assert sheet in src, f"{sheet} is not imported by the widget entry"


def test_vite_builds_both_pages_and_sets_no_base():
    """Vite emits absolute `/assets/…` paths, which resolve from `/chat-widget/` because FastAPI
    mounts the bundle at `/`. A `base` would break the root page."""
    cfg = code(Path(__file__).parent.parent / "web" / "vite.config.js")
    assert "chat-widget/index.html" in cfg, "the second entry point is not configured"
    assert "index.html" in cfg
    assert not re.search(r"^\s*base:", cfg, re.M), "a base path would break the root page"


def test_no_fastapi_route_was_added_for_the_widget():
    """`StaticFiles(html=True)` already resolves `dist/chat-widget/` to its index.html. The whole
    feature is front-end; if it needed a backend change, the seam would be wrong."""
    main = (Path(__file__).parent.parent / "app" / "main.py").read_text(encoding="utf-8")
    assert "chat-widget" not in main
