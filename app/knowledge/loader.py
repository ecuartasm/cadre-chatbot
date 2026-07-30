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


# Module-level, evaluated exactly once on import.
KNOWLEDGE: Final[str] = _load()
KNOWLEDGE_SHA256: Final[str] = hashlib.sha256(KNOWLEDGE.encode("utf-8")).hexdigest()


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
