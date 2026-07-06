"""
FastAPI auth dependencies.

  * require_admin            — a logged-in operator (session cookie or Bearer token)
  * require_api_key_or_admin — an external API key OR a logged-in operator
                               (used by the synchronous run endpoint)
  * current_subject          — non-raising helper for /auth/status

Admin sessions ride a cookie (auto-attached to fetch, <img>, downloads and the
WebSocket handshake on the same origin) with a Bearer-token fallback for
programmatic clients. API keys come via `X-API-Key` or `Authorization: Bearer af_…`.
"""
import hmac
import os
from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from loguru import logger
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AdminUser, ApiKey
from app.security import (
    hash_api_key, looks_like_api_key, verify_session_token,
)

COOKIE_NAME = "af_session"


def _admin_from_session(request: Request, db: Session) -> str | None:
    """Resolve a valid admin username from the session cookie or a Bearer
    session token. Returns None if neither is present/valid."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            candidate = auth[7:].strip()
            # API keys also arrive as Bearer; only treat non-key values as tokens
            if not looks_like_api_key(candidate):
                token = candidate
    payload = verify_session_token(token)
    if not payload:
        return None
    sub = payload.get("sub")
    if sub and db.query(AdminUser).filter_by(username=sub).first():
        return sub
    return None


def _api_key_from_request(request: Request) -> str | None:
    raw = request.headers.get("x-api-key")
    if raw:
        return raw.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        candidate = auth[7:].strip()
        if looks_like_api_key(candidate):
            return candidate
    return None


def require_admin(request: Request, db: Session = Depends(get_db)) -> str:
    sub = _admin_from_session(request, db)
    if not sub:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return sub


def require_api_key_or_admin(request: Request, db: Session = Depends(get_db)) -> str:
    # 1. logged-in operator (cookie / bearer session token)
    sub = _admin_from_session(request, db)
    if sub:
        return f"admin:{sub}"
    # 2. external API key
    raw = _api_key_from_request(request)
    if raw:
        rec = (
            db.query(ApiKey)
            .filter_by(key_hash=hash_api_key(raw), revoked=False)
            .first()
        )
        if rec:
            rec.last_used_at = datetime.utcnow()
            db.commit()
            return f"apikey:{rec.id}"
        logger.warning("Rejected API key: {}...", raw[:8])
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_subject(request: Request, db: Session) -> str | None:
    """Non-raising variant for status checks."""
    return _admin_from_session(request, db)


# ── Metrics endpoint gate ─────────────────────────────────────────────────────
# The Prometheus /metrics scrape target. Secure-by-default (same credentials as
# the run endpoint), with two operator escape hatches for the common case where a
# Prometheus server scrapes it over a trusted network:
#   * AGENTFLOW_METRICS_PUBLIC=true  → open, no auth (trusted network / behind a
#     scrape-only ingress).
#   * AGENTFLOW_METRICS_TOKEN=<tok>  → a dedicated scrape credential, accepted as a
#     Bearer token, an X-Metrics-Token header, or a ?token= query param — so you
#     can point Prometheus at it without minting an admin API key.
# With neither set, it needs an issued API key (X-API-Key / Bearer af_…) or an
# admin session, exactly like POST /api/executions/run.
def _truthy(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


def _metrics_token_from_request(request: Request) -> str | None:
    v = request.headers.get("x-metrics-token")
    if v:
        return v.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    q = request.query_params.get("token")
    return q.strip() if q else None


def require_metrics_access(request: Request, db: Session = Depends(get_db)) -> str:
    if _truthy(os.getenv("AGENTFLOW_METRICS_PUBLIC", "")):
        return "metrics:public"
    token = os.getenv("AGENTFLOW_METRICS_TOKEN", "").strip()
    if token:
        provided = _metrics_token_from_request(request)
        if provided and hmac.compare_digest(provided, token):
            return "metrics:token"
    # Fall back to the standard API-key / admin gate (raises 401 if neither).
    return require_api_key_or_admin(request, db)
