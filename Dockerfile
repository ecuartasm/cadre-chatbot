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
COPY --from=web /web/dist ./web/dist

# Run as a non-root user. Nothing here needs write access to the image.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /srv
USER appuser

EXPOSE 8000

# Railway injects $PORT at runtime; default only for local `docker run`.
# One worker is deliberate: the Phase 2 rate limiter and daily spend counter are in-process,
# so a second worker would silently double both budgets (CLAUDE.md).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
