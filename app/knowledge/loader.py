"""Knowledge layer — loads and validates the curated corpus.

⚠️ **Read once at import, never per request.** The corpus is part of the cached prompt prefix, and
prompt caching is a byte-exact prefix match. Re-reading per request risks a byte-different prefix
(trailing whitespace, encoding, mtime-dependent anything) and would silently disable the cache — the
same failure class as being under the token floor, reached from a different direction.

Fails loudly at startup if the corpus is missing. A bot that boots happily and answers from
nothing is far worse than one that refuses to start: the first is a silent wrong-answer machine,
the second is a deploy that visibly fails. This is the check that catches a Dockerfile that
forgot `COPY content/`.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Final

CONTENT_DIR: Final = Path(__file__).parent.parent.parent / "content"
KB_PATH: Final = CONTENT_DIR / "knowledge-base.md"

# Every disclosure tag the curated file is allowed to use. A typo here would silently create a
# section the escalation logic can't reason about.
VALID_DISCLOSURES: Final = frozenset({"answerable", "acknowledge-only", "refuse"})

# Sections whose absence means the corpus is not fit to serve. These are the boundary rules — if the
# curated file lost them, the bot would start answering things it must refuse.
REQUIRED_MARKERS: Final = (
    "NEGATIVE KNOWLEDGE",
    "cadreai.com/contact",
    "no-public-pricing",
    "no-public-portal-access",
    "no-episode-content",
)


class CorpusError(RuntimeError):
    """The corpus is missing or unfit to serve. Never swallow this."""


def _load() -> str:
    if not KB_PATH.exists():
        raise CorpusError(
            f"Curated knowledge base not found at {KB_PATH}. "
            "If this is a container, the image is missing `COPY content/ ./content/`."
        )

    text = KB_PATH.read_text(encoding="utf-8").strip()

    if len(text) < 2000:
        raise CorpusError(f"Corpus at {KB_PATH} is only {len(text)} chars — truncated or a stub?")

    missing = [m for m in REQUIRED_MARKERS if m not in text]
    if missing:
        raise CorpusError(
            f"Corpus is missing required boundary markers: {missing}. "
            "Refusing to serve a corpus without its negative-knowledge rules."
        )

    return text


# Middle column of the NEGATIVE KNOWLEDGE table: | topic | `slug` | correct behavior |
_TABLE_SLUG_RE: Final = re.compile(r"^\|[^|]+\|\s*`([a-z0-9-]+)`\s*\|", re.M)
# Inline tags on individual entries, e.g. "Log as `refusal_reason: off-topic`."
_INLINE_SLUG_RE: Final = re.compile(r"refusal_reason:\s*`?([a-z0-9-]+)`?")

# Slugs that must survive any future curation. If one of these disappears the corpus has lost a
# boundary rule, and the loader should refuse to serve rather than let the bot answer it.
_LOAD_BEARING_REASONS: Final = frozenset(
    {"no-public-pricing", "no-public-portal-access", "no-episode-content", "off-topic"}
)


def _parse_refusal_reasons(text: str) -> frozenset[str]:
    """Derive the closed set of `refusal_reason` values **from the corpus**.

    The corpus is the source of truth for what the bot refuses, so it is also the source of truth
    for the vocabulary those refusals are logged under. A hand-maintained list in Python would be a
    second place for it to live and therefore a place for it to drift — a slug renamed in the table
    would keep validating against a stale copy here, and the logs would quietly disagree with the
    corpus they came from.

    Two sources, unioned: the NEGATIVE KNOWLEDGE table (15 rows) and the inline
    `refusal_reason: <slug>` tags carried by individual entries, which is where `off-topic` lives —
    it is not a knowledge gap, so it has no row in the table.
    """
    try:
        table = text[text.index("NEGATIVE KNOWLEDGE") : text.index("## How to refuse")]
    except ValueError as e:
        raise CorpusError(
            "Could not locate the NEGATIVE KNOWLEDGE table or the 'How to refuse' section. "
            "The refusal vocabulary is parsed from between them; refusing to serve a corpus "
            "whose boundary rules cannot be read."
        ) from e

    reasons = set(_TABLE_SLUG_RE.findall(table)) | set(_INLINE_SLUG_RE.findall(text))

    missing = sorted(_LOAD_BEARING_REASONS - reasons)
    if missing:
        raise CorpusError(
            f"Corpus no longer defines these refusal reasons: {missing}. "
            "Each corresponds to a boundary the bot must not cross."
        )
    return frozenset(reasons)


# Module-level, evaluated exactly once on import.
KNOWLEDGE: Final[str] = _load()
KNOWLEDGE_SHA256: Final[str] = hashlib.sha256(KNOWLEDGE.encode("utf-8")).hexdigest()

# The closed enum a logged `refusal_reason` is validated against. A value outside it means the model
# invented a slug, which is recorded as a warning rather than written to the interaction log.
REFUSAL_REASONS: Final[frozenset[str]] = _parse_refusal_reasons(KNOWLEDGE)


def raw_page_count() -> int:
    """How many byte-faithful source pages back this corpus. 0 if `raw/` wasn't shipped —
    which is fine at runtime: `raw/` is provenance for humans, not something the app reads."""
    raw = CONTENT_DIR / "raw"
    return len(list(raw.glob("*.md"))) if raw.is_dir() else 0


def info() -> dict[str, object]:
    """Corpus provenance, safe to expose. Lets a deployed instance prove which corpus it is
    serving without shipping the whole file to the client."""
    return {
        "chars": len(KNOWLEDGE),
        "sha256": KNOWLEDGE_SHA256[:12],
        "raw_pages": raw_page_count(),
    }
