#!/usr/bin/env python3
"""
Video Mode database configuration and session management (v0.5.1)

Independent SQLite database for Video Mode at data/video_history.db.
Strictly isolated from Prompt Mode (data/prompt_history.db).
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Load environment variables (shared with Prompt Mode)
project_root = Path(__file__).parent.parent.parent
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

# Resolve Video Mode database URL.
# Priority:
# 1. VIDEO_DATABASE_URL env var (explicit override)
# 2. Default SQLite file at data/video_history.db
VIDEO_DATABASE_URL = os.getenv('VIDEO_DATABASE_URL')

if not VIDEO_DATABASE_URL:
    data_dir = project_root / 'data'
    data_dir.mkdir(exist_ok=True)
    video_db_path = data_dir / 'video_history.db'
    VIDEO_DATABASE_URL = f'sqlite:///{video_db_path}'

# Create engine for Video Mode (separate from prompt_history.db)
video_connect_args = {}
if VIDEO_DATABASE_URL.startswith('sqlite'):
    video_connect_args = {"check_same_thread": False}

video_engine = create_engine(
    VIDEO_DATABASE_URL,
    connect_args=video_connect_args,
    echo=False,
)

# Independent session factory for Video Mode.
VideoSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=video_engine)

# Independent declarative base for Video Mode tables.
# IMPORTANT: This Base is intentionally separate from web.db.database.Base so that
# Prompt Mode's Base.metadata.create_all() never touches video_history tables, and
# vice versa. Cross-mode mixing is forbidden by the v0.5.1 design.
VideoBase = declarative_base()


def get_video_db():
    """FastAPI dependency for a Video Mode database session."""
    db = VideoSessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_video_db():
    """
    Initialize Video Mode database.

    Read-only safe: only creates tables if they don't exist. Does not call any
    LLM. Does not touch Prompt Mode database. Does not touch outputs/.
    """
    # Import models so VideoBase.metadata is populated before create_all().
    from . import video_models  # noqa: F401  (registers VideoHistory)

    VideoBase.metadata.create_all(bind=video_engine)
