"""FastAPI entrypoint.

Phase 0c: an end-to-end slice — three hardcoded facts, a streaming chat endpoint, and the
built React bundle served from this same process (one deployable, see CLAUDE.md). The
knowledge layer and observability module still belong to later phases.

Route order matters: /health and /api/* are registered BEFORE the static mount at "/", so
the mount cannot shadow them.
"""

from __future__ import annotations

import mimetypes
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# ⚠️ `.env` is loaded by `app/__init__.py`, which Python runs before any of these imports. It is NOT
# loaded here: a `load_dotenv()` below the import block runs *after* `app.llm.client` has already
# resolved ANTHROPIC_MODEL, which silently pinned the app to the default model no matter what `.env`
# said. See the docstring in `app/__init__.py`.
from app.api.chat import router as chat_router
from app.api.stats import router as stats_router
from app.llm import client as llm_client
from app.obs import spend
from app.obs.log import get_logger, new_request_id, request_id_var
from app.obs.sink import SINK

log = get_logger("app")

# A base URL ending in /v1 makes every request 404 with an HTML body — worth saying at startup
# rather than leaving to the first user turn. Logged, not raised: the process still needs to serve
# /health, which is how the problem gets diagnosed.
if (_warn := llm_client.base_url_warning()):
    log.error("anthropic_base_url_misconfigured", extra={"detail": _warn})

# `StaticFiles` derives Content-Type from the stdlib `mimetypes` database, which is seeded from the
# host OS. macOS knows `.woff2`; the slim Debian image does not — so the self-hosted fonts served as
# `font/woff2` locally and `application/octet-stream` in production. Browsers honour the
# `format('woff2')` hint either way, so nothing was visibly broken, which is exactly why it would
# have gone unnoticed. Registered explicitly so local and deployed agree.
mimetypes.add_type("font/woff2", ".woff2")

ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
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

    # ⚠️ Vite hashes asset filenames, so `index.html` is the ONLY file whose name is stable — and
    # with no Cache-Control it gets *heuristic* caching (browsers guess, typically ~10% of the age
    # since Last-Modified). A stale index.html then references asset names that no longer exist,
    # which reads as "my fix did not deploy" rather than as a cache problem. It has cost this
    # project a debugging session twice.
    #
    # The two rules are opposites on purpose:
    #   - HTML: always revalidate. The ETag makes that a cheap 304, not a re-download.
    #   - /assets/*: the content hash IS the cache key, so a changed file has a changed name and
    #     the old one can be kept forever.
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"
    elif request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
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
    # Read from the client rather than resolving ANTHROPIC_MODEL a second time here. A private
    # copy agreed with the real one only by coincidence, and this is the endpoint you check to
    # answer "what model is actually deployed?" — the one place a stale answer is worst.
    return {
        "status": "ok",
        "environment": ENVIRONMENT,
        "model": llm_client.MODEL,
        # WHERE the model is being called, not just which one. "A key is configured" and "that key
        # works against the endpoint we call" are different claims, and the gap between them is
        # exactly what a wrong key looks like — a Cadre-supplied OpenRouter key (`sk-or-v1-…`) sent
        # to api.anthropic.com is a flat 401 that this field would have explained at a glance.
        "api_base": llm_client.model_info()["api_base"],
        "anthropic_key_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        "web_bundle_present": WEB_DIST.is_dir(),
        # Answers "are my logs actually persisting?" without needing a shell on the container.
        "log_sink": SINK.as_dict(),
        "spend": spend.status(),
    }


app.include_router(chat_router)
app.include_router(stats_router)


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
