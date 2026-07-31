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

import json
import re
from pathlib import Path

import pytest

WEB = Path(__file__).parent.parent / "web" / "src"
TOKENS = WEB / "tokens.css"
APP_CSS = WEB / "app.css"

# Every component, discovered rather than listed. The Phase 9 audit found seven checks here
# hardcoded to App.jsx: adding Playground.jsx would have left them passing while covering nothing —
# a guard that silently narrows is worse than one that fails, because it still reports green.
COMPONENTS = sorted(WEB.glob("*.jsx"))

# Every stylesheet except tokens.css, discovered rather than listed — tokens.css is the ONE file
# permitted a literal colour, size or font, so it is the thing these rules measure against rather
# than a member of the set. A hardcoded [APP_CSS] would have stopped covering the UI the moment
# widget.css appeared, which is the same narrowing that has cost this project coverage repeatedly.
STYLESHEETS = sorted(p for p in WEB.glob("*.css") if p != TOKENS)
STYLED = COMPONENTS + STYLESHEETS
APP = WEB / "App.jsx"  # the chat view specifically, for layout-only assertions

# Every file that can hold behaviour, discovered rather than listed. Guards that assert on logic
# must search THIS, not App.jsx: the conversation engine moved out to useChat.js when the widget
# arrived, and three checks pinned to App.jsx broke — which was the good outcome. Pinned to the old
# path they would have passed while covering nothing, which is how this project has lost coverage
# eight times.
SOURCES = sorted(WEB.glob("*.jsx")) + sorted(WEB.glob("*.js"))


def all_source() -> str:
    """Every component and module concatenated. For 'this behaviour exists somewhere' assertions,
    where pinning to one file is what silently narrows."""
    return "\n".join(code(p) for p in SOURCES)


# Anything Vite treats as an entry point. A new page means a new entry, and an entry that forgets
# the stylesheet imports builds cleanly and applies nothing.
ENTRY_POINTS = sorted(p for p in WEB.glob("*main*.jsx"))

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


@pytest.mark.parametrize("entry", ENTRY_POINTS, ids=lambda p: p.name)
def test_the_stylesheets_are_actually_imported(entry: Path):
    """Without this, Vite builds cleanly and applies nothing — the state the repo was in before
    Phase 5, when there was no CSS entry point at all.

    ⚠️ **Parametrised over every entry point, not hardcoded to `main.jsx`.** The audit of the
    widget plan caught this one before any code was written: a second entry that forgot the imports
    would render an unstyled page while the suite stayed green, and this test — the one guarding
    exactly that failure — would not have been looking.
    """
    src = code(entry)
    assert "./tokens.css" in src, f"{entry.name} does not import tokens.css"
    assert "./app.css" in src, f"{entry.name} does not import app.css"


def test_at_least_one_entry_point_is_discovered():
    """Guards the guard: a glob matching nothing parametrises to zero cases, reporting green."""
    assert ENTRY_POINTS, "no *main*.jsx entry points found — the glob has gone stale"


@pytest.mark.parametrize("path", COMPONENTS, ids=lambda p: p.name)
def test_no_inline_styles_in_any_component(path: Path):
    """`style={{…}}` is CSS-in-JS by another name, which CLAUDE.md rules out in favour of plain CSS
    with custom properties. Parametrised over every component so a new one cannot slip the rule."""
    assert "style={{" not in code(path)


def test_the_component_list_is_not_empty():
    """A glob that matches nothing turns every parametrised check above into a silent no-op."""
    assert len(COMPONENTS) >= 3, f"expected shell, chat and playground views, found {COMPONENTS}"


def test_no_colour_literals_outside_the_token_file():
    """A literal here is a value that cannot be restyled from one place, which is the entire point
    of the token layer."""
    for path in STYLED:
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
    src = all_source()
    assert "JSON.stringify({ messages: next })" in src, "history must still be sent whole"
    assert "copy[copy.length - 1].content + evt.text" in src, "deltas must still accumulate"


def test_woff2_mimetype_is_registered_explicitly():
    """Found on the deployed URL, not locally: `StaticFiles` reads the stdlib mimetypes database,
    which is seeded from the host OS. macOS knows `.woff2`, the slim Debian image does not — so the
    same code served `font/woff2` locally and `application/octet-stream` in production. Browsers
    honour the `format('woff2')` hint regardless, so nothing looked broken."""
    import mimetypes

    import app.main  # noqa: F401 — importing registers the type

    assert mimetypes.guess_type("x.woff2")[0] == "font/woff2"


