#!/usr/bin/env python3
"""
v0.6.8 — Auth glue: password hashing, session-cookie current-user
dependency, and the activity guards used by every route.

Session model: a Starlette HttpOnly signed cookie. The cookie payload only
holds {"user_id": int}; everything else (email, is_admin,
must_change_password) is rehydrated from auth.db on every request so the
cookie can never go stale relative to admin actions like reject/approve.
"""

from __future__ import annotations

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from web.db import User, UserRepository, get_auth_db


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    if not plain:
        raise ValueError("password must not be empty")
    pw_bytes = plain.encode("utf-8")
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

SESSION_USER_KEY = "user_id"


def login_session(request: Request, user_id: int) -> None:
    request.session[SESSION_USER_KEY] = int(user_id)


def logout_session(request: Request) -> None:
    request.session.pop(SESSION_USER_KEY, None)
    # Wipe everything just in case future code adds keys.
    request.session.clear()


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def get_current_user(
    request: Request,
    db: Session = Depends(get_auth_db),
) -> User:
    """Resolve the logged-in user. 401 if not logged in or row deleted."""
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not_logged_in",
        )
    user = UserRepository.get_by_id(db, int(user_id))
    if user is None:
        # Cookie references a deleted row — clear it.
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not_logged_in",
        )
    return user


def require_active_user(user: User = Depends(get_current_user)) -> User:
    """Reject pending / rejected accounts. Used by every content route."""
    if user.status == "pending":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="account_pending_approval",
        )
    if user.status == "rejected":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="account_rejected",
        )
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="account_inactive",
        )
    if user.must_change_password:
        # The frontend reads this code and routes the user through the
        # change-password flow before any other interaction.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="must_change_password",
        )
    return user


def require_admin(user: User = Depends(require_active_user)) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin_only",
        )
    return user


def user_to_public_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "status": user.status,
        "is_admin": bool(user.is_admin),
        "must_change_password": bool(user.must_change_password),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "approved_at": user.approved_at.isoformat() if user.approved_at else None,
    }
