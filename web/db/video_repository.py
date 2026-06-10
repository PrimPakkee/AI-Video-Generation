#!/usr/bin/env python3
"""
Video Mode repository (v0.5.1).

CRUD layer for VideoHistory. Mirrors PromptHistoryRepository semantics so the
frontend can reuse list/version/pin/favorite/trash patterns transparently.

Strict isolation: every method accepts a Session bound to VideoSessionLocal
(data/video_history.db). It must NEVER read or write the Prompt Mode database
(data/prompt_history.db).

v0.6.8: every public method takes ``user_id`` as the 2nd positional parameter
and scopes its query by owner.
"""

import re
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import and_, desc, func, or_
from sqlalchemy.orm import Session

from .video_models import VideoHistory


def normalize_video_title(title: str) -> str:
    if not title:
        return ''
    normalized = title.strip().lower()
    normalized = re.sub(r'\s+', ' ', normalized)
    normalized = re.sub(r'[?？!！。.,:：，、]+$', '', normalized)
    return normalized


class VideoHistoryRepository:

    @staticmethod
    def create_history_record(
        db: Session,
        user_id: int,
        title: str,
        slug: str,
        prompt_text: str,
        output_dir: str,
        model: Optional[str] = None,
        mode: Optional[str] = 'video',
        status: str = 'success',
        overview_cn: Optional[str] = None,
        web_copy_text: Optional[str] = None,
        metadata_json: Optional[str] = None,
        generation_method: Optional[str] = None,
    ) -> VideoHistory:
        title_normalized = normalize_video_title(title)

        existing = db.query(VideoHistory).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.title_normalized == title_normalized,
            VideoHistory.deleted_at.is_(None),
        ).order_by(desc(VideoHistory.created_at)).first()

        if existing and existing.topic_group_id:
            topic_group_id = existing.topic_group_id
            max_version = db.query(func.max(VideoHistory.version_number)).filter(
                VideoHistory.user_id == user_id,
                VideoHistory.topic_group_id == topic_group_id,
            ).scalar() or 0
            version_number = max_version + 1
        else:
            topic_group_id = str(uuid.uuid4())
            version_number = 1

        record = VideoHistory(
            user_id=user_id,
            title=title,
            slug=slug,
            prompt_text=prompt_text,
            output_dir=output_dir,
            model=model,
            mode=mode,
            status=status,
            metadata_json=metadata_json,
            title_normalized=title_normalized,
            topic_group_id=topic_group_id,
            version_number=version_number,
            overview_cn=overview_cn,
            web_copy_text=web_copy_text,
            video_status='not_generated',
            generation_method=(generation_method or 'seedance_video'),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def list_history_records(
        db: Session,
        user_id: int,
        limit: int = 100,
        q: Optional[str] = None,
        date_filter: Optional[str] = None,
    ) -> List[VideoHistory]:
        subquery = db.query(
            VideoHistory.topic_group_id,
            func.max(VideoHistory.version_number).label('max_version'),
        ).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.deleted_at.is_(None),
        ).group_by(VideoHistory.topic_group_id).subquery()

        query = db.query(VideoHistory).join(
            subquery,
            and_(
                VideoHistory.topic_group_id == subquery.c.topic_group_id,
                VideoHistory.version_number == subquery.c.max_version,
            ),
        ).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.deleted_at.is_(None),
        )

        if q:
            pattern = f"%{q}%"
            query = query.filter(or_(
                VideoHistory.title.like(pattern),
                VideoHistory.slug.like(pattern),
            ))

        if date_filter and date_filter != 'all':
            now = datetime.utcnow()
            cutoff = None
            if date_filter == '1h':
                cutoff = now - timedelta(hours=1)
            elif date_filter == '3h':
                cutoff = now - timedelta(hours=3)
            elif date_filter == 'today':
                cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif date_filter == 'yesterday':
                yesterday = now - timedelta(days=1)
                cutoff = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            elif date_filter == '7d':
                cutoff = now - timedelta(days=7)
            elif date_filter == '30d':
                cutoff = now - timedelta(days=30)
            if cutoff:
                query = query.filter(VideoHistory.created_at >= cutoff)

        query = query.order_by(
            desc(VideoHistory.is_pinned),
            desc(VideoHistory.pinned_at),
            desc(VideoHistory.created_at),
        ).limit(limit)
        return query.all()

    @staticmethod
    def get_history_record(db: Session, user_id: int, history_id: int) -> Optional[VideoHistory]:
        return db.query(VideoHistory).filter(
            VideoHistory.id == history_id,
            VideoHistory.user_id == user_id,
        ).first()

    @staticmethod
    def get_by_slug(db: Session, user_id: int, slug: str) -> Optional[VideoHistory]:
        return db.query(VideoHistory).filter(
            VideoHistory.slug == slug,
            VideoHistory.user_id == user_id,
        ).first()

    @staticmethod
    def get_versions_by_group(db: Session, user_id: int, topic_group_id: str) -> List[VideoHistory]:
        return db.query(VideoHistory).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.topic_group_id == topic_group_id,
        ).order_by(VideoHistory.version_number.asc()).all()

    @staticmethod
    def get_version_count(db: Session, user_id: int, topic_group_id: str) -> int:
        return db.query(VideoHistory).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.topic_group_id == topic_group_id,
        ).count()

    @staticmethod
    def pin_history_record(db: Session, user_id: int, history_id: int) -> Optional[VideoHistory]:
        record = db.query(VideoHistory).filter(
            VideoHistory.id == history_id,
            VideoHistory.user_id == user_id,
        ).first()
        if record:
            record.is_pinned = 1
            record.pinned_at = datetime.utcnow()
            db.commit()
            db.refresh(record)
        return record

    @staticmethod
    def unpin_history_record(db: Session, user_id: int, history_id: int) -> Optional[VideoHistory]:
        record = db.query(VideoHistory).filter(
            VideoHistory.id == history_id,
            VideoHistory.user_id == user_id,
        ).first()
        if record:
            record.is_pinned = 0
            record.pinned_at = None
            db.commit()
            db.refresh(record)
        return record

    @staticmethod
    def soft_delete_history_group(db: Session, user_id: int, topic_group_id: str) -> bool:
        records = db.query(VideoHistory).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.topic_group_id == topic_group_id,
            VideoHistory.deleted_at.is_(None),
        ).all()
        if not records:
            return False
        now = datetime.utcnow()
        for r in records:
            r.deleted_at = now
        db.commit()
        return True

    @staticmethod
    def restore_history_group(db: Session, user_id: int, topic_group_id: str) -> bool:
        records = db.query(VideoHistory).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.topic_group_id == topic_group_id,
            VideoHistory.deleted_at.isnot(None),
        ).all()
        if not records:
            return False
        for r in records:
            r.deleted_at = None
        db.commit()
        return True

    @staticmethod
    def permanently_delete_history_group(db: Session, user_id: int, topic_group_id: str) -> bool:
        records = db.query(VideoHistory).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.topic_group_id == topic_group_id,
        ).all()
        if not records:
            return False
        for r in records:
            db.delete(r)
        db.commit()
        return True

    @staticmethod
    def list_trash_records(
        db: Session,
        user_id: int,
        limit: int = 100,
        q: Optional[str] = None,
    ) -> List[VideoHistory]:
        subquery = db.query(
            VideoHistory.topic_group_id,
            func.max(VideoHistory.version_number).label('max_version'),
        ).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.deleted_at.isnot(None),
        ).group_by(VideoHistory.topic_group_id).subquery()

        query = db.query(VideoHistory).join(
            subquery,
            and_(
                VideoHistory.topic_group_id == subquery.c.topic_group_id,
                VideoHistory.version_number == subquery.c.max_version,
            ),
        ).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.deleted_at.isnot(None),
        )

        if q:
            query = query.filter(VideoHistory.title.like(f"%{q}%"))

        return query.order_by(desc(VideoHistory.deleted_at)).limit(limit).all()

    @staticmethod
    def favorite_history_group(db: Session, user_id: int, topic_group_id: str) -> Optional[VideoHistory]:
        records = db.query(VideoHistory).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.topic_group_id == topic_group_id,
        ).all()
        if not records:
            return None
        now = datetime.utcnow()
        for r in records:
            r.is_favorite = 1
            r.favorite_at = now
        db.commit()
        latest = max(records, key=lambda r: r.version_number)
        db.refresh(latest)
        return latest

    @staticmethod
    def unfavorite_history_group(db: Session, user_id: int, topic_group_id: str) -> Optional[VideoHistory]:
        records = db.query(VideoHistory).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.topic_group_id == topic_group_id,
        ).all()
        if not records:
            return None
        for r in records:
            r.is_favorite = 0
            r.favorite_at = None
        db.commit()
        latest = max(records, key=lambda r: r.version_number)
        db.refresh(latest)
        return latest

    @staticmethod
    def list_favorite_records(
        db: Session,
        user_id: int,
        limit: int = 100,
        q: Optional[str] = None,
    ) -> List[VideoHistory]:
        subquery = db.query(
            VideoHistory.topic_group_id,
            func.max(VideoHistory.version_number).label('max_version'),
        ).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.deleted_at.is_(None),
            VideoHistory.is_favorite == 1,
        ).group_by(VideoHistory.topic_group_id).subquery()

        query = db.query(VideoHistory).join(
            subquery,
            and_(
                VideoHistory.topic_group_id == subquery.c.topic_group_id,
                VideoHistory.version_number == subquery.c.max_version,
            ),
        ).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.deleted_at.is_(None),
            VideoHistory.is_favorite == 1,
        )

        if q:
            pattern = f"%{q}%"
            query = query.filter(or_(
                VideoHistory.title.like(pattern),
                VideoHistory.slug.like(pattern),
            ))

        return query.order_by(
            desc(VideoHistory.favorite_at),
            desc(VideoHistory.created_at),
        ).limit(limit).all()

    @staticmethod
    def update_asset_pipeline_result(
        db: Session,
        user_id: int,
        history_id: int,
        prompt_text: Optional[str] = None,
        preview_text: Optional[str] = None,
        overview_cn: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> Optional[VideoHistory]:
        record = db.query(VideoHistory).filter(
            VideoHistory.id == history_id,
            VideoHistory.user_id == user_id,
        ).first()
        if not record:
            return None
        if prompt_text is not None:
            record.prompt_text = prompt_text
        if preview_text is not None:
            record.preview_text = preview_text
        if overview_cn is not None:
            record.overview_cn = overview_cn
        if metadata_json is not None:
            record.metadata_json = metadata_json
        record.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def update_image_video_result(
        db: Session,
        user_id: int,
        history_id: int,
        video_file_path: Optional[str],
        video_duration_seconds: Optional[int],
        video_status: str = 'ready',
        metadata_json: Optional[str] = None,
        preview_text: Optional[str] = None,
        overview_cn: Optional[str] = None,
        prompt_text: Optional[str] = None,
    ) -> Optional[VideoHistory]:
        record = db.query(VideoHistory).filter(
            VideoHistory.id == history_id,
            VideoHistory.user_id == user_id,
        ).first()
        if not record:
            return None
        if video_file_path is not None:
            record.video_file_path = video_file_path
        if video_duration_seconds is not None:
            record.video_duration_seconds = video_duration_seconds
        if video_status:
            record.video_status = video_status
        if metadata_json is not None:
            record.metadata_json = metadata_json
        if preview_text is not None:
            record.preview_text = preview_text
        if overview_cn is not None:
            record.overview_cn = overview_cn
        if prompt_text is not None:
            record.prompt_text = prompt_text
        record.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def update_prompt_content(
        db: Session,
        user_id: int,
        history_id: int,
        view: str,
        content: str,
    ) -> Optional[VideoHistory]:
        record = db.query(VideoHistory).filter(
            VideoHistory.id == history_id,
            VideoHistory.user_id == user_id,
        ).first()
        if not record:
            return None

        if view == 'raw':
            record.prompt_text = content
        elif view == 'preview':
            record.preview_text = content
        elif view == 'overview':
            record.overview_cn = content
        elif view == 'web_copy':
            record.web_copy_text = content
        else:
            return None

        record.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def rename_topic_group(
        db: Session,
        user_id: int,
        topic_group_id: str,
        new_title: str,
    ) -> bool:
        new_title_clean = (new_title or '').strip()
        if not new_title_clean:
            return False
        records = db.query(VideoHistory).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.topic_group_id == topic_group_id,
        ).all()
        if not records:
            return False
        new_normalized = normalize_video_title(new_title_clean)
        now = datetime.utcnow()
        for r in records:
            r.title = new_title_clean
            r.title_normalized = new_normalized
            r.updated_at = now
        db.commit()
        return True

    @staticmethod
    def create_regenerated_version(
        db: Session,
        user_id: int,
        from_history_id: int,
        feedback: str,
        new_prompt_text: str,
        new_overview_cn: Optional[str],
        change_summary_cn: Optional[str],
        slug: str,
        output_dir: str,
        model: Optional[str] = None,
    ) -> Optional[VideoHistory]:
        original = db.query(VideoHistory).filter(
            VideoHistory.id == from_history_id,
            VideoHistory.user_id == user_id,
        ).first()
        if not original:
            return None

        max_version = db.query(func.max(VideoHistory.version_number)).filter(
            VideoHistory.user_id == user_id,
            VideoHistory.topic_group_id == original.topic_group_id,
        ).scalar() or 0

        new_record = VideoHistory(
            user_id=user_id,
            title=original.title,
            slug=slug,
            prompt_text=new_prompt_text,
            output_dir=output_dir,
            model=model or original.model,
            mode=original.mode or 'video',
            status='success',
            title_normalized=original.title_normalized,
            topic_group_id=original.topic_group_id,
            version_number=max_version + 1,
            overview_cn=new_overview_cn,
            change_summary_cn=change_summary_cn,
            regenerate_from_history_id=from_history_id,
            regenerate_feedback=feedback,
            is_pinned=0,
            is_favorite=original.is_favorite,
            favorite_at=original.favorite_at if original.is_favorite else None,
            video_status='not_generated',
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)
        return new_record
