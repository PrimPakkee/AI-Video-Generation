#!/usr/bin/env python3
"""
Video Mode Job Repository (v0.5.3).

Static-method CRUD wrappers around the VideoJob ORM. Operates exclusively on
the Video Mode database (data/video_history.db) via the session injected by
the caller. Never touches Prompt Mode tables.

v0.6.8: every public method takes ``user_id`` as the 2nd positional parameter
and scopes its query by owner.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .video_models import VideoJob


class VideoJobRepository:

    @staticmethod
    def create_job(
        db: Session,
        user_id: int,
        history_id: int,
        provider: str = 'mock',
        provider_job_id: Optional[str] = None,
        status: str = 'pending',
        stage: Optional[str] = None,
        progress: int = 0,
        request_payload: Optional[Dict[str, Any]] = None,
        response_payload: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        result_video_path: Optional[str] = None,
        result_video_url: Optional[str] = None,
        result_thumbnail_path: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        submitted_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> VideoJob:
        job = VideoJob(
            user_id=user_id,
            history_id=history_id,
            provider=provider,
            provider_job_id=provider_job_id,
            status=status,
            stage=stage,
            progress=int(progress or 0),
            request_json=json.dumps(request_payload, ensure_ascii=False) if request_payload is not None else None,
            response_json=json.dumps(response_payload, ensure_ascii=False) if response_payload is not None else None,
            error_message=error_message,
            result_video_path=result_video_path,
            result_video_url=result_video_url,
            result_thumbnail_path=result_thumbnail_path,
            duration_seconds=duration_seconds,
            metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
            submitted_at=submitted_at,
            completed_at=completed_at,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def get_job(db: Session, user_id: int, job_id: int) -> Optional[VideoJob]:
        return db.query(VideoJob).filter(
            VideoJob.id == job_id,
            VideoJob.user_id == user_id,
        ).first()

    @staticmethod
    def get_latest_job_for_history(db: Session, user_id: int, history_id: int) -> Optional[VideoJob]:
        return (
            db.query(VideoJob)
            .filter(
                VideoJob.user_id == user_id,
                VideoJob.history_id == history_id,
            )
            .order_by(VideoJob.created_at.desc(), VideoJob.id.desc())
            .first()
        )

    @staticmethod
    def list_jobs_for_history(
        db: Session, user_id: int, history_id: int, limit: int = 50,
    ) -> List[VideoJob]:
        return (
            db.query(VideoJob)
            .filter(
                VideoJob.user_id == user_id,
                VideoJob.history_id == history_id,
            )
            .order_by(VideoJob.created_at.desc(), VideoJob.id.desc())
            .limit(max(1, int(limit)))
            .all()
        )

    @staticmethod
    def update_job_status(
        db: Session,
        user_id: int,
        job_id: int,
        status: Optional[str] = None,
        stage: Optional[str] = None,
        progress: Optional[int] = None,
        provider_job_id: Optional[str] = None,
        response_payload: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        result_video_path: Optional[str] = None,
        result_video_url: Optional[str] = None,
        result_thumbnail_path: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        submitted_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> Optional[VideoJob]:
        job = db.query(VideoJob).filter(
            VideoJob.id == job_id,
            VideoJob.user_id == user_id,
        ).first()
        if job is None:
            return None

        if status is not None:
            job.status = status
        if stage is not None:
            job.stage = stage
        if progress is not None:
            job.progress = int(progress)
        if provider_job_id is not None:
            job.provider_job_id = provider_job_id
        if response_payload is not None:
            job.response_json = json.dumps(response_payload, ensure_ascii=False)
        if error_message is not None:
            job.error_message = error_message
        if result_video_path is not None:
            job.result_video_path = result_video_path
        if result_video_url is not None:
            job.result_video_url = result_video_url
        if result_thumbnail_path is not None:
            job.result_thumbnail_path = result_thumbnail_path
        if duration_seconds is not None:
            job.duration_seconds = int(duration_seconds)
        if submitted_at is not None:
            job.submitted_at = submitted_at
        if completed_at is not None:
            job.completed_at = completed_at

        job.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def mark_cancelled(
        db: Session,
        user_id: int,
        job_id: int,
        message: Optional[str] = None,
    ) -> Optional[VideoJob]:
        job = db.query(VideoJob).filter(
            VideoJob.id == job_id,
            VideoJob.user_id == user_id,
        ).first()
        if job is None:
            return None
        if job.status in ('succeeded', 'failed', 'cancelled', 'provider_not_configured'):
            return job
        job.status = 'cancelled'
        job.stage = 'failed'
        if message is not None:
            job.error_message = message
        job.updated_at = datetime.utcnow()
        job.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        return job
