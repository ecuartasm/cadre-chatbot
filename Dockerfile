# syntax=docker/dockerfile:1
#
# Two toolchains, one deployable. Nixpacks auto-detects Python from pyproject.toml and would
# never build the React bundle, so the build is explicit here instead. This also makes the
# deploy reproducible — the same image builds locally and on Railway.

# --- Stage 1: build the React bundle -------------------------------------------------
FROM node:22-alpine AS web

WORKDIR /web
# Copy manifests first so this layer caches independently of source changes.
COPY web/package.json web/package-lock.json* ./
# `npm ci` requires a lockfile; fall back on first build before one exists.
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY web/ ./
RUN npm run build


# --- Stage 2: python runtime ---------------------------------------------------------
FROM python:3.12-slim AS runtime

# Pinned, not :latest — a moving build tool is a moving deploy.
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Resolve dependencies from the lockfile, then install with pip. uv does the resolving
# (fast, and --frozen means the lock is authoritative); pip does the installing, which
# keeps the runtime free of any uv project semantics.
COPY pyproject.toml uv.lock ./
RUN uv export --no-dev --frozen --no-emit-project -o requirements.txt \
 && pip install --require-hashes -r requirements.txt \
 && rm requirements.txt

COPY app/ ./app/
# The curated corpus is what the bot reasons over — without this the deployed container has
# NO knowledge base while every local test still passes. Caught by the Phase 0 forward review.
COPY content/ ./content/
COPY --from=web /web/dist ./web/dist

# `scripts/` is deliberately NOT copied: the scraper is build-time tooling, re-run by a
# developer via /update-kb, and has no business in the runtime image.

# The app runs as uid 10001. The container *starts* as root only so the entrypoint can fix
# ownership on the runtime-mounted volume, then drops privileges before exec'ing uvicorn.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /srv

# Assert the privilege-drop tool exists NOW, not on the first deploy. `setpriv` ships with
# util-linux; if a future base image drops it, this breaks the build instead of silently
# leaving the app running as root.
RUN command -v setpriv >/dev/null 2>&1 \
 || { echo 'FATAL: setpriv not found — cannot drop privileges after fixing volume ownership'; exit 1; }

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

# The entrypoint owns $PORT and the single-worker choice. One worker is deliberate: the rate
# limiter and daily spend counter are in-process, so a second worker would silently double both.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