# ── Phase 9: the playground ──────────────────────────────────────────────────────────

PLAYGROUND = WEB / "Playground.jsx"
SHELL = WEB / "Shell.jsx"


def test_the_playground_does_not_recompute_cost_in_js():
    """`cost.py` exists so there is exactly one implementation of the four-rate cache maths. A
    second one in the browser would drift from it the first time a rate changed."""
    src = code(PLAYGROUND)
    assert "cost_usd" in src, "the playground should read the server's figure"
    for rate in ("1.25", "0.1", "5.00", "1000000", "1_000_000"):
        assert rate not in src, f"{rate} looks like a price rate reimplemented in JS"


def test_the_playground_never_renders_prompt_text():
    """The decision from plan.md §9.2. Metadata only — publishing the prompt would publish the
    refusal-marker syntax, which a user message could then inject to fake or suppress a refusal."""
    src = code(PLAYGROUND)
    assert "[[refusal" not in src
    for leaked in ("prompt.text", "promptText", "system_prompt\"", "'system_prompt'"):
        assert leaked not in src, f"{leaked} suggests the prompt body is being rendered"
    # It should show size, not content.
    assert "prompt?.tokens" in src or "prompt.tokens" in src


def test_no_router_dependency_was_added():
    """Two tabs do not justify a routing library; CLAUDE.md rules out the same instinct for
    component kits. Conditional rendering is the whole mechanism."""
    pkg = json.loads((WEB.parent / "package.json").read_text(encoding="utf-8"))
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    assert not any("router" in d for d in deps), f"a router crept in: {sorted(deps)}"


def test_both_views_stay_mounted_when_switching_tabs():
    """Unmounting would discard a conversation or a playground result on every tab click. Hidden
    with CSS instead — asserted because it is invisible in review and obvious in use."""
    src = code(SHELL)
    assert "view--hidden" in src
    assert "<App />" in src and "<Playground" in src
    assert ".map(" not in src, "views should be rendered directly, not conditionally unmounted"


# ── inline markdown rendering ────────────────────────────────────────────────────────

MARKDOWN = WEB / "markdown.jsx"
LINKS = WEB / "links.js"

# The renderer and the matching module together. These source checks assert that a property is
# implemented *somewhere* in the link path — pinning them to one file is what broke when the regexes
# moved into links.js, which is the same narrowing this file has now hit five times.
#
# The real coverage is behavioural: tests/test_links_behaviour.py runs web/scripts/link-audit.mjs
# over all 36 pages and 31 edge shapes. These remain as cheap structural backstops.
def link_path_source() -> str:
    return code(MARKDOWN) + "\n" + code(LINKS)


def test_markdown_renders_elements_never_html():
    """The string being rendered is model output, and model output is shaped by whatever the user
    typed. `dangerouslySetInnerHTML` is the obvious shortcut and it is an injection vector; a
    tokeniser emitting React elements cannot inject markup because React escapes text nodes."""
    src = code(MARKDOWN)
    assert "dangerouslySetInnerHTML" not in src
    assert "innerHTML" not in src
    # `<strong key=` not `<strong>` — the elements carry keys. Matching the narrower literal
    # would fail on correct code, which is the mistake this file has already made twice.
    for tag in ("<strong key=", "<em key=", "<code key="):
        assert tag in src, f"expected {tag} — the renderer must emit elements, not strings"


def test_no_markdown_library_was_added():
    """CLAUDE.md keeps the frontend at two dependencies. `react-markdown` pulls a remark/unified
    tree — a permanently-owned dependency to render bold text."""
    pkg = json.loads((WEB.parent / "package.json").read_text(encoding="utf-8"))
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    for banned in ("markdown", "remark", "unified", "marked", "showdown"):
        assert not any(banned in d for d in deps), f"a markdown library crept in: {sorted(deps)}"


