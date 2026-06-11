#!/usr/bin/env python3
"""
AI Video Prompt Generator - Web Interface
FastAPI backend for generating NotebookLM prompts via web UI
"""

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load .env from project root
from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

# Import database components
from web.db import init_db, get_db, PromptHistory, PromptHistoryRepository

# Video Mode (v0.5.3) - independent SQLite database, fully isolated from
# Prompt Mode. The Video Mode session/repository must never touch
# prompt_history / prompt_reviews tables.
from web.db import (
    init_video_db,
    get_video_db,
    VideoHistory,
    VideoJob,
    VideoHistoryRepository,
    VideoJobRepository,
)

# Auth (v0.6.8) — login/register, founder approval, session middleware.
from web.db import (
    UserRepository,
    init_auth_db,
    get_auth_db,
)
from web.auth import (
    hash_password,
    verify_password,
    login_session,
    logout_session,
    get_current_user,
    require_active_user,
    require_admin,
    user_to_public_dict,
)
from web.video_providers import MockVideoProvider, ApxSeedanceProvider
from web.video_providers.apx_seedance_provider import _scrub_api_key as _apx_scrub_api_key
from web.video_providers.seedance_prompt_compiler import (
    validate_seedance_prompt_quality as _validate_seedance_prompt_quality,
)

# v0.5.4: Video Content Asset Pipeline. Generates structured assets that a
# future real video provider integration will consume. Never calls a real
# video provider, never produces real mp4.
from web.video_asset_pipeline import (
    build_video_content_assets,
    VIDEO_ASSETS_SCHEMA_VERSION,
)

app = FastAPI(title="AI Video Prompt Generator")

# v0.6.8 — HttpOnly session cookie for auth. SESSION_SECRET is required;
# generate a 32-byte hex secret and store it in .env.
_session_secret = os.getenv("SESSION_SECRET")
if not _session_secret:
    # Fail-loud rather than ship a random secret that resets every restart
    # (which would silently log everyone out on every code reload).
    raise RuntimeError(
        "SESSION_SECRET is not set. Add a 32+ char random string to .env "
        "(e.g. `python -c 'import secrets; print(secrets.token_hex(32))'`)."
    )
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
    session_cookie="aivg_session",
    same_site="lax",
    https_only=False,  # local-only friend-share tool; flip to True if exposed via TLS
    max_age=60 * 60 * 24 * 30,  # 30 days
)


# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database tables on startup"""
    init_db()
    # v0.5.1: initialize the independent Video Mode database. This only
    # creates tables in data/video_history.db; it never modifies the
    # Prompt Mode database (data/prompt_history.db).
    init_video_db()
    # v0.6.8: independent auth database (data/auth.db).
    init_auth_db()

# Mount static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class GenerateRequest(BaseModel):
    """Request model for prompt generation"""
    title: str = Field(..., min_length=1, max_length=200, description="Video title")


class GenerateResponse(BaseModel):
    """Response model for successful generation"""
    success: bool
    slug: str
    prompt: str
    output_dir: str


class ErrorResponse(BaseModel):
    """Response model for errors"""
    success: bool
    error: str
    stdout: str = ""
    stderr: str = ""


class RenameRequest(BaseModel):
    """Request model for renaming"""
    title: str = Field(..., min_length=1, max_length=200)


class UpdateContentRequest(BaseModel):
    """Request model for updating prompt content"""
    view: str = Field(..., pattern='^(raw|preview|overview)$')
    content: str = Field(..., min_length=0)


class RegenerateRequest(BaseModel):
    """Request model for regenerating prompt"""
    feedback: str = Field(..., min_length=1, max_length=2000)


def sanitize_slug(title: str) -> str:
    """
    Generate a safe base slug from title

    Args:
        title: User input title

    Returns:
        Sanitized slug (alphanumeric, underscore, hyphen only)
    """
    # Convert to lowercase
    slug = title.lower()

    # Replace spaces with underscores
    slug = re.sub(r'\s+', '_', slug)

    # Remove all non-alphanumeric characters except underscore and hyphen
    slug = re.sub(r'[^a-z0-9_\-]', '', slug)

    # Limit length
    slug = slug[:40]

    # Ensure it's not empty
    if not slug or slug == "video" or len(slug) < 3:
        slug = "topic"

    return slug


def generate_unique_slug(title: str) -> str:
    """
    Generate a unique slug with timestamp and random suffix

    Args:
        title: User input title

    Returns:
        Unique slug in format: base_YYYYMMDD_HHMMSS_random
    """
    base = sanitize_slug(title)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(3)

    return f"{base}_{timestamp}_{suffix}"


@app.get("/")
async def serve_index(request: Request):
    """Serve the main HTML page; redirect to /auth.html if not logged in."""
    if not request.session.get("user_id"):
        return RedirectResponse(url="/auth.html", status_code=302)
    index_file = static_dir / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_file)


@app.get("/auth.html")
async def serve_auth_page():
    """Serve the login / register page (always public)."""
    auth_file = static_dir / "auth.html"
    if not auth_file.exists():
        raise HTTPException(status_code=404, detail="auth.html not found")
    return FileResponse(auth_file)


# ---------------------------------------------------------------------------
# v0.6.8 — Auth + admin routes
# ---------------------------------------------------------------------------

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


@app.post("/api/auth/register")
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


@app.post("/api/auth/login")
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


@app.post("/api/auth/logout")
async def auth_logout(request: Request) -> JSONResponse:
    logout_session(request)
    return JSONResponse({"ok": True})


@app.get("/api/auth/me")
async def auth_me(user=Depends(get_current_user)) -> JSONResponse:
    return JSONResponse({"ok": True, "user": user_to_public_dict(user)})


@app.post("/api/auth/change-password")
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


@app.post("/api/auth/change-email")
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


@app.get("/api/admin/users")
async def admin_list_users(
    admin=Depends(require_admin),
    db: Session = Depends(get_auth_db),
) -> JSONResponse:
    users = UserRepository.list_all(db)
    return JSONResponse({"ok": True, "users": [user_to_public_dict(u) for u in users]})


@app.get("/api/admin/users/pending")
async def admin_list_pending(
    admin=Depends(require_admin),
    db: Session = Depends(get_auth_db),
) -> JSONResponse:
    users = UserRepository.list_pending(db)
    return JSONResponse({"ok": True, "users": [user_to_public_dict(u) for u in users]})


@app.post("/api/admin/users/{user_id}/approve")
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


@app.post("/api/admin/users/{user_id}/reject")
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


@app.delete("/api/admin/users/{user_id}")
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


@app.post("/api/generate", response_model=GenerateResponse)
async def generate_prompt(
    request: GenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> JSONResponse:
    """
    Generate NotebookLM prompt from title

    Args:
        request: GenerateRequest with title
        db: Database session

    Returns:
        GenerateResponse with prompt text or ErrorResponse on failure
    """
    title = request.title.strip()

    if not title:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                success=False,
                error="Title cannot be empty"
            ).dict()
        )

    # Generate unique slug
    slug = generate_unique_slug(title)

    # Build command (use list to avoid shell injection)
    script_path = project_root / "scripts" / "generate_video_package.py"

    if not script_path.exists():
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                success=False,
                error=f"Script not found: {script_path}"
            ).dict()
        )

    cmd = [
        sys.executable,  # Use current Python interpreter
        str(script_path),
        "--title", title,
        "--mode", "llm",
        "--output-slug", slug,
        "--overwrite"
    ]

    try:
        # Run command with timeout
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=600  # 10 minutes timeout
        )

        # Check if command succeeded
        if result.returncode != 0:
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    success=False,
                    error=f"Command failed with exit code {result.returncode}",
                    stdout=result.stdout[-2000:] if result.stdout else "",  # Last 2000 chars
                    stderr=result.stderr[-2000:] if result.stderr else ""
                ).dict()
            )

        # Read generated prompt
        output_dir = project_root / "outputs" / slug
        prompt_file = output_dir / "notebooklm_clean_source.txt"

        if not prompt_file.exists():
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    success=False,
                    error=f"Prompt file not found: {prompt_file}",
                    stdout=result.stdout[-2000:] if result.stdout else "",
                    stderr=result.stderr[-2000:] if result.stderr else ""
                ).dict()
            )

        # Read prompt content
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_content = f.read()

        # Read overview_cn from topic.json if it exists
        overview_cn = None
        topic_json_file = output_dir / "topic.json"
        if topic_json_file.exists():
            try:
                import json
                with open(topic_json_file, 'r', encoding='utf-8') as f:
                    topic_data = json.load(f)
                    overview_cn = topic_data.get('overview_cn')
            except Exception as e:
                print(f"Warning: Failed to read overview_cn from topic.json: {e}")

        # Get current model from environment
        model = os.getenv('AI_VIDEO_LLM_MODEL', 'gpt-5-chat')
        mode = 'NotebookLM Prompt Generation'

        # Save to database
        try:
            history_record = PromptHistoryRepository.create_history_record(
                db=db,
                user_id=current_user.id,
                title=title,
                slug=slug,
                prompt_text=prompt_content,
                output_dir=str(output_dir),
                model=model,
                mode=mode,
                status='success',
                overview_cn=overview_cn
            )

            return JSONResponse(
                content={
                    'success': True,
                    'id': history_record.id,
                    'history_id': history_record.id,
                    'title': title,
                    'slug': slug,
                    'prompt': prompt_content,
                    'overview_cn': overview_cn,
                    'output_dir': str(output_dir),
                    'model': model,
                    'mode': mode,
                    'created_at': history_record.created_at.isoformat() if history_record.created_at else None
                }
            )
        except Exception as e:
            # If database save fails, still return success but log the error
            print(f"Warning: Failed to save to database: {e}")
            return JSONResponse(
                content=GenerateResponse(
                    success=True,
                    slug=slug,
                    prompt=prompt_content,
                    output_dir=str(output_dir)
                ).dict()
            )

    except subprocess.TimeoutExpired:
        return JSONResponse(
            status_code=504,
            content=ErrorResponse(
                success=False,
                error="Generation timed out (> 10 minutes)"
            ).dict()
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                success=False,
                error=f"Unexpected error: {str(e)}"
            ).dict()
        )


@app.get("/api/history")
async def get_history(
    limit: int = 100,
    q: Optional[str] = None,
    date_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """
    Get prompt history list (non-deleted, latest version per group)
    """
    try:
        records = PromptHistoryRepository.list_history_records(
            db, current_user.id, limit=limit, q=q, date_filter=date_filter
        )

        items = []
        for record in records:
            item = record.to_dict(include_prompt=False)

            # Add version count
            version_count = PromptHistoryRepository.get_version_count(db, current_user.id, record.topic_group_id)
            item['version_count'] = version_count

            items.append(item)

        return {
            "success": True,
            "items": items
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "items": []
        }


@app.get("/api/history/{history_id}")
async def get_history_by_id(
    history_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """
    Get a single prompt history record by ID (including deleted)
    """
    try:
        record = PromptHistoryRepository.get_history_record(db, current_user.id, history_id)

        if not record:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"History record {history_id} not found"
                }
            )

        item = record.to_dict(include_prompt=True)

        # Add version count
        version_count = PromptHistoryRepository.get_version_count(db, current_user.id, record.topic_group_id)
        item['version_count'] = version_count

        return {
            "success": True,
            "item": item
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.patch("/api/history/{history_id}")
async def update_history_content(
    history_id: int,
    request: UpdateContentRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """
    Update prompt content for a specific view

    Args:
        history_id: History record ID
        request: Update request with view type and content
        db: Database session

    Returns:
        Updated record
    """
    try:
        # CRITICAL DATA PROTECTION: Validate view and content before saving
        view = request.view
        content = request.content

        # Check 1: View must be one of the allowed values (already validated by Pydantic pattern)
        if view not in ['raw', 'preview', 'overview']:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": f"Invalid view: {view}. Only raw, preview, or overview can be edited."
                }
            )

        # Check 2: For raw text, validate format to prevent pollution
        if view == 'raw':
            trimmed_content = content.strip()

            # Empty check
            if not trimmed_content:
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "Raw Text cannot be empty. Save rejected to prevent data loss."
                    }
                )

            # Length check
            if len(trimmed_content) < 500:
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": f"Raw Text is too short ({len(trimmed_content)} characters). Save rejected to prevent data loss. NotebookLM prompts should be at least 500 characters."
                    }
                )

            # CRITICAL: Format check to prevent preview/overview pollution
            # Raw prompt should NOT start with preview format indicators
            if trimmed_content.startswith("BASIC INFO"):
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "Raw Text format looks invalid (starts with 'BASIC INFO'). This appears to be preview format, not raw NotebookLM prompt. Save rejected to prevent data corruption."
                    }
                )

            if trimmed_content.startswith("PROBLEM & ANSWER") or trimmed_content.startswith("PROBLEM AND ANSWER"):
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "Raw Text format looks invalid (starts with 'PROBLEM & ANSWER'). This appears to be preview format, not raw NotebookLM prompt. Save rejected to prevent data corruption."
                    }
                )

            # Raw prompt should contain at least one of these markers
            has_notebooklm = "NotebookLM" in content or "notebooklm" in content.lower()
            has_title = "## Title" in content
            has_topic = "## Topic" in content

            if not (has_notebooklm or has_title or has_topic):
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "Raw Text format looks invalid (missing '# NotebookLM Prompt' or '## Title' or '## Topic' markers). This does not appear to be a valid NotebookLM prompt. Save rejected to prevent data corruption."
                    }
                )

        # Proceed with save
        record = PromptHistoryRepository.update_prompt_content(
            db, current_user.id, history_id, request.view, request.content
        )

        if not record:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"History record {history_id} not found"
                }
            )

        # Mark AI Review as stale when prompt is edited (only for raw text)
        if view == 'raw':
            try:
                from web.db.repository_review import PromptReviewRepository
                PromptReviewRepository.mark_review_stale(db, current_user.id, history_id)
            except Exception:
                # Silently fail if review marking fails
                pass

        return {
            "success": True,
            "history_id": history_id,
            "view": request.view,
            "content": request.content,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.post("/api/history/{history_id}/pin")
async def pin_history(
    history_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Pin a history record."""
    try:
        record = PromptHistoryRepository.pin_history_record(db, current_user.id, history_id)

        if not record:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"History record {history_id} not found"
                }
            )

        return {
            "success": True,
            "item": record.to_dict(include_prompt=False)
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.post("/api/history/{history_id}/unpin")
async def unpin_history(
    history_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Unpin a history record."""
    try:
        record = PromptHistoryRepository.unpin_history_record(db, current_user.id, history_id)

        if not record:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"History record {history_id} not found"
                }
            )

        return {
            "success": True,
            "item": record.to_dict(include_prompt=False)
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.delete("/api/history/{history_id}")
async def delete_history(
    history_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Delete a history record (legacy hard delete)."""
    try:
        deleted = PromptHistoryRepository.delete_history_record(db, current_user.id, history_id)

        if not deleted:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"History record {history_id} not found"
                }
            )

        return {
            "success": True,
            "message": "History record deleted"
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.get("/api/history/group/{topic_group_id}/versions")
async def get_group_versions(
    topic_group_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Get all versions of a topic group."""
    try:
        versions = PromptHistoryRepository.get_versions_by_group(db, current_user.id, topic_group_id)

        if not versions:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Topic group {topic_group_id} not found"
                }
            )

        version_list = []
        for v in versions:
            version_list.append({
                'id': v.id,
                'version_number': v.version_number,
                'created_at': v.created_at.isoformat() if v.created_at else None,
                'slug': v.slug,
                'deleted_at': v.deleted_at.isoformat() if v.deleted_at else None
            })

        return {
            "success": True,
            "versions": version_list
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.patch("/api/history/group/{topic_group_id}/rename")
async def rename_history_group(
    topic_group_id: str,
    request: RenameRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Rename all versions in a topic group."""
    try:
        latest = PromptHistoryRepository.rename_history_group(db, current_user.id, topic_group_id, request.title)

        if not latest:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Topic group {topic_group_id} not found"
                }
            )

        # Add version count
        version_count = PromptHistoryRepository.get_version_count(db, current_user.id, topic_group_id)
        item = latest.to_dict(include_prompt=False)
        item['version_count'] = version_count

        return {
            "success": True,
            "item": item
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.post("/api/history/group/{topic_group_id}/trash")
async def trash_history_group(
    topic_group_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Soft delete a topic group (move to trash)."""
    try:
        deleted = PromptHistoryRepository.soft_delete_history_group(db, current_user.id, topic_group_id)

        if not deleted:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Topic group {topic_group_id} not found"
                }
            )

        return {
            "success": True,
            "topic_group_id": topic_group_id
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.get("/api/trash")
async def get_trash(
    limit: int = 100,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Get trash list (deleted records, latest version per group)."""
    try:
        records = PromptHistoryRepository.list_trash_records(db, current_user.id, limit=limit, q=q)

        items = []
        for record in records:
            item = record.to_dict(include_prompt=False)

            # Add version count
            version_count = PromptHistoryRepository.get_version_count(db, current_user.id, record.topic_group_id)
            item['version_count'] = version_count

            items.append(item)

        return {
            "success": True,
            "items": items
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "items": []
        }


@app.delete("/api/history/group/{topic_group_id}/permanent")
async def permanently_delete_group(
    topic_group_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Permanently delete a topic group (hard delete)."""
    try:
        deleted = PromptHistoryRepository.permanently_delete_history_group(db, current_user.id, topic_group_id)

        if not deleted:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Topic group {topic_group_id} not found"
                }
            )

        return {
            "success": True,
            "topic_group_id": topic_group_id
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.post("/api/history/group/{topic_group_id}/restore")
async def restore_history_group(
    topic_group_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Restore a topic group from trash."""
    try:
        restored = PromptHistoryRepository.restore_history_group(db, current_user.id, topic_group_id)

        if not restored:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Topic group {topic_group_id} not found in trash"
                }
            )

        return {
            "success": True,
            "topic_group_id": topic_group_id
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.post("/api/history/group/{topic_group_id}/favorite")
async def favorite_history_group(
    topic_group_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Favorite a topic group."""
    try:
        latest = PromptHistoryRepository.favorite_history_group(db, current_user.id, topic_group_id)

        if not latest:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Topic group {topic_group_id} not found"
                }
            )

        # Add version count
        version_count = PromptHistoryRepository.get_version_count(db, current_user.id, topic_group_id)
        item = latest.to_dict(include_prompt=False)
        item['version_count'] = version_count

        return {
            "success": True,
            "item": item
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.post("/api/history/group/{topic_group_id}/unfavorite")
async def unfavorite_history_group(
    topic_group_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Unfavorite a topic group."""
    try:
        latest = PromptHistoryRepository.unfavorite_history_group(db, current_user.id, topic_group_id)

        if not latest:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Topic group {topic_group_id} not found"
                }
            )

        # Add version count
        version_count = PromptHistoryRepository.get_version_count(db, current_user.id, topic_group_id)
        item = latest.to_dict(include_prompt=False)
        item['version_count'] = version_count

        return {
            "success": True,
            "item": item
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.get("/api/favorites")
async def get_favorites(
    limit: int = 100,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Get favorite list (latest version per group)."""
    try:
        records = PromptHistoryRepository.list_favorite_records(db, current_user.id, limit=limit, q=q)

        items = []
        for record in records:
            item = record.to_dict(include_prompt=False)

            # Add version count
            version_count = PromptHistoryRepository.get_version_count(db, current_user.id, record.topic_group_id)
            item['version_count'] = version_count

            items.append(item)

        return {
            "success": True,
            "items": items
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "items": []
        }


def generate_fallback_overview(title: str, core_concept: Optional[str] = None) -> str:
    """
    Generate fallback overview for old records without overview_cn

    Args:
        title: Video title
        core_concept: Core concept (optional)

    Returns:
        Fallback overview text in Chinese
    """
    if core_concept:
        return f"这个视频围绕「{title}」展开，核心概念是「{core_concept}」。内容会先提出一个反直觉问题，再通过分步推理解释答案。画面上将使用白底线稿和大号英文字幕，帮助观众理解关键逻辑。"
    else:
        return f"这个视频围绕「{title}」展开。内容会先提出一个适合短视频传播的问题，再通过分步推理解释答案。画面上将使用白底线稿和大号英文字幕，帮助观众理解关键逻辑。"


def generate_preview_text(raw_text: str) -> str:
    """
    Generate preview text from raw NotebookLM prompt

    Args:
        raw_text: Raw NotebookLM prompt text

    Returns:
        Structured preview text
    """
    # Simple markdown section parser
    sections = {}
    current_section = None
    current_content = []

    for line in raw_text.split('\n'):
        # Check if it's a markdown header
        if line.startswith('## '):
            # Save previous section
            if current_section:
                sections[current_section] = '\n'.join(current_content).strip()
            # Start new section
            current_section = line[3:].strip()
            current_content = []
        elif line.startswith('# '):
            # Top-level header (Title)
            if current_section:
                sections[current_section] = '\n'.join(current_content).strip()
            current_section = line[2:].strip()
            current_content = []
        else:
            current_content.append(line)

    # Save last section
    if current_section:
        sections[current_section] = '\n'.join(current_content).strip()

    # Build structured preview
    preview = []

    # Basic Info
    preview.append("=== BASIC INFO ===\n")
    for key in ['Title', 'Topic', 'Target platform', 'Target audience', 'Video length', 'Core concept']:
        if key in sections:
            preview.append(f"{key}:")
            preview.append(sections[key])
            preview.append("")

    # Problem & Answer
    preview.append("\n=== PROBLEM & ANSWER ===\n")
    for key in ['Puzzle setup', 'Question', 'Correct answer', 'Wrong intuition']:
        if key in sections:
            preview.append(f"{key}:")
            preview.append(sections[key])
            preview.append("")

    # Reasoning
    preview.append("\n=== REASONING ===\n")
    if 'Reasoning' in sections:
        preview.append(sections['Reasoning'])
        preview.append("")

    # Production
    preview.append("\n=== PRODUCTION PLAN ===\n")
    for key in ['Narration Script', 'On-screen text', 'Visual style']:
        if key in sections:
            preview.append(f"{key}:")
            preview.append(sections[key])
            preview.append("")

    # Requirements
    preview.append("\n=== REQUIREMENTS ===\n")
    if 'Important requirements' in sections:
        preview.append(sections['Important requirements'])

    return '\n'.join(preview)


def _build_ai_review_markdown(review_data: Optional[dict]) -> str:
    """Build a portable markdown rendering of an AI review payload.

    Mirrors the frontend reviewToMarkdown() shape so the bundled
    ai_review.md inside Download All matches what users see in the UI.
    Returns a placeholder string when no review data is available.
    """
    if not review_data:
        return "AI Review has not been generated yet.\n"

    rows = review_data.get("rows") or []
    total_score = review_data.get("total_score", 0)
    overall_review = review_data.get("overall_review") or ""

    def _esc(value: Any) -> str:
        text = "" if value is None else str(value)
        return text.replace("|", "\\|").replace("\n", " ")

    lines = ["# AI Quality Evaluation", ""]
    lines.append("| Criterion | Weight | Evaluation Focus | LLM Score | LLM Comment |")
    lines.append("|-----------|-------:|------------------|----------:|-------------|")
    for row in rows:
        lines.append(
            "| {criterion} | {weight} | {focus} | {score} | {comment} |".format(
                criterion=_esc(row.get("criterion", "")),
                weight=_esc(row.get("weight", "")),
                focus=_esc(row.get("evaluation_focus", "")),
                score=_esc(row.get("llm_score", "")),
                comment=_esc(row.get("llm_comment", "")),
            )
        )
    lines.append(
        f"| **Total Score** | **100%** | - | **{_esc(total_score)}/100** | - |"
    )
    lines.append(
        f"| **Overall Review** | - | - | - | {_esc(overall_review)} |"
    )
    return "\n".join(lines) + "\n"


@app.get("/api/history/{history_id}/download-all")
async def download_all(
    history_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
):
    """Download all prompt views as a zip package."""
    from fastapi.responses import StreamingResponse
    from web.db.models import PromptReview
    import io
    import zipfile

    try:
        # Get history record
        record = PromptHistoryRepository.get_history_record(db, current_user.id, history_id)

        if not record:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"History record {history_id} not found"
                }
            )

        # Get raw text
        raw_text = record.prompt_text or ""

        # Get preview - use preview_text if available, otherwise generate from raw
        if record.preview_text:
            preview_text = record.preview_text
        else:
            try:
                preview_text = generate_preview_text(raw_text)
            except Exception as e:
                print(f"Warning: Failed to generate preview: {e}")
                preview_text = "Preview generation failed. See raw_text.txt for full content."

        # Get or generate overview
        overview_cn = record.overview_cn
        if not overview_cn:
            # Try to read core_concept from topic.json
            core_concept = None
            try:
                output_dir = Path(record.output_dir)
                topic_json_file = output_dir / "topic.json"
                if topic_json_file.exists():
                    with open(topic_json_file, 'r', encoding='utf-8') as f:
                        topic_data = json.load(f)
                        core_concept = topic_data.get('core_concept')
            except Exception:
                pass

            overview_cn = generate_fallback_overview(record.title, core_concept)

        # Add change_summary_cn if available
        if record.change_summary_cn:
            overview_cn = f"{overview_cn}\n\n本次生成新增或改动的内容\n\n{record.change_summary_cn}"

        # ---- AI Review markdown (STRICTLY read-only) ----
        # IMPORTANT: download_all is a GET endpoint and MUST NOT mutate the
        # database. We deliberately bypass PromptReviewRepository helpers here
        # because:
        #   * get_review_status() side-effects timed-out generating rows.
        #   * get_review_by_history_id() filters to the current schema only,
        #     which would hide legacy reviews that are still worth archiving.
        # We do a direct read-only ORM query and derive everything in memory.
        CURRENT_REVIEW_SCHEMA = "v0.4.6.9_strict"

        review_records = []
        try:
            review_records = (
                db.query(PromptReview)
                .filter(
                    PromptReview.user_id == current_user.id,
                    PromptReview.history_id == history_id,
                )
                .order_by(PromptReview.updated_at.desc())
                .all()
            )
        except Exception as e:
            print(f"Warning: Failed to read review rows for download_all: {e}")
            review_records = []

        def _try_parse_review_json(raw):
            if not raw:
                return None
            try:
                parsed = json.loads(raw)
            except Exception:
                return None
            if not isinstance(parsed, dict):
                return None
            return parsed

        def _is_renderable(parsed):
            # We need at least one of rows / total_score / overall_review
            # for the markdown table to be meaningful.
            if not isinstance(parsed, dict):
                return False
            return any(k in parsed for k in ("rows", "total_score", "overall_review"))

        def _normalize_status(value):
            normalized = (value or "").strip().lower() or "none"
            # 'active' is the legacy synonym for a completed review
            # (see create_review()'s `status='active'`).
            if normalized == "active":
                return "completed"
            return normalized

        # Partition records into current-schema vs legacy (any other schema,
        # including missing/None — treat those as legacy too).
        current_schema_records = [
            r for r in review_records
            if r.review_schema_version == CURRENT_REVIEW_SCHEMA
        ]
        legacy_records = [
            r for r in review_records
            if r.review_schema_version != CURRENT_REVIEW_SCHEMA
        ]

        # Pick the best current-schema record by status priority, then recency.
        # `review_records` is already ordered by updated_at DESC, so we just
        # need to scan in priority order.
        STATUS_PRIORITY = ("completed", "stale", "generating", "failed")
        chosen_record = None
        chosen_origin = None  # 'current' | 'legacy' | None

        for status_key in STATUS_PRIORITY:
            for r in current_schema_records:
                if _normalize_status(r.status) == status_key:
                    chosen_record = r
                    chosen_origin = "current"
                    break
            if chosen_record is not None:
                break

        # Normalized status drives subsequent decisions; raw 'active' from
        # create_review() should fall into the 'completed' priority bucket
        # above, but if everything was unrecognized we still pick the newest.
        if chosen_record is None and current_schema_records:
            # Some other status value we didn't enumerate — still take newest.
            chosen_record = current_schema_records[0]
            chosen_origin = "current"

        # If we have no current-schema record (or only an `none`/empty one)
        # and there are legacy reviews, fall back to the newest renderable
        # legacy review. Otherwise keep the legacy fallback even if not
        # renderable, so metadata can still surface its existence.
        if chosen_record is None and legacy_records:
            renderable_legacy = None
            for r in legacy_records:
                parsed = _try_parse_review_json(r.review_json)
                if _is_renderable(parsed):
                    renderable_legacy = r
                    break
            if renderable_legacy is not None:
                chosen_record = renderable_legacy
            else:
                chosen_record = legacy_records[0]
            chosen_origin = "legacy"

        # Derive export-only fields from the chosen record. None of this writes
        # back to the database.
        review_status = "none"
        review_total_score = None
        review_schema_version = None
        review_data_for_md: Optional[dict] = None
        review_parse_failed = False

        if chosen_record is not None:
            review_total_score = chosen_record.total_score
            review_schema_version = chosen_record.review_schema_version
            parsed = _try_parse_review_json(chosen_record.review_json)
            if parsed is None and chosen_record.review_json:
                review_parse_failed = True
            elif parsed is not None and _is_renderable(parsed):
                review_data_for_md = parsed

            if chosen_origin == "legacy":
                review_status = "stale"
            else:
                # Current schema: trust the row's status, but also flag stale
                # when the row's own status field already says so.
                review_status = _normalize_status(chosen_record.status)
                if review_status not in ("completed", "stale", "generating", "failed"):
                    # Unknown status — fall through to "none" semantics for the
                    # ai_review.md text but keep schema/score in metadata.
                    review_status = "none"

        if review_status == "completed" and review_data_for_md:
            ai_review_md = _build_ai_review_markdown(review_data_for_md)
        elif review_status == "stale" and review_data_for_md:
            ai_review_md = (
                "Note: This AI Review may be outdated because the prompt has changed.\n\n"
                + _build_ai_review_markdown(review_data_for_md)
            )
        elif review_status == "generating":
            ai_review_md = (
                "AI Review is currently generating and has not been completed yet.\n"
            )
        elif review_status == "failed":
            ai_review_md = "AI Review generation failed or is unavailable.\n"
        elif review_parse_failed:
            ai_review_md = "AI Review data exists but could not be parsed.\n"
        else:
            ai_review_md = "AI Review has not been generated yet.\n"

        # ---- metadata.json (read-only summary; no secrets) ----
        def _iso(dt):
            try:
                return dt.isoformat() if dt else None
            except Exception:
                return None

        metadata_payload = {
            "id": record.id,
            "title": record.title,
            "slug": record.slug,
            "output_dir": record.output_dir,
            "model": record.model,
            "mode": record.mode,
            "status": record.status,
            "topic_group_id": record.topic_group_id,
            "version_number": record.version_number,
            "created_at": _iso(record.created_at),
            "updated_at": _iso(record.updated_at),
            "has_preview_text": bool(record.preview_text),
            "has_overview_cn": bool(record.overview_cn),
            "has_change_summary_cn": bool(record.change_summary_cn),
            "regenerate_from_history_id": record.regenerate_from_history_id,
            "regenerate_feedback": record.regenerate_feedback,
            "ai_review_status": review_status,
            "ai_review_total_score": review_total_score,
            "ai_review_schema_version": review_schema_version,
            "export_schema_version": "v0.4.10",
        }
        metadata_json_str = json.dumps(metadata_payload, ensure_ascii=False, indent=2)

        # Create zip in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add raw_text.txt
            zip_file.writestr('raw_text.txt', raw_text)

            # Add preview.txt
            zip_file.writestr('preview.txt', preview_text)

            # Add overview.txt
            zip_file.writestr('overview.txt', overview_cn)

            # Add ai_review.md (read-only; never triggers generation)
            zip_file.writestr('ai_review.md', ai_review_md)

            # Add metadata.json (read-only summary; no API keys/secrets)
            zip_file.writestr('metadata.json', metadata_json_str)

        # Prepare zip for download
        zip_buffer.seek(0)

        # Generate filename
        slug = record.slug or f"prompt_{history_id}"
        filename = f"{slug}_prompt_package.zip"

        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.post("/api/history/{history_id}/regenerate")
