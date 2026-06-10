#!/usr/bin/env python3
"""
Repository layer for database operations.

v0.6.8: every public method takes ``user_id`` as the 2nd positional
parameter (after ``db``) and scopes the query to that owner. Lookups that
miss the owner return ``None`` / ``False`` so the API layer can return 404
indistinguishably from "not found" — never leak existence of another
user's row.
"""

from typing import List, Optional
from datetime import datetime, timedelta
import re
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, func, and_
from .models import PromptHistory, PromptReview  # noqa: F401


def normalize_title(title: str) -> str:
    """
    Normalize title for version grouping
    """
    if not title:
        return ''
    normalized = title.strip().lower()
    normalized = re.sub(r'\s+', ' ', normalized)
    normalized = re.sub(r'[?？!！。.,:：，、]+$', '', normalized)
    return normalized


class PromptHistoryRepository:
    """Repository for PromptHistory CRUD, scoped per user_id."""

    @staticmethod
    def create_history_record(
        db: Session,
        user_id: int,
        title: str,
        slug: str,
        prompt_text: str,
        output_dir: str,
        model: Optional[str] = None,
        mode: Optional[str] = None,
        status: str = 'success',
        metadata_json: Optional[str] = None,
        overview_cn: Optional[str] = None,
    ) -> PromptHistory:
        title_normalized = normalize_title(title)

        # Find existing active group with same normalized title FOR THIS USER.
        existing = db.query(PromptHistory).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.title_normalized == title_normalized,
            PromptHistory.deleted_at.is_(None),
        ).order_by(desc(PromptHistory.created_at)).first()

        if existing and existing.topic_group_id:
            topic_group_id = existing.topic_group_id
            max_version = db.query(func.max(PromptHistory.version_number)).filter(
                PromptHistory.user_id == user_id,
                PromptHistory.topic_group_id == topic_group_id,
            ).scalar() or 0
            version_number = max_version + 1
        else:
            topic_group_id = str(uuid.uuid4())
            version_number = 1

        record = PromptHistory(
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
    ) -> List[PromptHistory]:
        subquery = db.query(
            PromptHistory.topic_group_id,
            func.max(PromptHistory.version_number).label('max_version'),
        ).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.deleted_at.is_(None),
        ).group_by(PromptHistory.topic_group_id).subquery()

        query = db.query(PromptHistory).join(
            subquery,
            and_(
                PromptHistory.topic_group_id == subquery.c.topic_group_id,
                PromptHistory.version_number == subquery.c.max_version,
            ),
        ).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.deleted_at.is_(None),
        )

        if q:
            search_pattern = f"%{q}%"
            query = query.filter(or_(
                PromptHistory.title.like(search_pattern),
                PromptHistory.slug.like(search_pattern),
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
                query = query.filter(PromptHistory.created_at >= cutoff)

        query = query.order_by(
            desc(PromptHistory.is_pinned),
            desc(PromptHistory.pinned_at),
            desc(PromptHistory.created_at),
        ).limit(limit)
        return query.all()

    @staticmethod
    def get_history_record(db: Session, user_id: int, history_id: int) -> Optional[PromptHistory]:
        return db.query(PromptHistory).filter(
            PromptHistory.id == history_id,
            PromptHistory.user_id == user_id,
        ).first()

    @staticmethod
    def get_by_slug(db: Session, user_id: int, slug: str) -> Optional[PromptHistory]:
        return db.query(PromptHistory).filter(
            PromptHistory.slug == slug,
            PromptHistory.user_id == user_id,
        ).first()

    @staticmethod
    def search_history_records(
        db: Session,
        user_id: int,
        query: str,
        limit: int = 50,
    ) -> List[PromptHistory]:
        search_pattern = f"%{query}%"
        return db.query(PromptHistory).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.title.like(search_pattern),
        ).order_by(desc(PromptHistory.created_at)).limit(limit).all()

    @staticmethod
    def pin_history_record(db: Session, user_id: int, history_id: int) -> Optional[PromptHistory]:
        record = db.query(PromptHistory).filter(
            PromptHistory.id == history_id,
            PromptHistory.user_id == user_id,
        ).first()
        if record:
            record.is_pinned = 1
            record.pinned_at = datetime.utcnow()
            db.commit()
            db.refresh(record)
        return record

    @staticmethod
    def unpin_history_record(db: Session, user_id: int, history_id: int) -> Optional[PromptHistory]:
        record = db.query(PromptHistory).filter(
            PromptHistory.id == history_id,
            PromptHistory.user_id == user_id,
        ).first()
        if record:
            record.is_pinned = 0
            record.pinned_at = None
            db.commit()
            db.refresh(record)
        return record

    @staticmethod
    def delete_history_record(db: Session, user_id: int, history_id: int) -> bool:
        record = db.query(PromptHistory).filter(
            PromptHistory.id == history_id,
            PromptHistory.user_id == user_id,
        ).first()
        if record:
            db.delete(record)
            db.commit()
            return True
        return False

    @staticmethod
    def list_trash_records(
        db: Session,
        user_id: int,
        limit: int = 100,
        q: Optional[str] = None,
    ) -> List[PromptHistory]:
        subquery = db.query(
            PromptHistory.topic_group_id,
            func.max(PromptHistory.version_number).label('max_version'),
        ).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.deleted_at.isnot(None),
        ).group_by(PromptHistory.topic_group_id).subquery()

        query = db.query(PromptHistory).join(
            subquery,
            and_(
                PromptHistory.topic_group_id == subquery.c.topic_group_id,
                PromptHistory.version_number == subquery.c.max_version,
            ),
        ).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.deleted_at.isnot(None),
        )

        if q:
            search_pattern = f"%{q}%"
            query = query.filter(PromptHistory.title.like(search_pattern))

        query = query.order_by(desc(PromptHistory.deleted_at)).limit(limit)
        return query.all()

    @staticmethod
    def get_versions_by_group(db: Session, user_id: int, topic_group_id: str) -> List[PromptHistory]:
        return db.query(PromptHistory).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.topic_group_id == topic_group_id,
        ).order_by(PromptHistory.version_number.asc()).all()

    @staticmethod
    def get_version_count(db: Session, user_id: int, topic_group_id: str) -> int:
        return db.query(PromptHistory).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.topic_group_id == topic_group_id,
        ).count()

    @staticmethod
    def rename_history_group(
        db: Session, user_id: int, topic_group_id: str, new_title: str,
    ) -> Optional[PromptHistory]:
        records = db.query(PromptHistory).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.topic_group_id == topic_group_id,
        ).all()
        if not records:
            return None
        new_normalized = normalize_title(new_title)
        for record in records:
            record.title = new_title
            record.title_normalized = new_normalized
        db.commit()
        latest = max(records, key=lambda r: r.version_number)
        db.refresh(latest)
        return latest

    @staticmethod
    def soft_delete_history_group(db: Session, user_id: int, topic_group_id: str) -> bool:
        records = db.query(PromptHistory).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.topic_group_id == topic_group_id,
            PromptHistory.deleted_at.is_(None),
        ).all()
        if not records:
            return False
        now = datetime.utcnow()
        for record in records:
            record.deleted_at = now
        db.commit()
        return True

    @staticmethod
    def permanently_delete_history_group(db: Session, user_id: int, topic_group_id: str) -> bool:
        records = db.query(PromptHistory).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.topic_group_id == topic_group_id,
        ).all()
        if not records:
            return False
        for record in records:
            db.delete(record)
        db.commit()
        return True

    @staticmethod
    def restore_history_group(db: Session, user_id: int, topic_group_id: str) -> bool:
        records = db.query(PromptHistory).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.topic_group_id == topic_group_id,
            PromptHistory.deleted_at.isnot(None),
        ).all()
        if not records:
            return False
        for record in records:
            record.deleted_at = None
        db.commit()
        return True

    @staticmethod
    def favorite_history_group(db: Session, user_id: int, topic_group_id: str) -> Optional[PromptHistory]:
        records = db.query(PromptHistory).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.topic_group_id == topic_group_id,
        ).all()
        if not records:
            return None
        now = datetime.utcnow()
        for record in records:
            record.is_favorite = 1
            record.favorite_at = now
        db.commit()
        latest = max(records, key=lambda r: r.version_number)
        db.refresh(latest)
        return latest

    @staticmethod
    def unfavorite_history_group(db: Session, user_id: int, topic_group_id: str) -> Optional[PromptHistory]:
        records = db.query(PromptHistory).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.topic_group_id == topic_group_id,
        ).all()
        if not records:
            return None
        for record in records:
            record.is_favorite = 0
            record.favorite_at = None
        db.commit()
        latest = max(records, key=lambda r: r.version_number)
        db.refresh(latest)
        return latest

    @staticmethod
    def update_prompt_content(
        db: Session,
        user_id: int,
        history_id: int,
        view: str,
        content: str,
    ) -> Optional[PromptHistory]:
        record = db.query(PromptHistory).filter(
            PromptHistory.id == history_id,
            PromptHistory.user_id == user_id,
        ).first()
        if not record:
            return None
        if view == 'raw':
            record.prompt_text = content
        elif view == 'preview':
            record.preview_text = content
        elif view == 'overview':
            record.overview_cn = content
        record.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def create_regenerated_version(
        db: Session,
        user_id: int,
        from_history_id: int,
        feedback: str,
        new_prompt_text: str,
        new_overview_cn: str,
        change_summary_cn: str,
        slug: str,
        output_dir: str,
        model: Optional[str] = None,
    ) -> Optional[PromptHistory]:
        original = db.query(PromptHistory).filter(
            PromptHistory.id == from_history_id,
            PromptHistory.user_id == user_id,
        ).first()
        if not original:
            return None

        max_version = db.query(func.max(PromptHistory.version_number)).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.topic_group_id == original.topic_group_id,
        ).scalar() or 0
        new_version_number = max_version + 1

        new_record = PromptHistory(
            user_id=user_id,
            title=original.title,
            slug=slug,
            prompt_text=new_prompt_text,
            output_dir=output_dir,
            model=model or original.model,
            mode=original.mode,
            status='success',
            title_normalized=original.title_normalized,
            topic_group_id=original.topic_group_id,
            version_number=new_version_number,
            overview_cn=new_overview_cn,
            change_summary_cn=change_summary_cn,
            regenerate_from_history_id=from_history_id,
            regenerate_feedback=feedback,
            is_pinned=0,
            is_favorite=original.is_favorite,
            favorite_at=original.favorite_at if original.is_favorite else None,
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)
        return new_record

    @staticmethod
    def list_favorite_records(
        db: Session,
        user_id: int,
        limit: int = 100,
        q: Optional[str] = None,
    ) -> List[PromptHistory]:
        subquery = db.query(
            PromptHistory.topic_group_id,
            func.max(PromptHistory.version_number).label('max_version'),
        ).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.deleted_at.is_(None),
            PromptHistory.is_favorite == 1,
        ).group_by(PromptHistory.topic_group_id).subquery()

        query = db.query(PromptHistory).join(
            subquery,
            and_(
                PromptHistory.topic_group_id == subquery.c.topic_group_id,
                PromptHistory.version_number == subquery.c.max_version,
            ),
        ).filter(
            PromptHistory.user_id == user_id,
            PromptHistory.deleted_at.is_(None),
            PromptHistory.is_favorite == 1,
        )

        if q:
            search_pattern = f"%{q}%"
            query = query.filter(or_(
                PromptHistory.title.like(search_pattern),
                PromptHistory.slug.like(search_pattern),
            ))

        query = query.order_by(
            desc(PromptHistory.favorite_at),
            desc(PromptHistory.created_at),
        ).limit(limit)
        return query.all()
