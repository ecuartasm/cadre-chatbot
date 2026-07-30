"""Phase 1 — corpus integrity and the cache floor.

The cache-floor test is the important one here. Prompt caching failing is a **silent** fault: no
error, `cache_creation_input_tokens` simply stays 0 and every turn costs ~10x more input forever.
The only way that becomes noticeable is a test. Everything else in this file guards the boundary
rules, because a corpus that quietly loses its refusal list is a bot that starts inventing prices.
"""

from __future__ import annotations

import os

import pytest

from app.knowledge.loader import KB_PATH, KNOWLEDGE, KNOWLEDGE_SHA256, info
from app.llm.prompt import (
    CACHE_FLOOR_TOKENS,
    MEASURED_SYSTEM_TOKENS,
    build_system_blocks,
)

# ── corpus is present and fit to serve ───────────────────────────────────────────────


def test_corpus_exists_and_is_substantial():
    assert KB_PATH.exists()
    assert len(KNOWLEDGE) > 10_000


def test_corpus_is_backed_by_scraped_pages():
    """`content/raw/` is the provenance record. Absent at runtime is fine (the app never reads it),
    but absent in the working tree means the corpus has no audit trail."""
    assert info()["raw_pages"] >= 30


def test_loader_is_read_once_not_per_call():
    """Byte-stability of the cached prefix depends on this. Two reads must be the same object."""
    from app.knowledge import loader

    assert loader.KNOWLEDGE is KNOWLEDGE
    assert loader.KNOWLEDGE_SHA256 == KNOWLEDGE_SHA256


# ── the boundary survives in the corpus ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "reason",
    [
        "no-public-pricing",
        "no-public-portal-access",
        "no-episode-content",
        "clients-anonymised",
        "security-specifics-not-public",
        "no-public-client-size",
        "off-topic",
    ],
)
def test_every_refusal_reason_is_declared(reason: str):
    assert reason in KNOWLEDGE, f"corpus lost refusal_reason '{reason}'"


def test_corpus_routes_refusals_to_contact():
    assert "cadreai.com/contact" in KNOWLEDGE


def test_corpus_names_no_client_company():
    """The gate resolved 2026-07-29: every client on /case-studies is 'Non-Disclosed Company', and
    'Griffin Funding' was a fabrication that never appeared on the page. It must not reappear."""
    assert "Non-Disclosed Company" in KNOWLEDGE
    for fabricated in ("Griffin Funding", "iSupport", "Avanti Capital", "TZP Group"):
        assert fabricated not in KNOWLEDGE, f"'{fabricated}' is not on the source page"


def test_corpus_states_eight_case_studies_not_nine():
    assert "eight" in KNOWLEDGE.lower()
    assert "nine engagements" not in KNOWLEDGE.lower()


def test_corpus_carries_no_revenue_band():
    """$30M–$500M was asserted by the research notes and appears nowhere on the site."""
    for banned in ("$30M", "$500M", "$50M", "$2B"):
        assert banned not in KNOWLEDGE


def test_corpus_declares_the_pillar_count_discrepancy():
    """The page says '8 Pillars' and lists nine. The corpus flags that, rather than picking."""
    assert "nine items" in KNOWLEDGE or "lists nine" in KNOWLEDGE


# ── the cache floor ──────────────────────────────────────────────────────────────────


def test_measured_token_count_clears_the_floor():
    assert MEASURED_SYSTEM_TOKENS >= CACHE_FLOOR_TOKENS, (
        f"assembled prompt measured {MEASURED_SYSTEM_TOKENS} tokens, below the "
        f"{CACHE_FLOOR_TOKENS}-token floor — caching would silently never engage"
    )


def test_prompt_has_not_shrunk_since_it_was_measured():
    """Cheap proxy that runs offline on every commit: if the corpus is trimmed substantially,
    this trips and tells you to re-measure rather than letting the cache quietly stop."""
    chars = len(build_system_blocks()[0]["text"])
    assert chars >= 16_000, (
        f"assembled prompt is {chars} chars; it was 17,336 when measured at "
        f"{MEASURED_SYSTEM_TOKENS} tokens. Re-run the count_tokens measurement before shipping."
    )


@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="needs an API key")
def test_real_token_count_matches_the_recorded_measurement():
    """The authoritative check. `count_tokens` is free, so there is no excuse for guessing —
    and this is what catches the recorded number drifting from reality."""
    from anthropic import Anthropic

    n = (
        Anthropic()
        .messages.count_tokens(
            model="claude-haiku-4-5",
            system=build_system_blocks(),
            messages=[{"role": "user", "content": "x"}],
        )
        .input_tokens
    )
    assert n >= CACHE_FLOOR_TOKENS, f"live count {n} is below the {CACHE_FLOOR_TOKENS} floor"
    assert abs(n - MEASURED_SYSTEM_TOKENS) < 150, (
        f"live count {n} has drifted from the recorded {MEASURED_SYSTEM_TOKENS}; update it"
    )