async def regenerate_prompt(
    history_id: int,
    request: RegenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Regenerate prompt based on current version and user feedback."""
    try:
        # Get current record
        current_record = PromptHistoryRepository.get_history_record(db, current_user.id, history_id)

        if not current_record:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"History record {history_id} not found"
                }
            )

        # Prepare data for regeneration
        title = current_record.title
        current_raw_text = current_record.prompt_text
        current_overview_cn = current_record.overview_cn or ""
        user_feedback = request.feedback

        # Generate new unique slug
        new_slug = generate_unique_slug(title)
        output_dir = project_root / "outputs" / new_slug

        # Call LLM to regenerate
        try:
            from scripts.llm_topic_enhancer import LLMTopicEnhancer

            enhancer = LLMTopicEnhancer()
            result = enhancer.regenerate_prompt(
                title=title,
                current_raw_text=current_raw_text,
                current_overview_cn=current_overview_cn,
                user_feedback=user_feedback,
                output_folder=output_dir,
                dry_run=False
            )

            if not result:
                return JSONResponse(
                    status_code=500,
                    content={
                        "success": False,
                        "error": "Regenerate returned empty result"
                    }
                )

            # Extract fields from result
            new_raw_text = result.get("raw_text", "")
            new_overview_cn = result.get("overview_cn", "")
            change_summary_cn = result.get("change_summary_cn", "")

            if not new_raw_text:
                return JSONResponse(
                    status_code=500,
                    content={
                        "success": False,
                        "error": "Regenerated raw_text is empty"
                    }
                )

            # Save new raw text to file
            output_dir.mkdir(parents=True, exist_ok=True)
            prompt_file = output_dir / "notebooklm_clean_source.txt"
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(new_raw_text)

            # Save topic.json with overview
            import json
            topic_json_file = output_dir / "topic.json"
            topic_data = {
                "title": title,
                "overview_cn": new_overview_cn,
                "change_summary_cn": change_summary_cn,
                "regenerate_feedback": user_feedback,
                "regenerate_from_history_id": history_id
            }
            with open(topic_json_file, 'w', encoding='utf-8') as f:
                json.dump(topic_data, f, ensure_ascii=False, indent=2)

            # Get current model
            model = os.getenv('AI_VIDEO_LLM_MODEL', 'gpt-5-chat')

            # Create new version in database
            new_record = PromptHistoryRepository.create_regenerated_version(
                db=db,
                user_id=current_user.id,
                from_history_id=history_id,
                feedback=user_feedback,
                new_prompt_text=new_raw_text,
                new_overview_cn=new_overview_cn,
                change_summary_cn=change_summary_cn,
                slug=new_slug,
                output_dir=str(output_dir),
                model=model
            )

            if not new_record:
                return JSONResponse(
                    status_code=500,
                    content={
                        "success": False,
                        "error": "Failed to create new version in database"
                    }
                )

            # Return full new record
            return {
                "success": True,
                "history_id": new_record.id,
                "topic_group_id": new_record.topic_group_id,
                "version_number": new_record.version_number,
                "title": new_record.title,
                "slug": new_record.slug,
                "output_dir": new_record.output_dir,
                "raw_text": new_raw_text,
                "preview_text": None,  # Will be generated dynamically
                "overview_cn": new_overview_cn,
                "change_summary_cn": change_summary_cn,
                "regenerate_feedback": user_feedback,
                "created_at": new_record.created_at.isoformat() if new_record.created_at else None,
                "updated_at": new_record.updated_at.isoformat() if new_record.updated_at else None
            }

        except Exception as llm_error:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": f"LLM regenerate error: {str(llm_error)}"
                }
            )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.get("/api/history/{history_id}/review")
async def get_review(
    history_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Get AI Review for a specific prompt version (read-only, never generates)."""
    try:
        from web.db.repository_review import PromptReviewRepository
        from web.db.models import PromptReview

        # Check if history record exists (and is owned by current user)
        record = PromptHistoryRepository.get_history_record(db, current_user.id, history_id)
        if not record:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"History record {history_id} not found"
                }
            )

        # Get review status
        status = PromptReviewRepository.get_review_status(db, current_user.id, history_id)

        # Handle different statuses
        if status == 'none':
            return {
                "success": True,
                "has_review": False,
                "status": "none",
                "review": None
            }

        if status == 'stale':
            # Try to surface the most recent reviewable content so the
            # frontend can keep showing the old review with a stale banner.
            stale_review_data = None
            try:
                stale_review = db.query(PromptReview).filter(
                    PromptReview.user_id == current_user.id,
                    PromptReview.history_id == history_id,
                ).order_by(PromptReview.updated_at.desc()).all()
                # Prefer the latest review record that actually has parseable JSON
                # with structured fields (not a placeholder/error envelope).
                for candidate in stale_review:
                    if not candidate.review_json:
                        continue
                    try:
                        parsed = json.loads(candidate.review_json)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(parsed, dict) and (
                        parsed.get('rows')
                        or parsed.get('total_score')
                        or parsed.get('overall_review')
                    ):
                        stale_review_data = parsed
                        break
            except Exception:
                stale_review_data = None

            return {
                "success": True,
                "has_review": stale_review_data is not None,
                "status": "stale",
                "review": stale_review_data,
                "message": "The prompt has changed since this review was generated. "
                           "Click Re-review to refresh."
            }

        if status == 'generating':
            return {
                "success": True,
                "has_review": False,
                "status": "generating",
                "review": None,
                "message": "AI Review is currently generating. Please wait..."
            }

        if status == 'failed':
            # Get error message if available
            review = PromptReviewRepository.get_review_by_history_id(db, current_user.id, history_id)
            error_data = None
            if review and review.review_json:
                try:
                    data = json.loads(review.review_json)
                    error_data = data.get('error')
                except:
                    pass

            return {
                "success": True,
                "has_review": False,
                "status": "failed",
                "review": None,
                "error": error_data or "AI Review generation failed. Please try again."
            }

        if status == 'completed':
            # Get review data
            review_data = PromptReviewRepository.get_review_json(db, current_user.id, history_id)

            if review_data:
                return {
                    "success": True,
                    "has_review": True,
                    "status": "completed",
                    "review": review_data
                }
            else:
                # Completed but no data - treat as failed
                return {
                    "success": True,
                    "has_review": False,
                    "status": "failed",
                    "review": None,
                    "error": "Review data is missing"
                }

        # Unknown status
        return {
            "success": True,
            "has_review": False,
            "status": "none",
            "review": None
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Failed to retrieve review status"
            }
        )


@app.get("/api/history/{history_id}/review/debug")
async def get_review_debug(
    history_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Get detailed debug information for AI Review (development/debugging only)."""
    try:
        from web.db.repository_review import PromptReviewRepository

        # Check if history record exists (and is owned by current user)
        record = PromptHistoryRepository.get_history_record(db, current_user.id, history_id)
        if not record:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"History record {history_id} not found"
                }
            )

        # Get review record (if exists)
        review = PromptReviewRepository.get_review_by_history_id(db, current_user.id, history_id)

        # Compute a content fingerprint that helps explain why a review may
        # be stale. This is local-only metadata, not a real schema field.
        prompt_text = record.prompt_text or ''
        try:
            import hashlib
            prompt_text_sha1 = hashlib.sha1(
                prompt_text.encode('utf-8', errors='replace')
            ).hexdigest()
        except Exception:
            prompt_text_sha1 = None

        debug_info = {
            "success": True,
            "history_id": history_id,
            "history_info": {
                "id": record.id,
                "slug": record.slug,
                "title": record.title,
                "topic_group_id": record.topic_group_id,
                "version_number": record.version_number,
                "status": record.status,
                "model": record.model,
                "mode": record.mode,
                "prompt_text_length": len(prompt_text),
                "prompt_text_sha1": prompt_text_sha1,
                "created_at": record.created_at.isoformat() if record.created_at else None,
                "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            }
        }

        if review:
            # Review record exists
            debug_info["review_record"] = {
                "id": review.id,
                "history_id": review.history_id,
                "status": review.status,
                "schema_version": review.review_schema_version,
                "total_score": review.total_score,
                "created_at": review.created_at.isoformat() if review.created_at else None,
                "updated_at": review.updated_at.isoformat() if review.updated_at else None,
            }

            # Parse review JSON
            if review.review_json:
                try:
                    review_data = json.loads(review.review_json)
                    debug_info["review_data"] = review_data
                    debug_info["review_json_length"] = len(review.review_json)
                    # Bubble up an error_message if present in the JSON envelope
                    # (mark_review_failed stores it under the 'error' key).
                    if isinstance(review_data, dict) and review_data.get('error'):
                        debug_info["review_record"]["error_message"] = (
                            review_data.get('error')
                        )
                except Exception as parse_error:
                    debug_info["review_data"] = None
                    debug_info["review_json_raw"] = review.review_json[:1000]
                    debug_info["parse_error"] = str(parse_error)
            else:
                debug_info["review_data"] = None
        else:
            # No review record
            debug_info["review_record"] = None
            debug_info["review_data"] = None
            debug_info["message"] = "No review record found for this history_id"

        return debug_info

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to retrieve review debug info: {str(e)}"
            }
        )


@app.post("/api/history/{history_id}/review")
async def generate_review(
    history_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Generate AI Review for a specific prompt version (idempotent)."""
    try:
        from web.db.repository_review import PromptReviewRepository
        from scripts.llm_topic_enhancer import LLMTopicEnhancer

        current_schema = 'v0.4.6.9_strict'

        # Check if history record exists (and is owned by current user)
        record = PromptHistoryRepository.get_history_record(db, current_user.id, history_id)
        if not record:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": "History record not found"
                }
            )

        # Get raw prompt text
        raw_prompt = record.prompt_text
        if not raw_prompt:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "Prompt text is empty"
                }
            )

        # Get current review status
        status = PromptReviewRepository.get_review_status(db, current_user.id, history_id, current_schema)

        # If review is completed and current, return it directly (idempotent)
        if status == 'completed' and not force:
            review_data = PromptReviewRepository.get_review_json(db, current_user.id, history_id)
            if review_data:
                return {
                    "success": True,
                    "status": "completed",
                    "review": review_data,
                    "cached": True
                }

        # If review is generating, don't start a new one
        if status == 'generating' and not force:
            return {
                "success": True,
                "status": "generating",
                "message": "AI Review is already generating. Please wait..."
            }

        # If review failed and not forcing, return error
        if status == 'failed' and not force:
            review = PromptReviewRepository.get_review_by_history_id(db, current_user.id, history_id)
            error_data = None
            if review and review.review_json:
                try:
                    data = json.loads(review.review_json)
                    error_data = data.get('error')
                except:
                    pass

            return {
                "success": False,
                "status": "failed",
                "error": error_data or "AI Review generation failed. Use force=true to retry."
            }

        # Create or get generating placeholder
        review_obj, is_new = PromptReviewRepository.create_or_get_generating_review(
            db=db,
            user_id=current_user.id,
            history_id=history_id,
            schema_version=current_schema
        )

        # If not new and not forcing, another request is already generating
        if not is_new and not force:
            return {
                "success": True,
                "status": "generating",
                "message": "AI Review is already generating. Please wait..."
            }

        # If forcing or status is stale/none, update to generating
        if force or status in ['stale', 'none', 'failed']:
            PromptReviewRepository.update_review_status(db, current_user.id, history_id, 'generating')

        # Call LLM to generate review
        try:
            enhancer = LLMTopicEnhancer()
            review_data = enhancer.review_prompt(raw_prompt, dry_run=False)

            if not review_data:
                # Mark as failed
                PromptReviewRepository.mark_review_failed(
                    db=db,
                    user_id=current_user.id,
                    history_id=history_id,
                    error_message="Review generation returned empty result"
                )

                return JSONResponse(
                    status_code=500,
                    content={
                        "success": False,
                        "error": "AI Review generation failed. Please try again."
                    }
                )

            # Update review with result
            PromptReviewRepository.update_review_with_result(
                db=db,
                user_id=current_user.id,
                history_id=history_id,
                review_data=review_data,
                schema_version=current_schema
            )

            return {
                "success": True,
                "status": "completed",
                "review": review_data
            }

        except Exception as llm_error:
            # Log real error for debugging
            error_detail = str(llm_error)
            print(f"[AI Review Error - history_id={history_id}] {error_detail}")

            # Mark as failed with real error
            PromptReviewRepository.mark_review_failed(
                db=db,
                user_id=current_user.id,
                history_id=history_id,
                error_message=error_detail,
                schema_version=current_schema
            )

            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "status": "failed",
                    "error": "AI Review generation failed. Please try again.",
                    "debug_error": error_detail
                }
            )

    except Exception as e:
        # Log outer exception with full traceback
        import traceback
        error_detail = str(e)
        print(f"[AI Review Outer Error - history_id={history_id}] {error_detail}")
        print(f"[AI Review Traceback]")
        traceback.print_exc()

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "status": "failed",
                "error": "AI Review generation failed. Please try again.",
                "debug_error": error_detail
            }
        )


