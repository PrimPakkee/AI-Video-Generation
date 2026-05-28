#!/usr/bin/env python3
"""
AI Video Prompt Generator - Web Interface
FastAPI backend for generating NotebookLM prompts via web UI
"""

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

app = FastAPI(title="AI Video Prompt Generator")

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database tables on startup"""
    init_db()

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
        Streaming zip file containing raw_text.txt, preview.txt, overview.txt
    """
    from fastapi.responses import StreamingResponse
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
                    import json
                    with open(topic_json_file, 'r', encoding='utf-8') as f:
                        topic_data = json.load(f)
                        core_concept = topic_data.get('core_concept')
            except:
                pass

            overview_cn = generate_fallback_overview(record.title, core_concept)

        # Add change_summary_cn if available
        if record.change_summary_cn:
            overview_cn = f"{overview_cn}\n\n本次生成新增或改动的内容\n\n{record.change_summary_cn}"

        # Create zip in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add raw_text.txt
            zip_file.writestr('raw_text.txt', raw_text)

            # Add preview.txt
            zip_file.writestr('preview.txt', preview_text)

            # Add overview.txt
            zip_file.writestr('overview.txt', overview_cn)

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
            return {
                "success": True,
                "has_review": False,
                "status": "stale",
                "review": None
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

        debug_info = {
            "success": True,
            "history_id": history_id,
            "history_info": {
                "prompt_id": record.prompt_id,
                "version": record.version,
                "prompt_hash": record.prompt_hash,
                "created_at": record.created_at.isoformat() if record.created_at else None,
                "updated_at": record.updated_at.isoformat() if record.updated_at else None
            }
        }

        if review:
            # Review record exists
            debug_info["review_record"] = {
                "id": review.id,
                "status": review.status,
                "schema_version": review.review_schema_version,
                "created_at": review.created_at.isoformat() if review.created_at else None,
                "updated_at": review.updated_at.isoformat() if review.updated_at else None,
                "error_message": review.error_message if hasattr(review, 'error_message') else None
            }

            # Parse review JSON
            if review.review_json:
                try:
                    review_data = json.loads(review.review_json)
                    debug_info["review_data"] = review_data
                    debug_info["review_json_length"] = len(review.review_json)
                except Exception as parse_error:
                    debug_info["review_data"] = None
                    debug_info["review_json_raw"] = review.review_json[:1000]  # First 1000 chars
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


@app.get("/api/health")
async def health_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Health check endpoint"""
    database_status = "ok"
    try:
        # Test database connection
        db.execute("SELECT 1")
    except Exception:
        database_status = "error"

    return {
        "status": "ok",
        "project_root": str(project_root),
        "env_loaded": env_path.exists(),
        "database": database_status
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
