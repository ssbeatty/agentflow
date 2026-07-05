"""Build the ``MultiServerMCPClient``-shaped connection dict for one MCP server.

Single source of truth shared by the runtime injector (``execution_engine``) and
the "test connection" endpoint, so a probe reflects exactly what a script run
will see. For OAuth servers it resolves a fresh bearer token and folds it into
the static ``headers`` map — the headless runner never deals with tokens itself.
"""
from __future__ import annotations


def build_connection(srv, db) -> dict:
    cfg: dict = {"transport": srv.transport}
    if srv.url:
        cfg["url"] = srv.url
    if srv.command:
        cfg["command"] = srv.command
    if srv.args:
        cfg["args"] = srv.args
    if srv.env_vars:
        cfg["env"] = srv.env_vars

    headers = dict(srv.headers or {})
    auth = getattr(srv, "auth_type", "none")
    if auth == "oauth2":
        from services.mcp_oauth import ensure_access_token
        token = ensure_access_token(srv, db)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth == "internal":
        # The built-in "AI 脚本助手" loopback → our own /mcp gateway. Inject the
        # internal API key at run time (never stored in the DB headers, so it
        # can't leak via MCPServerOut). See services/assistant_seed.py.
        from services.assistant_seed import get_internal_key
        headers["X-API-Key"] = get_internal_key(db)
    if headers:
        cfg["headers"] = headers

    return cfg