# =============================================================================
# Video Mode endpoints (v0.5.1)
# =============================================================================
# All endpoints below operate exclusively on the Video Mode database
# (data/video_history.db) via get_video_db(). They do NOT call any video
# generation provider, do NOT enqueue any video task, and do NOT populate
# real video URLs / mp4 / mov. The video player on the frontend is a UI
# framework only.
# =============================================================================


class VideoGenerateRequest(BaseModel):
    """Request body for Video Mode generation."""
    title: str = Field(..., min_length=1, max_length=200, description="Video topic")
    # v0.6.1: home-page duration selector. Allowed values 5/15/30/60/90;
    # default 15. Off-grid values are accepted (resolve_target_duration_seconds
    # snaps them to the nearest bucket inside the pipeline).
    duration_seconds: Optional[int] = Field(
        default=None, ge=3, le=120,
        description="Target video duration; one of 5/15/30/60/90. Defaults to 15 if omitted."
    )
    # v0.6.3: which generation route to use.
    #   "seedance_video" (default) -> existing v0.6.2 Seedance/APX chain.
    #   "image_video"              -> local Pillow + FFmpeg static-image MVP.
    # Missing or empty falls back to "seedance_video"; any other value 400s.
    generation_method: Optional[str] = Field(
        default="seedance_video",
        max_length=40,
        description="Generation route: 'seedance_video' or 'image_video'.",
    )


class VideoUpdateContentRequest(BaseModel):
    """Request body for updating Video Mode content."""
    view: str = Field(..., pattern='^(raw|preview|overview|web_copy)$')
    content: str = Field(..., min_length=0)


class VideoRegenerateRequest(BaseModel):
    feedback: str = Field(..., min_length=1, max_length=2000)
    # v0.6.1: optional duration override on regenerate; if omitted, the
    # original record's duration is reused.
    duration_seconds: Optional[int] = Field(default=None, ge=3, le=120)


VALID_GENERATION_METHODS = ("seedance_video", "image_video")


