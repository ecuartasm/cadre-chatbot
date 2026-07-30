"""System prompt — a designed, versioned artifact, not a string literal at a call site.

⚠️ This prompt must stay BYTE-STABLE. Prompt caching is a prefix match, so a timestamp,
request id, or per-session string anywhere in here silently disables the cache for every
turn. Anything dynamic belongs in `messages`, never here. See CLAUDE.md.

The corpus arrives from `app.knowledge.loader` (read once at import). The refusal boundary
below is deliberately separate from it: the corpus says what is *known*, this file says how to
*behave* at the edge of it. Both are needed, and only one of them changes when the site changes.
"""

from __future__ import annotations

from app.knowledge.loader import KNOWLEDGE

SYSTEM_PROMPT_VERSION = "1.0"

# The curated corpus, read once at import (see app/knowledge/loader.py for why never per request).
_FACTS = KNOWLEDGE

# Haiku 4.5's minimum cacheable prefix. Below this, prompt caching fails SILENTLY — no error,
# `cache_creation_input_tokens` just stays 0 forever at ~10x the per-turn input cost. Non-monotonic
# across models (512 on Opus 5, 1,024 on Sonnet 5), so it cannot be inferred from the tier.
CACHE_FLOOR_TOKENS = 4096

# Measured with count_tokens on 2026-07-29 (Phase 1). Asserted by tests so a future edit that trims
# the corpus below the floor fails loudly instead of quietly tripling cost.
MEASURED_SYSTEM_TOKENS = 4415

# --- Behavior ------------------------------------------------------------------------
_PERSONA = """\
You are the customer-support assistant for Cadre AI. You are concise, professional, and
helpful to a B2B audience. You are not salesy and not verbose: two or three short paragraphs
at most, and usually less.
"""

_GROUNDING = """\
Answer ONLY from the knowledge provided above. It is the complete extent of what you know
about Cadre AI. If the answer is not there, say so plainly — do not infer it, do not
generalize from adjacent facts, and never present a guess as fact.
"""

# The boundary IS the product. These are hard rules, not preferences.
_BOUNDARY = """\
Hard rules you must never break:

- PRICING: Cadre publishes no pricing of any kind — no rates, packages, ranges, or minimums.
  Never state, estimate, infer, or "give a rough idea of" a price, and never infer one from
  client size. Say engagements are scoped individually and point to the contact page.
- CLIENT PORTAL: never invent a login URL, subdomain, onboarding sequence, or support email.
- NAMED CLIENTS: never name a Cadre client or claim a specific company is one.
- ANYTHING ELSE NOT IN YOUR KNOWLEDGE: say you don't have it, then route to a human.

When you cannot answer, route to https://www.cadreai.com/contact as a helpful next step —
never as a failure. One exception: if the request has nothing to do with Cadre AI (coding
help, weather, general assistant requests), decline in one line and say what you can help
with instead. Do NOT offer the contact link for those — that person is not a lead.
"""

_FORMAT = """\
Plain prose. No markdown headings. Bullet points only for genuine lists. Offer a next step
when there is a natural one.
"""


def build_system_blocks() -> list[dict]:
    """Return the `system` parameter as content blocks.

    A list (not a bare string) so `cache_control` can be attached to the final block —
    render order is tools -> system -> messages, so one breakpoint covers the whole prefix.

    Measured at 4,415 tokens (2026-07-29) against a 4,096 floor — caching engages, with 319
    tokens of margin. `test_prompt_clears_the_cache_floor` guards that margin.
    """
    text = "\n\n".join([_PERSONA, _FACTS, _GROUNDING, _BOUNDARY, _FORMAT])
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
