#!/usr/bin/env python3
"""
Video Mode SQLAlchemy ORM models (v0.5.3)

Defines VideoHistory and VideoJob tables for Video Mode. Strictly isolated
from Prompt Mode tables (prompt_history / prompt_reviews). No real video
provider is invoked from this layer; VideoJob is created via a Mock provider
in v0.5.3 and yields a `provider_not_configured` shell — no network call,
no API key, no real mp4.
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

    # Owning user (v0.6.8+). Logical FK to auth.db users.id; not enforced at
    # the SQLite layer.
    user_id = Column(Integer, nullable=True, index=True)

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

    # v0.6.3 — which generation route produced this record.
    # Allowed values: 'seedance_video' (default, v0.6.2 APX chain) and
    # 'image_video' (v0.6.3 local Pillow + FFmpeg static-image MVP).
    # Older rows are migrated lazily on startup; their default is
    # 'seedance_video' so existing histories continue to behave as before.
    generation_method = Column(
        String(40), nullable=False, default='seedance_video'
    )

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
            'generation_method': self.generation_method or 'seedance_video',
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


class VideoJob(VideoBase):
    """
    Video Mode job record.

    A VideoJob represents one attempt to render a video for a given
    VideoHistory record. v0.5.3 only persists jobs created by the Mock
    provider, which never makes any network call and always returns a
    `provider_not_configured` shell. The columns here are forward-compatible
    with a real provider but no real provider is wired in this version.
    """
    __tablename__ = "video_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Owning user (v0.6.8+). Logical FK to auth.db users.id.
    user_id = Column(Integer, nullable=True, index=True)

    # Foreign key to VideoHistory.id (no DB-level FK to keep migrations simple).
    history_id = Column(Integer, nullable=False, index=True)

    # Provider identification. v0.5.3 only uses 'mock'.
    provider = Column(String(50), nullable=False, default='mock')
    provider_job_id = Column(String(200), nullable=True)

    # Status state machine:
    #   pending / preparing / submitted / running / succeeded / failed
    #   / cancelled / provider_not_configured
    status = Column(String(50), nullable=False, default='pending')

    # Stage finer-grained:
    #   analyzing_topic / generating_prompt / writing_script
    #   / preparing_provider_request / submitting_provider_job
    #   / generating_video / saving_assets / completed
    #   / provider_not_connected / failed
    stage = Column(String(80), nullable=True)

    # 0-100 progress hint (advisory only, not tied to a real renderer).
    progress = Column(Integer, nullable=False, default=0)

    # Snapshot of the provider request payload (JSON-encoded text).
    request_json = Column(Text, nullable=True)
    # Snapshot of the latest provider response (JSON-encoded text).
    response_json = Column(Text, nullable=True)
    # Human-readable error message when status == 'failed'.
    error_message = Column(Text, nullable=True)

    # Result asset paths / URL. v0.5.3 leaves these NULL — no real video.
    result_video_path = Column(String(500), nullable=True)
    result_video_url = Column(String(500), nullable=True)
    result_thumbnail_path = Column(String(500), nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Reserved metadata bag for future provider-specific extensions.
    metadata_json = Column(Text, nullable=True)

    def to_dict(self) -> dict:
        """Convert to a JSON-friendly dict for API responses.

        v0.6.0: safely surface a small set of provider-friendly fields
        (`message`, `http_status`, `raw_status`) extracted from the persisted
        response_json, so the frontend can show the human-readable APX
        message. The full request_json / response_json are NEVER returned,
        and the redaction performed at write time means no API key /
        Authorization header / x-api-key can leak even if read from disk.
        """
        message: str | None = None
        http_status: int | None = None
        raw_status: int | None = None
        try:
            if self.response_json:
                import json as _json
                parsed = _json.loads(self.response_json)
                if isinstance(parsed, dict):
                    msg = parsed.get('message')
                    if isinstance(msg, str):
                        message = msg
                    hs = parsed.get('http_status')
                    if isinstance(hs, int):
                        http_status = hs
                    rs = parsed.get('raw_status')
                    if isinstance(rs, int):
                        raw_status = rs
        except Exception:
            pass

        return {
            'id': self.id,
            'history_id': self.history_id,
            'provider': self.provider,
            'provider_job_id': self.provider_job_id,
            'status': self.status,
            'stage': self.stage,
            'progress': self.progress,
            'error_message': self.error_message,
            'message': message,
            'http_status': http_status,
            'raw_status': raw_status,
            'result_video_path': self.result_video_path,
            'result_video_url': self.result_video_url,
            'result_thumbnail_path': self.result_thumbnail_path,
            'duration_seconds': self.duration_seconds,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<VideoJob(id={self.id}, history_id={self.history_id}, "
            f"provider='{self.provider}', status='{self.status}')>"
        )


Index('idx_video_jobs_history_id', VideoJob.history_id)
Index('idx_video_jobs_history_created', VideoJob.history_id, VideoJob.created_at.desc())