def _normalize_generation_method(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """v0.6.3 — normalize the request's generation_method.

    Returns (method, error_message). When ``raw`` is None / empty the method
    defaults to ``seedance_video``. Anything else returns an error string
    that callers should surface as HTTP 400.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "seedance_video", None
    method = str(raw).strip().lower()
    if method not in VALID_GENERATION_METHODS:
        return None, (
            f"generation_method must be one of {VALID_GENERATION_METHODS}; "
            f"got {raw!r}"
        )
    return method, None


def _build_image_video_metadata_json(pipeline_result: Dict[str, Any]) -> str:
    """Serialise the v0.6.3 Image Video pipeline result into VideoHistory.metadata_json.

    Stores the image_video manifest, route flags, has_audio/tts_status, and
    the safe relative paths to the generated assets. Never stores any API
    key (the pipeline never sees one).
    """
    blob = {
        "video_assets_schema_version": "image_video_v0.6.3",
        "generation_method": "image_video",
        "image_video": {
            "version": pipeline_result.get("version"),
            "route_status": pipeline_result.get("route_status"),
            "duration_seconds": pipeline_result.get("duration_seconds"),
            "slide_count": pipeline_result.get("slide_count"),
            "duration_per_slide": pipeline_result.get("duration_per_slide"),
            "subject": pipeline_result.get("subject"),
            "slide_plan_path": pipeline_result.get("slide_plan_path"),
            "overlay_plan_path": pipeline_result.get("overlay_plan_path"),
            "llm_debug_path": pipeline_result.get("llm_debug_path"),
            "llm_slide_content_path": pipeline_result.get("llm_slide_content_path"),
            "overview_cn_path": pipeline_result.get("overview_cn_path"),
            "slides_dir": pipeline_result.get("slides_dir"),
            "concat_path": pipeline_result.get("concat_path"),
            "ffmpeg_command_path": pipeline_result.get("ffmpeg_command_path"),
            "final_video_path": pipeline_result.get("final_video_path"),
            "image_source": pipeline_result.get("image_source"),
            "video_composer": pipeline_result.get("video_composer"),
            "content_source": pipeline_result.get("content_source"),
            "llm_used": bool(pipeline_result.get("llm_used")),
            "llm_model": pipeline_result.get("llm_model"),
            "llm_fallback_used": bool(pipeline_result.get("llm_fallback_used")),
            "llm_fallback_reason": pipeline_result.get("llm_fallback_reason"),
            "video_title_en": pipeline_result.get("video_title_en"),
            "hook_question_en": pipeline_result.get("hook_question_en"),
            "answer_en": pipeline_result.get("answer_en"),
            "bgm_used": bool(pipeline_result.get("bgm_used")),
            "bgm_filename": pipeline_result.get("bgm_filename"),
            "bgm_display_name": pipeline_result.get("bgm_display_name"),
            "bgm_mood_keywords": pipeline_result.get("bgm_mood_keywords") or [],
            "bgm_volume_db": pipeline_result.get("bgm_volume_db"),
            "bgm_chosen_by_llm": bool(pipeline_result.get("bgm_chosen_by_llm")),
            "bgm_llm_why": pipeline_result.get("bgm_llm_why"),
            "bgm_disabled_by_env": bool(pipeline_result.get("bgm_disabled_by_env")),
            "bgm_fallback_used": bool(pipeline_result.get("bgm_fallback_used")),
            "bgm_fallback_reason": pipeline_result.get("bgm_fallback_reason"),
            # v0.6.8.4 — pass through real TTS metadata. Image Video has
            # actually shipped edge-tts narration since v0.6.7; the
            # previous hardcoded "not implemented" + has_audio=bgm-only
            # made the UI lie about generated videos.
            "has_audio": bool(
                pipeline_result.get("has_audio")
                or pipeline_result.get("bgm_used")
            ),
            "tts_status": pipeline_result.get("tts_status") or "unknown",
            "voiceover_source": pipeline_result.get("voiceover_source") or "none",
        },
        # v0.6.3 stabilization + v0.6.4 — distinguish content LLM (text)
        # from media APIs (Image2 / Seedance / APX / TTS). The image_video
        # route never calls Seedance/APX; it MAY call image2 in v0.6.4
        # when APX_IMAGE2_ENABLED=true and edge-tts since v0.6.7.
        # `media_api_called` flips true only for media providers;
        # `network_call_performed` is preserved as the broader signal
        # that any external network call happened (image2 OR LLM).
        # `llm_network_call_performed` is the LLM-only subset.
        "external_api_called": bool(pipeline_result.get("external_api_called")),
        "content_llm_called": bool(pipeline_result.get("content_llm_called")),
        "media_api_called": bool(pipeline_result.get("media_api_called")),
        "llm_network_call_performed": bool(pipeline_result.get("content_llm_called")),
        "seedance_called": False,
        "apx_called": False,
        "image2_called": bool(pipeline_result.get("image2_called")),
        "image2_succeeded": int(pipeline_result.get("image2_succeeded") or 0),
        "image2_failed": int(pipeline_result.get("image2_failed") or 0),
        "image2_requested": int(pipeline_result.get("image2_requested") or 0),
        "tts_called": bool(pipeline_result.get("tts_called")),
        "llm_used": bool(pipeline_result.get("llm_used")),
        "real_video_generated": pipeline_result.get("route_status") == "succeeded",
        "real_video_downloaded": False,
        "network_call_performed": bool(
            pipeline_result.get("media_api_called")
            or pipeline_result.get("content_llm_called")
        ),
        "provider_status": "image_video_local",
    }
    try:
        return json.dumps(blob, ensure_ascii=False)
    except Exception:
        return json.dumps({
            "video_assets_schema_version": "image_video_v0.6.3",
            "generation_method": "image_video",
            "serialisation_error": True,
        }, ensure_ascii=False)


def _describe_audio_status(
    tts_status: Optional[str],
    voiceover_source: Optional[str],
    has_audio: Optional[bool],
) -> str:
    """v0.6.8.4 — render the human-readable audio/旁白 line for the
    Overview metadata block. Reflects real TTS state instead of the
    old hardcoded "not_implemented" line."""
    src = (voiceover_source or "none").lower()
    status = (tts_status or "").lower()
    if status == "succeeded" and src and src != "none":
        provider_label = {
            "edge_tts": "edge-tts",
            "elevenlabs": "ElevenLabs",
        }.get(src, src)
        return f"已生成（has_audio=true, voiceover={provider_label}, tts_status={status}）"
    if has_audio:
        return f"仅背景音乐（has_audio=true, tts_status={status or 'unknown'}）"
    if status in ("tts_failed", "import_failed"):
        return f"未生成（tts_status={status}）"
    return f"未生成（has_audio=false, tts_status={status or 'unknown'}）"


def _build_image_video_overview_text(
    title: str, duration_seconds: int, slide_count: int, route_status: str,
    llm_overview_cn: Optional[str] = None,
    image2_succeeded: int = 0, image2_failed: int = 0, image2_requested: int = 0,
    tts_status: Optional[str] = None,
    voiceover_source: Optional[str] = None,
    has_audio: Optional[bool] = None,
) -> str:
    """Build the Overview-tab text for image_video records.

    v0.6.4 — the metadata footer reflects whether image2 actually ran:
    when image2 returned at least one image, the footer says
    "gpt-image-2 + Pillow 文字叠加"; when image2 was disabled or fell
    back per slide, it says "本地 Pillow" so the user knows what the
    underlying image source was.
    """
    status_label = "已生成" if route_status == "succeeded" else "未生成"
    if image2_succeeded > 0:
        if image2_failed > 0:
            image_source_label = (
                f"gpt-image-2（{image2_succeeded}/{image2_requested} 成功）"
                f" + Pillow 文字叠加；{image2_failed} 张回退到本地几何图"
            )
        else:
            image_source_label = (
                f"gpt-image-2（{image2_succeeded}/{image2_requested} 成功）"
                f" + Pillow 文字叠加"
            )
        image2_called_label = "是"
    else:
        image_source_label = "本地 Pillow 渲染（image2 未启用或全部失败）"
        image2_called_label = "否"
    metadata_block = (
        f"\n---\n"
        f"题目: {title}\n"
        f"生成路线: Image Video\n"
        f"视频时长: {duration_seconds} 秒\n"
        f"幻灯片数: {slide_count} 张\n"
        f"画面来源: {image_source_label}\n"
        f"合成方式: 本地 FFmpeg\n"
        f"文案来源: {'LLM (gpt-5-chat)' if llm_overview_cn else '本地静态模板（LLM 未启用或失败）'}\n"
        f"音频/旁白: {_describe_audio_status(tts_status, voiceover_source, has_audio)}\n"
        f"是否调用 Seedance: 否\n"
        f"是否调用 APX: 否\n"
        f"是否调用 Image2: {image2_called_label}\n"
        f"最终视频文件: {status_label}"
    )
    if llm_overview_cn and llm_overview_cn.strip():
        return f"【本视频内容简介】\n\n{llm_overview_cn.strip()}\n{metadata_block}"
    fallback_paragraph = (
        f"【本视频内容简介】\n\n"
        f"本视频以「{title}」为主题，使用本地静态图 + FFmpeg 合成 "
        f"{slide_count} 张幻灯片，时长 {duration_seconds} 秒。"
        f"由于本次 AI_VIDEO_LLM_* 未配置或调用失败，每张幻灯片的英文文案"
        f"使用了通用静态模板，可能与题目细节不完全对齐；如需贴合题目，"
        f"请在 .env 中配置 AI_VIDEO_LLM_API_KEY 后重新生成。"
    )
    return f"{fallback_paragraph}\n{metadata_block}"


def _build_image_video_preview_text(slide_plan: Dict[str, Any]) -> str:
    """v0.6.3 — human-readable summary of the slide plan for the Preview tab.

    Acts as a friendly index of the Raw Text (which now holds the full
    image-generation prompts). Each slide gets: index / role / start-end /
    title / caption / visual focus.
    """
    if not slide_plan:
        return ""
    out = [
        "[Image Video MVP - Slide Plan]",
        "Raw Text contains the detailed image-generation prompts that will",
        "be sent to the image2 provider in v0.6.4.",
        "",
    ]
    for slide in slide_plan.get("slides", []):
        out.append(
            f"#{slide.get('index'):>2}  "
            f"{slide.get('role'):<14}  "
            f"{slide.get('start')}s-{slide.get('end')}s  "
            f"| {slide.get('title')}"
        )
        cap = slide.get("caption") or ""
        if cap:
            out.append(f"      caption  : {cap}")
        vf = slide.get("visual_focus") or ""
        if vf:
            out.append(f"      visual   : {vf}")
    return "\n".join(out)


def _build_image_video_raw_text(
    slide_plan: Dict[str, Any], llm_content: Optional[Dict[str, Any]] = None,
) -> str:
    """v0.6.3 — Raw Text holds the per-slide image-generation prompts.

    These are the strings that will be sent verbatim to the image2 provider
    in v0.6.4. Today they are only consumed by the local Pillow renderer,
    but persisting them now means upgrading to a real image generator is
    a one-line provider swap.
    """
    if not slide_plan:
        return ""
    lines: List[str] = ["# Image Video — image generation prompts (v0.6.3)"]
    title_en = (llm_content or {}).get("video_title_en") or slide_plan.get(
        "video_title_en"
    ) or ""
    if title_en:
        lines.append(f"# Working title: {title_en}")
    answer_en = (llm_content or {}).get("answer_en") or ""
    if answer_en:
        lines.append(f"# One-line answer: {answer_en}")
    lines.append("# Each block below is one slide. The prompt body is what")
    lines.append("# will be sent to the image2 model in v0.6.4 (today: local")
    lines.append("# Pillow renderer reads it as a hint).")
    lines.append("")
    for slide in slide_plan.get("slides", []):
        lines.append(
            f"## Slide {slide.get('index'):02d}  ·  {slide.get('role')}  "
            f"·  {slide.get('start')}s–{slide.get('end')}s"
        )
        title = slide.get("title") or ""
        caption = slide.get("caption") or ""
        if title:
            lines.append(f"on-screen title: {title}")
        if caption:
            lines.append(f"on-screen caption: {caption}")
        vf = slide.get("visual_focus") or ""
        if vf:
            lines.append(f"visual focus: {vf}")
        ip = slide.get("image_prompt") or ""
        if ip:
            lines.append("image_prompt:")
            lines.append(ip)
        else:
            lines.append("image_prompt: (LLM did not supply one; using local "
                         "Pillow template instead.)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _safe_relative_outputs_path(path_str: Optional[str]) -> Optional[str]:
    """Return a path relative to ``project_root/outputs`` if ``path_str`` is
    inside that directory, otherwise None. Used to keep absolute machine
    paths out of the database / API responses.
    """
    if not path_str:
        return None
    try:
        candidate = Path(path_str).resolve()
        outputs_root = (project_root / "outputs").resolve()
        rel = candidate.relative_to(outputs_root)
        return f"outputs/{rel.as_posix()}"
    except Exception:
        return None


def _run_image_video_pipeline(
    db: Session,
    user_id: int,
    title: str,
    slug: str,
    duration_seconds: int,
    output_dir: Path,
    history_id: Optional[int] = None,
) -> Dict[str, Any]:
    """v0.6.3 — invoke the local Image Video pipeline and persist the result
    onto an existing VideoHistory record. Returns the pipeline result dict
    augmented with a ``relative_video_path`` key when an mp4 was produced.

    Never calls APX, Seedance, Image2, or TTS.
    """
    from web.image_video_pipeline import generate_image_video_package

    pipeline_result = generate_image_video_package(
        title=title,
        duration_seconds=duration_seconds,
        output_dir=str(output_dir),
        slug=slug,
    )

    final_video_path = pipeline_result.get("final_video_path")
    relative_video_path = _safe_relative_outputs_path(final_video_path)
    pipeline_result["relative_video_path"] = relative_video_path

    if history_id is None:
        return pipeline_result

    llm_overview_cn = pipeline_result.get("overview_cn") or ""
    if pipeline_result.get("route_status") == "succeeded":
        slide_plan_path = pipeline_result.get("slide_plan_path")
        slide_plan: Dict[str, Any] = {}
        if slide_plan_path and Path(slide_plan_path).exists():
            try:
                slide_plan = json.loads(Path(slide_plan_path).read_text(encoding="utf-8"))
            except Exception:
                slide_plan = {}
        # v0.6.3 update — Raw Text holds the per-slide image-generation
        # prompts (sent to image2 in v0.6.4). Preview is a human-readable
        # index summarising those prompts. Overview is the Chinese
        # paragraph from gpt-5-chat.
        llm_content_for_text: Optional[Dict[str, Any]] = None
        llm_content_path = pipeline_result.get("llm_slide_content_path")
        if llm_content_path and Path(llm_content_path).exists():
            try:
                llm_content_for_text = json.loads(
                    Path(llm_content_path).read_text(encoding="utf-8")
                )
            except Exception:
                llm_content_for_text = None
        raw_text = _build_image_video_raw_text(slide_plan, llm_content_for_text)
        preview_text = _build_image_video_preview_text(slide_plan)
        overview_text = _build_image_video_overview_text(
            title=title,
            duration_seconds=duration_seconds,
            slide_count=int(pipeline_result.get("slide_count") or 0),
            route_status="succeeded",
            llm_overview_cn=llm_overview_cn,
            image2_succeeded=int(pipeline_result.get("image2_succeeded") or 0),
            image2_failed=int(pipeline_result.get("image2_failed") or 0),
            image2_requested=int(pipeline_result.get("image2_requested") or 0),
            tts_status=pipeline_result.get("tts_status"),
            voiceover_source=pipeline_result.get("voiceover_source"),
            has_audio=bool(
                pipeline_result.get("has_audio")
                or pipeline_result.get("bgm_used")
            ),
        )
        VideoHistoryRepository.update_image_video_result(
            db=db,
            user_id=user_id,
            history_id=history_id,
            video_file_path=relative_video_path,
            video_duration_seconds=int(duration_seconds),
            video_status="ready",
            metadata_json=_build_image_video_metadata_json(pipeline_result),
            preview_text=preview_text,
            overview_cn=overview_text,
            prompt_text=raw_text,
        )
    else:
        # Failure path — still record the metadata so the operator can see
        # why the pipeline didn't produce final_video.mp4.
        overview_text = _build_image_video_overview_text(
            title=title,
            duration_seconds=duration_seconds,
            slide_count=int(pipeline_result.get("slide_count") or 0),
            route_status="failed",
            llm_overview_cn=llm_overview_cn,
            image2_succeeded=int(pipeline_result.get("image2_succeeded") or 0),
            image2_failed=int(pipeline_result.get("image2_failed") or 0),
            image2_requested=int(pipeline_result.get("image2_requested") or 0),
            tts_status=pipeline_result.get("tts_status"),
            voiceover_source=pipeline_result.get("voiceover_source"),
            has_audio=bool(
                pipeline_result.get("has_audio")
                or pipeline_result.get("bgm_used")
            ),
        )
        VideoHistoryRepository.update_image_video_result(
            db=db,
            user_id=user_id,
            history_id=history_id,
            video_file_path=None,
            video_duration_seconds=int(duration_seconds),
            video_status="failed",
            metadata_json=_build_image_video_metadata_json(pipeline_result),
            preview_text=overview_text,
            overview_cn=overview_text,
            prompt_text=overview_text,
        )

    return pipeline_result


def _build_image_video_response_payload(
    record: "VideoHistory",
    pipeline_result: Dict[str, Any],
    title: str,
    duration_seconds: int,
) -> Dict[str, Any]:
    """Shape the JSON payload the frontend receives for an image_video run."""
    relative_video_path = pipeline_result.get("relative_video_path")
    route_status = pipeline_result.get("route_status")
    error = pipeline_result.get("error")
    success = route_status == "succeeded"
    return {
        "success": success,
        "id": record.id,
        "history_id": record.id,
        "title": title,
        "slug": record.slug,
        "topic_group_id": record.topic_group_id,
        "version_number": record.version_number,
        "prompt": record.prompt_text,
        "raw_text": record.prompt_text,
        "prompt_text": record.prompt_text,
        "preview_text": record.preview_text,
        "overview_cn": record.overview_cn,
        "video_status": record.video_status,
        "video_file_path": record.video_file_path,
        "video_duration_seconds": record.video_duration_seconds,
        "generation_method": "image_video",
        "generation_method_label": "Image Video",
        "route_status": route_status,
        "image_video_route_status": route_status,
        "error": error,
        "image_video": {
            "duration_seconds": duration_seconds,
            "slide_count": pipeline_result.get("slide_count"),
            "duration_per_slide": pipeline_result.get("duration_per_slide"),
            "slide_plan_path": pipeline_result.get("slide_plan_path"),
            "overlay_plan_path": pipeline_result.get("overlay_plan_path"),
            "slides_dir": pipeline_result.get("slides_dir"),
            "ffmpeg_command_path": pipeline_result.get("ffmpeg_command_path"),
            "concat_path": pipeline_result.get("concat_path"),
            "final_video_path": relative_video_path,
            "video_composer": pipeline_result.get("video_composer"),
            "ffmpeg_found": bool(pipeline_result.get("ffmpeg_found")),
            "ffmpeg_path": pipeline_result.get("ffmpeg_path"),
            "image_source": pipeline_result.get("image_source"),
            "image_sources": pipeline_result.get("image_sources") or [],
            "content_source": pipeline_result.get("content_source"),
            "content_llm_called": bool(pipeline_result.get("content_llm_called")),
            "media_api_called": bool(pipeline_result.get("media_api_called")),
            "image2_called": bool(pipeline_result.get("image2_called")),
            "image2_succeeded": int(pipeline_result.get("image2_succeeded") or 0),
            "image2_failed": int(pipeline_result.get("image2_failed") or 0),
            "image2_requested": int(pipeline_result.get("image2_requested") or 0),
            "image2_disabled_by_env": bool(
                pipeline_result.get("image2_disabled_by_env")
            ),
            "image2_skipped_reason": pipeline_result.get("image2_skipped_reason"),
            "image2_debug_path": pipeline_result.get("image2_debug_path"),
            "llm_used": bool(pipeline_result.get("llm_used")),
            "llm_model": pipeline_result.get("llm_model"),
            "llm_fallback_used": bool(pipeline_result.get("llm_fallback_used")),
            "llm_fallback_reason": pipeline_result.get("llm_fallback_reason"),
            "video_title_en": pipeline_result.get("video_title_en"),
            "hook_question_en": pipeline_result.get("hook_question_en"),
            "answer_en": pipeline_result.get("answer_en"),
            "overview_cn": pipeline_result.get("overview_cn"),
            "bgm_used": bool(pipeline_result.get("bgm_used")),
            "bgm_filename": pipeline_result.get("bgm_filename"),
            "bgm_display_name": pipeline_result.get("bgm_display_name"),
            "bgm_mood_keywords": pipeline_result.get("bgm_mood_keywords") or [],
            "bgm_volume_db": pipeline_result.get("bgm_volume_db"),
            "bgm_chosen_by_llm": bool(pipeline_result.get("bgm_chosen_by_llm")),
            "bgm_llm_why": pipeline_result.get("bgm_llm_why"),
            "bgm_disabled_by_env": bool(pipeline_result.get("bgm_disabled_by_env")),
            "bgm_fallback_used": bool(pipeline_result.get("bgm_fallback_used")),
            "bgm_fallback_reason": pipeline_result.get("bgm_fallback_reason"),
            # v0.6.8.4 — pass real TTS metadata through to the response,
            # so the frontend Generation Evidence panel can show
            # "voiceover=edge_tts" instead of the old "not implemented".
            "has_audio": bool(
                pipeline_result.get("has_audio")
                or pipeline_result.get("bgm_used")
            ),
            "tts_status": pipeline_result.get("tts_status") or "unknown",
            "voiceover_source": pipeline_result.get("voiceover_source") or "none",
        },
        "generation_evidence": {
            "route": "image_video",
            "media_api_called": bool(pipeline_result.get("media_api_called")),
            "content_llm_called": bool(pipeline_result.get("content_llm_called")),
            "real_api_call": bool(pipeline_result.get("media_api_called")),
            "seedance_called": False,
            "apx_called": False,
            "image2_called": bool(pipeline_result.get("image2_called")),
            "image2_succeeded": int(pipeline_result.get("image2_succeeded") or 0),
            "image2_failed": int(pipeline_result.get("image2_failed") or 0),
            "image2_requested": int(pipeline_result.get("image2_requested") or 0),
            "tts_called": bool(pipeline_result.get("tts_called")),
            "tts_status": pipeline_result.get("tts_status") or "unknown",
            "voiceover_source": pipeline_result.get("voiceover_source") or "none",
            "has_audio": bool(
                pipeline_result.get("has_audio")
                or pipeline_result.get("bgm_used")
            ),
            "bgm_used": bool(pipeline_result.get("bgm_used")),
            "bgm_display_name": pipeline_result.get("bgm_display_name"),
            "bgm_volume_db": pipeline_result.get("bgm_volume_db"),
            "llm_used_for_text": bool(pipeline_result.get("llm_used")),
            "llm_model": pipeline_result.get("llm_model"),
            "local_slides_generated": True,
            "ffmpeg_composed": success,
            "final_video_available": bool(relative_video_path) and success,
        },
        "item": record.to_dict(include_prompt=True),
    }


def _build_video_assets_metadata_json(pipeline_result: Dict[str, Any]) -> str:
    """Serialise the v0.5.4 Seedance asset pipeline result into a compact
    JSON string suitable for ``VideoHistory.metadata_json``. Stores schema
    version, asset manifest, asset paths, warnings, llm_used / fallback_used
    flags, and provider status — never the API key, never any secret.

    v0.6.3 stabilization hotfix — restored as a top-level function. An
    earlier refactor accidentally left the function body inside
    ``_build_image_video_response_payload`` after the return statement, so
    every Seedance Video run was hitting NameError at the three call sites.
    """
    manifest = pipeline_result.get('asset_manifest') or {}
    contract_validation = pipeline_result.get('provider_contract_validation') or {}
    asset_paths = pipeline_result.get('asset_paths') or {}
    blob = {
        'video_assets_schema_version': pipeline_result.get('schema_version', VIDEO_ASSETS_SCHEMA_VERSION),
        'provider_contract_schema_version': manifest.get('provider_contract_schema_version', 'seedance_contract_v0.5.5'),
        'seedance_prompt_compiler_version': manifest.get(
            'seedance_prompt_compiler_version',
            pipeline_result.get('seedance_prompt_compiler_version'),
        ),
        'seedance_prompt_profile_version': manifest.get(
            'seedance_prompt_profile_version',
            pipeline_result.get('seedance_prompt_profile_version'),
        ),
        'seedance_contract_ready': bool(contract_validation.get('valid')) if contract_validation else False,
        'provider_contract_validation_valid': bool(contract_validation.get('valid')) if contract_validation else False,
        'seedance_prompt_ready': bool(
            manifest.get('seedance_prompt_ready', pipeline_result.get('seedance_prompt_ready', False))
        ),
        'seedance_payload_preview_path': asset_paths.get('seedance_payload_preview'),
        'provider_contract_validation_path': asset_paths.get('provider_contract_validation'),
        'provider_lifecycle_preview_path': asset_paths.get('provider_lifecycle_preview'),
        'seedance_prompt_path': asset_paths.get('seedance_prompt'),
        'seedance_negative_prompt_path': asset_paths.get('seedance_negative_prompt'),
        'seedance_prompt_debug_path': asset_paths.get('seedance_prompt_debug'),
        'prompt_source_for_seedance_payload': manifest.get(
            'prompt_source_for_seedance_payload',
            'video_assets/seedance_prompt.txt'
            if manifest.get('seedance_prompt_ready')
            else 'video_assets/provider_prompt.txt',
        ),
        'asset_manifest': manifest,
        'asset_paths': asset_paths,
        'warnings': pipeline_result.get('warnings', []),
        'llm_used': bool(pipeline_result.get('llm_used', False)),
        'fallback_used': not bool(pipeline_result.get('llm_used', False)),
        'provider_status': 'provider_not_configured',
        'real_video_generated': False,
        'real_video_downloaded': False,
        'network_call_performed': False,
    }
    try:
        return json.dumps(blob, ensure_ascii=False)
    except Exception:
        return json.dumps({
            'video_assets_schema_version': VIDEO_ASSETS_SCHEMA_VERSION,
            'provider_status': 'provider_not_configured',
            'real_video_generated': False,
            'serialisation_error': True,
        }, ensure_ascii=False)


def _create_mock_video_job_for_record(
    db: Session,
    user_id: int,
    record: VideoHistory,
    request_title: str,
) -> Optional[Dict[str, Any]]:
    """v0.5.3: create a Mock VideoJob for a freshly-saved Video Mode record
    and return its `to_dict()` payload. Returns None on failure.

    v0.6.8: the job is owned by ``user_id`` (caller must pass the
    authenticated user's id; the helper does not derive it).
    """
    try:
        provider = MockVideoProvider()
        request_payload = {
            "history_id": record.id,
            "title": request_title,
            "slug": record.slug,
            "mode": record.mode,
            "model": record.model,
        }
        response_payload = provider.submit(request_payload)

        # v0.6.0 duration sync: read target duration from the asset bundle so
        # the Mock job's duration_seconds matches the manifest the operator
        # already saw on disk.
        try:
            mock_assets = _load_apx_assets_for_record(record)
            mock_manifest = mock_assets.get("manifest") if isinstance(mock_assets, dict) else None
            mock_target = (
                mock_manifest.get("target_duration_seconds")
                if isinstance(mock_manifest, dict) else None
            )
            mock_duration: Optional[int] = (
                int(mock_target) if isinstance(mock_target, (int, float)) else None
            )
        except Exception:
            mock_duration = None

        now = datetime.utcnow()
        job = VideoJobRepository.create_job(
            db=db,
            user_id=user_id,
            history_id=record.id,
            provider=provider.provider_name,
            provider_job_id=response_payload.get("provider_job_id"),
            status=response_payload.get("status", "provider_not_configured"),
            stage=response_payload.get("stage", "provider_not_connected"),
            progress=int(response_payload.get("progress") or 0),
            request_payload=request_payload,
            response_payload=response_payload,
            error_message=None,
            submitted_at=now,
            completed_at=now,
            duration_seconds=mock_duration,
        )
        # v0.6.0 duration sync: keep VideoHistory.video_duration_seconds in
        # line with the manifest target so the Mock and APX paths look
        # identical in the operator UI.
        try:
            if mock_duration is not None and record.video_duration_seconds != mock_duration:
                record.video_duration_seconds = mock_duration
                db.add(record)
                db.commit()
                db.refresh(record)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

        # v0.5.3: sync VideoHistory.video_status with the freshly-created job so
        # the record no longer reads `not_generated` once a Mock job exists.
        # Mapping is intentionally minimal (no full state machine in v0.5.3).
        try:
            mapped = _map_job_status_to_video_status(job.status)
            if mapped and record.video_status != mapped:
                record.video_status = mapped
                db.add(record)
                db.commit()
                db.refresh(record)
        except Exception as sync_exc:
            print(f"[Video Mode] Warning: failed to sync video_status: {sync_exc}")
            try:
                db.rollback()
            except Exception:
                pass
        return job.to_dict()
    except Exception as exc:
        print(f"[Video Mode] Warning: failed to create Mock VideoJob: {exc}")
        return None


def _map_job_status_to_video_status(job_status: Optional[str]) -> Optional[str]:
    """v0.5.3 → v0.6.0: map VideoJob.status to VideoHistory.video_status.

    v0.6.0 adds the APX states: submitted / pending / running / succeeded /
    blocked_fallback_prompt / succeeded_but_no_video_url. The mapping keeps
    the Video Mode UI in sync with the latest job state.
    """
    if not job_status:
        return None
    if job_status == "provider_not_configured":
        return "provider_not_configured"
    if job_status == "succeeded":
        return "ready"
    if job_status == "failed":
        return "failed"
    if job_status == "cancelled":
        return "cancelled"
    if job_status in ("submitted", "pending", "running"):
        return job_status
    if job_status == "blocked_fallback_prompt":
        return "blocked_fallback_prompt"
    if job_status == "blocked_prompt_quality":
        return "blocked_prompt_quality"
    if job_status == "succeeded_but_no_video_url":
        return "succeeded_but_no_video_url"
    return None


def _load_apx_assets_for_record(record: VideoHistory) -> Dict[str, Any]:
    """Load seedance_prompt.txt + manifest + payload preview + prompt debug
    from ``outputs/<slug>/video_assets/``. All values default to empty so the
    APX provider's fallback safety check still runs even when files are
    missing (it will block in that case).
    """
    output_dir = record.output_dir or ""
    base = Path(output_dir)
    if not base.is_absolute():
        base = project_root / base
    assets_dir = base / "video_assets"

    seedance_prompt = ""
    manifest: Dict[str, Any] = {}
    payload_preview: Dict[str, Any] = {}
    prompt_debug: Dict[str, Any] = {}

    try:
        sp = assets_dir / "seedance_prompt.txt"
        if sp.exists():
            with open(sp, "r", encoding="utf-8") as f:
                seedance_prompt = f.read()
    except Exception:
        seedance_prompt = ""

    def _safe_json(p: Path) -> Dict[str, Any]:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    manifest = _safe_json(assets_dir / "generation_manifest.json")
    payload_preview = _safe_json(assets_dir / "seedance_payload_preview.json")
    prompt_debug = _safe_json(assets_dir / "seedance_prompt_debug.json")

    return {
        "output_dir": str(base),
        "assets_dir": str(assets_dir),
        "seedance_prompt": seedance_prompt,
        "manifest": manifest,
        "payload_preview": payload_preview,
        "prompt_debug": prompt_debug,
    }


def _create_apx_video_job_for_record(
    db: Session,
    user_id: int,
    record: VideoHistory,
    request_title: str,
) -> Optional[Dict[str, Any]]:
    """v0.6.0: create an APX Seedance VideoJob for a freshly-saved record.

    Returns ``None`` when the APX provider is not configured (caller should
    fall back to ``_create_mock_video_job_for_record``). Otherwise calls
    ``check_fallback_safety`` and either persists a ``blocked_fallback_prompt``
    job (refusing to burn credits on placeholder content) or calls
    ``ApxSeedanceProvider.submit`` and persists a ``submitted`` job. The API
    key is never written into request_json / response_json — the provider
    redacts before returning.
    """
    try:
        provider = ApxSeedanceProvider()
        if not provider.is_configured():
            return None

        assets = _load_apx_assets_for_record(record)
        seedance_prompt = assets["seedance_prompt"]
        manifest = assets["manifest"]
        prompt_debug = assets["prompt_debug"]

        # v0.6.0 duration sync: read target duration from manifest first, then
        # prompt_debug.prompt_metrics, then provider config (APX_VIDEO_DURATION).
        target_duration_seconds: Optional[int] = None
        try:
            mtd = manifest.get("target_duration_seconds") if isinstance(manifest, dict) else None
            if isinstance(mtd, (int, float)):
                target_duration_seconds = int(mtd)
        except Exception:
            target_duration_seconds = None
        if target_duration_seconds is None and isinstance(prompt_debug, dict):
            pm = prompt_debug.get("prompt_metrics")
            if isinstance(pm, dict):
                pmd = pm.get("duration_seconds")
                if isinstance(pmd, (int, float)):
                    try:
                        target_duration_seconds = int(pmd)
                    except Exception:
                        pass
        if target_duration_seconds is None:
            try:
                target_duration_seconds = int(provider.public_config().get("duration") or 15)
            except Exception:
                target_duration_seconds = 15

        allowed, reason = provider.check_fallback_safety(
            manifest=manifest,
            prompt_debug=prompt_debug,
            seedance_prompt=seedance_prompt,
        )

        # v0.6.2 — Final-prompt quality gate. This runs even when the
        # legacy fallback-safety check is happy: the gate inspects the
        # actual prompt the runtime is about to ship to APX (CJK,
        # ``this topic`` / ``A`` / ``AB`` / ``BAB`` / ``does not yet
        # generate audio``, missing 16:9 / single-narrator wording, empty
        # english_subject / english_question / correct_answer /
        # narration / scene_plan / on-screen-text). If anything fails,
        # APX submit is blocked. The ``APX_VIDEO_ALLOW_FALLBACK_SUBMIT``
        # override skips this only via ``check_fallback_safety``; the
        # quality gate itself is always evaluated and recorded so the
        # Provider Evidence panel can surface why a submit was refused.
        normalized_input_for_gate: Dict[str, Any] = {}
        if isinstance(prompt_debug, dict):
            normalized_input_for_gate = (
                prompt_debug.get("normalized_input")
                or (prompt_debug.get("prompt_quality") or {}).get("normalized_input")
                or {}
            )
        quality_passed, quality_reasons, quality_rules = _validate_seedance_prompt_quality(
            seedance_prompt,
            compiled_payload={"normalized_input": normalized_input_for_gate},
            duration_seconds=target_duration_seconds,
        )

        now = datetime.utcnow()

        if quality_passed is False and not provider.public_config().get("allow_fallback_submit"):
            quality_reason_text = "; ".join(quality_reasons) or "Prompt quality check failed."
            blocked_response = {
                "provider": provider.provider_name,
                "status": "blocked_prompt_quality",
                "stage": "blocked_before_submit",
                "progress": 0,
                "network_call_performed": False,
                "real_video_generated": False,
                "real_video_downloaded": False,
                "block_reason": quality_reason_text,
                "prompt_quality": {
                    "passed": False,
                    "reasons": quality_reasons,
                    "rules": quality_rules,
                },
                "message": (
                    "Real APX submit refused because the compiled Seedance prompt "
                    "did not pass the v0.6.2 prompt-quality gate."
                ),
            }
            request_payload = {
                "history_id": record.id,
                "title": request_title,
                "slug": record.slug,
                "mode": record.mode,
                "model": provider.public_config().get("model"),
                "block_reason": quality_reason_text,
                "prompt_quality_failed": True,
            }
            job = VideoJobRepository.create_job(
                db=db,
                user_id=user_id,
                history_id=record.id,
                provider=provider.provider_name,
                provider_job_id=None,
                status="blocked_prompt_quality",
                stage="blocked_before_submit",
                progress=0,
                request_payload=request_payload,
                response_payload=blocked_response,
                error_message=quality_reason_text,
                submitted_at=now,
                completed_at=now,
                duration_seconds=target_duration_seconds,
            )
            try:
                if record.video_status != "blocked_prompt_quality":
                    record.video_status = "blocked_prompt_quality"
                    db.add(record)
                    db.commit()
                    db.refresh(record)
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
            return job.to_dict()

        if not allowed:
            blocked_response = {
                "provider": provider.provider_name,
                "status": "blocked_fallback_prompt",
                "stage": "blocked_before_submit",
                "progress": 0,
                "network_call_performed": False,
                "real_video_generated": False,
                "real_video_downloaded": False,
                "block_reason": reason,
                "message": (
                    "Real APX submit refused because the compiled assets look "
                    "like a fallback. Set APX_VIDEO_ALLOW_FALLBACK_SUBMIT=true "
                    "to override."
                ),
            }
            request_payload = {
                "history_id": record.id,
                "title": request_title,
                "slug": record.slug,
                "mode": record.mode,
                "model": provider.public_config().get("model"),
                "block_reason": reason,
            }
            job = VideoJobRepository.create_job(
                db=db,
                user_id=user_id,
                history_id=record.id,
                provider=provider.provider_name,
                provider_job_id=None,
                status="blocked_fallback_prompt",
                stage="blocked_before_submit",
                progress=0,
                request_payload=request_payload,
                response_payload=blocked_response,
                error_message=reason,
                submitted_at=now,
                completed_at=now,
                duration_seconds=target_duration_seconds,
            )
            try:
                if record.video_status != "blocked_fallback_prompt":
                    record.video_status = "blocked_fallback_prompt"
                    db.add(record)
                    db.commit()
                    db.refresh(record)
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
            return job.to_dict()

        # Allowed: real submit. Pass the target duration explicitly so the
        # APX submit payload matches the asset bundle (no drift).
        submit_result = provider.submit(seedance_prompt, duration_seconds=target_duration_seconds)
        # Build the request_payload snapshot (sanitized).
        request_payload = {
            "history_id": record.id,
            "title": request_title,
            "slug": record.slug,
            "mode": record.mode,
            "submit_payload": _apx_scrub_api_key(submit_result.get("request") or {}),
            "endpoint": "POST /v1/async/chat",
        }
        response_payload = {
            **{k: v for k, v in submit_result.items() if k != "request"},
        }
        # Defensive: the provider already redacts — apply again to be sure.
        response_payload = _apx_scrub_api_key(response_payload)

        status_value = submit_result.get("status") or "submitted"
        stage_value = submit_result.get("stage") or "submitted"
        progress_value = int(submit_result.get("progress") or 10)

        job = VideoJobRepository.create_job(
            db=db,
            user_id=user_id,
            history_id=record.id,
            provider=provider.provider_name,
            provider_job_id=submit_result.get("provider_job_id"),
            status=status_value,
            stage=stage_value,
            progress=progress_value,
            request_payload=request_payload,
            response_payload=response_payload,
            error_message=(
                submit_result.get("message") if status_value == "failed" else None
            ),
            submitted_at=now,
            completed_at=now if status_value == "failed" else None,
            duration_seconds=target_duration_seconds,
        )

        # v0.6.0 duration sync: keep VideoHistory.video_duration_seconds in
        # sync with the target so /history rows show the same number that
        # the asset manifest, prompt, and submit payload carried.
        try:
            if target_duration_seconds is not None and record.video_duration_seconds != target_duration_seconds:
                record.video_duration_seconds = target_duration_seconds
                db.add(record)
                db.commit()
                db.refresh(record)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

        try:
            mapped = _map_job_status_to_video_status(job.status)
            if mapped and record.video_status != mapped:
                record.video_status = mapped
                db.add(record)
                db.commit()
                db.refresh(record)
        except Exception as sync_exc:
            print(f"[Video Mode] Warning: failed to sync video_status (apx): {sync_exc}")
            try:
                db.rollback()
            except Exception:
                pass

        return job.to_dict()
    except Exception as exc:
        print(f"[Video Mode] Warning: failed to create APX VideoJob: {exc}")
        return None


def _create_video_job_for_record(
    db: Session,
    user_id: int,
    record: VideoHistory,
    request_title: str,
) -> Optional[Dict[str, Any]]:
    """v0.6.0 dispatcher: prefer the APX provider when configured, otherwise
    fall back to the Mock provider so the UI keeps showing a status panel.
    """
    apx_job = _create_apx_video_job_for_record(db, user_id, record, request_title)
    if apx_job is not None:
        return apx_job
    return _create_mock_video_job_for_record(db, user_id, record, request_title)


# ---------------------------------------------------------------------------
# v0.6.2 — Real Video Mode generation run store
# ---------------------------------------------------------------------------
# The home-page generation flow used to be driven by a JS setInterval that
# advanced through fake stages on a 1.5s timer. v0.6.2 replaces that with a
# tiny in-memory run store: /api/video/generate/start spawns a worker thread
# that runs the same pipeline + APX submit logic, recording per-stage timing
# into VIDEO_GENERATION_RUNS. The frontend polls /api/video/generate/runs/
# {run_id} every ~1s and renders the actual stage that is in flight.
#
# State lives only in this process (single-machine FastAPI) — sessions are
# recreated per stage from VideoSessionLocal so there is no DB sharing
# between threads.
VIDEO_RUN_STAGES = (
    ("validate_topic", "Validate topic"),
    ("build_llm_content_package", "Build LLM content package"),
    ("parse_package_output", "Parse package output"),
    ("create_video_history_record", "Create video history record"),
    ("build_video_assets", "Build video assets"),
    ("compile_seedance_prompt", "Compile Seedance prompt"),
    ("validate_prompt_quality", "Validate prompt quality"),
    ("submit_video_job", "Submit video job"),
    ("open_video_status_panel", "Open video status panel"),
)

# v0.6.3.2 — Image Video has its own real stage list. The Seedance route
# above used to be reused for both, which left 5 stages permanently at 0 ms
# on the image_video path. The new stages match the actual work the
# image_video pipeline performs (LLM content + Pillow render + FFmpeg
# compose), so each row in the progress panel reports a real duration.
IMAGE_VIDEO_RUN_STAGES = (
    ("validate_topic",         "Validate topic"),
    ("plan_slides",            "Plan slides"),
    ("write_slide_content",    "Write slide content with AI"),
    ("select_bgm",             "Select background music"),
    ("generate_slide_images",  "Generate slide images (gpt-image-2)"),
    ("render_slide_overlays",  "Render on-screen text overlays"),
    ("synthesize_narration",   "Synthesize narration with Edge TTS"),
    ("compose_final_video",    "Compose final video with FFmpeg"),
    ("save_history",           "Save to history"),
)

VIDEO_GENERATION_RUNS: Dict[str, Dict[str, Any]] = {}
VIDEO_GENERATION_RUNS_LOCK = threading.Lock()


def _stages_for_method(generation_method: str) -> tuple:
    if generation_method == "image_video":
        return IMAGE_VIDEO_RUN_STAGES
    return VIDEO_RUN_STAGES


def _video_run_init(
    run_id: str,
    user_id: int,
    title: str,
    duration_seconds: Optional[int],
    generation_method: str = "seedance_video",
) -> Dict[str, Any]:
    now_iso = datetime.utcnow().isoformat() + "Z"
    stages = [
        {
            "key": key,
            "label": label,
            "status": "pending",
            "started_at": None,
            "ended_at": None,
            "duration_ms": None,
            "message": "",
        }
        for key, label in _stages_for_method(generation_method)
    ]
    run = {
        "run_id": run_id,
        "user_id": user_id,
        "title": title,
        "duration_seconds": duration_seconds,
        "generation_method": generation_method,
        "status": "running",
        "created_at": now_iso,
        "updated_at": now_iso,
        "completed_at": None,
        "stages": stages,
        "result": None,
        "error": None,
    }
    with VIDEO_GENERATION_RUNS_LOCK:
        VIDEO_GENERATION_RUNS[run_id] = run
        # Cap the dict so a long-lived process doesn't grow unbounded — keep
        # the 32 most-recent runs.
        if len(VIDEO_GENERATION_RUNS) > 64:
            old_keys = sorted(
                VIDEO_GENERATION_RUNS.keys(),
                key=lambda k: VIDEO_GENERATION_RUNS[k].get("created_at") or "",
            )[: len(VIDEO_GENERATION_RUNS) - 32]
            for k in old_keys:
                VIDEO_GENERATION_RUNS.pop(k, None)
    return run


def _video_run_set_stage(
    run_id: str, key: str, status: str, message: str = ""
) -> None:
    now_iso = datetime.utcnow().isoformat() + "Z"
    with VIDEO_GENERATION_RUNS_LOCK:
        run = VIDEO_GENERATION_RUNS.get(run_id)
        if not run:
            return
        run["updated_at"] = now_iso
        for stage in run["stages"]:
            if stage["key"] != key:
                continue
            if status == "running":
                stage["status"] = "running"
                stage["started_at"] = now_iso
                if message:
                    stage["message"] = message
            elif status == "done":
                stage["status"] = "done"
                stage["ended_at"] = now_iso
                if stage["started_at"]:
                    try:
                        start = datetime.fromisoformat(stage["started_at"].rstrip("Z"))
                        end = datetime.fromisoformat(now_iso.rstrip("Z"))
                        stage["duration_ms"] = int((end - start).total_seconds() * 1000)
                    except Exception:
                        stage["duration_ms"] = None
                if message:
                    stage["message"] = message
            elif status == "failed":
                stage["status"] = "failed"
                stage["ended_at"] = now_iso
                if message:
                    stage["message"] = message
            break


def _video_run_finalize(
    run_id: str,
    status: str,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    now_iso = datetime.utcnow().isoformat() + "Z"
    with VIDEO_GENERATION_RUNS_LOCK:
        run = VIDEO_GENERATION_RUNS.get(run_id)
        if not run:
            return
        run["status"] = status
        run["completed_at"] = now_iso
        run["updated_at"] = now_iso
        if result is not None:
            run["result"] = result
        if error is not None:
            run["error"] = error


def _video_run_snapshot(run_id: str) -> Optional[Dict[str, Any]]:
    with VIDEO_GENERATION_RUNS_LOCK:
        run = VIDEO_GENERATION_RUNS.get(run_id)
        if run is None:
            return None
        # Shallow copy + nested copies of mutable fields so we never hand the
        # caller a reference the worker is still mutating.
        return {
            **run,
            "stages": [dict(s) for s in run["stages"]],
            "result": dict(run["result"]) if isinstance(run["result"], dict) else run["result"],
        }


def _video_run_worker(
    run_id: str,
    user_id: int,
    title: str,
    duration_seconds: Optional[int],
    generation_method: str = "seedance_video",
) -> None:
    from web.db import VideoSessionLocal  # local import: same as the rest of the file
    db = None

    # v0.6.3 — Image Video runs a different (much shorter) sequence: it
    # never calls APX/Seedance/Image2/TTS. We surface a compact 4-stage
    # progress so the home-page UI doesn't lie about which work happened.
    if generation_method == "image_video":
        _run_image_video_worker(run_id, user_id, title, duration_seconds)
        return

    try:
        # Stage 1: validate topic
        _video_run_set_stage(run_id, "validate_topic", "running")
        if not title.strip():
            _video_run_set_stage(run_id, "validate_topic", "failed", "Title cannot be empty")
            _video_run_finalize(run_id, "failed", error="Title cannot be empty")
            return
        _video_run_set_stage(run_id, "validate_topic", "done")

        # Stage 2: build LLM content package (delegates to the existing
        # generate_video_package.py CLI so we mirror /api/video/generate).
        _video_run_set_stage(run_id, "build_llm_content_package", "running")
        slug = generate_unique_slug(title)
        script_path = project_root / "scripts" / "generate_video_package.py"
        if not script_path.exists():
            _video_run_set_stage(
                run_id, "build_llm_content_package", "failed", "generate_video_package.py missing"
            )
            _video_run_finalize(run_id, "failed", error="generate_video_package.py missing")
            return
        try:
            result = subprocess.run(
                [sys.executable, str(script_path), "--title", title, "--mode", "llm",
                 "--output-slug", slug, "--overwrite"],
                cwd=str(project_root), capture_output=True, text=True, timeout=600,
            )
        except subprocess.TimeoutExpired:
            _video_run_set_stage(
                run_id, "build_llm_content_package", "failed", "package script timed out"
            )
            _video_run_finalize(run_id, "failed", error="package script timed out")
            return
        if result.returncode != 0:
            _video_run_set_stage(
                run_id, "build_llm_content_package", "failed",
                f"package script exit {result.returncode}",
            )
            _video_run_finalize(
                run_id, "failed",
                error=f"package script exit {result.returncode}: {(result.stderr or '')[-500:]}",
            )
            return
        _video_run_set_stage(run_id, "build_llm_content_package", "done")

        # Stage 3: parse package output
        _video_run_set_stage(run_id, "parse_package_output", "running")
        output_dir = project_root / "outputs" / slug
        prompt_file = output_dir / "notebooklm_clean_source.txt"
        if not prompt_file.exists():
            _video_run_set_stage(
                run_id, "parse_package_output", "failed", "notebooklm_clean_source.txt missing"
            )
            _video_run_finalize(run_id, "failed", error="notebooklm_clean_source.txt missing")
            return
        with open(prompt_file, "r", encoding="utf-8") as f:
            prompt_content = f.read()
        overview_cn = None
        topic_json_file = output_dir / "topic.json"
        if topic_json_file.exists():
            try:
                with open(topic_json_file, "r", encoding="utf-8") as f:
                    overview_cn = json.load(f).get("overview_cn")
            except Exception:
                overview_cn = None
        _video_run_set_stage(run_id, "parse_package_output", "done")

        # Stage 4: create video history record
        _video_run_set_stage(run_id, "create_video_history_record", "running")
        model = os.getenv("AI_VIDEO_LLM_MODEL", "gpt-5-chat")
        db = VideoSessionLocal()
        record = VideoHistoryRepository.create_history_record(
            db=db, user_id=user_id, title=title, slug=slug, prompt_text=prompt_content,
            output_dir=str(output_dir), model=model, mode="video",
            status="success", overview_cn=overview_cn, web_copy_text=None,
        )
        history_id = record.id
        _video_run_set_stage(run_id, "create_video_history_record", "done")

        # Stage 5: build video assets (also runs compile + writes
        # seedance_prompt.txt under the hood, but we surface them as
        # separate stages for the UI).
        _video_run_set_stage(run_id, "build_video_assets", "running")
        pipeline_result = build_video_content_assets(
            topic=title, output_dir=output_dir, history_id=history_id,
            target_duration_seconds=duration_seconds,
        )
        provider_prompt_text = pipeline_result.get("provider_prompt") or prompt_content
        pipeline_overview_cn = pipeline_result.get("overview_cn") or overview_cn or ""
        pipeline_preview_text = pipeline_result.get("preview_text") or ""
        asset_metadata_json = _build_video_assets_metadata_json(pipeline_result)
        record = VideoHistoryRepository.update_asset_pipeline_result(
            db=db, user_id=user_id, history_id=history_id, prompt_text=provider_prompt_text,
            preview_text=pipeline_preview_text, overview_cn=pipeline_overview_cn,
            metadata_json=asset_metadata_json,
        ) or record
        _video_run_set_stage(run_id, "build_video_assets", "done")

        # Stage 6: compile seedance prompt — already happened inside the
        # pipeline above. Surface it as done so the user sees both stages.
        _video_run_set_stage(run_id, "compile_seedance_prompt", "running")
        compiled_prompt_ready = bool(pipeline_result.get("seedance_prompt_ready"))
        _video_run_set_stage(
            run_id, "compile_seedance_prompt",
            "done" if compiled_prompt_ready else "failed",
            "" if compiled_prompt_ready else "Compiler did not produce a ready prompt.",
        )

        # Stage 7: validate prompt quality (offline gate; the same gate
        # _create_apx_video_job_for_record runs before APX submit).
        _video_run_set_stage(run_id, "validate_prompt_quality", "running")
        normalized_for_gate = (
            (pipeline_result.get("seedance_prompt_debug") or {}).get("normalized_input") or {}
        )
        gate_passed, gate_reasons, _gate_rules = _validate_seedance_prompt_quality(
            pipeline_result.get("seedance_prompt") or "",
            compiled_payload={"normalized_input": normalized_for_gate},
            duration_seconds=duration_seconds,
        )
        if gate_passed:
            _video_run_set_stage(run_id, "validate_prompt_quality", "done", "Quality gate passed.")
        else:
            _video_run_set_stage(
                run_id, "validate_prompt_quality", "done",
                "Quality gate failed: " + "; ".join(gate_reasons),
            )

        # Stage 8: submit video job (APX when configured, otherwise Mock,
        # otherwise blocked_prompt_quality if the gate failed).
        _video_run_set_stage(run_id, "submit_video_job", "running")
        video_job_dict = _create_video_job_for_record(db, user_id, record, title)
        _video_run_set_stage(run_id, "submit_video_job", "done")

        # Stage 9: open video status panel — sentinel that signals the UI
        # to switch from the home-page run progress into the Video Output
        # tab + Video Job status panel.
        _video_run_set_stage(run_id, "open_video_status_panel", "running")
        _video_run_set_stage(run_id, "open_video_status_panel", "done")

        result_payload = {
            "success": True,
            "id": record.id,
            "history_id": record.id,
            "title": title,
            "slug": slug,
            "topic_group_id": record.topic_group_id,
            "version_number": record.version_number,
            "prompt": record.prompt_text,
            "raw_text": record.prompt_text,
            "prompt_text": record.prompt_text,
            "preview_text": record.preview_text,
            "overview_cn": record.overview_cn,
            "video_status": record.video_status,
            "video_duration_seconds": record.video_duration_seconds,
            "video_job": video_job_dict,
            "video_assets": pipeline_result.get("video_assets"),
            "provider_prompt": pipeline_result.get("provider_prompt"),
            "seedance_prompt_ready": compiled_prompt_ready,
            "prompt_quality_passed": gate_passed,
            "prompt_quality_reasons": gate_reasons,
            "output_dir": str(output_dir),
        }
        _video_run_finalize(run_id, "completed", result=result_payload)
    except Exception as exc:
        try:
            _video_run_finalize(run_id, "failed", error=f"Worker error: {exc}")
        except Exception:
            pass
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def _run_image_video_worker(
    run_id: str, user_id: int, title: str, duration_seconds: Optional[int]
) -> None:
    """v0.6.3.2 — background worker for the Image Video route.

    Drives the 6-stage IMAGE_VIDEO_RUN_STAGES sequence:

        validate_topic
        plan_slides
        write_slide_content
        render_slide_images
        compose_final_video
        save_history

    Stages 2-5 are emitted by ``image_video_pipeline.generate_image_video_package``
    via the ``progress_cb`` hook so each row records real wall-clock time.
    Never calls APX, Seedance, Image2, or TTS.
    """
    from web.db import VideoSessionLocal
    from web.image_video_pipeline import generate_image_video_package
    db = None
    try:
        # Stage 1 — validate_topic
        _video_run_set_stage(run_id, "validate_topic", "running")
        if not title.strip():
            _video_run_set_stage(run_id, "validate_topic", "failed", "Title cannot be empty")
            _video_run_finalize(run_id, "failed", error="Title cannot be empty")
            return
        _video_run_set_stage(run_id, "validate_topic", "done")

        duration_for_image = duration_seconds or 15
        if duration_for_image not in (5, 15, 30, 60, 90):
            duration_for_image = min(
                (5, 15, 30, 60, 90),
                key=lambda x: abs(x - (duration_seconds or 15)),
            )

        slug = generate_unique_slug(title)
        output_dir = project_root / "outputs" / slug
        output_dir.mkdir(parents=True, exist_ok=True)

        # Stages 2-5 (plan_slides / write_slide_content / render_slide_images /
        # compose_final_video) are reported by the pipeline itself via this
        # callback. Each call resolves to _video_run_set_stage on this run.
        def _progress_cb(stage_key: str, status: str, message: str = "") -> None:
            _video_run_set_stage(run_id, stage_key, status, message)

        pipeline_result = generate_image_video_package(
            title=title,
            duration_seconds=duration_for_image,
            output_dir=str(output_dir),
            slug=slug,
            progress_cb=_progress_cb,
        )

        # Stage 6 — save_history (DB write happens here, not inside the
        # pipeline, so we know its real duration too).
        _video_run_set_stage(run_id, "save_history", "running",
                             "Persisting video history record + assets.")
        db = VideoSessionLocal()
        record = VideoHistoryRepository.create_history_record(
            db=db, user_id=user_id, title=title, slug=slug,
            prompt_text=f"[Image Video] {title}",
            output_dir=str(output_dir),
            model="image_video_local_renderer",
            mode="video", status="success",
            overview_cn=None, web_copy_text=None,
            generation_method="image_video",
        )
        history_id = record.id
        # Wire pipeline result into the freshly-created history record
        # (writes video_file_path / metadata_json / overview_cn / preview_text /
        # prompt_text). This is the same persistence helper the synchronous
        # /api/video/generate path uses.
        relative_video_path = _safe_relative_outputs_path(
            pipeline_result.get("final_video_path")
        )
        pipeline_result["relative_video_path"] = relative_video_path
        llm_overview_cn = pipeline_result.get("overview_cn") or ""
        if pipeline_result.get("route_status") == "succeeded":
            slide_plan_path = pipeline_result.get("slide_plan_path")
            slide_plan: Dict[str, Any] = {}
            if slide_plan_path and Path(slide_plan_path).exists():
                try:
                    slide_plan = json.loads(
                        Path(slide_plan_path).read_text(encoding="utf-8")
                    )
                except Exception:
                    slide_plan = {}
            llm_content_for_text: Optional[Dict[str, Any]] = None
            llm_content_path = pipeline_result.get("llm_slide_content_path")
            if llm_content_path and Path(llm_content_path).exists():
                try:
                    llm_content_for_text = json.loads(
                        Path(llm_content_path).read_text(encoding="utf-8")
                    )
                except Exception:
                    llm_content_for_text = None
            raw_text = _build_image_video_raw_text(slide_plan, llm_content_for_text)
            preview_text = _build_image_video_preview_text(slide_plan)
            overview_text = _build_image_video_overview_text(
                title=title,
                duration_seconds=duration_for_image,
                slide_count=int(pipeline_result.get("slide_count") or 0),
                route_status="succeeded",
                llm_overview_cn=llm_overview_cn,
                image2_succeeded=int(pipeline_result.get("image2_succeeded") or 0),
                image2_failed=int(pipeline_result.get("image2_failed") or 0),
                image2_requested=int(pipeline_result.get("image2_requested") or 0),
                tts_status=pipeline_result.get("tts_status"),
                voiceover_source=pipeline_result.get("voiceover_source"),
                has_audio=bool(
                    pipeline_result.get("has_audio")
                    or pipeline_result.get("bgm_used")
                ),
            )
            VideoHistoryRepository.update_image_video_result(
                db=db, user_id=user_id, history_id=history_id,
                video_file_path=relative_video_path,
                video_duration_seconds=int(duration_for_image),
                video_status="ready",
                metadata_json=_build_image_video_metadata_json(pipeline_result),
                preview_text=preview_text,
                overview_cn=overview_text,
                prompt_text=raw_text,
            )
            _video_run_set_stage(run_id, "save_history", "done",
                                 "History record updated; mp4 path recorded.")
        else:
            overview_text = _build_image_video_overview_text(
                title=title,
                duration_seconds=duration_for_image,
                slide_count=int(pipeline_result.get("slide_count") or 0),
                route_status="failed",
                llm_overview_cn=llm_overview_cn,
                image2_succeeded=int(pipeline_result.get("image2_succeeded") or 0),
                image2_failed=int(pipeline_result.get("image2_failed") or 0),
                image2_requested=int(pipeline_result.get("image2_requested") or 0),
                tts_status=pipeline_result.get("tts_status"),
                voiceover_source=pipeline_result.get("voiceover_source"),
                has_audio=bool(
                    pipeline_result.get("has_audio")
                    or pipeline_result.get("bgm_used")
                ),
            )
            VideoHistoryRepository.update_image_video_result(
                db=db, user_id=user_id, history_id=history_id,
                video_file_path=None,
                video_duration_seconds=int(duration_for_image),
                video_status="failed",
                metadata_json=_build_image_video_metadata_json(pipeline_result),
                preview_text=overview_text,
                overview_cn=overview_text,
                prompt_text=overview_text,
            )
            _video_run_set_stage(run_id, "save_history", "done",
                                 "History record updated (route_status=failed).")
        db.refresh(record)

        result_payload = _build_image_video_response_payload(
            record=record,
            pipeline_result=pipeline_result,
            title=title,
            duration_seconds=duration_for_image,
        )
        _video_run_finalize(
            run_id,
            "completed" if pipeline_result.get("route_status") == "succeeded" else "failed",
            result=result_payload,
            error=pipeline_result.get("error"),
        )
    except Exception as exc:
        try:
            _video_run_finalize(run_id, "failed", error=f"Image Video worker error: {exc}")
        except Exception:
            pass
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


@app.post("/api/video/generate/start")
async def video_generate_start(
    request: VideoGenerateRequest,
    current_user=Depends(require_active_user),
) -> JSONResponse:
    """v0.6.2 — kick off a Video Mode generation run in the background.

    v0.6.8: the ``run_id`` is bound to ``current_user.id`` so other
    authenticated users can't poll it.
    """
    title = (request.title or "").strip()
    if not title:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Title cannot be empty"},
        )
    generation_method, method_error = _normalize_generation_method(
        request.generation_method
    )
    if method_error:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": method_error},
        )
    duration_seconds = request.duration_seconds
    run_id = uuid.uuid4().hex
    _video_run_init(run_id, current_user.id, title, duration_seconds, generation_method)
    thread = threading.Thread(
        target=_video_run_worker,
        args=(run_id, current_user.id, title, duration_seconds, generation_method),
        name=f"video-run-{run_id[:8]}",
        daemon=True,
    )
    thread.start()
    # v0.6.3.2 — return the initial stage list so the UI can paint the
    # right pending rows immediately (previously the frontend hardcoded
    # the Seedance 9-stage list, which left image_video showing 5
    # phantom 0 ms rows).
    initial = _video_run_snapshot(run_id) or {}
    return JSONResponse(content={
        "success": True,
        "run_id": run_id,
        "generation_method": generation_method,
        "stages": initial.get("stages", []),
    })


@app.get("/api/video/generate/runs/{run_id}")
async def video_generate_run_status(
    run_id: str,
    current_user=Depends(require_active_user),
) -> JSONResponse:
    """Return the current snapshot of a Video Mode generation run.

    v0.6.8: 404s if the run isn't owned by the current user — same error code
    as missing run, so existence isn't leaked to other authenticated users.
    """
    snap = _video_run_snapshot(run_id)
    if not snap or snap.get("user_id") != current_user.id:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Run {run_id} not found"},
        )
    return JSONResponse(content={"success": True, "run": snap})


def _build_video_generate_provider_contract_response(
    video_job_dict: Optional[Dict[str, Any]],
    pipeline_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a v0.6.0-aware provider_contract + message pair for /api/video/generate
    and /api/video/history/{id}/regenerate responses.

    Returned dict:
        {"provider_contract": {...}, "message": "..."}

    Never reflects raw API key / Authorization headers — only status/stage/progress
    fields surfaced from VideoJob.to_dict() and pipeline-derived flags.
    """
    job = video_job_dict or {}
    provider = job.get("provider")
    status = job.get("status")
    stage = job.get("stage")
    progress = job.get("progress")

    contract_validation = pipeline_result.get('provider_contract_validation') or {}
    contract_ready = bool(contract_validation.get('valid'))
    prompt_compiler_ready = bool(pipeline_result.get('seedance_prompt_ready'))
    prompt_compiler_version = pipeline_result.get('seedance_prompt_compiler_version')

    is_apx = provider == "apx_seedance"
    apx_inflight_or_terminal = status in (
        "submitted", "pending", "running",
        "succeeded", "failed", "succeeded_but_no_video_url",
    )
    network_call_performed = bool(
        is_apx and apx_inflight_or_terminal and status != "blocked_fallback_prompt"
    )

    if is_apx:
        future_provider = "apx_seedance"
    else:
        future_provider = "seedance"

    if status == "blocked_fallback_prompt":
        message = (
            "APX Seedance submit was blocked because prompt assets require human review. "
            "Resolve the warnings and regenerate before retrying."
        )
    elif is_apx and status == "submitted":
        message = (
            "APX Seedance job submitted. Open the Video tab and click Refresh to "
            "poll status and download the video when ready."
        )
    elif is_apx and status in ("pending", "running"):
        message = (
            "APX Seedance job is in flight. Open the Video tab and click Refresh "
            "to poll status and download the video when ready."
        )
    elif is_apx and status == "succeeded":
        message = "APX Seedance job succeeded. Local video.mp4 download is in progress or complete."
    elif is_apx and status == "succeeded_but_no_video_url":
        message = (
            "APX Seedance job succeeded but no video_url was returned. "
            "No real video file was downloaded."
        )
    elif is_apx and status == "failed":
        message = "APX Seedance job failed. See the latest job error for details."
    elif provider == "mock" or status == "provider_not_configured":
        message = (
            "Content assets were generated, but APX real provider is not configured. "
            "Set APX_VIDEO_ENABLED=true and APX_VIDEO_API_KEY to enable real generation."
        )
    else:
        message = (
            "Content assets and compiled Seedance prompt are ready. "
            "No video job has been submitted yet."
        )

    return {
        "provider_contract": {
            "future_provider": future_provider,
            "provider": provider,
            "provider_job_status": status,
            "provider_job_stage": stage,
            "provider_job_progress": progress,
            "contract_ready": contract_ready,
            "prompt_compiler_ready": prompt_compiler_ready,
            "prompt_compiler_version": prompt_compiler_version,
            "network_call_performed": network_call_performed,
            "real_video_generated": False,
            "real_video_downloaded": False,
        },
        "message": message,
    }


@app.post("/api/video/generate")
async def video_generate(
    request: VideoGenerateRequest,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> JSONResponse:
    """
    Generate a Video Mode entry.

    Video Mode reuses ``scripts/generate_video_package.py`` for the first
    package stage and then runs the Video Content Asset Pipeline, which writes
    structured Seedance assets (compiled prompt, negative prompt, debug
    payload) and dry-run contract assets (payload preview, contract
    validation, lifecycle preview).

    v0.6.0 provider behavior:
      - When ``APX_VIDEO_ENABLED=true`` and ``APX_VIDEO_API_KEY`` is set, the
        endpoint submits an APX Seedance async task (``POST /v1/async/chat``)
        carrying the v0.5.6 compiled Seedance prompt.
      - When APX is not configured, the system falls back to
        ``MockVideoProvider`` and produces no real video.
      - This endpoint returns immediately after submit; it does NOT wait for
        the video to finish rendering. Polling and downloading happen through
        ``POST /api/video/jobs/{id}/refresh``.
      - The Prompt Mode database is not touched; only the Video Mode database
        (``data/video_history.db``) and ``outputs/<slug>/video_assets/`` are
        written.
    """
    title = request.title.strip()
    if not title:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Title cannot be empty"},
        )

    # v0.6.3 — dispatch on generation_method. Default is the existing
    # Seedance Video chain (preserves all v0.6.2 behaviour). Image Video
    # runs the local Pillow + FFmpeg pipeline and never calls APX, Seedance,
    # Image2, or TTS.
    generation_method, method_error = _normalize_generation_method(
        request.generation_method
    )
    if method_error:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": method_error},
        )

    if generation_method == "image_video":
        duration_for_image = request.duration_seconds or 15
        if duration_for_image not in (5, 15, 30, 60, 90):
            # snap to nearest supported bucket
            duration_for_image = min(
                (5, 15, 30, 60, 90),
                key=lambda x: abs(x - duration_for_image),
            )
        slug = generate_unique_slug(title)
        output_dir = project_root / "outputs" / slug
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            record = VideoHistoryRepository.create_history_record(
                db=db,
                user_id=current_user.id,
                title=title,
                slug=slug,
                prompt_text=f"[Image Video] {title}",
                output_dir=str(output_dir),
                model="image_video_local_renderer",
                mode="video",
                status="success",
                overview_cn=None,
                web_copy_text=None,
                generation_method="image_video",
            )
            pipeline_result = _run_image_video_pipeline(
                db=db,
                user_id=current_user.id,
                title=title,
                slug=slug,
                duration_seconds=duration_for_image,
                output_dir=output_dir,
                history_id=record.id,
            )
            db.refresh(record)
            payload = _build_image_video_response_payload(
                record=record,
                pipeline_result=pipeline_result,
                title=title,
                duration_seconds=duration_for_image,
            )
            status_code = 200 if payload["success"] else 200
            return JSONResponse(content=payload, status_code=status_code)
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": f"Image Video pipeline crashed: {exc}",
                    "generation_method": "image_video",
                },
            )

    slug = generate_unique_slug(title)
    script_path = project_root / "scripts" / "generate_video_package.py"
    if not script_path.exists():
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Script not found: {script_path}"},
        )

    cmd = [
        sys.executable,
        str(script_path),
        "--title", title,
        "--mode", "llm",
        "--output-slug", slug,
        "--overwrite",
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": f"Command failed with exit code {result.returncode}",
                    "stdout": result.stdout[-2000:] if result.stdout else "",
                    "stderr": result.stderr[-2000:] if result.stderr else "",
                },
            )

        output_dir = project_root / "outputs" / slug
        prompt_file = output_dir / "notebooklm_clean_source.txt"
        if not prompt_file.exists():
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": f"Prompt file not found: {prompt_file}",
                },
            )

        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_content = f.read()

        overview_cn = None
        topic_json_file = output_dir / "topic.json"
        if topic_json_file.exists():
            try:
                with open(topic_json_file, 'r', encoding='utf-8') as f:
                    topic_data = json.load(f)
                    overview_cn = topic_data.get('overview_cn')
            except Exception as e:
                print(f"[Video Mode] Warning: failed to read overview_cn: {e}")

        model = os.getenv('AI_VIDEO_LLM_MODEL', 'gpt-5-chat')
        mode = 'video'

        try:
            # v0.5.4 structural fix: create the VideoHistory record FIRST so
            # the asset pipeline can stamp the real history_id into
            # generation_manifest.json. Initial values use the script-stage
            # outputs (overwritten with the pipeline result a few lines below).
            record = VideoHistoryRepository.create_history_record(
                db=db,
                user_id=current_user.id,
                title=title,
                slug=slug,
                prompt_text=prompt_content,
                output_dir=str(output_dir),
                model=model,
                mode=mode,
                status='success',
                overview_cn=overview_cn,
                web_copy_text=None,
                generation_method='seedance_video',
            )

            # v0.6.1: pull the user-selected duration from the request body
            # (5/15/30/60/90, default 15). resolve_target_duration_seconds
            # inside the pipeline still applies the env fallback chain.
            requested_duration_seconds = request.duration_seconds

            # v0.5.4: build the Video Content Asset bundle for the record we
            # just created. The pipeline never raises; real video providers
            # are NOT contacted.
            pipeline_result = build_video_content_assets(
                topic=title,
                output_dir=output_dir,
                history_id=record.id,
                target_duration_seconds=requested_duration_seconds,
            )
            provider_prompt_text = pipeline_result.get('provider_prompt') or prompt_content
            pipeline_overview_cn = pipeline_result.get('overview_cn') or overview_cn or ''
            pipeline_preview_text = pipeline_result.get('preview_text') or ''
            asset_metadata_json = _build_video_assets_metadata_json(pipeline_result)

            record = VideoHistoryRepository.update_asset_pipeline_result(
                db=db,
                user_id=current_user.id,
                history_id=record.id,
                prompt_text=provider_prompt_text,
                preview_text=pipeline_preview_text,
                overview_cn=pipeline_overview_cn,
                metadata_json=asset_metadata_json,
            ) or record

            # v0.6.0: create a VideoJob — APX Seedance provider when configured,
            # otherwise fall back to the Mock shell.
            video_job_dict = _create_video_job_for_record(db, current_user.id, record, title)
            return JSONResponse(content={
                'success': True,
                'id': record.id,
                'history_id': record.id,
                'title': title,
                'slug': slug,
                'topic_group_id': record.topic_group_id,
                'version_number': record.version_number,
                'prompt': record.prompt_text,
                'raw_text': record.prompt_text,
                'prompt_text': record.prompt_text,
                'preview_text': record.preview_text,
                'overview_cn': record.overview_cn,
                'change_summary_cn': record.change_summary_cn,
                'web_copy_text': record.web_copy_text,
                'output_dir': str(output_dir),
                'model': model,
                'mode': mode,
                'status': record.status,
                'video_status': record.video_status,
                'video_file_path': record.video_file_path,
                'video_url': record.video_url,
                'video_thumbnail_path': record.video_thumbnail_path,
                'video_duration_seconds': record.video_duration_seconds,
                'created_at': record.created_at.isoformat() if record.created_at else None,
                'updated_at': record.updated_at.isoformat() if record.updated_at else None,
                'item': record.to_dict(include_prompt=True),
                'video_job': video_job_dict,
                # v0.5.4 — Video Content Asset bundle
                'video_assets': pipeline_result.get('video_assets'),
                'provider_prompt': pipeline_result.get('provider_prompt'),
                'provider_request_preview': pipeline_result.get('provider_request_preview'),
                'asset_manifest': pipeline_result.get('asset_manifest'),
                'asset_paths': pipeline_result.get('asset_paths'),
                'video_assets_schema_version': pipeline_result.get('schema_version'),
                'video_assets_warnings': pipeline_result.get('warnings', []),
                'llm_used': pipeline_result.get('llm_used', False),
                # v0.5.5 — Seedance contract adapter
                'seedance_payload_preview': pipeline_result.get('seedance_payload_preview'),
                'provider_contract_validation': pipeline_result.get('provider_contract_validation'),
                'provider_lifecycle_preview': pipeline_result.get('provider_lifecycle_preview'),
                # v0.5.6 — Seedance prompt compiler
                'seedance_prompt': pipeline_result.get('seedance_prompt'),
                'seedance_negative_prompt': pipeline_result.get('seedance_negative_prompt'),
                'seedance_prompt_debug': pipeline_result.get('seedance_prompt_debug'),
                'seedance_prompt_compiler_version': pipeline_result.get(
                    'seedance_prompt_compiler_version'
                ),
                'seedance_prompt_profile_version': pipeline_result.get(
                    'seedance_prompt_profile_version'
                ),
                'seedance_prompt_ready': bool(pipeline_result.get('seedance_prompt_ready')),
                **_build_video_generate_provider_contract_response(video_job_dict, pipeline_result),
            })
        except Exception as e:
            print(f"[Video Mode] Warning: failed to save: {e}")
            return JSONResponse(content={
                'success': True,
                'slug': slug,
                'prompt': prompt_content,
                'raw_text': prompt_content,
                'output_dir': str(output_dir),
            })

    except subprocess.TimeoutExpired:
        return JSONResponse(
            status_code=504,
            content={"success": False, "error": "Generation timed out (> 10 minutes)"},
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Unexpected error: {e}"},
        )


