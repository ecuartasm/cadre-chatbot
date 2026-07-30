"""Phase 3 — structural refusals.

Two things are under test and they fail differently.

The **marker scanner** is pure and deterministic, so it is tested exhaustively — including the
adversarial splits a real token stream produces. Its failure mode is the only one in this phase a
user sees directly: a `[[refusal:...]]` tag rendered in the chat window.

The **vocabulary** is derived from the corpus, so the tests assert the derivation rather than a
hard-coded list. A list copied into this file would be the second source of truth the loader
deliberately avoids.

All offline: no API key, no network.
"""

from __future__ import annotations

import pytest

from app.knowledge.loader import REFUSAL_REASONS
from app.llm.client import MarkerScanner
from app.llm.prompt import (
    CACHE_FLOOR_TOKENS,
    MEASURED_SYSTEM_TOKENS,
    SYSTEM_PROMPT_VERSION,
    build_system_blocks,
)

# ── the vocabulary comes from the corpus ─────────────────────────────────────────────


def test_reasons_are_parsed_from_the_corpus_not_hardcoded():
    # 15 rows in the NEGATIVE KNOWLEDGE table + off-topic, which has no row because it is not a
    # knowledge gap.
    assert len(REFUSAL_REASONS) == 16


@pytest.mark.parametrize(
    "slug",
    ["no-public-pricing", "no-public-portal-access", "no-episode-content", "off-topic"],
)
def test_load_bearing_reasons_are_present(slug: str):
    """Each maps to a boundary the bot must not cross. The loader refuses to serve without them."""
    assert slug in REFUSAL_REASONS


def test_reasons_look_like_slugs():
    assert all(s == s.lower() and " " not in s for s in REFUSAL_REASONS)


def test_a_corpus_missing_its_boundary_rules_is_rejected():
    from app.knowledge.loader import CorpusError, _parse_refusal_reasons

    with pytest.raises(CorpusError, match="no longer defines"):
        _parse_refusal_reasons(
            "NEGATIVE KNOWLEDGE\n| x | `no-public-pricing` |\n## How to refuse\n"
        )


def test_a_corpus_without_the_table_is_rejected_rather_than_yielding_an_empty_enum():
    """An empty vocabulary would validate nothing, so every model-invented slug would be dropped
    and the refusal rate would silently read as zero."""
    from app.knowledge.loader import CorpusError, _parse_refusal_reasons

    with pytest.raises(CorpusError, match="Could not locate"):
        _parse_refusal_reasons("a corpus with no boundary section at all")


# ── the marker scanner ───────────────────────────────────────────────────────────────


def _run(scanner: MarkerScanner, *pieces: str) -> str:
    """Feed pieces in order, return everything the user would have seen."""
    return "".join(scanner.feed(p) for p in pieces) + scanner.finish()


def test_marker_is_stripped_and_the_reason_captured():
    s = MarkerScanner()
    out = _run(s, "[[refusal:no-public-pricing]]We don't publish pricing.")
    assert out == "We don't publish pricing."
    assert s.reason == "no-public-pricing"


def test_marker_split_across_deltas_is_still_caught():
    """The realistic case: tokens arrive in arbitrary pieces, never aligned to the marker."""
    s = MarkerScanner()
    out = _run(s, "[[re", "fusal:no-e", "pisode-content]]", "I can name the episode")
    assert out == "I can name the episode"
    assert s.reason == "no-episode-content"


def test_marker_split_character_by_character():
    s = MarkerScanner()
    out = _run(s, *list("[[refusal:off-topic]]I can help with Cadre AI questions."))
    assert out == "I can help with Cadre AI questions."
    assert s.reason == "off-topic"


def test_an_ordinary_answer_passes_through_untouched():
    s = MarkerScanner()
    text = "Cadre works with construction, healthcare, and financial services."
    assert _run(s, text) == text
    assert s.reason is None


