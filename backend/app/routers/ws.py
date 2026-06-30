"""
WebSocket endpoints:
  /ws/executions/{execution_id}  — real-time execution logs
  /ws/install/{script_id}        — real-time install output
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services.execution_engine import ws_manager
from services.venv_manager import venv_exists, stream_create_venv, stream_install
from app.database import SessionLocal
from app.models import Script, AdminUser
from app.security import verify_session_token
from app.auth_deps import COOKIE_NAME

router = APIRouter()


def _ws_authenticated(ws: WebSocket) -> bool:
    """Validate the admin session cookie carried on the WS handshake. The cookie
    is auto-sent by the browser on same-origin WebSocket connections."""
    payload = verify_session_token(ws.cookies.get(COOKIE_NAME))
    if not payload:
        return False
    db = SessionLocal()
    try:
        return db.query(AdminUser).filter_by(username=payload.get("sub")).first() is not None
    finally:
        db.close()


@router.websocket("/executions/{execution_id}")
async def execution_ws(execution_id: str, ws: WebSocket):
    if not _ws_authenticated(ws):
        await ws.close(code=4401)  # 4401: application-level "unauthorized"
        return
    await ws.accept()
    await ws_manager.connect(execution_id, ws)
    try:
        # block until the client disconnects; logs are pushed from the engine
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(execution_id, ws)


@router.websocket("/install/{script_id}")
async def install_ws(script_id: str, action: str = "install", ws: WebSocket = None):
    if not _ws_authenticated(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    db = SessionLocal()
    try:
        script = db.query(Script).filter_by(id=script_id).first()
        if not script:
            await ws.send_json({"type": "error", "message": "Script not found"})
            await ws.close()
            return

        if action == "venv":
            gen = stream_create_venv(script_id)
        else:
            if not venv_exists(script_id):
                await ws.send_json({"type": "error", "message": "Create venv first"})
                await ws.close()
                return
            gen = stream_install(script_id, script.requirements or "")

        async for line in gen:
            done = line in ("DONE", ) or line.startswith("ERROR:")
            await ws.send_json({"type": "line", "text": line, "done": done})
            if done:
                break
    except WebSocketDisconnect:
        pass
    finally:
        db.close()
        try:
            await ws.close()
        except Exception:
            pass