@app.get("/api/video/history")
async def video_get_history(
    limit: int = 100,
    q: Optional[str] = None,
    date_filter: Optional[str] = None,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    try:
        records = VideoHistoryRepository.list_history_records(
            db, current_user.id, limit=limit, q=q, date_filter=date_filter,
        )
        items = []
        for r in records:
            item = r.to_dict(include_prompt=False)
            item['version_count'] = VideoHistoryRepository.get_version_count(db, current_user.id, r.topic_group_id)
            items.append(item)
        return {"success": True, "items": items}
    except Exception as e:
        return {"success": False, "error": str(e), "items": []}


@app.get("/api/video/history/{history_id}")
async def video_get_history_by_id(
    history_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    try:
        record = VideoHistoryRepository.get_history_record(db, current_user.id, history_id)
        if not record:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": f"Video history record {history_id} not found"},
            )
        item = record.to_dict(include_prompt=True)
        item['version_count'] = VideoHistoryRepository.get_version_count(db, current_user.id, record.topic_group_id)
        return {"success": True, "item": item}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)},
        )


@app.patch("/api/video/history/{history_id}")
async def video_update_content(
    history_id: int,
    request: VideoUpdateContentRequest,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """
    Update editable content for a Video Mode record.

    Allowed views: raw / preview / overview / web_copy.
    Same Raw-Text protections as Prompt Mode are mirrored here.
    """
    view = request.view
    content = request.content

    if view not in ('raw', 'preview', 'overview', 'web_copy'):
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": f"Invalid view: {view}"},
        )

    if view == 'raw':
        trimmed = content.strip()
        if not trimmed:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Raw Text cannot be empty."},
            )
        if len(trimmed) < 500:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": f"Raw Text is too short ({len(trimmed)} characters). Save rejected.",
                },
            )

    try:
        record = VideoHistoryRepository.update_prompt_content(
            db, current_user.id, history_id=history_id, view=view, content=content,
        )
        if not record:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": f"Video history record {history_id} not found"},
            )
        return {"success": True, "item": record.to_dict(include_prompt=True)}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)},
        )


