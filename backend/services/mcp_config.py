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
    if getattr(srv, "auth_type", "none") == "oauth2":
        from services.mcp_oauth import ensure_access_token
        token = ensure_access_token(srv, db)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    if headers:
        cfg["headers"] = headers

    return cfg