def test_leading_whitespace_before_the_marker_is_tolerated():
    """The prompt says the marker comes first; models add a stray newline anyway, and losing the
    classification over one would be silly."""
    s = MarkerScanner()
    out = _run(s, "\n\n[[refusal:no-public-pricing]]\nEngagements are scoped individually.")
    assert out == "Engagements are scoped individually."
    assert s.reason == "no-public-pricing"


def test_text_that_merely_starts_like_a_marker_is_released_intact():
    s = MarkerScanner()
    text = "[[this is not a marker]] but it is an answer"
    assert _run(s, text) == text
    assert s.reason is None


def test_an_unterminated_marker_does_not_swallow_the_reply():
    """If the model opens a marker and never closes it, the held text must still reach the user —
    a silently truncated answer would be worse than a visible tag."""
    s = MarkerScanner()
    text = "[[refusal:" + "x" * 200
    assert _run(s, text) == text
    assert s.reason is None


def test_a_reply_that_is_only_a_marker_yields_no_visible_text():
    s = MarkerScanner()
    assert _run(s, "[[refusal:off-topic]]") == ""
    assert s.reason == "off-topic"


def test_marker_later_in_the_reply_is_not_stripped():
    """Only a leading marker is structural. One mid-sentence is the model quoting itself, and
    rewriting the middle of an answer is not this class's job."""
    s = MarkerScanner()
    text = "Here is the answer. [[refusal:no-public-pricing]] was not meant literally."
    assert _run(s, text) == text
    assert s.reason is None


def test_scanner_never_drops_characters():
    """The invariant that matters: held text is delayed, never lost."""
    for text in [
        "[[refusal:off-topic]]tail",
        "[[refu",
        "[",
        "",
        "normal answer",
        "[[refusal:bad slug]]body",
    ]:
        s = MarkerScanner()
        out = _run(s, text)
        stripped = f"[[refusal:{s.reason}]]" if s.reason else ""
        assert stripped + out == text.lstrip() or stripped + out == text


@pytest.mark.parametrize("slug", sorted(REFUSAL_REASONS))
def test_every_corpus_slug_round_trips_through_the_scanner(slug: str):
    """Guards the regex against a slug the corpus adds later — a 41-char reason or one with an
    unexpected character would fail to match and the refusal would go unclassified."""
    s = MarkerScanner()
    out = _run(s, f"[[refusal:{slug}]]the reply")
    assert s.reason == slug, f"corpus slug {slug!r} is not matched by the marker regex"
    assert out == "the reply"


# ── the prompt itself ────────────────────────────────────────────────────────────────


def test_prompt_teaches_the_marker_format_it_parses():
    """If these drift apart the model emits a tag nothing strips, and it renders in the chat."""
    text = build_system_blocks()[0]["text"]
    assert "[[refusal:" in text


def test_prompt_still_clears_the_cache_floor_after_phase_3():
    assert MEASURED_SYSTEM_TOKENS >= CACHE_FLOOR_TOKENS
    assert MEASURED_SYSTEM_TOKENS - CACHE_FLOOR_TOKENS >= 300, (
        "margin under 300 tokens is too thin — a later prose edit would silently disable caching"
    )


def test_prompt_version_was_bumped_for_phase_3():
    """Log lines from two different prompts are otherwise indistinguishable."""
    assert SYSTEM_PROMPT_VERSION != "1.0"


def test_conversion_guidance_is_present_and_bounded():
    text = build_system_blocks()[0]["text"]
    assert "cadreai.com/contact" in text
    # The restraint half matters as much as the invitation: an answer followed by an unnecessary
    # pitch reads worse than the answer alone.
    assert "Do not do it in every message" in text


def test_prompt_has_no_per_request_content():
    """Byte-stability: anything dynamic here silently disables caching for every turn."""
    assert build_system_blocks()[0]["text"] == build_system_blocks()[0]["text"]
    assert build_system_blocks()[0]["cache_control"] == {"type": "ephemeral"}