@app.get("/api/video/history/group/{topic_group_id}/versions")
async def video_get_versions_by_group(
    topic_group_id: str,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """v0.5.1.2: return ``versions`` for the frontend version dropdown."""
    try:
        versions = VideoHistoryRepository.get_versions_by_group(db, current_user.id, topic_group_id)
        if not versions:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Topic group {topic_group_id} not found",
                },
            )
        version_list = [
            {
                'id': v.id,
                'version_number': v.version_number,
                'created_at': v.created_at.isoformat() if v.created_at else None,
                'slug': v.slug,
                'deleted_at': v.deleted_at.isoformat() if v.deleted_at else None,
            }
            for v in versions
        ]
        items = [v.to_dict(include_prompt=False) for v in versions]
        return {
            "success": True,
            "versions": version_list,
            "items": items,
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)},
        )


@app.post("/api/video/history/{history_id}/regenerate")
async def video_regenerate(
    history_id: int,
    request: VideoRegenerateRequest,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> JSONResponse:
    """Regenerate a Video Mode version. Saves to Video Mode database only."""
    record = VideoHistoryRepository.get_history_record(db, current_user.id, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )

    feedback = request.feedback.strip()
    if not feedback:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Feedback cannot be empty"},
        )

    new_slug = generate_unique_slug(record.title)
    script_path = project_root / "scripts" / "generate_video_package.py"
    if not script_path.exists():
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Script not found: {script_path}"},
        )

    cmd = [
        sys.executable,
        str(script_path),
        "--title", record.title,
        "--mode", "llm",
        "--output-slug", new_slug,
        "--overwrite",
        "--feedback", feedback,
    ]

    try:
        result = subprocess.run(
            cmd, cwd=str(project_root), capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": f"Command failed with exit code {result.returncode}",
                    "stdout": result.stdout[-2000:] if result.stdout else "",
                    "stderr": result.stderr[-2000:] if result.stderr else "",
                },
            )

        output_dir = project_root / "outputs" / new_slug
        prompt_file = output_dir / "notebooklm_clean_source.txt"
        if not prompt_file.exists():
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": f"Prompt file not found: {prompt_file}"},
            )

        with open(prompt_file, 'r', encoding='utf-8') as f:
            new_prompt = f.read()

        new_overview_cn = None
        change_summary_cn = None
        topic_json_file = output_dir / "topic.json"
        if topic_json_file.exists():
            try:
                with open(topic_json_file, 'r', encoding='utf-8') as f:
                    topic_data = json.load(f)
                    new_overview_cn = topic_data.get('overview_cn')
                    change_summary_cn = topic_data.get('change_summary_cn')
            except Exception as e:
                print(f"[Video Mode] regenerate: failed to read topic.json: {e}")

        model = os.getenv('AI_VIDEO_LLM_MODEL', 'gpt-5-chat')

        # v0.5.4 structural fix: create the new VideoHistory version FIRST
        # using the script-stage outputs, then call the asset pipeline with
        # the real new history_id, then write the pipeline result back.
        new_record = VideoHistoryRepository.create_regenerated_version(
            db=db,
            user_id=current_user.id,
            from_history_id=history_id,
            feedback=feedback,
            new_prompt_text=new_prompt,
            new_overview_cn=new_overview_cn,
            change_summary_cn=change_summary_cn,
            slug=new_slug,
            output_dir=str(output_dir),
            model=model,
        )
        if not new_record:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "Failed to create regenerated version"},
            )

        # v0.6.1: regenerate inherits the previous record's duration unless
        # the request explicitly overrides it.
        regen_duration_seconds = request.duration_seconds
        if regen_duration_seconds is None and record is not None:
            regen_duration_seconds = record.video_duration_seconds

        # v0.5.4: rebuild the Video Content Asset bundle for the new version.
        # Always returns a result dict; never raises.
        pipeline_result = build_video_content_assets(
            topic=new_record.title,
            output_dir=output_dir,
            history_id=new_record.id,
            target_duration_seconds=regen_duration_seconds,
        )
        provider_prompt_text = pipeline_result.get('provider_prompt') or new_prompt
        pipeline_overview_cn = pipeline_result.get('overview_cn') or new_overview_cn or ''
        pipeline_preview_text = pipeline_result.get('preview_text') or ''
        asset_metadata_json = _build_video_assets_metadata_json(pipeline_result)

        new_record = VideoHistoryRepository.update_asset_pipeline_result(
            db=db,
            user_id=current_user.id,
            history_id=new_record.id,
            prompt_text=provider_prompt_text,
            preview_text=pipeline_preview_text,
            overview_cn=pipeline_overview_cn,
            metadata_json=asset_metadata_json,
        ) or new_record

        # v0.6.0: create a VideoJob for the new version — APX when configured,
        # Mock fallback otherwise. Non-blocking; client refreshes for status.
        video_job_dict = _create_video_job_for_record(db, current_user.id, new_record, new_record.title)
        return JSONResponse(content={
            "success": True,
            "id": new_record.id,
            "history_id": new_record.id,
            "title": new_record.title,
            "slug": new_record.slug,
            "topic_group_id": new_record.topic_group_id,
            "version_number": new_record.version_number,
            "prompt": new_record.prompt_text,
            "raw_text": new_record.prompt_text,
            "prompt_text": new_record.prompt_text,
            "preview_text": new_record.preview_text,
            "overview_cn": new_record.overview_cn,
            "change_summary_cn": new_record.change_summary_cn,
            "web_copy_text": new_record.web_copy_text,
            "output_dir": new_record.output_dir,
            "model": new_record.model,
            "mode": new_record.mode,
            "status": new_record.status,
            "video_status": new_record.video_status,
            "video_file_path": new_record.video_file_path,
            "video_url": new_record.video_url,
            "video_thumbnail_path": new_record.video_thumbnail_path,
            "video_duration_seconds": new_record.video_duration_seconds,
            "created_at": new_record.created_at.isoformat() if new_record.created_at else None,
            "updated_at": new_record.updated_at.isoformat() if new_record.updated_at else None,
            "item": new_record.to_dict(include_prompt=True),
            "video_job": video_job_dict,
            # v0.5.4 — Video Content Asset bundle
            "video_assets": pipeline_result.get('video_assets'),
            "provider_prompt": pipeline_result.get('provider_prompt'),
            "provider_request_preview": pipeline_result.get('provider_request_preview'),
            "asset_manifest": pipeline_result.get('asset_manifest'),
            "asset_paths": pipeline_result.get('asset_paths'),
            "video_assets_schema_version": pipeline_result.get('schema_version'),
            "video_assets_warnings": pipeline_result.get('warnings', []),
            "llm_used": pipeline_result.get('llm_used', False),
            # v0.5.5 — Seedance contract adapter
            "seedance_payload_preview": pipeline_result.get('seedance_payload_preview'),
            "provider_contract_validation": pipeline_result.get('provider_contract_validation'),
            "provider_lifecycle_preview": pipeline_result.get('provider_lifecycle_preview'),
            # v0.5.6 — Seedance prompt compiler
            "seedance_prompt": pipeline_result.get('seedance_prompt'),
            "seedance_negative_prompt": pipeline_result.get('seedance_negative_prompt'),
            "seedance_prompt_debug": pipeline_result.get('seedance_prompt_debug'),
            "seedance_prompt_compiler_version": pipeline_result.get(
                'seedance_prompt_compiler_version'
            ),
            "seedance_prompt_profile_version": pipeline_result.get(
                'seedance_prompt_profile_version'
            ),
            "seedance_prompt_ready": bool(pipeline_result.get('seedance_prompt_ready')),
            **_build_video_generate_provider_contract_response(video_job_dict, pipeline_result),
        })

    except subprocess.TimeoutExpired:
        return JSONResponse(
            status_code=504,
            content={"success": False, "error": "Regeneration timed out"},
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)},
        )


