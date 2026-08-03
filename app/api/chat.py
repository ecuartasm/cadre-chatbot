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
import os
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

# A hard stop on how long ONE conversation may run, distinct from MAX_TURNS above: that one bounds
# how much history the model *reads*, this one bounds how long the exchange may continue at all.
#
# ⚠️ **0 means unlimited**, not "block every turn". The literal reading — zero turns allowed — is a
# kill switch nobody wants by accident, and `limits.py` already records what happens when a limit of
# zero is taken literally without thinking it through. Unlimited is also the behaviour that existed
# before this constant, so an unset variable changes nothing.
#
# Deliberately NOT an abuse control. A cap that resets when the user starts a new conversation
# cannot stop abuse — opening a new one is free. The global daily spend cap is the control that
# holds; this is a product decision about when to route someone to a human.
MAX_TURNS_PER_CONVERSATION = int(os.getenv("MAX_TURNS_PER_CONVERSATION", "0"))

# The refusal marker, as it would appear in an inbound message. Deliberately lenient
# about whitespace and slug shape — this is stripping hostile input, not parsing ours.
# Looser than the OUTBOUND pattern in client.py, deliberately -- that one parses our own format.
_CLIENT_MARKER = re.compile(r"\[\[\s*refusal\s*:[^\]]*\]\]", re.I)


# One turn in the conversation, as it arrives from the browser.
#   role    -- 'user' | 'assistant' (validated; anything else is a 422)
#   content -- the text, sanitised by the validator below before any handler sees it
class Message(BaseModel):
    role: str
    content: str

    # Reject unknown roles.
    #   in : v -- the role string
    #   out: v unchanged, or ValueError -> HTTP 422
    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        if v not in ("user", "assistant"):
            raise ValueError("role must be 'user' or 'assistant'")
        return v

    # Sanitise message text. Three controls live here, so no code path can skip them.
    #   in : v -- raw content from the client
    #   out: stripped, marker-free, truncated to MAX_MESSAGE_CHARS
    #   raises: ValueError (-> 422) when empty, before OR after marker removal
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


# The POST /api/chat body.
#   messages -- the whole conversation, browser-supplied and therefore untrusted
class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)

    # Bound the history SERVER-side; the array comes from the browser and is not trusted.
    #   in : v -- the full array as sent
    #   out: the last MAX_TURNS*2 messages. Truncated, never rejected -- turn 9 works, the model
    #        just no longer sees turn 1. The *2 keeps whole user/assistant pairs, so the model is
    #        never handed a reply whose question was dropped.
    @field_validator("messages")
    @classmethod
    def cap_history(cls, v: list[Message]) -> list[Message]:
        return v[-(MAX_TURNS * 2) :]


# Format one Server-Sent Events frame.
#   in : payload -- the object to send
#   out: 'data: {json}\n\n'. The trailing BLANK LINE is the frame delimiter -- without it the
#        browser never dispatches the event.
def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


# Emit a single error frame for a rejected turn, without calling the model.
#   in : reason -- server-side slug ('rate-limited', 'daily-cap-reached', ...). NOT a corpus
#                  refusal slug; these never reach REFUSAL_REASONS.
#        text   -- user-facing prose
#   out: a one-frame async iterator, delivered at HTTP 200 -- see the docstring for why.
async def _guard_frame(reason: str, text: str, request_id: str) -> AsyncIterator[str]:
    """A rejection, delivered as a normal SSE error frame.

    Deliberately HTTP 200 with an error frame rather than a 429/503: the client is reading an event
    stream, and a status-code rejection surfaces in the UI as "Couldn't reach the server". The
    frontend
    already renders error frames, so this costs nothing and reads properly.
    """
    log.warning("turn_rejected", extra={"stream": "app", "refusal_reason": reason})
    yield _sse({"type": "error", "text": text, "reason": reason, "request_id": request_id})


# The turn itself: stream the model's reply and account for it exactly once.
#   in : messages   -- validated, capped conversation
#        request_id -- carried explicitly, not read from the ContextVar late (the middleware
#                      resets it before an SSE body finishes iterating)
#   out: yields SSE frames -- many `delta`, then one `done`, or an `error`
#   side effects: records spend and writes one interactions.jsonl line, from `finally`, so an
#                 abandoned stream is still accounted for rather than being silently free.
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


# POST /api/chat -- the only endpoint that spends money.
#   in : req     -- validated body (history already capped, markers already stripped)
#        request -- for client IP and headers
#   out: StreamingResponse of text/event-stream
# Three guards run BEFORE the model call, cheapest first: conversation length (a pure count),
# then the rate limiter, then the spend cap. Each returns an error FRAME at HTTP 200, because a
# status-code rejection surfaces in the UI as "couldn't reach the server".
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

    # --- Guards, all checked BEFORE the model call -------------------------------------------
    # Conversation length first: it is a pure count with no state to touch, so a caller past the
    # limit costs nothing — not a bucket entry, not a spend read, and certainly not a model call.
    if MAX_TURNS_PER_CONVERSATION > 0 and len(req.messages) > MAX_TURNS_PER_CONVERSATION * 2 - 1:
        return StreamingResponse(
            _guard_frame(
                "conversation-limit-reached",
                f"We've covered about {MAX_TURNS_PER_CONVERSATION} exchanges here — roughly as "
                f"much as I can carry usefully in one conversation. Start a new one any time, or "
                f"reach the team directly at https://www.cadreai.com/contact.",
                request_id,
            ),
            media_type="text/event-stream",
            headers=headers,
        )

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


# GET /api/config -- what this instance is actually configured with. No secrets.
#   out: model info, limits, corpus fingerprint, and prompt METADATA only (version, token count,
#        floor margin). Never the prompt text: publishing it would expose the marker syntax and
#        the wording of every boundary rule.
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
        # 0 = unlimited. Reported so a deployed instance can prove which it is, rather than leaving
        # "why did that conversation stop?" to be answered by reading the source.
        "max_turns_per_conversation": MAX_TURNS_PER_CONVERSATION,
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
