"""POST /api/chat — SSE stream, instrumented.

Two things here are load-bearing and easy to get wrong.

**The anti-buffering headers.** A reverse proxy that buffers the body turns streaming into a long
pause then one lump, and it is invisible locally because there is no proxy in front of uvicorn.

**The `finally` block.** `usage` only arrives at the *end* of a stream. If the browser disconnects
mid-answer the generator is cancelled, and a naive implementation logs nothing — no usage, no cost,
no record — while the tokens are still billed. Logging from `finally` means an abandoned stream is
accounted for rather than silently free.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.knowledge.loader import REFUSAL_REASONS
from app.knowledge.loader import info as corpus_info
from app.llm.client import model_info, stream_reply
from app.llm.prompt import (
    CACHE_FLOOR_TOKENS,
    MEASURED_SYSTEM_TOKENS,
    SYSTEM_PROMPT_VERSION,
)
from app.obs import limits, spend
from app.obs.cost import InteractionLog, Usage, cost_usd
from app.obs.log import get_logger, request_id_var
from app.obs.redact import redact

router = APIRouter(prefix="/api", tags=["chat"])
log = get_logger("chat")

# History arrives from the browser, so it is bounded HERE. "In-memory per session" describes where
# the
# server reads history, not a limit on what a caller can send.
MAX_TURNS = 8
MAX_MESSAGE_CHARS = 4000

# The refusal marker, as it would appear in an inbound message. Deliberately lenient
# about whitespace and slug shape — this is stripping hostile input, not parsing ours.
_CLIENT_MARKER = re.compile(r"\[\[\s*refusal\s*:[^\]]*\]\]", re.I)


class Message(BaseModel):
    role: str
    content: str

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        if v not in ("user", "assistant"):
            raise ValueError("role must be 'user' or 'assistant'")
        return v

    @field_validator("content")
    @classmethod
    def content_must_be_sane(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("content must not be empty")
        # Strip any refusal marker arriving from the client. The tag is OURS — the model emits it
        # and MarkerScanner removes it before display — so it has no business in an inbound
        # message. Found by the `full` eval suite: a user message containing
        # `[[refusal:no-public-pricing]]` caused the model to skip emitting its own tag, so a turn
        # that refused correctly in prose logged status="ok". The boundary held; the measurement
        # was suppressed, which is exactly the attack plan.md §9.2 predicted.
        #
        # Stripped here rather than instructed away in the prompt: this does not depend on the
        # model choosing correctly, and it also cleans the text before it reaches the log.
        v = _CLIENT_MARKER.sub("", v).strip()
        if not v:
            raise ValueError("content must not be empty")
        return v[:MAX_MESSAGE_CHARS]


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)

    @field_validator("messages")
    @classmethod
    def cap_history(cls, v: list[Message]) -> list[Message]:
        return v[-(MAX_TURNS * 2) :]


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def _guard_frame(reason: str, text: str, request_id: str) -> AsyncIterator[str]:
    """A rejection, delivered as a normal SSE error frame.

    Deliberately HTTP 200 with an error frame rather than a 429/503: the client is reading an event
    stream, and a status-code rejection surfaces in the UI as "Couldn't reach the server". The
    frontend
    already renders error frames, so this costs nothing and reads properly.
    """
    log.warning("turn_rejected", extra={"stream": "app", "refusal_reason": reason})
    yield _sse({"type": "error", "text": text, "reason": reason, "request_id": request_id})


async def _event_stream(messages: list[dict], request_id: str) -> AsyncIterator[str]:
    started = time.monotonic()
    usage = Usage()
    chars = 0
    status = "error"
    stop_reason: str | None = None
    refusal_reason: str | None = None
    err: str | None = None
    # Computed ONCE at `done` and reused by the `finally`. The frame is emitted before the finally
    # runs, so computing them separately would give the playground and the log two different
    # latencies for the same turn — small enough to look like rounding, real enough to be a
    # discrepancy, and whoever spots it stops trusting both numbers rather than one.
    latency_ms: int | None = None
    turn_cost: float | None = None

    try:
        async for chunk in stream_reply(messages):
            if chunk.type == "delta":
                chars += len(chunk.text)
                yield _sse({"type": "delta", "text": chunk.text})
            elif chunk.type == "done":
                status = "ok"
                stop_reason = chunk.stop_reason
                if chunk.refusal_reason:
                    # The model refused. Validate against the corpus-derived enum rather than
                    # trusting the slug: an invented value would pollute the one field the refusal
                    # rate is computed from, and silently make the metric unaggregatable.
                    status = "refused"
                    if chunk.refusal_reason in REFUSAL_REASONS:
                        refusal_reason = chunk.refusal_reason
                    else:
                        log.warning(
                            "refusal_reason_not_in_corpus",
                            extra={"stream": "app", "invented_slug": chunk.refusal_reason},
                        )
                usage = Usage(
                    input_tokens=chunk.usage.input_tokens,
                    output_tokens=chunk.usage.output_tokens,
                    cache_creation_input_tokens=chunk.usage.cache_creation_input_tokens,
                    cache_read_input_tokens=chunk.usage.cache_read_input_tokens,
                )
                latency_ms = int((time.monotonic() - started) * 1000)
                turn_cost = cost_usd(usage, str(model_info()["model"]))
                yield _sse(
                    {
                        "type": "done",
                        "stop_reason": chunk.stop_reason,
                        # On the wire for the playground. `cost_usd` comes from cost.py rather than
                        # being recomputed in JS — a second implementation of the four-rate maths is
                        # exactly what that module exists to prevent.
                        "latency_ms": latency_ms,
                        "cost_usd": turn_cost,
                        # On the wire, not only in the log. The golden set runs against the
                        # DEPLOYED url, where interactions.jsonl sits on a volume it cannot read —
                        # so without these the eval could only match substrings in prose, which is
                        # exactly what the refusal marker was built to avoid. Both are facts about
                        # the caller's own turn, and the slugs come from the public corpus.
                        "status": status,
                        "refusal_reason": refusal_reason,
                        "usage": usage.as_dict(),
                        "request_id": request_id,
                    }
                )
            else:
                err = chunk.text
                yield _sse({"type": "error", "text": chunk.text, "request_id": request_id})

    except BaseException as e:  # noqa: BLE001 — includes CancelledError/GeneratorExit on disconnect
        # A client disconnect cancels this generator. Mark it and re-raise; `finally` still logs.
        status = "abandoned"
        err = type(e).__name__
        raise

    finally:
        model = model_info()["model"]
        entry = InteractionLog(
            request_id=request_id,
            model=str(model),
            system_prompt_version=SYSTEM_PROMPT_VERSION,
            user_message_redacted=redact(messages[-1]["content"]) if messages else "",
            # Reuses the value computed at `done` so the frame and the log agree exactly. Falls
            # back for turns that never reached `done` — errors and abandoned streams.
            latency_ms=latency_ms if latency_ms is not None else int(
                (time.monotonic() - started) * 1000
            ),
            status=status,
            usage=usage,
            assistant_chars=chars,
            stop_reason=stop_reason,
            refusal_reason=refusal_reason,
            error=err,
            history_turns_sent=len(messages),
        )
        # Record unconditionally, including abandoned turns. Stated honestly: `usage` only arrives
        # with the `done` event, so an abandoned turn records $0 even though Anthropic bills for
        # the tokens that did stream. The ledger therefore *under-counts* by the abandoned share.
        # That gap is deliberate — inventing a number from `assistant_chars` would put a guess into
        # a money ledger — and it is bounded by the rate limiter. It is greppable rather than
        # invisible: `status="abandoned"` with `cost_usd=0` and a non-zero `assistant_chars` is
        # exactly this case.
        await spend.record(turn_cost if turn_cost is not None else cost_usd(usage, str(model)))
        log.info("interaction", extra={"stream": "interactions", **entry.as_dict()})


@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    request_id = request_id_var.get()
    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        # The critical one: tells nginx-family proxies not to buffer the body.
        "X-Accel-Buffering": "no",
        # Surfaced so a user reporting a bad answer can quote something greppable.
        "X-Request-Id": request_id,
    }

    # --- Guards, both checked BEFORE the model call -----------------------------------------
    peer = request.client.host if request.client else None
    client = limits.client_key(dict(request.headers), peer)
    # Logged on every turn, not only on a rejection: `source="peer"` in production means the limiter
    # has silently degraded to one shared bucket for all visitors, and that is only visible here.
    log.info("rate_limit_check", extra={"stream": "app", "client_key_source": client.source})
    allowed, retry_after = limits.check(client.key)
    if not allowed:
        return StreamingResponse(
            _guard_frame(
                "rate-limited",
                f"You're sending messages faster than I can keep up. "
                f"Try again in {retry_after} seconds.",
                request_id,
            ),
            media_type="text/event-stream",
            headers={**headers, "Retry-After": str(retry_after)},
        )

    if spend.would_exceed_cap():
        return StreamingResponse(
            _guard_frame(
                "daily-cap-reached",
                "I've reached my usage limit for today. Please try again tomorrow, "
                "or reach the team directly at https://www.cadreai.com/contact.",
                request_id,
            ),
            media_type="text/event-stream",
            headers=headers,
        )

    messages = [m.model_dump() for m in req.messages]
    return StreamingResponse(
        _event_stream(messages, request_id), media_type="text/event-stream", headers=headers
    )


@router.get("/config")
async def config() -> dict[str, object]:
    """What the running instance is actually configured with. No secrets.

    `prompt` is metadata ONLY — size and version, never the text. Serving it would publish the
    `[[refusal:…]]` syntax, which a user message could then try to inject to fake or suppress a
    refusal, corrupting the field this bot is judged on — plus the wording of every boundary rule,
    which is what you would want in order to find the seam between two of them.
    Deliberately not a per-section breakdown either: naming a `marker` section reveals that the
    mechanism exists, for decoration rather than value.
    """
    return {
        **model_info(),
        "max_turns": MAX_TURNS,
        "max_message_chars": MAX_MESSAGE_CHARS,
        "corpus": corpus_info(),
        "rate_limit_per_minute": limits.RATE_LIMIT_PER_MINUTE,
        "prompt": {
            "version": SYSTEM_PROMPT_VERSION,
            "tokens": MEASURED_SYSTEM_TOKENS,
            "cache_floor_tokens": CACHE_FLOOR_TOKENS,
            # The number that explains why a cached turn is cheap and how close the prefix sits to
            # the cliff. Below the floor, caching stops silently at ~6x the per-turn cost.
            "margin_over_floor": MEASURED_SYSTEM_TOKENS - CACHE_FLOOR_TOKENS,
        },
    }