@app.post("/api/video/history/{history_id}/pin")
async def video_pin(
    history_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    record = VideoHistoryRepository.pin_history_record(db, current_user.id, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )
    return {"success": True, "item": record.to_dict(include_prompt=False)}


@app.post("/api/video/history/{history_id}/unpin")
async def video_unpin(
    history_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    record = VideoHistoryRepository.unpin_history_record(db, current_user.id, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )
    return {"success": True, "item": record.to_dict(include_prompt=False)}


@app.patch("/api/video/history/group/{topic_group_id}/rename")
async def video_rename_history_group(
    topic_group_id: str,
    request: RenameRequest,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """v0.5.1.2: Rename a Video Mode topic group."""
    try:
        ok = VideoHistoryRepository.rename_topic_group(db, current_user.id, topic_group_id, request.title)
        if not ok:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Video topic group {topic_group_id} not found",
                },
            )
        # Return latest version as the canonical updated item.
        versions = VideoHistoryRepository.get_versions_by_group(db, current_user.id, topic_group_id)
        latest = max(versions, key=lambda r: r.version_number) if versions else None
        item = latest.to_dict(include_prompt=False) if latest else {}
        if latest:
            item['version_count'] = VideoHistoryRepository.get_version_count(db, current_user.id, topic_group_id)
        return {"success": True, "item": item}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)},
        )


@app.post("/api/video/history/group/{topic_group_id}/trash")
async def video_trash_group(
    topic_group_id: str,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    ok = VideoHistoryRepository.soft_delete_history_group(db, current_user.id, topic_group_id)
    if not ok:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Group not found or already deleted"},
        )
    return {"success": True}


@app.post("/api/video/history/group/{topic_group_id}/restore")
async def video_restore_group(
    topic_group_id: str,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    ok = VideoHistoryRepository.restore_history_group(db, current_user.id, topic_group_id)
    if not ok:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Group not found in trash"},
        )
    return {"success": True}


@app.delete("/api/video/history/group/{topic_group_id}/permanent")
async def video_permanent_delete_group(
    topic_group_id: str,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    ok = VideoHistoryRepository.permanently_delete_history_group(db, current_user.id, topic_group_id)
    if not ok:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Group not found"},
        )
    return {"success": True}


