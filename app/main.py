"""FastAPI entrypoint.

Phase 0c: an end-to-end slice — three hardcoded facts, a streaming chat endpoint, and the
built React bundle served from this same process (one deployable, see CLAUDE.md). The
knowledge layer and observability module still belong to later phases.

Route order matters: /health and /api/* are registered BEFORE the static mount at "/", so
the mount cannot shadow them.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from app.api.chat import router as chat_router

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
