"""
Database module for AI Video Prompt Generator
"""

from .database import engine, SessionLocal, get_db, init_db
from .models import PromptHistory, PromptReview
from .repository import PromptHistoryRepository
from .repository_review import PromptReviewRepository

# Video Mode (v0.5.3) - independent SQLite database, fully isolated from
# Prompt Mode. The Video Mode imports below MUST NOT touch the Prompt Mode
# tables (prompt_history / prompt_reviews) at import or runtime.
from .video_database import (
    VideoBase,
    VideoSessionLocal,
    get_video_db,
    init_video_db,
    video_engine,
)
from .video_models import VideoHistory, VideoJob
from .video_repository import VideoHistoryRepository
from .video_job_repository import VideoJobRepository

__all__ = [
    # Prompt Mode
    "engine",
    "SessionLocal",
    "get_db",
    "init_db",
    "PromptHistory",
    "PromptReview",
    "PromptHistoryRepository",
    "PromptReviewRepository",
    # Video Mode (v0.5.3)
    "VideoBase",
    "VideoSessionLocal",
    "video_engine",
    "get_video_db",
    "init_video_db",
    "VideoHistory",
    "VideoJob",
    "VideoHistoryRepository",
    "VideoJobRepository",
]