@app.get("/api/video/trash")
async def video_list_trash(
    limit: int = 100,
    q: Optional[str] = None,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    try:
        records = VideoHistoryRepository.list_trash_records(db, current_user.id, limit=limit, q=q)
        return {
            "success": True,
            "items": [r.to_dict(include_prompt=False) for r in records],
        }
    except Exception as e:
        return {"success": False, "error": str(e), "items": []}


@app.post("/api/video/history/group/{topic_group_id}/favorite")
async def video_favorite_group(
    topic_group_id: str,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    record = VideoHistoryRepository.favorite_history_group(db, current_user.id, topic_group_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Group not found"},
        )
    return {"success": True, "item": record.to_dict(include_prompt=False)}


@app.post("/api/video/history/group/{topic_group_id}/unfavorite")
async def video_unfavorite_group(
    topic_group_id: str,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    record = VideoHistoryRepository.unfavorite_history_group(db, current_user.id, topic_group_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Group not found"},
        )
    return {"success": True, "item": record.to_dict(include_prompt=False)}


@app.get("/api/video/favorites")
async def video_list_favorites(
    limit: int = 100,
    q: Optional[str] = None,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    try:
        records = VideoHistoryRepository.list_favorite_records(db, current_user.id, limit=limit, q=q)
        return {
            "success": True,
            "items": [r.to_dict(include_prompt=False) for r in records],
        }
    except Exception as e:
        return {"success": False, "error": str(e), "items": []}


@app.get("/api/video/history/{history_id}/download-all")
async def video_download_all(
    history_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Any:
    """
    Read-only Download All for Video Mode.

    v0.6.0 semantics: package raw_text.txt / preview.txt / overview.txt /
    web_copy.txt / metadata.json plus the structured video_assets/* bundle.
    When the latest VideoJob is APX Seedance and the record holds a local
    video.mp4 (and optionally a cover) under project_root/outputs, those
    files are also included. The bundle never includes the API key, request
    headers, or the remote APX video_url.
    """
    import io
    import zipfile
    from fastapi.responses import StreamingResponse

    record = VideoHistoryRepository.get_history_record(db, current_user.id, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )

    raw_text = record.prompt_text or ""
    preview_text = record.preview_text or ""
    overview_text = record.overview_cn or ""
    change_summary = record.change_summary_cn or ""
    web_copy_text = record.web_copy_text or ""

    # v0.5.4: try to discover the on-disk Video Content Asset bundle. The
    # bundle is read-only here — Download All never modifies asset files.
    video_assets_dir: Optional[Path] = None
    has_video_assets = False
    asset_manifest: Dict[str, Any] = {}
    try:
        if record.output_dir:
            candidate = Path(record.output_dir) / "video_assets"
            if candidate.exists() and candidate.is_dir():
                video_assets_dir = candidate
                has_video_assets = True
                manifest_path = candidate / "generation_manifest.json"
                if manifest_path.exists():
                    try:
                        with open(manifest_path, 'r', encoding='utf-8') as mf:
                            asset_manifest = json.load(mf) or {}
                    except Exception as e:
                        print(f"[Video Mode] download_all: failed to read manifest: {e}")
    except Exception as e:
        print(f"[Video Mode] download_all: failed to inspect video_assets dir: {e}")

    # v0.5.4: if the DB preview_text is empty but the asset bundle has a
    # script + storyboard, build a fallback preview from disk so preview.txt
    # in the zip is never blank when assets exist.
    if not preview_text.strip() and video_assets_dir is not None:
        try:
            script_md_path = video_assets_dir / "video_script.md"
            storyboard_path = video_assets_dir / "storyboard.json"
            parts: List[str] = []
            if script_md_path.exists():
                with open(script_md_path, 'r', encoding='utf-8') as sf:
                    parts.append(sf.read().rstrip())
            if storyboard_path.exists():
                with open(storyboard_path, 'r', encoding='utf-8') as sf:
                    sb = json.load(sf) or {}
                lines = ["# Storyboard", ""]
                for sc in sb.get("scenes", []) or []:
                    lines.append(
                        f"- Scene {sc.get('scene_id', '?')} "
                        f"({sc.get('time_range', '')}): "
                        f"{sc.get('visual', '')} | OST: {sc.get('on_screen_text', '')}"
                    )
                parts.append("\n".join(lines))
            if parts:
                preview_text = "\n\n".join(parts).rstrip() + "\n"
        except Exception as e:
            print(f"[Video Mode] download_all: failed to build fallback preview: {e}")

    overview_full_parts: List[str] = []
    if overview_text.strip():
        overview_full_parts.append(overview_text.rstrip())
    if change_summary.strip():
        overview_full_parts.append("本次生成新增或改动的内容")
        overview_full_parts.append(change_summary.strip())
    overview_bundle = "\n\n".join(overview_full_parts)

    if not web_copy_text.strip():
        web_copy_text = (
            "Web Copy is not generated yet. This tab will later contain "
            "YouTube/TikTok titles, descriptions, captions, and posting copy."
        )

    # Asset list: prefer the manifest's "assets" array (matches what was
    # actually written), else fall back to a directory scan.
    asset_list: List[Dict[str, Any]] = []
    if isinstance(asset_manifest.get("assets"), list):
        asset_list = [
            {"key": entry.get("key"), "relative_path": entry.get("relative_path")}
            for entry in asset_manifest["assets"]
            if isinstance(entry, dict)
        ]
    elif video_assets_dir is not None:
        for asset_path in sorted(video_assets_dir.rglob("*")):
            if asset_path.is_file():
                try:
                    rel = asset_path.relative_to(video_assets_dir.parent)
                    asset_list.append({"key": asset_path.stem, "relative_path": rel.as_posix()})
                except ValueError:
                    continue

    # v0.6.0: surface latest VideoJob (APX or Mock) and check whether a real
    # local mp4 exists inside project_root/outputs/. The remote APX video_url,
    # api-key, request headers, request_json/response_json are NEVER exported.
    latest_job = VideoJobRepository.get_latest_job_for_history(db, current_user.id, history_id)
    latest_job_provider = latest_job.provider if latest_job else None
    latest_job_status = latest_job.status if latest_job else None
    latest_job_stage = latest_job.stage if latest_job else None
    latest_job_progress = latest_job.progress if latest_job else None

    is_apx = latest_job_provider == "apx_seedance"
    network_call_performed = bool(
        is_apx and latest_job_status not in (None, "blocked_fallback_prompt", "provider_not_configured")
    )

    safe_video_path = _resolve_safe_outputs_path(record.video_file_path)
    safe_cover_path = _resolve_safe_outputs_path(record.video_thumbnail_path)
    has_local_video_file = safe_video_path is not None
    has_local_video_cover = safe_cover_path is not None

    real_video_generated = bool(
        record.video_status == "ready"
        and has_local_video_file
    )
    real_video_downloaded = has_local_video_file
    has_remote_video_url = bool(record.video_url)

    if is_apx:
        provider_status_label = "apx_seedance"
    elif latest_job_provider:
        provider_status_label = latest_job_provider
    else:
        provider_status_label = "provider_not_configured"

    metadata = {
        "id": record.id,
        "title": record.title,
        "slug": record.slug,
        "output_dir": record.output_dir,
        "model": record.model,
        "mode": record.mode,
        "status": record.status,
        "topic_group_id": record.topic_group_id,
        "version_number": record.version_number,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "has_preview_text": bool(preview_text.strip()),
        "has_overview_cn": bool(overview_text.strip()),
        "has_change_summary_cn": bool(change_summary.strip()),
        "has_web_copy_text": bool(record.web_copy_text and record.web_copy_text.strip()),
        "regenerate_from_history_id": record.regenerate_from_history_id,
        "regenerate_feedback": record.regenerate_feedback,
        "video_status": record.video_status,
        "video_duration_seconds": record.video_duration_seconds,
        "target_duration_seconds": (
            asset_manifest.get("target_duration_seconds")
            if isinstance(asset_manifest, dict) else None
        ),
        "duration_synced": bool(
            isinstance(asset_manifest, dict)
            and asset_manifest.get("target_duration_seconds") is not None
            and (
                record.video_duration_seconds is None
                or record.video_duration_seconds == asset_manifest.get("target_duration_seconds")
            )
        ),
        "duration_source": (
            asset_manifest.get("duration_source")
            if isinstance(asset_manifest, dict) else None
        ),
        "duration_profile": (
            asset_manifest.get("duration_profile")
            if isinstance(asset_manifest, dict) else None
        ),
        "export_schema_version": "video_v0.6.0",
        "legacy_export_schema_version": "video_v0.5.6",
        # v0.5.4 additions
        "video_assets_schema_version": VIDEO_ASSETS_SCHEMA_VERSION,
        "has_video_assets": has_video_assets,
        # v0.6.0 provider state (no API key, no headers, no remote URL).
        "provider_status": provider_status_label,
        "provider": latest_job_provider,
        "provider_job_status": latest_job_status,
        "provider_job_stage": latest_job_stage,
        "provider_job_progress": latest_job_progress,
        "network_call_performed": network_call_performed,
        "real_video_generated": real_video_generated,
        "real_video_downloaded": real_video_downloaded,
        "has_local_video_file": has_local_video_file,
        "has_local_video_cover": has_local_video_cover,
        "video_file_name": "video.mp4" if has_local_video_file else None,
        "video_cover_file_name": "video_cover.jpg" if has_local_video_cover else None,
        "has_remote_video_url": has_remote_video_url,
        "llm_used": bool(asset_manifest.get("llm_used", False)),
        "fallback_used": bool(asset_manifest.get("fallback_used", not asset_manifest.get("llm_used", False))),
        "asset_history_id": asset_manifest.get("history_id"),
        "asset_list": asset_list,
        # v0.5.5 additions
        "provider_contract_schema_version": asset_manifest.get(
            "provider_contract_schema_version", "seedance_contract_v0.5.5"
        ),
        "seedance_contract_ready": bool(asset_manifest.get("seedance_contract_ready", False)),
        "provider_contract_validation_valid": bool(
            asset_manifest.get("provider_contract_validation_valid", False)
        ),
        # v0.5.6 additions
        "seedance_prompt_compiler_version": asset_manifest.get(
            "seedance_prompt_compiler_version", "seedance_prompt_compiler_v0.5.6"
        ),
        "seedance_prompt_profile_version": asset_manifest.get(
            "seedance_prompt_profile_version", "seedance_prompt_profile_v0.5.6"
        ),
        "seedance_prompt_ready": bool(asset_manifest.get("seedance_prompt_ready", False)),
        "seedance_prompt_path": asset_manifest.get(
            "seedance_prompt_path", "video_assets/seedance_prompt.txt"
        ),
        "seedance_negative_prompt_path": asset_manifest.get(
            "seedance_negative_prompt_path", "video_assets/seedance_negative_prompt.txt"
        ),
        "seedance_prompt_debug_path": asset_manifest.get(
            "seedance_prompt_debug_path", "video_assets/seedance_prompt_debug.json"
        ),
        "prompt_source_for_seedance_payload": asset_manifest.get(
            "prompt_source_for_seedance_payload",
            "video_assets/seedance_prompt.txt"
            if asset_manifest.get("seedance_prompt_ready")
            else "video_assets/provider_prompt.txt",
        ),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("raw_text.txt", raw_text)
        zf.writestr("preview.txt", preview_text)
        zf.writestr("overview.txt", overview_bundle)
        zf.writestr("web_copy.txt", web_copy_text)
        zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        # v0.5.4: include the Video Content Asset bundle (read-only). The
        # bundle never includes mp4/mov/video URL/token; the pipeline only
        # writes structured text files.
        if video_assets_dir is not None:
            for asset_path in sorted(video_assets_dir.rglob("*")):
                if not asset_path.is_file():
                    continue
                try:
                    rel = asset_path.relative_to(video_assets_dir)
                except ValueError:
                    continue
                arcname = f"video_assets/{rel.as_posix()}"
                try:
                    with open(asset_path, 'rb') as fp:
                        zf.writestr(arcname, fp.read())
                except Exception as e:
                    print(f"[Video Mode] download_all: skipped asset {asset_path}: {e}")
        # v0.6.0: include the locally-saved mp4 + optional cover when they
        # exist safely under outputs/. The remote APX video_url is never
        # exported.
        if safe_video_path is not None:
            try:
                with open(safe_video_path, 'rb') as fp:
                    zf.writestr("video.mp4", fp.read())
            except Exception as e:
                print(f"[Video Mode] download_all: skipped local video.mp4: {e}")
        if safe_cover_path is not None:
            try:
                with open(safe_cover_path, 'rb') as fp:
                    zf.writestr("video_cover.jpg", fp.read())
            except Exception as e:
                print(f"[Video Mode] download_all: skipped local video_cover.jpg: {e}")
    buf.seek(0)

    safe_slug = record.slug or f"video_{record.id}"
    filename = f"{safe_slug}_video_package.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# =============================================================================
# Video Mode v0.5.3 - Job + Asset endpoints
# =============================================================================


def _resolve_safe_outputs_path(candidate: Optional[str]) -> Optional[Path]:
    """Resolve a stored asset path against project_root/outputs and reject any
    path that escapes that directory. Returns None if the candidate is empty,
    relative to outside outputs, or doesn't exist on disk.
    """
    if not candidate:
        return None
    try:
        p = Path(candidate)
        if not p.is_absolute():
            p = project_root / p
        resolved = p.resolve()
        outputs_root = (project_root / "outputs").resolve()
        try:
            resolved.relative_to(outputs_root)
        except ValueError:
            return None
        if not resolved.exists() or not resolved.is_file():
            return None
        return resolved
    except Exception:
        return None


@app.post("/api/video/history/{history_id}/jobs")
async def video_create_job(
    history_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """v0.5.3: explicitly create a Mock VideoJob for an existing record."""
    record = VideoHistoryRepository.get_history_record(db, current_user.id, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )
    job_dict = _create_video_job_for_record(db, current_user.id, record, record.title or "")
    if job_dict is None:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Failed to create VideoJob"},
        )
    return {"success": True, "job": job_dict}


@app.get("/api/video/history/{history_id}/jobs/latest")
async def video_get_latest_job(
    history_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Return the most recent VideoJob for a Video Mode record, or null."""
    record = VideoHistoryRepository.get_history_record(db, current_user.id, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )
    job = VideoJobRepository.get_latest_job_for_history(db, current_user.id, history_id)
    return {"success": True, "job": job.to_dict() if job else None}


@app.get("/api/video/jobs/{job_id}")
async def video_get_job_detail(
    job_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    job = VideoJobRepository.get_job(db, current_user.id, job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"VideoJob {job_id} not found"},
        )
    return {"success": True, "job": job.to_dict()}


@app.post("/api/video/jobs/{job_id}/refresh")
async def video_refresh_job(
    job_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    """Refresh a job. v0.6.0: APX-aware. v0.6.8: scoped to current_user."""
    job = VideoJobRepository.get_job(db, current_user.id, job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"VideoJob {job_id} not found"},
        )

    if job.status in ("succeeded", "failed", "cancelled"):
        return {"success": True, "job": job.to_dict()}

    if job.provider == "apx_seedance":
        return _refresh_apx_job(db, current_user.id, job)

    if job.provider != "mock":
        return JSONResponse(
            status_code=501,
            content={
                "success": False,
                "error": f"Provider '{job.provider}' is not supported by /refresh.",
            },
        )

    provider = MockVideoProvider()
    response_payload = provider.get_status(job.provider_job_id or "")
    updated = VideoJobRepository.update_job_status(
        db,
        current_user.id,
        job_id=job_id,
        status=response_payload.get("status", "provider_not_configured"),
        stage=response_payload.get("stage", "provider_not_connected"),
        progress=int(response_payload.get("progress") or 0),
        response_payload=response_payload,
    )
    return {"success": True, "job": updated.to_dict() if updated else None}


def _refresh_apx_job(db: Session, user_id: int, job: VideoJob) -> Dict[str, Any]:
    """v0.6.0 APX refresh branch.

    Calls ``ApxSeedanceProvider.poll`` once per request. When status maps to
    ``succeeded``, atomically downloads the mp4 + (optional) cover into the
    record's ``output_dir``, updates the job with sanitized response_json +
    result paths, and syncs the VideoHistory row to ``ready``. The provider
    redacts API keys before returning, and we never persist headers.
    """
    provider = ApxSeedanceProvider()
    if not provider.is_configured():
        # The provider was once configured (we have a job for it) but env
        # vars have since been cleared. Return an unchanged snapshot rather
        # than mutate state.
        return {"success": True, "job": job.to_dict()}

    if not job.provider_job_id:
        updated = VideoJobRepository.update_job_status(
            db,
            user_id,
            job_id=job.id,
            status="failed",
            stage="poll_failed",
            progress=0,
            error_message="Cannot poll: provider_job_id is empty.",
        )
        return {"success": True, "job": updated.to_dict() if updated else None}

    record = VideoHistoryRepository.get_history_record(db, user_id, job.history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "VideoHistory not found for job."},
        )

    poll_result = provider.poll(job.provider_job_id)
    poll_response_clean = _apx_scrub_api_key(
        {k: v for k, v in poll_result.items() if k != "request"}
    )

    status_value = poll_result.get("status") or "running"
    stage_value = poll_result.get("stage") or "running"
    progress_value = int(poll_result.get("progress") or 60)

    # In-flight (pending/running): just persist the snapshot.
    if status_value in ("pending", "running"):
        updated = VideoJobRepository.update_job_status(
            db,
            user_id,
            job_id=job.id,
            status=status_value,
            stage=stage_value,
            progress=progress_value,
            response_payload=poll_response_clean,
        )
        try:
            mapped = _map_job_status_to_video_status(status_value)
            if mapped and record.video_status != mapped:
                record.video_status = mapped
                db.add(record)
                db.commit()
                db.refresh(record)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        return {"success": True, "job": updated.to_dict() if updated else None}

    # Failure path.
    if status_value == "failed":
        err = poll_result.get("error_message") or poll_result.get("message") or "APX failed."
        updated = VideoJobRepository.update_job_status(
            db,
            user_id,
            job_id=job.id,
            status="failed",
            stage="failed",
            progress=int(poll_result.get("progress") or 100),
            response_payload=poll_response_clean,
            error_message=err,
            completed_at=datetime.utcnow(),
        )
        try:
            if record.video_status != "failed":
                record.video_status = "failed"
                db.add(record)
                db.commit()
                db.refresh(record)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        return {"success": True, "job": updated.to_dict() if updated else None}

    # APX 200 but no video_url found in the body.
    if status_value == "succeeded_but_no_video_url":
        updated = VideoJobRepository.update_job_status(
            db,
            user_id,
            job_id=job.id,
            status="succeeded_but_no_video_url",
            stage="video_url_missing",
            progress=int(poll_result.get("progress") or 90),
            response_payload=poll_response_clean,
            error_message="APX status=3 but response.video_url was not found.",
        )
        try:
            if record.video_status != "succeeded_but_no_video_url":
                record.video_status = "succeeded_but_no_video_url"
                db.add(record)
                db.commit()
                db.refresh(record)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        return {"success": True, "job": updated.to_dict() if updated else None}

    # Succeeded — download mp4 (and cover when present).
    output_dir = record.output_dir or ""
    base = Path(output_dir)
    if not base.is_absolute():
        base = project_root / base

    # Path-safety: refuse to write anywhere outside project_root/outputs.
    try:
        outputs_root = (project_root / "outputs").resolve()
        base_resolved = base.resolve()
        base_resolved.relative_to(outputs_root)
    except (ValueError, Exception):
        err_msg = "Refused to download video outside project outputs directory."
        updated = VideoJobRepository.update_job_status(
            db,
            user_id,
            job_id=job.id,
            status="failed",
            stage="download_failed",
            progress=95,
            response_payload=_apx_scrub_api_key(
                {**poll_response_clean, "download_blocked": err_msg}
            ),
            error_message=err_msg,
            completed_at=datetime.utcnow(),
        )
        try:
            if record.video_status != "failed":
                record.video_status = "failed"
                db.add(record)
                db.commit()
                db.refresh(record)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        return {"success": True, "job": updated.to_dict() if updated else None}

    base_str = str(base_resolved)

    video_url = poll_result.get("video_url")
    cover_url = poll_result.get("video_cover_url")

    download_result = provider.download_video(video_url or "", base_str)
    cover_result = provider.download_cover(cover_url, base_str) if cover_url else None

    if not download_result.get("real_video_downloaded"):
        # Treat as a soft failure on the job side: status stays succeeded
        # remotely, but our local state is failed because we couldn't save.
        err_msg = download_result.get("message") or "Video download failed."
        updated = VideoJobRepository.update_job_status(
            db,
            user_id,
            job_id=job.id,
            status="failed",
            stage="download_failed",
            progress=95,
            response_payload=_apx_scrub_api_key(
                {**poll_response_clean, "download_result": download_result}
            ),
            error_message=err_msg,
            completed_at=datetime.utcnow(),
        )
        try:
            if record.video_status != "failed":
                record.video_status = "failed"
                db.add(record)
                db.commit()
                db.refresh(record)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        return {"success": True, "job": updated.to_dict() if updated else None}

    result_video_path = download_result.get("result_video_path")
    result_thumbnail_path = (cover_result or {}).get("result_thumbnail_path")

    # Persist DB rows.
    final_response = _apx_scrub_api_key({
        **poll_response_clean,
        "download_result": {
            "real_video_downloaded": True,
            "result_video_path": result_video_path,
            "result_thumbnail_path": result_thumbnail_path,
            "video_url": video_url,
            "video_cover_url": cover_url,
        },
    })

    updated = VideoJobRepository.update_job_status(
        db,
        user_id,
        job_id=job.id,
        status="succeeded",
        stage="video_ready",
        progress=100,
        response_payload=final_response,
        result_video_path=result_video_path,
        result_video_url=video_url,
        result_thumbnail_path=result_thumbnail_path,
        completed_at=datetime.utcnow(),
    )

    try:
        record.video_status = "ready"
        if result_video_path:
            record.video_file_path = result_video_path
        if result_thumbnail_path:
            record.video_thumbnail_path = result_thumbnail_path
        if video_url:
            record.video_url = video_url
        db.add(record)
        db.commit()
        db.refresh(record)
    except Exception as sync_exc:
        print(f"[Video Mode] Warning: failed to sync video_status to ready: {sync_exc}")
        try:
            db.rollback()
        except Exception:
            pass

    # Optional confirm DELETE.
    try:
        confirm_result = provider.confirm(job.provider_job_id)
        if confirm_result.get("network_call_performed"):
            print(
                f"[Video Mode] APX confirm DELETE for job {job.id}: "
                f"confirmed={confirm_result.get('confirmed')}"
            )
    except Exception as exc:
        print(f"[Video Mode] APX confirm error (non-fatal): {exc}")

    return {"success": True, "job": updated.to_dict() if updated else None}


@app.post("/api/video/jobs/{job_id}/cancel")
async def video_cancel_job(
    job_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    job = VideoJobRepository.get_job(db, current_user.id, job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"VideoJob {job_id} not found"},
        )
    cancelled = VideoJobRepository.mark_cancelled(
        db, current_user.id, job_id=job_id, message="Cancelled by user."
    )
    return {"success": True, "job": cancelled.to_dict() if cancelled else None}


# v0.5.5 — Seedance Contract Adapter dry-run endpoints. None of these
# perform any real network call. They exist so the frontend (or a
# future v0.6.0 integration) can preview the contract handshake before
# any real Seedance API is connected.
@app.get("/api/video/history/{history_id}/provider-contract")
async def video_get_provider_contract(
    history_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    record = VideoHistoryRepository.get_history_record(db, current_user.id, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )

    # v0.6.4 — image_video records have no Seedance contract assets to
    # surface. Build the panel payload directly from image_video metadata
    # (image2_called / content_llm_called / image2 success/total / final
    # mp4 availability) so the frontend's Generation Evidence panel shows
    # accurate values without falling back to "all No".
    if (record.generation_method or "seedance_video") == "image_video":
        meta_blob: Dict[str, Any] = {}
        try:
            if record.metadata_json:
                meta_blob = json.loads(record.metadata_json) or {}
        except Exception:
            meta_blob = {}
        iv = (meta_blob.get("image_video") or {}) if isinstance(meta_blob, dict) else {}
        image2_called = bool(iv.get("llm_used") is not None and (
            iv.get("content_source") == "llm"
            or meta_blob.get("media_api_called")
            or meta_blob.get("image2_called")
        ))
        # Prefer the explicit flags written by _build_image_video_metadata_json.
        media_called = bool(meta_blob.get("media_api_called"))
        content_llm = bool(meta_blob.get("content_llm_called"))
        image2_called = bool(meta_blob.get("image2_called"))
        image2_succeeded = int(meta_blob.get("image2_succeeded") or 0)
        image2_failed = int(meta_blob.get("image2_failed") or 0)
        image2_requested = int(meta_blob.get("image2_requested") or 0)
        safe_video_path = _resolve_safe_outputs_path(record.video_file_path)
        final_video_available = (
            record.video_status == "ready"
            and bool(record.video_file_path)
            and safe_video_path is not None
        )
        image_video_payload = {
            "duration_seconds": iv.get("duration_seconds") or record.video_duration_seconds,
            "slide_count": iv.get("slide_count"),
            "content_source": iv.get("content_source"),
            "content_llm_called": content_llm,
            "media_api_called": media_called,
            "image2_called": image2_called,
            "image2_succeeded": image2_succeeded,
            "image2_failed": image2_failed,
            "image2_requested": image2_requested,
            "llm_model": iv.get("llm_model"),
            # v0.6.8.4 — pull TTS metadata from the persisted image_video
            # blob so historical records served via provider-contract
            # also reflect the real edge-tts state.
            "has_audio": bool(iv.get("has_audio") or meta_blob.get("has_audio")),
            "tts_status": iv.get("tts_status") or "unknown",
            "voiceover_source": iv.get("voiceover_source") or "none",
        }
        return {
            "success": True,
            "history_id": history_id,
            "generation_method": "image_video",
            "real_provider_configured": media_called,
            "network_call_performed": bool(media_called or content_llm),
            "real_video_generated": record.video_status == "ready",
            "real_video_downloaded": False,
            "image_video": image_video_payload,
            "generation_evidence": {
                "route": "image_video",
                "media_api_called": media_called,
                "content_llm_called": content_llm,
                "real_api_call": media_called,
                "seedance_called": False,
                "apx_called": False,
                "image2_called": image2_called,
                "image2_succeeded": image2_succeeded,
                "image2_failed": image2_failed,
                "image2_requested": image2_requested,
                "tts_called": bool(meta_blob.get("tts_called")),
                "tts_status": iv.get("tts_status") or "unknown",
                "voiceover_source": iv.get("voiceover_source") or "none",
                "has_audio": bool(iv.get("has_audio") or meta_blob.get("has_audio")),
                "llm_used_for_text": bool(iv.get("llm_used")),
                "llm_model": iv.get("llm_model"),
                "local_slides_generated": True,
                "ffmpeg_composed": final_video_available,
                "final_video_available": final_video_available,
            },
        }

    project_root = Path(__file__).resolve().parent.parent
    output_dir = record.output_dir or ""
    candidate_dir: Optional[Path] = None
    if output_dir:
        p = Path(output_dir)
        if not p.is_absolute():
            p = project_root / p
        if (p / "video_assets").exists():
            candidate_dir = p / "video_assets"

    def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    provider_request_preview = None
    seedance_payload_preview = None
    provider_contract_validation = None
    provider_lifecycle_preview = None
    asset_paths: Dict[str, str] = {}
    seedance_prompt_text = ""
    seedance_negative_prompt_text = ""
    seedance_prompt_debug = None
    if candidate_dir is not None:
        for key, name in [
            ("provider_request_preview", "provider_request_preview.json"),
            ("seedance_payload_preview", "seedance_payload_preview.json"),
            ("provider_contract_validation", "provider_contract_validation.json"),
            ("provider_lifecycle_preview", "provider_lifecycle_preview.json"),
            ("seedance_prompt", "seedance_prompt.txt"),
            ("seedance_negative_prompt", "seedance_negative_prompt.txt"),
            ("seedance_prompt_debug", "seedance_prompt_debug.json"),
        ]:
            fp = candidate_dir / name
            if fp.exists():
                asset_paths[key] = str(fp)
        provider_request_preview = _safe_load_json(candidate_dir / "provider_request_preview.json")
        seedance_payload_preview = _safe_load_json(candidate_dir / "seedance_payload_preview.json")
        provider_contract_validation = _safe_load_json(candidate_dir / "provider_contract_validation.json")
        provider_lifecycle_preview = _safe_load_json(candidate_dir / "provider_lifecycle_preview.json")
        seedance_prompt_debug = _safe_load_json(candidate_dir / "seedance_prompt_debug.json")
        try:
            sp = candidate_dir / "seedance_prompt.txt"
            if sp.exists():
                with open(sp, "r", encoding="utf-8") as f:
                    seedance_prompt_text = f.read()
        except Exception:
            seedance_prompt_text = ""
        try:
            sn = candidate_dir / "seedance_negative_prompt.txt"
            if sn.exists():
                with open(sn, "r", encoding="utf-8") as f:
                    seedance_negative_prompt_text = f.read()
        except Exception:
            seedance_negative_prompt_text = ""

    contract_ready = bool(
        provider_contract_validation and provider_contract_validation.get("valid")
    )
    prompt_compiler_ready = bool(seedance_prompt_text.strip())

    # v0.6.0: surface live VideoJob state and APX configuration. We never
    # return the API key, request headers, or the remote APX video_url.
    latest_job = VideoJobRepository.get_latest_job_for_history(db, current_user.id, history_id)
    latest_job_provider = latest_job.provider if latest_job else None
    latest_job_status = latest_job.status if latest_job else None
    latest_job_stage = latest_job.stage if latest_job else None
    latest_job_progress = latest_job.progress if latest_job else None
    real_provider_configured = bool(ApxSeedanceProvider().is_configured())
    is_apx_job = latest_job_provider == "apx_seedance"

    # v0.6.2-hotfix — Real-API-call evidence is *positive* only: an APX
    # request actually went out. Never infer Yes from "provider == apx".
    # The block_status set below is the explicit "submission was refused"
    # set; a job in any of these states proves no APX HTTP call was made.
    BLOCKED_STATUSES = {
        "blocked_prompt_quality",
        "blocked_fallback_prompt",
        "blocked_before_submit",
        "provider_not_configured",
        "failed_prompt_quality",
    }
    network_call_performed = False
    if latest_job is not None and is_apx_job and latest_job_status not in BLOCKED_STATUSES:
        # Look for hard evidence in the persisted response_payload first.
        resp_payload = {}
        try:
            raw_resp = getattr(latest_job, "response_payload", None) or {}
            if isinstance(raw_resp, dict):
                resp_payload = raw_resp
        except Exception:
            resp_payload = {}
        if resp_payload.get("network_call_performed") is True:
            network_call_performed = True
        elif any(
            resp_payload.get(k) for k in ("http_status", "raw_status", "video_url")
        ):
            network_call_performed = True
        elif latest_job.provider_job_id:
            # The job has a real provider_job_id only after a successful
            # submit returned an APX task id.
            network_call_performed = True

    real_video_generated = bool(
        record.video_status == "ready" or latest_job_status == "succeeded"
    )
    safe_video_path = _resolve_safe_outputs_path(record.video_file_path)
    real_video_downloaded = bool(record.video_file_path) and safe_video_path is not None

    # v0.6.2 — Provider Evidence summary. Carefully redacted: never returns
    # API keys, full signed video URLs, request headers, or absolute disk
    # paths. ``has_remote_video_url`` is the safe replacement for the URL.
    prompt_quality_block = None
    if isinstance(seedance_prompt_debug, dict):
        prompt_quality_block = seedance_prompt_debug.get("prompt_quality") or {}
    quality_passed = bool(prompt_quality_block and prompt_quality_block.get("passed"))
    quality_reasons_full = (
        list(prompt_quality_block.get("reasons") or [])
        if isinstance(prompt_quality_block, dict)
        else []
    )
    has_remote_video_url = False
    block_reason_for_panel: Optional[str] = None
    if latest_job is not None:
        try:
            resp = (latest_job.response_payload or {}) if hasattr(latest_job, 'response_payload') else {}
            if isinstance(resp, dict):
                if resp.get("video_url"):
                    has_remote_video_url = True
                if resp.get("block_reason"):
                    block_reason_for_panel = str(resp.get("block_reason"))
        except Exception:
            pass
        if not block_reason_for_panel and getattr(latest_job, "error_message", None):
            block_reason_for_panel = latest_job.error_message
    duration_for_evidence = None
    if latest_job is not None:
        duration_for_evidence = getattr(latest_job, "duration_seconds", None)
    if duration_for_evidence is None:
        duration_for_evidence = record.video_duration_seconds
    provider_job_id_for_panel = getattr(latest_job, "provider_job_id", None) if latest_job else None
    local_video_filename: Optional[str] = None
    if record.video_file_path:
        try:
            local_video_filename = Path(record.video_file_path).name
        except Exception:
            local_video_filename = None

    provider_evidence = {
        "provider": latest_job_provider or ("apx_seedance" if real_provider_configured else "mock"),
        "real_api_call": network_call_performed,
        "provider_job_id": provider_job_id_for_panel,
        "job_status": latest_job_status,
        "has_remote_video_url": has_remote_video_url,
        "real_video_downloaded": real_video_downloaded,
        "real_video_available": bool(record.video_file_path) and safe_video_path is not None,
        "local_video_filename": local_video_filename,
        "duration_seconds": duration_for_evidence,
        "prompt_quality_passed": quality_passed,
        "prompt_quality_reasons": quality_reasons_full,
        "block_reason": block_reason_for_panel,
    }

    return {
        "success": True,
        "history_id": history_id,
        "future_provider": "apx_seedance" if real_provider_configured else "seedance",
        "real_provider_configured": real_provider_configured,
        "latest_job_provider": latest_job_provider,
        "latest_job_status": latest_job_status,
        "latest_job_stage": latest_job_stage,
        "latest_job_progress": latest_job_progress,
        "contract_ready": contract_ready,
        "prompt_compiler_ready": prompt_compiler_ready,
        "prompt_compiler_version": (
            (seedance_prompt_debug or {}).get("compiler_version")
            if seedance_prompt_debug
            else None
        ),
        "network_call_performed": network_call_performed,
        "real_video_generated": real_video_generated,
        "real_video_downloaded": real_video_downloaded,
        "provider_evidence": provider_evidence,
        "provider_request_preview": provider_request_preview,
        "seedance_payload_preview": seedance_payload_preview,
        "provider_contract_validation": provider_contract_validation,
        "provider_lifecycle_preview": provider_lifecycle_preview,
        "seedance_prompt": seedance_prompt_text,
        "seedance_negative_prompt": seedance_negative_prompt_text,
        "seedance_prompt_debug": seedance_prompt_debug,
        "asset_paths": asset_paths,
        "readiness_summary": {
            "has_provider_request_preview": provider_request_preview is not None,
            "has_seedance_payload_preview": seedance_payload_preview is not None,
            "has_provider_contract_validation": provider_contract_validation is not None,
            "has_provider_lifecycle_preview": provider_lifecycle_preview is not None,
            "has_seedance_prompt": prompt_compiler_ready,
            "has_seedance_negative_prompt": bool(seedance_negative_prompt_text.strip()),
            "has_seedance_prompt_debug": seedance_prompt_debug is not None,
            "contract_ready": contract_ready,
            "prompt_compiler_ready": prompt_compiler_ready,
            "real_provider_configured": real_provider_configured,
        },
    }


@app.post("/api/video/jobs/{job_id}/dry-run-submit")
async def video_dry_run_submit(
    job_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    job = VideoJobRepository.get_job(db, current_user.id, job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"VideoJob {job_id} not found"},
        )
    from web.video_providers.seedance_contract_adapter import SeedanceContractAdapter
    adapter = SeedanceContractAdapter()
    result = adapter.dry_run_submit({})
    return {"success": True, "job_id": job_id, "dry_run": result}


@app.post("/api/video/jobs/{job_id}/dry-run-poll")
async def video_dry_run_poll(
    job_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    job = VideoJobRepository.get_job(db, current_user.id, job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"VideoJob {job_id} not found"},
        )
    from web.video_providers.seedance_contract_adapter import SeedanceContractAdapter
    adapter = SeedanceContractAdapter()
    result = adapter.dry_run_poll(job.provider_job_id or "")
    return {"success": True, "job_id": job_id, "dry_run": result}


@app.post("/api/video/jobs/{job_id}/dry-run-download")
async def video_dry_run_download(
    job_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Dict[str, Any]:
    job = VideoJobRepository.get_job(db, current_user.id, job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"VideoJob {job_id} not found"},
        )
    from web.video_providers.seedance_contract_adapter import SeedanceContractAdapter
    adapter = SeedanceContractAdapter()
    result = adapter.dry_run_download(job.provider_job_id or "")
    return {"success": True, "job_id": job_id, "dry_run": result}


@app.get("/api/video/history/{history_id}/asset/video")
async def video_asset_video(
    history_id: int,
    download: bool = False,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Any:
    """Serve the video asset for a Video Mode record, if and only if a real
    file exists under project_root/outputs.

    v0.6.0 download hotfix: the optional ``download`` query parameter
    (``?download=1``) instructs FastAPI to set Content-Disposition with a
    safe slug-derived filename so the single-file Download button can
    trigger a real save dialog. The streamed bytes are unchanged; only the
    filename header changes. Local absolute paths are never exposed.
    """
    record = VideoHistoryRepository.get_history_record(db, current_user.id, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )

    candidate = record.video_file_path
    if not candidate:
        latest_job = VideoJobRepository.get_latest_job_for_history(db, current_user.id, history_id)
        if latest_job:
            candidate = latest_job.result_video_path

    safe_path = _resolve_safe_outputs_path(candidate)
    if not safe_path:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Video asset is not available."},
        )

    if download:
        raw_slug = (record.slug or "").strip()
        safe_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_slug).strip("._") if raw_slug else ""
        download_filename = f"{safe_slug}.mp4" if safe_slug else "video.mp4"
        return FileResponse(
            str(safe_path),
            media_type="video/mp4",
            filename=download_filename,
        )

    return FileResponse(str(safe_path), media_type="video/mp4")


@app.get("/api/video/history/{history_id}/asset/thumbnail")
async def video_asset_thumbnail(
    history_id: int,
    db: Session = Depends(get_video_db),
    current_user=Depends(require_active_user),
) -> Any:
    """Serve the thumbnail asset for a Video Mode record."""
    record = VideoHistoryRepository.get_history_record(db, current_user.id, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )

    candidate = record.video_thumbnail_path
    if not candidate:
        latest_job = VideoJobRepository.get_latest_job_for_history(db, current_user.id, history_id)
        if latest_job:
            candidate = latest_job.result_thumbnail_path

    safe_path = _resolve_safe_outputs_path(candidate)
    if not safe_path:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Thumbnail asset is not available."},
        )

    suffix = safe_path.suffix.lower()
    media_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    media_type = media_map.get(suffix, "application/octet-stream")
    return FileResponse(str(safe_path), media_type=media_type)


# =============================================================================
# Diagnostics
# =============================================================================


@app.get("/api/video/diagnostics/ffmpeg")
async def video_diagnostics_ffmpeg(
    admin=Depends(require_admin),
) -> Dict[str, Any]:
    """v0.6.3 stabilization — read-only FFmpeg discovery report.

    Reuses ``image_video_pipeline.resolve_ffmpeg_binary()`` so the
    diagnostics endpoint and the production rendering path agree on which
    locations were probed and which one was selected. Calls no external
    APIs, never modifies any file, and never reads or returns API keys.
    When ffmpeg is found, the first line of ``ffmpeg -version`` is included
    so the operator can confirm the build.
    """
    from web.image_video_pipeline import resolve_ffmpeg_binary

    found, diagnostics = resolve_ffmpeg_binary()
    version_line: Optional[str] = None
    if found:
        try:
            proc = subprocess.run(
                [found, "-version"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0 and proc.stdout:
                version_line = proc.stdout.splitlines()[0].strip()
        except Exception:
            version_line = None
    payload: Dict[str, Any] = {
        "found": bool(found),
        "path": diagnostics.get("path"),
        "checked_paths": diagnostics.get("checked_paths") or [],
        "server_path_env": diagnostics.get("server_path_env"),
    }
    if found:
        payload["version"] = version_line
    else:
        payload["install_hint"] = diagnostics.get(
            "install_hint", "macOS: brew install ffmpeg"
        )
    return {"success": True, "ffmpeg": payload}


# =============================================================================
# Health
# =============================================================================


@app.get("/api/health")
async def health_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Health check endpoint"""
    from sqlalchemy import text

    database_status = "ok"
    try:
        # Test database connection (SQLAlchemy 2.0 requires text() wrapper)
        db.execute(text("SELECT 1"))
    except Exception:
        database_status = "error"

    # v0.5.1: also report Video Mode database health, with its own session.
    video_database_status = "ok"
    try:
        from web.db import VideoSessionLocal
        vdb = VideoSessionLocal()
        try:
            vdb.execute(text("SELECT 1"))
        finally:
            vdb.close()
    except Exception:
        video_database_status = "error"

    return {
        "status": "ok",
        "project_root": str(project_root),
        "env_loaded": env_path.exists(),
        "database": database_status,
        "video_database": video_database_status,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
