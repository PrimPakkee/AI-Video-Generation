"""Auth routes (v0.6.8.5 split out of web/app.py).

Endpoint paths are unchanged from the v0.6.8 era — every route below still
mounts under ``/api/auth/...`` because of ``APIRouter(prefix="/api/auth")``.
Business logic, validation rules, and response shapes are byte-identical to
the previous in-app definitions; only the file location moved.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from web.db import UserRepository, get_auth_db
from web.auth import (
    hash_password,
    verify_password,
    login_session,
    logout_session,
    get_current_user,
    require_active_user,
    user_to_public_dict,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])


_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_MIN_PASSWORD_LEN = 8


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _validate_email(email: str) -> str:
    e = _normalize_email(email)
    if not e or not _EMAIL_RE.match(e) or len(e) > 320:
        raise HTTPException(status_code=400, detail="invalid_email")
    return e


def _validate_password(pw: str) -> str:
    if not isinstance(pw, str) or len(pw) < _MIN_PASSWORD_LEN or len(pw) > 200:
        raise HTTPException(status_code=400, detail="invalid_password")
    return pw


class AuthCredentials(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=_MIN_PASSWORD_LEN, max_length=200)


class ChangeEmailRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_email: str = Field(..., min_length=3, max_length=320)


@router.post("/register")
async def auth_register(
    request: Request,
    credentials: AuthCredentials,
    db: Session = Depends(get_auth_db),
) -> JSONResponse:
    email = _validate_email(credentials.email)
    _validate_password(credentials.password)

    if UserRepository.get_by_email(db, email) is not None:
        # Don't leak existence — but here we explicitly tell the user since
        # this is an internal friend-share tool and "your email is taken" is
        # the actually-useful UX.
        raise HTTPException(status_code=409, detail="email_already_registered")

    user = UserRepository.create_pending(db, email, hash_password(credentials.password))
    return JSONResponse({
        "ok": True,
        "user": user_to_public_dict(user),
        "message": "registered_pending_approval",
    })


@router.post("/login")
async def auth_login(
    request: Request,
    credentials: AuthCredentials,
    db: Session = Depends(get_auth_db),
) -> JSONResponse:
    email = _normalize_email(credentials.email)
    user = UserRepository.get_by_email(db, email)
    if user is None or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")

    if user.status == "pending":
        raise HTTPException(status_code=403, detail="account_pending_approval")
    if user.status == "rejected":
        raise HTTPException(status_code=403, detail="account_rejected")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="account_inactive")

    login_session(request, user.id)
    return JSONResponse({"ok": True, "user": user_to_public_dict(user)})


@router.post("/logout")
async def auth_logout(request: Request) -> JSONResponse:
    logout_session(request)
    return JSONResponse({"ok": True})


@router.get("/me")
async def auth_me(user=Depends(get_current_user)) -> JSONResponse:
    return JSONResponse({"ok": True, "user": user_to_public_dict(user)})


@router.post("/change-password")
async def auth_change_password(
    body: ChangePasswordRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_auth_db),
) -> JSONResponse:
    if user.status not in ("active",):
        raise HTTPException(status_code=403, detail="account_inactive")
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="old_password_mismatch")
    if body.new_password == body.old_password:
        raise HTTPException(status_code=400, detail="new_password_same_as_old")
    _validate_password(body.new_password)
    UserRepository.set_password(db, user.id, hash_password(body.new_password))
    return JSONResponse({"ok": True})


@router.post("/change-email")
async def auth_change_email(
    body: ChangeEmailRequest,
    user=Depends(require_active_user),
    db: Session = Depends(get_auth_db),
) -> JSONResponse:
    """v0.6.8.1 — let a signed-in user change their own email after
    re-confirming the current password. Email format validated server-side;
    collisions return 409.
    """
    new_email = _validate_email(body.new_email)
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="current_password_mismatch")
    if new_email == user.email:
        raise HTTPException(status_code=400, detail="new_email_same_as_old")
    existing = UserRepository.get_by_email(db, new_email)
    if existing is not None and existing.id != user.id:
        raise HTTPException(status_code=409, detail="email_already_registered")
    user.email = new_email
    db.commit()
    db.refresh(user)
    return JSONResponse({"ok": True, "user": user_to_public_dict(user)})
