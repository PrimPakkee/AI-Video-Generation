"""Admin routes (v0.6.8.5 split out of web/app.py).

Endpoint paths are unchanged — every route below still mounts under
``/api/admin/...`` because of ``APIRouter(prefix="/api/admin")``. Behavior
is byte-identical to the previous in-app definitions.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from web.db import UserRepository, get_auth_db
from web.auth import require_admin, user_to_public_dict


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
async def admin_list_users(
    admin=Depends(require_admin),
    db: Session = Depends(get_auth_db),
) -> JSONResponse:
    users = UserRepository.list_all(db)
    return JSONResponse({"ok": True, "users": [user_to_public_dict(u) for u in users]})


@router.get("/users/pending")
async def admin_list_pending(
    admin=Depends(require_admin),
    db: Session = Depends(get_auth_db),
) -> JSONResponse:
    users = UserRepository.list_pending(db)
    return JSONResponse({"ok": True, "users": [user_to_public_dict(u) for u in users]})


@router.post("/users/{user_id}/approve")
async def admin_approve_user(
    user_id: int,
    admin=Depends(require_admin),
    db: Session = Depends(get_auth_db),
) -> JSONResponse:
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="cannot_modify_self")
    target = UserRepository.get_by_id(db, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    UserRepository.approve(db, user_id, admin.id)
    target = UserRepository.get_by_id(db, user_id)
    return JSONResponse({"ok": True, "user": user_to_public_dict(target)})


@router.post("/users/{user_id}/reject")
async def admin_reject_user(
    user_id: int,
    admin=Depends(require_admin),
    db: Session = Depends(get_auth_db),
) -> JSONResponse:
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="cannot_modify_self")
    target = UserRepository.get_by_id(db, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    UserRepository.reject(db, user_id)
    target = UserRepository.get_by_id(db, user_id)
    return JSONResponse({"ok": True, "user": user_to_public_dict(target)})


@router.delete("/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    admin=Depends(require_admin),
    db: Session = Depends(get_auth_db),
) -> JSONResponse:
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="cannot_modify_self")
    target = UserRepository.get_by_id(db, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    if target.is_admin:
        raise HTTPException(status_code=400, detail="cannot_delete_admin")
    ok = UserRepository.delete_user(db, user_id)
    return JSONResponse({"ok": bool(ok)})
