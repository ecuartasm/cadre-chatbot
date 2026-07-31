"""Cost accounting — four rates, not two.

Phase 0 measured `cache_read=0`, so a two-rate table (input/output) would have looked correct and
been wrong the moment caching engaged. Phase 1 production shows a 4,409-token cache **write** on
the first call of a TTL window and a 4,409-token **read** thereafter, billing at 1.25× and 0.1× of
input respectively. Computing `cost_usd` from input+output alone would have over-counted cached
turns by ~4× and made the daily cap throttle on money never spent.

Rates are per million tokens, Haiku 4.5, verified against the published pricing."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.models import UnknownModelError, spec_for

__all__ = ["UnknownModelError", "Usage", "InteractionLog", "cost_usd", "rates_for"]

# Rates live in app/llm/models.py, with the cache floor and thinking config for the same model.
# Keeping a second table here would be a second place for a rate to drift — and the one that drifted
# would silently corrupt the spend cap, which is the only control that costs money.
def rates_for(model: str) -> dict[str, float]:
    """Four rates for a model. Raises `UnknownModelError` rather than guessing."""
    return spec_for(model).rates


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_prompt_tokens(self) -> int:
        """What the model actually read. `input_tokens` alone excludes the cached portion, which is
        why a naive 'prompt size' reading of it looks absurdly small on a cache hit (12 tokens)."""
        return (
            self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "total_prompt_tokens": self.total_prompt_tokens,
        }


def cost_usd(usage: Usage, model: str) -> float:
    r = rates_for(model)
    return (
        usage.input_tokens * r["input"]
        + usage.output_tokens * r["output"]
        + usage.cache_creation_input_tokens * r["cache_write"]
        + usage.cache_read_input_tokens * r["cache_read"]
    ) / 1_000_000


@dataclass
class InteractionLog:
    """One chat turn. Written to interactions.jsonl at turn end — including when the turn was
    abandoned mid-stream, which is the case a naive implementation loses entirely (plan.md §2.2)."""

    request_id: str
    model: str
    system_prompt_version: str
    user_message_redacted: str
    latency_ms: int
    status: str  # 'ok' | 'refused' | 'error' | 'abandoned'
    usage: Usage = field(default_factory=Usage)
    assistant_chars: int = 0
    stop_reason: str | None = None
    refusal_reason: str | None = None
    error: str | None = None
    history_turns_sent: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            # Emitted explicitly rather than left to the formatter's ContextVar fallback. This
            # record is written from a generator's `finally`, which on a client disconnect may run
            # outside the request's context — and losing the id on an abandoned turn would break
            # the one case this log exists to capture. The formatter prefers this over the
            # ContextVar, so the two cannot silently disagree.
            "request_id": self.request_id,
            "model": self.model,
            "system_prompt_version": self.system_prompt_version,
            "user_message_redacted": self.user_message_redacted,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "usage": self.usage.as_dict(),
            "cost_usd": round(cost_usd(self.usage, self.model), 8),
            "assistant_chars": self.assistant_chars,
            "stop_reason": self.stop_reason,
            "refusal_reason": self.refusal_reason,
            "error": self.error,
            "history_turns_sent": self.history_turns_sent,
        }
