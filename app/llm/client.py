"""The only module in this codebase that imports `anthropic`.

That is the point: it is what makes the provider swappable. Everything upstream depends on
`stream_reply()` and the `Chunk` shape, not on the SDK. See CLAUDE.md.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Final, Literal

import anthropic
from anthropic import AsyncAnthropic

from app.llm.models import DEFAULT_MODEL, spec_for
from app.llm.prompt import SYSTEM_PROMPT_VERSION, build_system_blocks

# The model this process talks to. Resolved ONCE at import -- which is why .env must be loaded
# by app/__init__.py, before any app.* module runs. Editing .env needs a restart.
MODEL = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)

# Optional gateway. Unset — the default — means talking to api.anthropic.com exactly as before, so
# nothing about local development changes. Set, it routes through a compatible endpoint; the
# deployed instance uses OpenRouter, because the key Cadre supplied for the project is theirs
# (`sk-or-v1-…`), not an Anthropic one.
#
# The seam makes this a one-line change rather than a port: everything upstream depends on
# `stream_reply()` and the `Chunk` shape, and the gateway speaks the same `/v1/messages` wire
# format, so `MarkerScanner`, the four-rate cost model, the refusal enum and the spend cap are all
# untouched. Verified end to end on both models, including prompt caching.
#
# ⚠️ **Do NOT include `/v1`.** The SDK appends `/v1/messages` itself, so a base of
# `https://openrouter.ai/api/v1` requests `/api/v1/v1/messages` and gets a 404 HTML page — an
# error that names nothing useful. The correct value is `https://openrouter.ai/api`.
# `or None` so an empty string is treated as unset rather than as a broken URL.
BASE_URL = os.getenv("ANTHROPIC_BASE_URL") or None

# Support answers are short. A low ceiling bounds cost and keeps latency honest — it is not a limit
# we expect to hit (the longest observed answer was 150 output tokens). Clamped to the model's own
# maximum so a swap to a model with a lower ceiling fails loudly here rather than at the API.
# Output ceiling per turn. min() rather than a bare 1024, so a model with a lower ceiling than
# ours is respected instead of producing an API error.
MAX_TOKENS = min(1024, spec_for(MODEL).max_output)

# Fail fast rather than leaving a user watching a dead stream.
# Wall-clock budget for one model call. Long enough for a slow first token, short enough that a
# hung upstream surfaces as a readable error rather than a browser spinning indefinitely.
REQUEST_TIMEOUT_S = 30.0


# The four token counters, mirrored from the SDK response so nothing upstream imports an SDK type.
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
    # Raw slug from the refusal marker, if the model emitted one. NOT validated here — the caller
    # checks it against the corpus enum, because the corpus is what defines the vocabulary.
    refusal_reason: str | None = None


# --- Refusal marker ------------------------------------------------------------------
#
# The model opens a refusal with `[[refusal:<slug>]]`. Making the refusal structural is the whole
# point: without it, "how often does the bot refuse and why" can only be answered by matching
# substrings in prose, which CLAUDE.md's verification rule already rules out as untrustworthy.
#
# The marker MUST NOT reach the browser. It is stripped here, in the only module that knows the
# marker exists, rather than in the API layer or the UI — a leak would be the one Phase 3 failure a
# user sees directly.

# Two patterns, for two different jobs.
#   _MARKER_OPEN     -- the literal prefix. Used to ask "could this tail still BECOME a marker?"
#                       while the stream is mid-flight, when no regex can match yet.
#   _MARKER_ANYWHERE -- matches a COMPLETE tag and captures the slug. Strict about slug shape
#                       ([a-z0-9-], 1-40) because this parses OUR format. The inbound pattern in
#                       chat.py is deliberately looser: that one sanitises hostile input.
# ⚠️ "ANYWHERE", not "at the start". The prompt tells the model to put the tag first and Haiku
# does -- but Sonnet uses it as a mid-answer section separator, and leading-only stripping
# printed it into the chat in 2 of 4 runs while 171 unit tests stayed green.
_MARKER_OPEN: Final = "[[refusal:"
_MARKER_ANYWHERE: Final = re.compile(r"\[\[refusal:([a-z0-9-]{1,40})\]\]")
# Longest real slug is 29 chars, so a well-formed marker is ~42. Past this the model is writing
# prose that merely began like a marker; stop holding it back. Bounded on purpose: an unterminated
# '[[refusal:' must not buffer the whole reply forever.
_MARKER_MAX: Final = 64


class MarkerScanner:
    """Strips `[[refusal:<slug>]]` from a token stream, wherever it appears.

    Deltas arrive in arbitrary pieces — `[[refu` / `sal:no-public-pricing]]Cadre...` is normal — so
    this holds back a short tail (`_MARKER_MAX` characters) that might still turn out to be part of
    a marker. Held text is delayed, never dropped.

    ⚠️ **This used to strip a LEADING marker only**, on the Phase 3 reasoning that a marker
    mid-sentence is the model quoting itself and rewriting the middle of an answer is not this
    class's job. That was right for Haiku 4.5, which reliably puts the tag first as instructed.

    It is wrong across models. **Sonnet 5 emits the tag mid-answer as a section separator** — after
    a paragraph of general answer, before the part it is declining — and leading-only stripping
    printed it straight into the chat. Measured: 2 leaks in 4 runs.

    The risk that justified leading-only is also gone: prompt v1.8 forbids the model discussing its
    own tag at all, so a marker in the text is never legitimate content. And the pattern is specific
    enough (`[[refusal:` + lowercase slug + `]]`) that prose cannot produce it by accident.
    """

    # State for one stream. A scanner is single-use -- one per turn, never shared.
    def __init__(self) -> None:
        self._buf = ""
        # False until the first visible character has been emitted. Until then, leading whitespace
        # is dropped: a marker on its own line leaves the newline behind it, and an answer that
        # opens with a blank line is a visible artifact of a tag the user is never supposed to see.
        self._started = False
        self.reason: str | None = None
        # Set when a stream ended while holding something marker-shaped. Surfaced so the
        # suppression is greppable rather than a silent deletion of model output.
        self.truncated_marker: str | None = None

    # Consume one delta from the model.
    #   in : text -- the raw fragment as it arrived
    #   out: the portion SAFE to display now, with any complete marker removed. May be "" while
    #        the scanner is holding a possible partial tag.
    #   side effect: sets self.reason when a complete marker is found.
    def feed(self, text: str) -> str:
        """Return the portion safe to emit, holding back a tail that might be a partial tag."""
        self._buf += text
        self._buf, found = _strip_markers(self._buf)
        if found and not self.reason:
            self.reason = found

        # Anything beyond a marker's maximum length cannot be part of one still arriving, so it is
        # safe to release. Only the tail waits.
        if not self._started:
            self._buf = self._buf.lstrip()

        if len(self._buf) <= _MARKER_MAX:
            return ""
        out, self._buf = self._buf[:-_MARKER_MAX], self._buf[-_MARKER_MAX:]
        if out:
            self._started = True
        return out

    # Flush at end of stream.
    #   out: whatever remained in the buffer, marker-stripped. Called exactly once, after the
    #        last feed(), so a marker at the very end of a reply is still caught.
    def finish(self) -> str:
        """Flush the held tail when the stream ends.

        One exception: if what remains is an *unterminated* marker, suppress it. The buffer then
        contains nothing but a broken tag, so releasing it would print `[[refusal:no-public-pri`
        into the chat while hiding no content at all.
        """
        held, self._buf = self._buf, ""
        if not self._started:
            held = held.lstrip()
        stripped = held.lstrip()
        if stripped.startswith(_MARKER_OPEN) and "]]" not in stripped:
            self.truncated_marker = held
            return ""
        return held


# Remove every complete refusal tag from a block of text, and report the first slug found.
#   in : text -- any text that may contain one or more `[[refusal:<slug>]]` markers
#   out: (cleaned_text, first_slug_or_None)
# Pure and stateless -- MarkerScanner owns the streaming problem (holding back a partial tag across
# deltas); this handles only text already known to be complete. Splitting them keeps the tricky
# part in one place and makes this half exhaustively testable with no stream to simulate.
#
# The newline collapse at the end is not cosmetic: a tag on its own line leaves a blank gap where
# it was, and an answer that opens with a hole is a visible artifact of something the user is never
# supposed to know exists.
def _strip_markers(text: str) -> tuple[str, str | None]:
    """Remove every complete marker from `text`; return the remainder and the first slug found."""
    first: str | None = None

    # re.sub replacement callback: records the FIRST slug seen, replaces every match with "".
    #   in : m -- the regex match for one complete marker
    #   out: "" -- the tag is deleted, never rendered
    # `nonlocal first` keeps only the first: a reply with two tags is malformed, and the first is
    # the one the model meant.
    def take(m: re.Match[str]) -> str:
        nonlocal first
        if first is None:
            first = m.group(1)
        return ""

    out = _MARKER_ANYWHERE.sub(take, text)
    # A tag on its own line leaves a blank gap behind it; collapse runs of three or more newlines
    # so removing it does not show as a hole in the prose.
    return re.sub(r"\n{3,}", "\n\n", out), first


_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    """Lazy singleton. Built on first use so importing this module never requires a key —
    which is what lets the tests and `/health` work without one."""
    global _client
    if _client is None:
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        extra = {"base_url": BASE_URL} if BASE_URL else {}
        _client = AsyncAnthropic(
            api_key=key, timeout=REQUEST_TIMEOUT_S, max_retries=2, **extra
        )
    return _client


def base_url_warning() -> str | None:
    """The one misconfiguration worth catching at startup rather than on the first turn.

    A base URL ending in `/v1` produces `/v1/v1/messages` and a 404 whose body is an HTML page —
    the SDK surfaces it as `NotFoundError` with a wall of markup and no hint about the cause. It
    cost a debugging round trip when this was first wired up.

    Returned rather than raised: a wrong gateway should not stop the app booting, because the same
    process still serves `/health`, which is how you would diagnose it.
    """
    if BASE_URL and BASE_URL.rstrip("/").endswith("/v1"):
        return (
            f"ANTHROPIC_BASE_URL ends with /v1 ({BASE_URL!r}). The SDK appends /v1/messages "
            "itself, so every request will 404. Drop the /v1."
        )
    return None


async def stream_reply(messages: list[dict]) -> AsyncIterator[Chunk]:
    """Stream one assistant turn.

    Yields `delta` chunks, then exactly one terminal `done` or `error`. Never raises to the
    caller: an exception here would abort the HTTP stream mid-flight and the browser would
    see a truncated response with no explanation, so failures are yielded as data instead.
    """
    scanner = MarkerScanner()
    try:
        client = get_client()
        # `thinking` is sent only for models that accept it — Haiku 4.5 rejects the parameter,
        # Sonnet 5 takes it. Sending nothing on Sonnet would leave the behaviour to a default
        # rather than a decision; measured on this workload adaptive thinking never fired, but
        # "did not fire on the prompts I tried" is weaker than "cannot fire", and this is a
        # latency-sensitive support bot.
        extra = {"thinking": spec_for(MODEL).thinking} if spec_for(MODEL).thinking else {}
        async with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=build_system_blocks(),
            messages=messages,
            **extra,
        ) as stream:
            async for text in stream.text_stream:
                visible = scanner.feed(text)
                if visible:
                    yield Chunk(type="delta", text=visible)

            # A reply that was nothing but a marker, or that ended while still being held.
            tail = scanner.finish()
            if tail:
                yield Chunk(type="delta", text=tail)

            final = await stream.get_final_message()
            u = final.usage
            yield Chunk(
                type="done",
                stop_reason=final.stop_reason,
                refusal_reason=scanner.reason,
                usage=Usage(
                    input_tokens=u.input_tokens,
                    output_tokens=u.output_tokens,
                    # Absent on models/paths without caching — default rather than assume.
                    cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
                    cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                ),
            )

    # A stream that raises mid-hold never reaches `finish()`, so up to _MARKER_MAX characters the
    # scanner was holding are dropped. That is the accepted behaviour, decided rather than
    # inherited: the held text is at most a partial marker plus a few characters of a reply the
    # user is about to see replaced by an error frame anyway, and re-emitting it would mean showing
    # a fragment of an answer immediately above "something went wrong".
    #
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


# Non-secret description of the configured model, for /api/config and /health.
#   out: model id, window, max_tokens, thinking, api_base, via_gateway.
#        Reports WHICH gateway, never the key -- api_base is a hostname, not a credential.
def model_info() -> dict[str, object]:
    spec = spec_for(MODEL)
    return {
        "model": MODEL,
        # Which endpoint is actually serving this. Surfaced because "the key is configured" and
        # "the key works against the endpoint we are calling" are different claims, and the gap
        # between them is exactly what a wrong key looks like.
        "api_base": BASE_URL or "https://api.anthropic.com",
        "via_gateway": BASE_URL is not None,
        "max_tokens": MAX_TOKENS,
        "system_prompt_version": SYSTEM_PROMPT_VERSION,
        # Surfaced so the playground and /api/config describe the model actually in use rather
        # than a hardcoded assumption about which one that is.
        "context_window": spec.context_window,
        "thinking": spec.thinking,
    }
