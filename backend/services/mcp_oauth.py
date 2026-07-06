"""OAuth 2.0 (Authorization Code + PKCE) for remote MCP servers.

Servers like Todoist / Fastmail expose their MCP endpoint behind OAuth — you
can't just paste a static bearer token. A desktop MCP client handles this by
popping a browser window; AgentFlow runs scripts headless in subprocesses, so
the *backend* owns the flow instead:

  1. ``build_authorize_url`` — discover the auth server (RFC 9728 protected
     resource metadata → RFC 8414 / OIDC auth server metadata), dynamically
     register a client if needed (RFC 7591), generate PKCE, and return a URL the
     user opens in their browser.
  2. ``handle_callback`` — exchange the returned ``code`` for tokens and store
     them on the server config.
  3. ``ensure_access_token`` — called at script-run time: refresh if expired and
     hand back a bearer token, which the runner injects as an ``Authorization``
     header (so the headless subprocess only ever sees a plain header).

Everything here uses sync ``httpx`` so it composes with the sync FastAPI handlers
and the sync execution-engine setup path. Discovered endpoints + client creds are
cached in ``MCPServerConfig.oauth_config``; live tokens in ``oauth_token``.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode, urlsplit

import httpx
from loguru import logger

_USER_AGENT = "AgentFlow-MCP-OAuth/1.0"
_TIMEOUT = 20.0
# In-flight authorization attempts, keyed by `state`. Short-lived; a backend
# reload mid-flow just means the user re-clicks "Connect".
_PENDING: dict[str, dict] = {}
_PENDING_TTL = 600.0  # seconds
# Refresh a little before the real expiry to avoid races on slow links.
_EXPIRY_SKEW = 30.0


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def _gc_pending() -> None:
    now = time.time()
    for state in [s for s, v in _PENDING.items() if now - v.get("created", 0) > _PENDING_TTL]:
        _PENDING.pop(state, None)


# ── discovery ───────────────────────────────────────────────────────────────────

def _discover_endpoints(server_url: str, manual: dict, client: httpx.Client) -> dict:
    """Resolve authorization/token/registration endpoints for an MCP server URL.

    Honours manually-configured endpoints first, then falls back to spec-based
    discovery. Raises ValueError if it can't find what it needs.
    """
    eps = {
        "authorization_endpoint": manual.get("authorization_endpoint"),
        "token_endpoint": manual.get("token_endpoint"),
        "registration_endpoint": manual.get("registration_endpoint"),
        "resource": manual.get("resource") or server_url,
    }
    if eps["authorization_endpoint"] and eps["token_endpoint"]:
        return eps

    origin = _origin(server_url)

    # 1) Protected Resource Metadata (RFC 9728) → authorization server issuer(s).
    issuer = None
    try:
        r = client.get(origin + "/.well-known/oauth-protected-resource",
                       headers={"Accept": "application/json"})
        if r.status_code == 200:
            servers = (r.json() or {}).get("authorization_servers") or []
            if servers:
                issuer = servers[0]
    except Exception:
        pass

    # 2) Authorization Server Metadata (RFC 8414 / OIDC). Try the discovered
    #    issuer first, then the MCP origin itself (many servers co-locate).
    candidates = [c for c in (issuer, origin) if c]
    meta = None
    for base in candidates:
        for suffix in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
            try:
                r = client.get(base.rstrip("/") + suffix, headers={"Accept": "application/json"})
                if r.status_code == 200:
                    meta = r.json()
                    break
            except Exception:
                continue
        if meta:
            break

    if meta:
        eps["authorization_endpoint"] = eps["authorization_endpoint"] or meta.get("authorization_endpoint")
        eps["token_endpoint"] = eps["token_endpoint"] or meta.get("token_endpoint")
        eps["registration_endpoint"] = eps["registration_endpoint"] or meta.get("registration_endpoint")

    if not eps["authorization_endpoint"] or not eps["token_endpoint"]:
        raise ValueError(
            "could not auto-discover OAuth endpoints for this server; set "
            "authorization_endpoint and token_endpoint manually in the config"
        )
    return eps


def _register_client(reg_endpoint: str, redirect_uri: str, scope: str | None,
                     client: httpx.Client) -> tuple[str, str | None]:
    """Dynamic Client Registration (RFC 7591). Returns (client_id, client_secret?)."""
    body = {
        "client_name": "AgentFlow",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    if scope:
        body["scope"] = scope
    r = client.post(reg_endpoint, json=body, headers={"Accept": "application/json"})
    r.raise_for_status()
    data = r.json() or {}
    cid = data.get("client_id")
    if not cid:
        raise ValueError("dynamic client registration returned no client_id")
    return cid, data.get("client_secret")


# ── token bookkeeping ────────────────────────────────────────────────────────────

def _store_token(tok: dict) -> dict:
    out = {
        "access_token": tok.get("access_token"),
        "refresh_token": tok.get("refresh_token"),
        "token_type": tok.get("token_type", "Bearer"),
        "scope": tok.get("scope"),
    }
    expires_in = tok.get("expires_in")
    if expires_in:
        try:
            out["expires_at"] = time.time() + float(expires_in) - _EXPIRY_SKEW
        except (TypeError, ValueError):
            pass
    return out


# ── public API ───────────────────────────────────────────────────────────────────

def build_authorize_url(srv, redirect_uri: str, db) -> tuple[str, str]:
    """Discover/register as needed, then return (authorize_url, state).

    Persists discovered endpoints + client creds onto ``srv.oauth_config`` so the
    callback and later refreshes don't have to rediscover.
    """
    if not srv.url:
        raise ValueError("server has no URL")
    cfg = dict(srv.oauth_config or {})
    scope = cfg.get("scope")

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                      headers={"User-Agent": _USER_AGENT}) as client:
        eps = _discover_endpoints(srv.url, cfg, client)
        client_id = cfg.get("client_id")
        client_secret = cfg.get("client_secret")
        if not client_id:
            if not eps.get("registration_endpoint"):
                raise ValueError(
                    "server requires a client_id but offers no dynamic registration; "
                    "set client_id (and client_secret) manually in the config"
                )
            client_id, client_secret = _register_client(
                eps["registration_endpoint"], redirect_uri, scope, client)

    cfg.update({
        "authorization_endpoint": eps["authorization_endpoint"],
        "token_endpoint": eps["token_endpoint"],
        "registration_endpoint": eps.get("registration_endpoint"),
        "resource": eps.get("resource"),
        "client_id": client_id,
    })
    if client_secret:
        cfg["client_secret"] = client_secret
    srv.oauth_config = cfg
    db.commit()

    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = _b64url(secrets.token_bytes(24))

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if scope:
        params["scope"] = scope
    if eps.get("resource"):
        params["resource"] = eps["resource"]  # RFC 8707 resource indicator

    _PENDING[state] = {
        "srv_id": srv.id,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "token_endpoint": eps["token_endpoint"],
        "client_id": client_id,
        "client_secret": client_secret,
        "resource": eps.get("resource"),
        "created": time.time(),
    }
    _gc_pending()

    sep = "&" if "?" in eps["authorization_endpoint"] else "?"
    return eps["authorization_endpoint"] + sep + urlencode(params), state


def handle_callback(state: str, code: str, db):
    """Exchange the authorization code for tokens; store them on the server."""
    pend = _PENDING.pop(state, None)
    if not pend:
        raise ValueError("invalid or expired authorization state")

    from app.models import MCPServerConfig
    srv = db.query(MCPServerConfig).filter_by(id=pend["srv_id"]).first()
    if not srv:
        raise ValueError("MCP server not found")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pend["redirect_uri"],
        "client_id": pend["client_id"],
        "code_verifier": pend["code_verifier"],
    }
    if pend.get("resource"):
        data["resource"] = pend["resource"]
    auth = (pend["client_id"], pend["client_secret"]) if pend.get("client_secret") else None

    with httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
        r = client.post(pend["token_endpoint"], data=data, auth=auth,
                        headers={"Accept": "application/json"})
        r.raise_for_status()
        tok = r.json() or {}

    if not tok.get("access_token"):
        raise ValueError("token endpoint returned no access_token")
    srv.oauth_token = _store_token(tok)
    db.commit()
    return srv


def _refresh(srv, db) -> dict | None:
    tok = srv.oauth_token or {}
    refresh_token = tok.get("refresh_token")
    cfg = srv.oauth_config or {}
    token_endpoint = cfg.get("token_endpoint")
    client_id = cfg.get("client_id")
    if not refresh_token or not token_endpoint or not client_id:
        return None

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if cfg.get("resource"):
        data["resource"] = cfg["resource"]
    auth = (client_id, cfg["client_secret"]) if cfg.get("client_secret") else None

    try:
        with httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
            r = client.post(token_endpoint, data=data, auth=auth,
                            headers={"Accept": "application/json"})
            r.raise_for_status()
            new = r.json() or {}
    except Exception as exc:
        logger.warning("OAuth token refresh failed for MCP server {}: {}", srv.id, exc)
        return None

    if not new.get("access_token"):
        logger.warning("OAuth token refresh for MCP server {} returned no access_token", srv.id)
        return None
    stored = _store_token(new)
    # Many providers don't rotate the refresh token — keep the old one if absent.
    if not stored.get("refresh_token"):
        stored["refresh_token"] = refresh_token
    srv.oauth_token = stored
    db.commit()
    logger.info("OAuth token refreshed for MCP server {}", srv.id)
    return stored


def ensure_access_token(srv, db) -> str | None:
    """Return a usable access token (refreshing if near expiry), or None if the
    server isn't connected."""
    tok = srv.oauth_token or {}
    access = tok.get("access_token")
    if not access:
        return None
    expires_at = tok.get("expires_at")
    if expires_at and time.time() >= expires_at:
        refreshed = _refresh(srv, db)
        if refreshed:
            return refreshed.get("access_token")
    return access


def disconnect(srv, db) -> None:
    srv.oauth_token = None
    db.commit()