def test_only_assistant_text_is_formatted():
    """The user typed their own asterisks; reinterpreting them would be surprising. And an error
    frame is server prose, not model output.

    ⚠️ **Pinned to `Turn.jsx`, and this is the one place a narrow assertion is RIGHT.** The markup
    used to live twice — in `App.jsx` and `Widget.jsx` — while this check searched *all* sources,
    so one copy satisfying it masked the other regressing. Searching everywhere can only prove that
    *somewhere* obeys the rule. There is now exactly one turn renderer, so naming it is precise.
    """
    src = code(WEB / "Turn.jsx")
    assert "message.role === 'assistant' && !message.isError" in src
    assert "renderInline(message.content)" in src
    assert ": message.content" in src, "non-assistant text must bypass the renderer"


def test_there_is_exactly_one_turn_renderer():
    """The property the extraction exists to hold: if a component renders turns itself again, the
    guard above silently stops covering it.

    ⚠️ **I got the marker wrong twice writing this**, which is worth recording because it is the
    exact failure mode this file keeps documenting. First I asked "which files call
    `renderInline`" — that flagged `markdown.jsx`, which *defines* it. Then I used the streaming
    caret — but `Playground.jsx` has one too, on a single answer.

    What makes something a transcript *turn* is the **speaker label**: choosing between "You" and
    "Cadre AI". The playground renders one unattributed answer; the chat and the widget render
    attributed turns. That is the property — precise, rather than merely narrow.
    """
    others = [p.name for p in COMPONENTS if p.name != "Turn.jsx" and "'Cadre AI'" in code(p)]
    assert not others, f"turn markup duplicated in {others}; they must render through Turn.jsx"


def test_user_turns_align_right():
    css = code(APP_CSS)
    assert ".turn--user" in css and "text-align: right" in css
    # Applied in Turn.jsx from a per-surface class map, so assert the mechanism and the chat view's
    # mapping rather than a concatenated literal that no longer exists anywhere.
    assert "classes.turnUser" in code(WEB / "Turn.jsx"), "the modifier must actually be applied"
    assert "turnUser: 'turn--user'" in code(APP), "the chat view must map it to the styled class"


# ── clickable links ──────────────────────────────────────────────────────────────────
#
# The chat now turns Cadre URLs into real links. `href` is the one attribute in this renderer
# that is *live* — `<strong>` is inert, a link is not — so these guard the boundary rather than
# the appearance.

CADRE_URLS_JS = WEB / "cadre-urls.js"


def _corpus_urls() -> set[str]:
    """Every page `content/raw/` proves the scraper actually fetched, canonicalised."""
    urls = set()
    for p in (WEB.parent.parent / "content" / "raw").glob("*.md"):
        m = re.search(r"^url:\s*(\S+)", p.read_text(encoding="utf-8"), re.M)
        if m:
            urls.add(m.group(1).rstrip("/").lower())
    return urls


def test_the_link_allowlist_matches_the_scraped_corpus():
    """`cadre-urls.js` is generated from `content/raw/` frontmatter and must not drift from it.

    Drift in either direction is a defect: a missing URL silently stops rendering as a link, and
    an extra one links to a page the provenance record cannot vouch for — which is the whole
    property the allowlist exists to hold.
    """
    in_js = {
        u.lower().rstrip("/")
        for u in re.findall(r"'(https?://[^']+)'", code(CADRE_URLS_JS))
    }
    corpus = _corpus_urls()

    assert in_js == corpus, (
        "web/src/cadre-urls.js has drifted from content/raw/.\n"
        f"  only in js     : {sorted(in_js - corpus)}\n"
        f"  only in corpus : {sorted(corpus - in_js)}\n"
        "Regenerate it from the frontmatter rather than hand-editing."
    )


def test_the_href_comes_from_the_allowlist_not_from_the_reply():
    """The strongest property here, and the reason this is an allowlist rather than a sanitiser.

    A matched URL is used as a KEY to look up the canonical string, and that constant is what
    reaches the DOM. So an `href` can only ever be one of the 36 values in `cadre-urls.js` — never
    a substring of model output, however the model was influenced into producing it. There is
    nothing left to sanitise.
    """
    src = link_path_source()
    assert "knownCadreUrl" in src, "the link path must resolve URLs through the allowlist"
    assert "href={resolved.href}" in code(MARKDOWN), "href must be the looked-up constant"
    # The matched text may be displayed but must never become the href.
    assert "href={piece}" not in src and "href={label}" not in src


def test_an_unknown_url_renders_as_plain_text():
    """An invented portal URL must not become a clickable link that looks official — the KB's
    first rule. Falling back to plain text is the pre-existing behaviour, so the failure mode of
    the whole feature is a no-op rather than a broken render."""
    src = link_path_source()
    assert "if (!resolved) return piece" in src, "an unresolved candidate must pass through"


