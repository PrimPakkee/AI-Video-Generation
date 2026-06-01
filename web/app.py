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
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

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
from web.video_providers import MockVideoProvider

app = FastAPI(title="AI Video Prompt Generator")

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database tables on startup"""
    init_db()
    # v0.5.1: initialize the independent Video Mode database. This only
    # creates tables in data/video_history.db; it never modifies the
    # Prompt Mode database (data/prompt_history.db).
    init_video_db()

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
async def serve_index():
    """Serve the main HTML page"""
    index_file = static_dir / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_file)


@app.post("/api/generate", response_model=GenerateResponse)
async def generate_prompt(request: GenerateRequest, db: Session = Depends(get_db)) -> JSONResponse:
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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get prompt history list (non-deleted, latest version per group)

    Args:
        limit: Maximum number of records to return
        q: Optional search query for title
        date_filter: Optional date filter (all, 1h, 3h, today, yesterday, 7d, 30d)
        db: Database session

    Returns:
        List of history records (without full prompt text) with version counts
    """
    try:
        records = PromptHistoryRepository.list_history_records(
            db, limit=limit, q=q, date_filter=date_filter
        )

        items = []
        for record in records:
            item = record.to_dict(include_prompt=False)

            # Add version count
            version_count = PromptHistoryRepository.get_version_count(db, record.topic_group_id)
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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get a single prompt history record by ID (including deleted)

    Args:
        history_id: History record ID
        db: Database session

    Returns:
        Full history record including prompt text and version count
    """
    try:
        record = PromptHistoryRepository.get_history_record(db, history_id)

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
        version_count = PromptHistoryRepository.get_version_count(db, record.topic_group_id)
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
    db: Session = Depends(get_db)
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
            db, history_id, request.view, request.content
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
                PromptReviewRepository.mark_review_stale(db, history_id)
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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Pin a history record

    Args:
        history_id: History record ID to pin
        db: Database session

    Returns:
        Success response with updated item
    """
    try:
        record = PromptHistoryRepository.pin_history_record(db, history_id)

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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Unpin a history record

    Args:
        history_id: History record ID to unpin
        db: Database session

    Returns:
        Success response with updated item
    """
    try:
        record = PromptHistoryRepository.unpin_history_record(db, history_id)

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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Delete a history record (legacy - for backward compatibility)

    Args:
        history_id: History record ID to delete
        db: Database session

    Returns:
        Success response
    """
    try:
        deleted = PromptHistoryRepository.delete_history_record(db, history_id)

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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get all versions of a topic group

    Args:
        topic_group_id: Topic group ID
        db: Database session

    Returns:
        List of all versions
    """
    try:
        versions = PromptHistoryRepository.get_versions_by_group(db, topic_group_id)

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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Rename all versions in a topic group

    Args:
        topic_group_id: Topic group ID
        request: New title
        db: Database session

    Returns:
        Updated latest version item
    """
    try:
        latest = PromptHistoryRepository.rename_history_group(db, topic_group_id, request.title)

        if not latest:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Topic group {topic_group_id} not found"
                }
            )

        # Add version count
        version_count = PromptHistoryRepository.get_version_count(db, topic_group_id)
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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Soft delete a topic group (move to trash)

    Args:
        topic_group_id: Topic group ID
        db: Database session

    Returns:
        Success response
    """
    try:
        deleted = PromptHistoryRepository.soft_delete_history_group(db, topic_group_id)

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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get trash list (deleted records, latest version per group)

    Args:
        limit: Maximum number of records to return
        q: Optional search query for title
        db: Database session

    Returns:
        List of deleted records
    """
    try:
        records = PromptHistoryRepository.list_trash_records(db, limit=limit, q=q)

        items = []
        for record in records:
            item = record.to_dict(include_prompt=False)

            # Add version count
            version_count = PromptHistoryRepository.get_version_count(db, record.topic_group_id)
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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Permanently delete a topic group (hard delete from database)

    Args:
        topic_group_id: Topic group ID
        db: Database session

    Returns:
        Success response
    """
    try:
        deleted = PromptHistoryRepository.permanently_delete_history_group(db, topic_group_id)

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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Restore a topic group from trash

    Args:
        topic_group_id: Topic group ID
        db: Database session

    Returns:
        Success response
    """
    try:
        restored = PromptHistoryRepository.restore_history_group(db, topic_group_id)

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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Favorite a topic group

    Args:
        topic_group_id: Topic group ID
        db: Database session

    Returns:
        Success response with updated item
    """
    try:
        latest = PromptHistoryRepository.favorite_history_group(db, topic_group_id)

        if not latest:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Topic group {topic_group_id} not found"
                }
            )

        # Add version count
        version_count = PromptHistoryRepository.get_version_count(db, topic_group_id)
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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Unfavorite a topic group

    Args:
        topic_group_id: Topic group ID
        db: Database session

    Returns:
        Success response with updated item
    """
    try:
        latest = PromptHistoryRepository.unfavorite_history_group(db, topic_group_id)

        if not latest:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Topic group {topic_group_id} not found"
                }
            )

        # Add version count
        version_count = PromptHistoryRepository.get_version_count(db, topic_group_id)
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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get favorite list (latest version per group)

    Args:
        limit: Maximum number of records to return
        q: Optional search query for title
        db: Database session

    Returns:
        List of favorite records
    """
    try:
        records = PromptHistoryRepository.list_favorite_records(db, limit=limit, q=q)

        items = []
        for record in records:
            item = record.to_dict(include_prompt=False)

            # Add version count
            version_count = PromptHistoryRepository.get_version_count(db, record.topic_group_id)
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
    db: Session = Depends(get_db)
):
    """
    Download all prompt views as a zip package

    Args:
        history_id: History record ID
        db: Database session

    Returns:
        Streaming zip file containing raw_text.txt, preview.txt, overview.txt,
        ai_review.md, and metadata.json
    """
    from fastapi.responses import StreamingResponse
    from web.db.models import PromptReview
    import io
    import zipfile

    try:
        # Get history record
        record = PromptHistoryRepository.get_history_record(db, history_id)

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
                .filter(PromptReview.history_id == history_id)
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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Regenerate prompt based on current version and user feedback

    Args:
        history_id: Current history record ID
        request: Regenerate request with feedback
        db: Database session

    Returns:
        New version record with regenerated content
    """
    try:
        # Get current record
        current_record = PromptHistoryRepository.get_history_record(db, history_id)

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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get AI Review for a specific prompt version (read-only, never generates)

    Args:
        history_id: History record ID
        db: Database session

    Returns:
        Review data with status: none/generating/completed/failed/stale
    """
    try:
        from web.db.repository_review import PromptReviewRepository
        from web.db.models import PromptReview

        # Check if history record exists
        record = PromptHistoryRepository.get_history_record(db, history_id)
        if not record:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"History record {history_id} not found"
                }
            )

        # Get review status
        status = PromptReviewRepository.get_review_status(db, history_id)

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
                    PromptReview.history_id == history_id
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
            review = PromptReviewRepository.get_review_by_history_id(db, history_id)
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
            review_data = PromptReviewRepository.get_review_json(db, history_id)

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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get detailed debug information for AI Review (for development/debugging only)

    Returns:
        - Review database record (status, timestamps, error messages)
        - Raw review JSON
        - History record info (version, prompt hash)
        - Schema version
    """
    try:
        from web.db.repository_review import PromptReviewRepository

        # Check if history record exists
        record = PromptHistoryRepository.get_history_record(db, history_id)
        if not record:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"History record {history_id} not found"
                }
            )

        # Get review record (if exists)
        review = PromptReviewRepository.get_review_by_history_id(db, history_id)

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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Generate AI Review for a specific prompt version (idempotent)

    Args:
        history_id: History record ID
        force: Force regenerate even if review exists (default: False)
        db: Database session

    Returns:
        Review data or status
    """
    try:
        from web.db.repository_review import PromptReviewRepository
        from scripts.llm_topic_enhancer import LLMTopicEnhancer

        current_schema = 'v0.4.6.9_strict'

        # Check if history record exists
        record = PromptHistoryRepository.get_history_record(db, history_id)
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
        status = PromptReviewRepository.get_review_status(db, history_id, current_schema)

        # If review is completed and current, return it directly (idempotent)
        if status == 'completed' and not force:
            review_data = PromptReviewRepository.get_review_json(db, history_id)
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
            review = PromptReviewRepository.get_review_by_history_id(db, history_id)
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
            PromptReviewRepository.update_review_status(db, history_id, 'generating')

        # Call LLM to generate review
        try:
            enhancer = LLMTopicEnhancer()
            review_data = enhancer.review_prompt(raw_prompt, dry_run=False)

            if not review_data:
                # Mark as failed
                PromptReviewRepository.mark_review_failed(
                    db=db,
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


class VideoUpdateContentRequest(BaseModel):
    """Request body for updating Video Mode content."""
    view: str = Field(..., pattern='^(raw|preview|overview|web_copy)$')
    content: str = Field(..., min_length=0)


class VideoRegenerateRequest(BaseModel):
    feedback: str = Field(..., min_length=1, max_length=2000)


def _create_mock_video_job_for_record(
    db: Session,
    record: VideoHistory,
    request_title: str,
) -> Optional[Dict[str, Any]]:
    """v0.5.3: create a Mock VideoJob for a freshly-saved Video Mode record
    and return its `to_dict()` payload. Returns None on failure (the caller
    proceeds without a job rather than erroring the user-facing flow).

    The Mock provider performs no network call and yields a
    `provider_not_configured` shell. This function only writes to the Video
    Mode database; it never touches Prompt Mode tables.
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

        now = datetime.utcnow()
        job = VideoJobRepository.create_job(
            db=db,
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
        )
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
    """v0.5.3: minimal mapping from VideoJob.status to VideoHistory.video_status.

    For v0.5.3 the only status produced in practice is `provider_not_configured`
    (Mock provider). The other branches keep the mapping forward-compatible.
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
    return None


@app.post("/api/video/generate")
async def video_generate(
    request: VideoGenerateRequest,
    db: Session = Depends(get_video_db),
) -> JSONResponse:
    """
    Generate a Video Mode entry.

    v0.5.1 reuses the existing Prompt generation script
    (scripts/generate_video_package.py) so the underlying NotebookLM-style
    Prompt is identical. The result is saved to the Video Mode database
    (data/video_history.db) only. No real video provider is invoked.
    """
    title = request.title.strip()
    if not title:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Title cannot be empty"},
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
            record = VideoHistoryRepository.create_history_record(
                db=db,
                title=title,
                slug=slug,
                prompt_text=prompt_content,
                output_dir=str(output_dir),
                model=model,
                mode=mode,
                status='success',
                overview_cn=overview_cn,
                web_copy_text=None,
            )
            # v0.5.3: auto-create a Mock VideoJob so the frontend can render a
            # provider_not_configured status panel. No real provider invoked.
            video_job_dict = _create_mock_video_job_for_record(db, record, title)
            return JSONResponse(content={
                'success': True,
                'id': record.id,
                'history_id': record.id,
                'title': title,
                'slug': slug,
                'topic_group_id': record.topic_group_id,
                'version_number': record.version_number,
                'prompt': prompt_content,
                'raw_text': prompt_content,
                'prompt_text': prompt_content,
                'preview_text': record.preview_text,
                'overview_cn': overview_cn,
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
) -> Dict[str, Any]:
    try:
        records = VideoHistoryRepository.list_history_records(
            db, limit=limit, q=q, date_filter=date_filter,
        )
        items = []
        for r in records:
            item = r.to_dict(include_prompt=False)
            item['version_count'] = VideoHistoryRepository.get_version_count(db, r.topic_group_id)
            items.append(item)
        return {"success": True, "items": items}
    except Exception as e:
        return {"success": False, "error": str(e), "items": []}


@app.get("/api/video/history/{history_id}")
async def video_get_history_by_id(
    history_id: int,
    db: Session = Depends(get_video_db),
) -> Dict[str, Any]:
    try:
        record = VideoHistoryRepository.get_history_record(db, history_id)
        if not record:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": f"Video history record {history_id} not found"},
            )
        item = record.to_dict(include_prompt=True)
        item['version_count'] = VideoHistoryRepository.get_version_count(db, record.topic_group_id)
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
            db, history_id=history_id, view=view, content=content,
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
) -> Dict[str, Any]:
    """v0.5.1.2: return ``versions`` (matching Prompt Mode's contract) so the
    frontend version dropdown works for Video Mode. ``items`` is preserved
    for older callers that may still consume the original v0.5.1 shape."""
    try:
        versions = VideoHistoryRepository.get_versions_by_group(db, topic_group_id)
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
) -> JSONResponse:
    """
    Regenerate a Video Mode version using the same script as the original
    generate flow. Saves to Video Mode database only.
    """
    record = VideoHistoryRepository.get_history_record(db, history_id)
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
        new_record = VideoHistoryRepository.create_regenerated_version(
            db=db,
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

        # v0.5.3: auto-create a Mock VideoJob for the new version so the UI
        # can show a provider_not_configured status panel after regenerate.
        video_job_dict = _create_mock_video_job_for_record(db, new_record, new_record.title)
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
async def video_pin(history_id: int, db: Session = Depends(get_video_db)) -> Dict[str, Any]:
    record = VideoHistoryRepository.pin_history_record(db, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )
    return {"success": True, "item": record.to_dict(include_prompt=False)}


@app.post("/api/video/history/{history_id}/unpin")
async def video_unpin(history_id: int, db: Session = Depends(get_video_db)) -> Dict[str, Any]:
    record = VideoHistoryRepository.unpin_history_record(db, history_id)
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
) -> Dict[str, Any]:
    """
    v0.5.1.2: Rename a Video Mode topic group.

    Independent from Prompt Mode rename: this endpoint only writes to
    data/video_history.db (via Depends(get_video_db)) and never touches
    Prompt Mode tables. Mirrors the Prompt Mode rename response shape.
    """
    try:
        ok = VideoHistoryRepository.rename_topic_group(db, topic_group_id, request.title)
        if not ok:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Video topic group {topic_group_id} not found",
                },
            )
        # Return latest version as the canonical updated item.
        versions = VideoHistoryRepository.get_versions_by_group(db, topic_group_id)
        latest = max(versions, key=lambda r: r.version_number) if versions else None
        item = latest.to_dict(include_prompt=False) if latest else {}
        if latest:
            item['version_count'] = VideoHistoryRepository.get_version_count(db, topic_group_id)
        return {"success": True, "item": item}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)},
        )


@app.post("/api/video/history/group/{topic_group_id}/trash")
async def video_trash_group(topic_group_id: str, db: Session = Depends(get_video_db)) -> Dict[str, Any]:
    ok = VideoHistoryRepository.soft_delete_history_group(db, topic_group_id)
    if not ok:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Group not found or already deleted"},
        )
    return {"success": True}


@app.post("/api/video/history/group/{topic_group_id}/restore")
async def video_restore_group(topic_group_id: str, db: Session = Depends(get_video_db)) -> Dict[str, Any]:
    ok = VideoHistoryRepository.restore_history_group(db, topic_group_id)
    if not ok:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Group not found in trash"},
        )
    return {"success": True}


@app.delete("/api/video/history/group/{topic_group_id}/permanent")
async def video_permanent_delete_group(topic_group_id: str, db: Session = Depends(get_video_db)) -> Dict[str, Any]:
    ok = VideoHistoryRepository.permanently_delete_history_group(db, topic_group_id)
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
) -> Dict[str, Any]:
    try:
        records = VideoHistoryRepository.list_trash_records(db, limit=limit, q=q)
        return {
            "success": True,
            "items": [r.to_dict(include_prompt=False) for r in records],
        }
    except Exception as e:
        return {"success": False, "error": str(e), "items": []}


@app.post("/api/video/history/group/{topic_group_id}/favorite")
async def video_favorite_group(topic_group_id: str, db: Session = Depends(get_video_db)) -> Dict[str, Any]:
    record = VideoHistoryRepository.favorite_history_group(db, topic_group_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Group not found"},
        )
    return {"success": True, "item": record.to_dict(include_prompt=False)}


@app.post("/api/video/history/group/{topic_group_id}/unfavorite")
async def video_unfavorite_group(topic_group_id: str, db: Session = Depends(get_video_db)) -> Dict[str, Any]:
    record = VideoHistoryRepository.unfavorite_history_group(db, topic_group_id)
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
) -> Dict[str, Any]:
    try:
        records = VideoHistoryRepository.list_favorite_records(db, limit=limit, q=q)
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
) -> Any:
    """
    Read-only Download All for Video Mode.

    Mirrors the v0.4.10 contract for Prompt Mode: package raw_text.txt /
    preview.txt / overview.txt / web_copy.txt / metadata.json. Does NOT touch
    any DB writes; does NOT download/produce any video file. The bundle never
    includes mp4 / mov / video URL or token.
    """
    import io
    import zipfile
    from fastapi.responses import StreamingResponse

    record = VideoHistoryRepository.get_history_record(db, history_id)
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
        "export_schema_version": "video_v0.5.3",
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("raw_text.txt", raw_text)
        zf.writestr("preview.txt", preview_text)
        zf.writestr("overview.txt", overview_bundle)
        zf.writestr("web_copy.txt", web_copy_text)
        zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
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
) -> Dict[str, Any]:
    """v0.5.3: explicitly create a Mock VideoJob for an existing record.

    Used when the Video Mode generate flow could not auto-create a job (e.g.
    older record without a job, or user clicks a future "retry provider"
    affordance). No real provider is contacted.
    """
    record = VideoHistoryRepository.get_history_record(db, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )
    job_dict = _create_mock_video_job_for_record(db, record, record.title or "")
    if job_dict is None:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Failed to create Mock VideoJob"},
        )
    return {"success": True, "job": job_dict}


@app.get("/api/video/history/{history_id}/jobs/latest")
async def video_get_latest_job(
    history_id: int,
    db: Session = Depends(get_video_db),
) -> Dict[str, Any]:
    """Return the most recent VideoJob for a Video Mode record, or null."""
    record = VideoHistoryRepository.get_history_record(db, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )
    job = VideoJobRepository.get_latest_job_for_history(db, history_id)
    return {"success": True, "job": job.to_dict() if job else None}


@app.get("/api/video/jobs/{job_id}")
async def video_get_job_detail(
    job_id: int,
    db: Session = Depends(get_video_db),
) -> Dict[str, Any]:
    job = VideoJobRepository.get_job(db, job_id)
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
) -> Dict[str, Any]:
    """Refresh a job by polling the (mock) provider. v0.5.3 always yields a
    `provider_not_configured` shell — no network call is made."""
    job = VideoJobRepository.get_job(db, job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"VideoJob {job_id} not found"},
        )

    if job.provider != "mock":
        # v0.5.3 ships only the mock provider. Real providers are out of scope.
        return JSONResponse(
            status_code=501,
            content={
                "success": False,
                "error": f"Provider '{job.provider}' is not connected in v0.5.3",
            },
        )

    if job.status in ("succeeded", "failed", "cancelled"):
        return {"success": True, "job": job.to_dict()}

    provider = MockVideoProvider()
    response_payload = provider.get_status(job.provider_job_id or "")
    updated = VideoJobRepository.update_job_status(
        db,
        job_id=job_id,
        status=response_payload.get("status", "provider_not_configured"),
        stage=response_payload.get("stage", "provider_not_connected"),
        progress=int(response_payload.get("progress") or 0),
        response_payload=response_payload,
    )
    return {"success": True, "job": updated.to_dict() if updated else None}


@app.post("/api/video/jobs/{job_id}/cancel")
async def video_cancel_job(
    job_id: int,
    db: Session = Depends(get_video_db),
) -> Dict[str, Any]:
    job = VideoJobRepository.get_job(db, job_id)
    if not job:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"VideoJob {job_id} not found"},
        )
    cancelled = VideoJobRepository.mark_cancelled(
        db, job_id=job_id, message="Cancelled by user."
    )
    return {"success": True, "job": cancelled.to_dict() if cancelled else None}


@app.get("/api/video/history/{history_id}/asset/video")
async def video_asset_video(
    history_id: int,
    db: Session = Depends(get_video_db),
) -> Any:
    """Serve the video asset for a Video Mode record, if and only if a real
    file exists under project_root/outputs. v0.5.3 never produces a real
    video, so this endpoint returns 404 in normal use.
    """
    record = VideoHistoryRepository.get_history_record(db, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )

    candidate = record.video_file_path
    if not candidate:
        latest_job = VideoJobRepository.get_latest_job_for_history(db, history_id)
        if latest_job:
            candidate = latest_job.result_video_path

    safe_path = _resolve_safe_outputs_path(candidate)
    if not safe_path:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Video asset is not available."},
        )

    return FileResponse(str(safe_path), media_type="video/mp4")


@app.get("/api/video/history/{history_id}/asset/thumbnail")
async def video_asset_thumbnail(
    history_id: int,
    db: Session = Depends(get_video_db),
) -> Any:
    """Serve the thumbnail asset for a Video Mode record, with the same
    outputs-only path safety as the video endpoint. 404 when missing.
    """
    record = VideoHistoryRepository.get_history_record(db, history_id)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": f"Video history record {history_id} not found"},
        )

    candidate = record.video_thumbnail_path
    if not candidate:
        latest_job = VideoJobRepository.get_latest_job_for_history(db, history_id)
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
