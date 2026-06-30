"""
Admin authentication.

  GET  /api/auth/status           public — { initialized, authenticated, username }
  POST /api/auth/setup            public, first-run only — create the admin account
  POST /api/auth/login            public — username/password -> session cookie + token
  POST /api/auth/logout           clears the session cookie
  POST /api/auth/change-password  admin — rotate the password
  GET  /api/auth/me               admin — who am I

A single admin account gates the whole management UI/API. The login is stateless
(HMAC-signed token) delivered as an httpOnly cookie so it also flows to <img>,
file downloads and the WebSocket handshake on the same origin.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AdminUser
from app.schemas import (
    AdminSetup, AdminLogin, ChangePassword, AuthStatus, AuthResult,
)
from app.security import (
    hash_password, verify_password, create_session_token,
)
from app.auth_deps import require_admin, current_subject, COOKIE_NAME

router = APIRouter()


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


@router.get("/status", response_model=AuthStatus)
def auth_status(request: Request, db: Session = Depends(get_db)):
    initialized = db.query(AdminUser).count() > 0
    sub = current_subject(request, db)
    return AuthStatus(initialized=initialized, authenticated=bool(sub), username=sub)


@router.post("/setup", response_model=AuthResult)
def setup_admin(body: AdminSetup, response: Response, db: Session = Depends(get_db)):
    if db.query(AdminUser).count() > 0:
        raise HTTPException(409, "管理员账户已初始化")
    user = AdminUser(
        username=body.username.strip(),
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    token = create_session_token(user.username)
    _set_session_cookie(response, token)
    return AuthResult(username=user.username, token=token)


@router.post("/login", response_model=AuthResult)
def login(body: AdminLogin, response: Response, db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter_by(username=body.username.strip()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    token = create_session_token(user.username)
    _set_session_cookie(response, token)
    return AuthResult(username=user.username, token=token)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/change-password")
def change_password(
    body: ChangePassword,
    response: Response,
    username: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(AdminUser).filter_by(username=username).first()
    if not user or not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "原密码错误")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    # Re-issue the cookie so the current session stays valid.
    _set_session_cookie(response, create_session_token(user.username))
    return {"ok": True}


@router.get("/me")
def me(username: str = Depends(require_admin)):
    return {"username": username}
