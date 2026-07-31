"""Per-model facts, in one place.

Swapping the model is meant to be a `.env` change — `ANTHROPIC_MODEL=claude-sonnet-5` — and this
module is what makes that safe rather than merely possible. Before it existed, three things were
hardcoded to Haiku and would have been silently wrong after a swap:

1. **The cache floor.** 4,096 on Haiku 4.5, 1,024 on Sonnet 5. The floor test would have kept
   asserting Haiku's number: still passing, no longer checking anything real.
2. **The price table.** Every Sonnet rate is 3x. Cost, the daily cap, and `/api/stats` all read it.
3. **Thinking.** Sonnet 5 accepts a `thinking` parameter and Haiku 4.5 does not; sending one to
   Haiku is an error, and omitting it on Sonnet leaves the behaviour to a default.

⚠️ **Cache floors are NON-MONOTONIC.** The cheaper, smaller model has the *higher* floor — 4,096 on
Haiku against 1,024 on Sonnet. It cannot be inferred from the tier, so it lives here as data.

⚠️ **`rates` is the single source of truth for pricing.** `app/obs/cost.py` imports from here rather
than keeping its own copy; two tables would be two places for a rate to drift, and the one that
drifted would silently corrupt the spend cap.

**Adding a model** means adding a row here — and measuring the prefix against its floor, since
`MEASURED_SYSTEM_TOKENS` is recorded per tokeniser.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    id: str
    context_window: int
    max_output: int
    # Minimum cacheable prefix. Below it, caching fails SILENTLY — no error, the cache counters
    # simply stay 0 while every turn pays full input price.
    cache_floor: int
    # Per million tokens. Four rates, never two: a cost computed from input+output alone is wrong
    # the moment caching engages.
    rates: dict[str, float]
    # Sonnet 5 accepts `thinking`; Haiku 4.5 does not. `None` means "do not send the parameter".
    #
    # Set to disabled rather than omitted on models that support it. Measured on this workload,
    # adaptive thinking did not trigger anyway (no thinking blocks, same 2.8s latency with and
    # without) — but "it didn't fire on the prompts I tried" is weaker than "it cannot fire", and
    # this is a latency-sensitive support bot where the variance is not worth keeping.
    thinking: dict[str, str] | None = None


HAIKU_4_5 = ModelSpec(
    id="claude-haiku-4-5",
    context_window=200_000,
    max_output=64_000,
    cache_floor=4096,
    rates={"input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10},
    thinking=None,  # not supported; sending it is an error
)

SONNET_5 = ModelSpec(
    id="claude-sonnet-5",
    context_window=1_000_000,
    max_output=128_000,
    cache_floor=1024,
    # Every rate is exactly 3x Haiku, which is why scale is an argument FOR Haiku rather than
    # against it: the gap compounds with volume rather than shrinking.
    rates={"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
    thinking={"type": "disabled"},
)

MODELS: dict[str, ModelSpec] = {m.id: m for m in (HAIKU_4_5, SONNET_5)}

DEFAULT_MODEL = HAIKU_4_5.id


class UnknownModelError(KeyError):
    """A model with no spec. Never fall back to another model's numbers — a wrong cache floor
    disables caching silently and a wrong rate corrupts the only control that costs money."""


def spec_for(model_id: str) -> ModelSpec:
    try:
        return MODELS[model_id]
    except KeyError as e:
        raise UnknownModelError(
            f"No spec for {model_id!r}. Add it to app/llm/models.py before using it — an unspecced "
            f"model has no cache floor and no price table. Known: {sorted(MODELS)}"
        ) from e


def active() -> ModelSpec:
    """The model this process is configured to use. Resolved from the environment at call time so
    a test can monkeypatch `ANTHROPIC_MODEL` without reimporting."""
    return spec_for(os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL))
