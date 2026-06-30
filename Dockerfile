# syntax=docker/dockerfile:1.7

# ── 1) frontend builder ───────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# install deps with cache
COPY frontend/package.json frontend/package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci || npm install

# copy source and build static export
COPY frontend/ ./
RUN npm run build


# ── 2) backend runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1

# minimal build tools so any non-wheel transitive deps still install;
# `uv` is included for fast per-script venv + install at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# uv: fast venv & pip-replacement used by the platform's venv_manager
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && cp /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app/backend

# python deps (cached layer)
COPY backend/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# backend source + agentflow SDK
COPY backend/ ./

# baked-in frontend static export served by FastAPI catch-all route
COPY --from=frontend-builder /app/frontend/out /app/frontend/out

# data dir (db file in sqlite mode + per-script venvs) — declared volume
RUN mkdir -p /app/backend/data/scripts
VOLUME ["/app/backend/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# --proxy-headers + trusting forwarded IPs so X-Forwarded-Proto/Host from a
# reverse proxy are honoured (correct https scheme in OAuth redirect URIs etc.).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
