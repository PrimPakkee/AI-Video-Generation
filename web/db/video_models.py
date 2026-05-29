#!/usr/bin/env python3
"""
Video Mode SQLAlchemy ORM models (v0.5.1)

Defines a single VideoHistory table for Video Mode. Strictly isolated from
Prompt Mode tables (prompt_history / prompt_reviews). No real video provider
is invoked from this layer; video_status is a placeholder column for the
future Video Mode generation pipeline.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from .video_database import VideoBase


class VideoHistory(VideoBase):
    """
    Video Mode history table.

    Mirrors the version-management semantics of PromptHistory (topic_group_id +
    version_number, soft delete, pin, favorite, regenerate-from), but lives in
    its own database file to keep the two modes fully isolated.
    """
    __tablename__ = "video_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # User input + generated slug
    title = Column(String(500), nullable=False, index=True)
    slug = Column(String(200), nullable=False, unique=True, index=True)

    # Generated prompt content (the same NotebookLM-style Prompt as Prompt Mode)
    prompt_text = Column(Text, nullable=False)

    # Output directory path on disk
    output_dir = Column(String(500), nullable=False)

    # Model and mode metadata
    model = Column(String(100), nullable=True)
    mode = Column(String(100), nullable=True, default='video')

    # Lifecycle status of the database record itself (success / failed / etc.)
    status = Column(String(50), nullable=False, default='success')

    # Pin
    is_pinned = Column(Integer, nullable=False, default=0)
    pinned_at = Column(DateTime, nullable=True)

    # Soft delete
    deleted_at = Column(DateTime, nullable=True)

    # Version management
    title_normalized = Column(Text, nullable=True)
    topic_group_id = Column(String(100), nullable=True, index=True)
    version_number = Column(Integer, nullable=False, default=1)

    # Favorite
    is_favorite = Column(Integer, nullable=False, default=0)
    favorite_at = Column(DateTime, nullable=True)

    # Existing Prompt-Mode-style content fields, mirrored for Video Mode
    overview_cn = Column(Text, nullable=True)
    preview_text = Column(Text, nullable=True)
    change_summary_cn = Column(Text, nullable=True)
    regenerate_from_history_id = Column(Integer, nullable=True)
    regenerate_feedback = Column(Text, nullable=True)

    # Web Copy tab content (titles, descriptions, captions, posting copy).
    # v0.5.1 only writes None / empty placeholder strings — real generation is
    # deferred to a later version.
    web_copy_text = Column(Text, nullable=True)

    # Video player placeholder fields. v0.5.1 does not invoke any real video
    # provider, never populates a remote URL, and does not download mp4 / mov.
    # These columns exist only so the schema is stable when the future Video
    # Mode generation pipeline is wired up.
    #   not_generated  - row exists, no video has ever been produced
    #   placeholder    - reserved for a deferred / mock state
    #   ready          - a real video file has been produced (NOT used in v0.5.1)
    #   failed         - attempt failed (NOT used in v0.5.1)
    video_status = Column(String(50), nullable=False, default='not_generated')
    video_file_path = Column(String(500), nullable=True)
    video_url = Column(String(500), nullable=True)
    video_thumbnail_path = Column(String(500), nullable=True)
    video_duration_seconds = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Reserved metadata bag for future Video Mode extensions
    metadata_json = Column(Text, nullable=True)

    def to_dict(self, include_prompt: bool = False) -> dict:
        """Convert to a JSON-friendly dict for API responses."""
        data = {
            'id': self.id,
            'title': self.title,
            'slug': self.slug,
            'output_dir': self.output_dir,
            'model': self.model,
            'mode': self.mode,
            'status': self.status,
            'is_pinned': bool(self.is_pinned),
            'pinned_at': self.pinned_at.isoformat() if self.pinned_at else None,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'topic_group_id': self.topic_group_id,
            'version_number': self.version_number,
            'is_favorite': bool(self.is_favorite),
            'favorite_at': self.favorite_at.isoformat() if self.favorite_at else None,
            'video_status': self.video_status,
            'video_file_path': self.video_file_path,
            'video_url': self.video_url,
            'video_thumbnail_path': self.video_thumbnail_path,
            'video_duration_seconds': self.video_duration_seconds,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_prompt:
            data['prompt'] = self.prompt_text
            data['overview_cn'] = self.overview_cn
            data['preview_text'] = self.preview_text
            data['change_summary_cn'] = self.change_summary_cn
            data['regenerate_feedback'] = self.regenerate_feedback
            data['regenerate_from_history_id'] = self.regenerate_from_history_id
            data['web_copy_text'] = self.web_copy_text

        return data

    def __repr__(self) -> str:
        return f"<VideoHistory(id={self.id}, title='{(self.title or '')[:30]}', slug='{self.slug}')>"


# Common-query indexes
Index('idx_video_created_at_desc', VideoHistory.created_at.desc())
Index('idx_video_title_search', VideoHistory.title)
Index('idx_video_topic_group', VideoHistory.topic_group_id)
