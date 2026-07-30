"""FastAPI entrypoint.

Phase 0c: an end-to-end slice — three hardcoded facts, a streaming chat endpoint, and the
built React bundle served from this same process (one deployable, see CLAUDE.md). The
knowledge layer and observability module still belong to later phases.

Route order matters: /health and /api/* are registered BEFORE the static mount at "/", so
the mount cannot shadow them.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.chat import router as chat_router
from app.obs import spend
from app.obs.log import get_logger, new_request_id, request_id_var
from app.obs.sink import SINK

log = get_logger("app")

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
WEB_DIST = Path(__file__).parent.parent / "web" / "dist"

app = FastAPI(
    title="Cadre AI Support Chatbot",
    version="0.2.0",
    # A public URL does not need to advertise its schema.
    docs_url="/docs" if ENVIRONMENT == "development" else None,
    redoc_url=None,
)


@app.middleware("http")
async def request_context(request: Request, call_next):  # noqa: ANN001, ANN201
    """Stamp a request id onto the whole request and echo it back.

    Every log line in the turn carries this, so one grep reconstructs the middleware, the LLM call,
    and the cost record together. Reusing an inbound X-Request-Id keeps a proxy-assigned id intact.

    The id is carried in three places on purpose, because the ContextVar alone does not survive
    long enough:

    - `request.state.request_id` — readable by the exception handler, which runs *above* this
      middleware and therefore after the reset below.
    - the explicit `request_id` in the log call — the reset happens in a `finally` that fires
      before this function returns, so a line logged from here cannot rely on the ambient value.
    - `request_id_var` — the ambient default for everything running inside `call_next`.

    Note what this means for streaming: `call_next` returns once the headers are ready, so the SSE
    body is iterated *after* the reset. That is why `InteractionLog` emits its own request_id
    rather than letting the formatter fall back to the ContextVar.
    """
    rid = request.headers.get("x-request-id") or new_request_id()
    request.state.request_id = rid
    token = request_id_var.set(rid)
    started = time.monotonic()
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    # Healthchecks fire constantly; logging them would bury real traffic.
    if request.url.path != "/health":
        log.info(
            "http_request",
            extra={
                "request_id": rid,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
    response.headers["X-Request-Id"] = rid
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: log the traceback, return a safe message. Never leak a stack trace to a
    browser.

    Reads `request.state`, not the ContextVar: this handler runs above the middleware, so by the
    time it fires the ContextVar has already been reset to "-". Returning an id that matches
    nothing in the logs would be worse than returning none, because the 500 page invites the user
    to quote it.
    """
    rid = getattr(request.state, "request_id", None) or request_id_var.get()
    log.exception(
        "unhandled_exception",
        extra={"stream": "errors", "request_id": rid, "path": request.url.path},
    )
    return JSONResponse(
        status_code=500,
        content={"error": "Something went wrong on our side.", "request_id": rid},
        headers={"X-Request-Id": rid},
    )


@app.get("/health")
def health() -> dict[str, object]:
    """Liveness probe — Railway's healthcheckPath.

    Reports whether the key is CONFIGURED, never whether it is valid: validating would mean
    a billed API call on every healthcheck.
    """
    return {
        "status": "ok",
        "environment": ENVIRONMENT,
        "model": MODEL,
        "anthropic_key_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        "web_bundle_present": WEB_DIST.is_dir(),
        # Answers "are my logs actually persisting?" without needing a shell on the container.
        "log_sink": SINK.as_dict(),
        "spend": spend.status(),
    }


app.include_router(chat_router)


# Serve the React bundle if it was built; otherwise expose an honest JSON placeholder so a
# visitor is never misled about how finished this is.
if WEB_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
else:

    @app.get("/")
    def root() -> dict[str, object]:
        return {
            "service": "Cadre AI Support Chatbot",
            "phase": "0c — vertical slice (frontend bundle not built)",
            "built": ["GET /health", "POST /api/chat", "GET /api/config"],
            "hint": "run `npm ci && npm run build` in web/ to serve the UI from this process",
        }
