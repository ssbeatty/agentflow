from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import MCPServerConfig
from app.schemas import MCPServerCreate, MCPServerUpdate, MCPServerOut

router = APIRouter()

VALID_TRANSPORTS = {"http", "sse", "stdio", "websocket"}


def _validate(transport: str) -> None:
    if transport not in VALID_TRANSPORTS:
        raise HTTPException(400, f"transport must be one of: {sorted(VALID_TRANSPORTS)}")


@router.get("", response_model=list[MCPServerOut])
def list_servers(db: Session = Depends(get_db)):
    return db.query(MCPServerConfig).order_by(MCPServerConfig.created_at).all()


@router.post("", response_model=MCPServerOut, status_code=201)
def create_server(body: MCPServerCreate, db: Session = Depends(get_db)):
    _validate(body.transport)
    srv = MCPServerConfig(**body.model_dump())
    db.add(srv)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"MCP server name {body.name!r} already exists")
    db.refresh(srv)
    return srv


@router.get("/{srv_id}", response_model=MCPServerOut)
def get_server(srv_id: str, db: Session = Depends(get_db)):
    return _get_or_404(srv_id, db)


@router.patch("/{srv_id}", response_model=MCPServerOut)
def update_server(srv_id: str, body: MCPServerUpdate, db: Session = Depends(get_db)):
    srv = _get_or_404(srv_id, db)
    data = body.model_dump(exclude_none=True)
    if "transport" in data:
        _validate(data["transport"])
    # oauth_config is shallow-merged so a UI edit (e.g. scope) doesn't wipe the
    # endpoints / client creds the OAuth flow discovered and stored.
    if "oauth_config" in data:
        merged = dict(srv.oauth_config or {})
        merged.update(data.pop("oauth_config") or {})
        srv.oauth_config = merged
    for k, v in data.items():
        setattr(srv, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"MCP server name already exists")
    db.refresh(srv)
    return srv


@router.delete("/{srv_id}", status_code=204)
def delete_server(srv_id: str, db: Session = Depends(get_db)):
    srv = _get_or_404(srv_id, db)
    db.delete(srv)
    db.commit()


# ── connection test ──────────────────────────────────────────────────────────────

@router.post("/{srv_id}/probe")
def probe_server_endpoint(srv_id: str, db: Session = Depends(get_db)):
    """Connect to the server and list its tools. Returns
    ``{ok, tools, error, needs_auth}`` — used by the UI's "Test" button."""
    srv = _get_or_404(srv_id, db)
    from services.mcp_config import build_connection
    from services.mcp_probe import probe_server
    cfg = build_connection(srv, db)
    return probe_server(cfg)


# ── OAuth 2.0 ──────────────────────────────────────────────────────────────────────

@router.get("/{srv_id}/oauth/authorize-url")
def oauth_authorize_url(srv_id: str, request: Request, db: Session = Depends(get_db)):
    """Return the provider authorization URL for the user to open in a browser."""
    srv = _get_or_404(srv_id, db)
    if srv.transport == "stdio":
        raise HTTPException(400, "OAuth applies to network transports (http/sse/websocket)")
    if not srv.url:
        raise HTTPException(400, "server has no URL")
    redirect_uri = str(request.base_url).rstrip("/") + f"/api/mcp-servers/{srv_id}/oauth/callback"
    from services.mcp_oauth import build_authorize_url
    try:
        url, _ = build_authorize_url(srv, redirect_uri, db)
    except Exception as e:  # noqa: BLE001 - surface discovery/registration failures
        raise HTTPException(400, f"OAuth setup failed: {e}")
    return {"authorize_url": url}


@router.get("/{srv_id}/oauth/callback", include_in_schema=False)
def oauth_callback(
    srv_id: str,
    db: Session = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    """OAuth redirect target: exchange the code, then render a self-closing page."""
    if error:
        return HTMLResponse(_callback_html(False, error_description or error))
    if not code or not state:
        return HTMLResponse(_callback_html(False, "missing code or state"))
    from services.mcp_oauth import handle_callback
    try:
        handle_callback(state, code, db)
    except Exception as e:  # noqa: BLE001
        return HTMLResponse(_callback_html(False, str(e)))
    return HTMLResponse(_callback_html(True, None))


@router.post("/{srv_id}/oauth/disconnect", response_model=MCPServerOut)
def oauth_disconnect(srv_id: str, db: Session = Depends(get_db)):
    srv = _get_or_404(srv_id, db)
    from services.mcp_oauth import disconnect
    disconnect(srv, db)
    db.refresh(srv)
    return srv


def _callback_html(ok: bool, detail: str | None) -> str:
    title = "Connected" if ok else "Authorization failed"
    msg = "You can close this window." if ok else (detail or "Something went wrong.")
    ok_js = "true" if ok else "false"
    detail_js = (detail or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    color = "#16a34a" if ok else "#dc2626"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font:14px system-ui,sans-serif;display:flex;height:100vh;margin:0;
align-items:center;justify-content:center;background:#0a0a0a;color:#e5e5e5}}
.card{{text-align:center;padding:2rem 2.5rem;border:1px solid #262626;border-radius:12px}}
h1{{font-size:16px;margin:0 0 .5rem;color:{color}}}p{{margin:0;color:#a3a3a3}}</style></head>
<body><div class="card"><h1>{title}</h1><p>{msg}</p></div>
<script>
try {{ window.opener && window.opener.postMessage(
  {{source:"agentflow-oauth", ok:{ok_js}, detail:"{detail_js}"}}, "*"); }} catch(e) {{}}
setTimeout(function(){{ try {{ window.close(); }} catch(e) {{}} }}, 1200);
</script></body></html>"""


def _get_or_404(srv_id: str, db: Session) -> MCPServerConfig:
    s = db.query(MCPServerConfig).filter_by(id=srv_id).first()
    if not s:
        raise HTTPException(404, "MCP server not found")
    return s
