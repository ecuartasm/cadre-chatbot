"""FastAPI entrypoint.

Phase 0a scope: a deployable skeleton and nothing more. The chat endpoint, the
knowledge layer, and the observability module arrive in later phases (see plan.md).
Keeping this file honest about what exists matters more than making it look finished.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")

app = FastAPI(
    title="Cadre AI Support Chatbot",
    version="0.1.0",
    # Docs stay on in development only — a public URL doesn't need to advertise its schema.
    docs_url="/docs" if ENVIRONMENT == "development" else None,
    redoc_url=None,
)


@app.get("/health")
def health() -> dict[str, object]:
    """Liveness probe. Railway's healthcheckPath points here.

    Reports whether the API key is *present* — never its value, and never whether
    it is valid (that would mean a billed call on every healthcheck).
    """
    return {
        "status": "ok",
        "environment": ENVIRONMENT,
        "model": MODEL,
        "anthropic_key_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
    }


@app.get("/")
def root() -> dict[str, object]:
    """Placeholder root.

    Phase 0c replaces this with the built React bundle served from static files
    (one deployable — see CLAUDE.md). Until then it states what is and isn't built,
    so a visitor to the public URL is never misled about how finished this is.
    """
    return {
        "service": "Cadre AI Support Chatbot",
        "phase": "0a — deploy skeleton",
        "built": ["GET /health", "GET /"],
        "not_yet_built": [
            "POST /api/chat (streaming)  — Phase 0c",
            "curated knowledge base      — Phase 1",
            "observability + cost caps   — Phase 2",
            "GET /api/stats              — Phase 6",
        ],
    }


# Serve the React bundle if it has been built. Absent in Phase 0a, present from 0c on.
_dist = Path(__file__).parent.parent / "web" / "dist"
if _dist.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
