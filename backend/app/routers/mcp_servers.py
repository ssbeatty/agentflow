from fastapi import APIRouter, Depends, HTTPException
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


def _get_or_404(srv_id: str, db: Session) -> MCPServerConfig:
    s = db.query(MCPServerConfig).filter_by(id=srv_id).first()
    if not s:
        raise HTTPException(404, "MCP server not found")
    return s