def test_blank_targets_carry_noopener():
    """Without `rel`, the opened page gets a live `window.opener` handle back to this one."""
    src = code(MARKDOWN)
    if 'target="_blank"' in src:
        assert 'rel="noopener noreferrer"' in src


def test_trailing_punctuation_is_not_swallowed_into_the_href():
    """"…see https://www.cadreai.com/contact." — the full stop must stay in the prose.

    This is the most common way a naive linkifier fails, and it fails *silently*: the lookup
    misses, so the URL renders as plain text and nobody notices the link never appeared.
    """
    assert "TRAILING" in link_path_source(), "trailing punctuation must be trimmed before lookup"
    assert "{resolved.trailing}" in code(MARKDOWN), "the trimmed punctuation must still render"


def test_urls_inside_bold_are_still_linked():
    """The model emits `**https://www.cadreai.com/contact**`; the eval has caught a bolded
    `/contact` before. Bold must not defeat the link."""
    src = code(MARKDOWN)
    assert "<strong key={i}>{linkify(" in src
    assert "<em key={i}>{linkify(" in src


def test_links_are_black_with_an_underline():
    """CLAUDE.md: all text is black, de-emphasise with size and weight, never grey — and
    `--cadre-red` is the one documented colour exception. A link therefore carries its
    affordance with an underline rather than a colour."""
    css = code(APP_CSS)
    block = css.split(".message a {", 1)
    assert len(block) == 2, "no .message a rule found"
    rule = block[1].split("}", 1)[0]
    assert "text-decoration: underline" in rule
    assert "var(--text)" in rule
    assert "blue" not in rule.lower()


def test_bare_site_paths_resolve_through_the_allowlist():
    """The model writes `/contact` at least as often as the absolute form — it reads better in a
    list — and before paths resolved, those printed as dead text while absolute URLs became links.
    Reported by the user as "the real working URLs are gone again".

    ⚠️ **Resolving paths is also what puts an invented one under the allowlist.** A bare
    `/ai-agents` (the real page is `/agents`) previously bypassed the check entirely and sat in a
    list of genuine paths looking equally authoritative. Now it simply fails to become a link, so
    the one the corpus cannot vouch for is the one that is visibly different.
    """
    src = code(CADRE_URLS_JS)
    assert "candidate.startsWith('/')" in src, "bare paths must resolve against the site origin"
    assert "new URL(CADRE_URLS[0]).origin" in src, (
        "the origin must be derived from the allowlist, not written as a literal that could "
        "disagree with the list it describes"
    )
    assert "URL_RE" in code(LINKS), "the matching patterns belong in links.js"


def test_a_loose_path_match_is_harmless_because_the_allowlist_is_the_gate():
    """`and/or`, `24/7` and `he/she` all match the path pattern. That is fine and deliberate:
    matching is not what creates a link — the lookup is — so each falls through to plain text.

    Named explicitly because the tempting "fix" is a stricter regex, which would start rejecting
    real pages as the corpus grows."""
    assert "if (!resolved) return piece" in code(MARKDOWN), (
        "an unmatched candidate must be returned untouched"
    )


def test_html_revalidates_and_hashed_assets_are_immutable():
    """Vite hashes asset filenames, so index.html is the ONLY file with a stable name — and with no
    Cache-Control a browser applies *heuristic* caching. A stale index.html then references asset
    names that no longer exist, which presents as "my fix did not deploy" rather than as a cache
    problem. It has cost this project a debugging session twice.

    The two rules are deliberate opposites: HTML always revalidates (cheap, the ETag makes it a
    304), and hashed assets are immutable because the content hash IS the cache key.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)

    html = client.get("/")
    assert html.status_code == 200
    assert html.headers.get("cache-control") == "no-cache", (
        "index.html must revalidate, or a stale copy points at deleted asset filenames"
    )

    asset = re.search(r'/assets/[^"]+\.js', html.text)
    assert asset, "no hashed asset referenced by index.html"
    js = client.get(asset.group(0))
    assert js.status_code == 200
    assert "immutable" in js.headers.get("cache-control", ""), (
        "content-hashed assets are safe to cache forever; not doing so wastes every reload"
    )
