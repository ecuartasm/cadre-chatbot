"""The only module in this codebase that imports `anthropic`.

That is the point: it is what makes the provider swappable. Everything upstream depends on
`stream_reply()` and the `Chunk` shape, not on the SDK. See CLAUDE.md.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

import anthropic
from anthropic import AsyncAnthropic

from app.llm.prompt import SYSTEM_PROMPT_VERSION, build_system_blocks

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")

# Support answers are short. A low ceiling bounds cost and keeps latency honest —
# it is not a limit we expect to hit.
MAX_TOKENS = 1024

# Fail fast rather than leaving a user watching a dead stream.
REQUEST_TIMEOUT_S = 30.0


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    # Tracked from the start: with caching on, writes bill ~1.25x input and reads ~0.1x,
    # so a cost computed from input/output alone is wrong. See CLAUDE.md.
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class Chunk:
    """One event on the wire. `type` drives how the client renders it."""

    type: Literal["delta", "done", "error"]
    text: str = ""
    usage: Usage = field(default_factory=Usage)
    stop_reason: str | None = None


_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    """Lazy singleton. Built on first use so importing this module never requires a key —
    which is what lets the tests and `/health` work without one."""
    global _client
    if _client is None:
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _client = AsyncAnthropic(api_key=key, timeout=REQUEST_TIMEOUT_S, max_retries=2)
    return _client


async def stream_reply(messages: list[dict]) -> AsyncIterator[Chunk]:
    """Stream one assistant turn.

    Yields `delta` chunks, then exactly one terminal `done` or `error`. Never raises to the
    caller: an exception here would abort the HTTP stream mid-flight and the browser would
    see a truncated response with no explanation, so failures are yielded as data instead.
    """
    try:
        client = get_client()
        async with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=build_system_blocks(),
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield Chunk(type="delta", text=text)

            final = await stream.get_final_message()
            u = final.usage
            yield Chunk(
                type="done",
                stop_reason=final.stop_reason,
                usage=Usage(
                    input_tokens=u.input_tokens,
                    output_tokens=u.output_tokens,
                    # Absent on models/paths without caching — default rather than assume.
                    cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
                    cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                ),
            )

    # Distinguish the failures a user can act on from the ones they cannot.
    except anthropic.RateLimitError:
        yield Chunk(type="error", text="I'm getting more requests than I can handle right now. "
                                      "Please try again in a moment.")
    except anthropic.APITimeoutError:
        yield Chunk(type="error", text="That took too long to answer. Please try again.")
    except anthropic.AuthenticationError:
        # Never surface credential detail to the browser; the log carries the real cause.
        yield Chunk(type="error", text="I'm not able to answer right now. Please try again later.")
    except anthropic.APIError:
        yield Chunk(type="error", text="Something went wrong reaching the model. "
                                      "Please try again.")
    except Exception:
        yield Chunk(type="error", text="Something went wrong. Please try again.")


def model_info() -> dict[str, object]:
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system_prompt_version": SYSTEM_PROMPT_VERSION,
    }
