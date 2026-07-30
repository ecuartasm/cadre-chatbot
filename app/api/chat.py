"""POST /api/chat — SSE stream.

The headers on the response are the load-bearing part of this file. A reverse proxy that
buffers the body turns streaming into a long pause followed by one lump of text, which is
invisible in local development because there is no proxy in front of uvicorn. Proving this
works through Railway's router is the entire reason Phase 0c exists.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.knowledge.loader import info as corpus_info
from app.llm.client import model_info, stream_reply

router = APIRouter(prefix="/api", tags=["chat"])

# History arrives from the browser, so it is bounded HERE. "In-memory per session" describes
# where the server reads history, not a limit on what a caller can send. See CLAUDE.md.
MAX_TURNS = 8
MAX_MESSAGE_CHARS = 4000


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
        return v[:MAX_MESSAGE_CHARS]


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)

    @field_validator("messages")
    @classmethod
    def cap_history(cls, v: list[Message]) -> list[Message]:
        # Drop-oldest. Keeps the prompt bounded no matter what the client sends.
        return v[-(MAX_TURNS * 2) :]


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def _event_stream(messages: list[dict]) -> AsyncIterator[str]:
    async for chunk in stream_reply(messages):
        if chunk.type == "delta":
            yield _sse({"type": "delta", "text": chunk.text})
        elif chunk.type == "done":
            yield _sse(
                {
                    "type": "done",
                    "stop_reason": chunk.stop_reason,
                    "usage": {
                        "input_tokens": chunk.usage.input_tokens,
                        "output_tokens": chunk.usage.output_tokens,
                        "cache_creation_input_tokens": chunk.usage.cache_creation_input_tokens,
                        "cache_read_input_tokens": chunk.usage.cache_read_input_tokens,
                    },
                }
            )
        else:
            yield _sse({"type": "error", "text": chunk.text})


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    messages = [m.model_dump() for m in req.messages]
    return StreamingResponse(
        _event_stream(messages),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # The critical one: tells nginx-family proxies not to buffer the body.
            # Without it the stream arrives as a single chunk at the end.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/config")
async def config() -> dict[str, object]:
    """What the running instance is actually configured with. No secrets.

    `corpus` proves *which* corpus this instance is serving — the sha lets you confirm a deploy
    actually shipped the file you curated, rather than trusting that it did."""
    return {
        **model_info(),
        "max_turns": MAX_TURNS,
        "max_message_chars": MAX_MESSAGE_CHARS,
        "corpus": corpus_info(),
    }
