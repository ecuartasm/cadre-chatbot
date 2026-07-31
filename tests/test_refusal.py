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


def test_marker_mid_answer_is_stripped_too():
    """⚠️ **This asserts the OPPOSITE of what it did through Phase 9.**

    The original rule was leading-only, reasoning that a marker mid-sentence is the model quoting
    itself and rewriting the middle of an answer is not this class's job. That held for Haiku 4.5,
    which reliably puts the tag first as instructed.

    It broke on the first model swap. **Sonnet 5 uses the tag as a section separator** — general
    answer, tag, then the part it is declining — so leading-only stripping printed
    `[[refusal:security-specifics-not-public]]` straight into the chat. Measured at 2 leaks in 4
    runs of the same question, so not an edge case.

    Reversed deliberately, and the risk that justified leading-only is gone: prompt v1.8 forbids
    the model discussing its own tag at all, so a marker in the text is never legitimate content.
    """
    s = MarkerScanner()
    out = _run(s, "The general answer.\n\n[[refusal:no-public-pricing]]\n\nThe specifics are not.")
    assert "[[refusal" not in out
    assert out == "The general answer.\n\nThe specifics are not."
    assert s.reason == "no-public-pricing", "a mid-answer tag still classifies the turn"


def test_removing_a_tag_does_not_leave_a_hole_in_the_prose():
    """The tag usually arrives on its own line. Deleting it without collapsing the newlines around
    it leaves a visible gap where it was — the leak made cosmetic rather than fixed."""
    s = MarkerScanner()
    out = _run(s, "First paragraph.\n\n[[refusal:no-public-pricing]]\n\nSecond paragraph.")
    assert "\n\n\n" not in out
    assert not out.startswith(("\n", " "))


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


# ── the two ways a stream can end mid-marker ─────────────────────────────────────────
#
# These fail in OPPOSITE directions and are easy to conflate, which is why each has its own test.
# `test_an_unterminated_marker_does_not_swallow_the_reply` above covers a *long* buffer, where the
# opening bytes are followed by real prose and releasing is correct. Below is a *short* buffer at
# end-of-stream, where the buffer is nothing but a broken tag and releasing would print it.


def test_a_stream_ending_mid_marker_suppresses_the_broken_tag():
    """Found in the Phase 4 audit: `finish()` used to release unconditionally, so a truncated
    marker rendered as `[[refusal:no-public-pri` in the chat window."""
    s = MarkerScanner()
    assert s.feed("[[refusal:no-public-pri") == ""
    assert s.finish() == "", "a partial marker must never reach the user"
    assert s.truncated_marker == "[[refusal:no-public-pri", "and the suppression must be greppable"
    assert s.reason is None, "an unterminated marker classifies nothing"


def test_suppression_only_applies_to_marker_shaped_buffers():
    """A stream ending on ordinary held text must still release it — the suppression is narrow."""
    s = MarkerScanner()
    s.feed("[")  # a viable marker prefix, so it is held
    assert s.finish() == "["
    assert s.truncated_marker is None


def test_a_malformed_but_closed_marker_releases_the_whole_reply():
    """The regression the invariant test caught: suppressing everything that merely *starts* with
    the opening bytes threw away a real reply. A `]]` that failed the slug pattern can never become
    a valid marker, so it is released immediately rather than held — which is also what keeps the
    end-of-stream suppression narrow enough to be safe."""
    s = MarkerScanner()
    text = "[[refusal:bad slug]]body"
    assert _run(s, text) == text
    assert s.reason is None
    assert s.truncated_marker is None


def test_truncated_marker_is_not_set_on_a_normal_reply():
    s = MarkerScanner()
    _run(s, "[[refusal:off-topic]]a complete reply")
    assert s.truncated_marker is None


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


def test_prompt_tells_the_model_to_keep_tagging_across_turns():
    """The Phase 4 finding. The marker is stripped before display, so the model's own transcript
    shows its earlier refusals untagged — and it then stopped tagging on the pushback turn, which
    is exactly where the refusal metric matters most. Measured: pushback turns 2 and 3 logged
    status="ok" while refusing in prose; with this instruction all three log "refused"."""
    text = build_system_blocks()[0]["text"]
    assert "look untagged" in text
    assert "Tag EVERY refusal" in text


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
