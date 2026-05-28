#!/usr/bin/env python3
"""
Repository layer for database operations
"""

from typing import List, Optional
from datetime import datetime, timedelta
import re
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, case, func, and_
from .models import PromptHistory, PromptReview


def normalize_title(title: str) -> str:
    """
    Normalize title for version grouping

    Rules:
    - Trim whitespace
    - Convert to lowercase
    - Remove extra spaces
    - Remove common punctuation differences
    - Preserve Chinese characters
    """
    if not title:
        return ''

    # Trim and lowercase
    normalized = title.strip().lower()

    # Replace multiple spaces with single space
    normalized = re.sub(r'\s+', ' ', normalized)

    # Remove common trailing punctuation
    normalized = re.sub(r'[?？!！。.,:：，、]+$', '', normalized)

    return normalized


class PromptHistoryRepository:
    """
    Repository for PromptHistory CRUD operations
    """

    @staticmethod
    def create_history_record(
        db: Session,
        title: str,
        slug: str,
        prompt_text: str,
        output_dir: str,
        model: Optional[str] = None,
        mode: Optional[str] = None,
        status: str = 'success',
        metadata_json: Optional[str] = None,
        overview_cn: Optional[str] = None
    ) -> PromptHistory:
        """
        Create a new prompt history record with version management

        If a non-deleted record with the same normalized title exists,
        create a new version in the same topic group.
        Otherwise, create a new topic group.
        """
        # Normalize title
        title_normalized = normalize_title(title)

        # Find existing active group with same normalized title
        existing = db.query(PromptHistory).filter(
            PromptHistory.title_normalized == title_normalized,
            PromptHistory.deleted_at.is_(None)
        ).order_by(desc(PromptHistory.created_at)).first()

        if existing and existing.topic_group_id:
            # Use existing topic_group_id and increment version
            topic_group_id = existing.topic_group_id

            # Get max version number in this group
            max_version = db.query(func.max(PromptHistory.version_number)).filter(
                PromptHistory.topic_group_id == topic_group_id
            ).scalar() or 0

            version_number = max_version + 1
        else:
            # Create new topic group
            topic_group_id = str(uuid.uuid4())
            version_number = 1

        # Create record
        record = PromptHistory(
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
            overview_cn=overview_cn
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def list_history_records(
        db: Session,
        limit: int = 100,
        q: Optional[str] = None,
        date_filter: Optional[str] = None
    ) -> List[PromptHistory]:
        """
        List prompt history records (only non-deleted, latest version per group)

        Returns only the latest version of each topic group.
        Pinned items appear first, sorted by pinned_at DESC, then by created_at DESC.

        Args:
            db: Database session
            limit: Max records to return
            q: Search query for title/slug
            date_filter: Date filter (all, 1h, 3h, today, yesterday, 7d, 30d)

        Returns:
            List of latest version records per topic group
        """
        # Subquery to get latest version per topic_group
        subquery = db.query(
            PromptHistory.topic_group_id,
            func.max(PromptHistory.version_number).label('max_version')
        ).filter(
            PromptHistory.deleted_at.is_(None)
        ).group_by(
            PromptHistory.topic_group_id
        ).subquery()

        # Main query: join with subquery to get only latest versions
        query = db.query(PromptHistory).join(
            subquery,
            and_(
                PromptHistory.topic_group_id == subquery.c.topic_group_id,
                PromptHistory.version_number == subquery.c.max_version
            )
        ).filter(
            PromptHistory.deleted_at.is_(None)
        )

        # Apply search filter if provided
        if q:
            search_pattern = f"%{q}%"
            query = query.filter(
                or_(
                    PromptHistory.title.like(search_pattern),
                    PromptHistory.slug.like(search_pattern)
                )
            )

        # Apply date filter if provided
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

        # Order by: pinned first, then by pinned_at DESC, then by created_at DESC
        query = query.order_by(
            desc(PromptHistory.is_pinned),
            desc(PromptHistory.pinned_at),
            desc(PromptHistory.created_at)
        )

        # Apply limit
        query = query.limit(limit)

        return query.all()

    @staticmethod
    def get_history_record(db: Session, history_id: int) -> Optional[PromptHistory]:
        """
        Get a single prompt history record by ID
        """
        return db.query(PromptHistory).filter(PromptHistory.id == history_id).first()

    @staticmethod
    def get_by_slug(db: Session, slug: str) -> Optional[PromptHistory]:
        """
        Get a prompt history record by slug
        """
        return db.query(PromptHistory).filter(PromptHistory.slug == slug).first()

    @staticmethod
    def search_history_records(
        db: Session,
        query: str,
        limit: int = 50
    ) -> List[PromptHistory]:
        """
        Search prompt history by title
        """
        search_pattern = f"%{query}%"
        return db.query(PromptHistory).filter(
            PromptHistory.title.like(search_pattern)
        ).order_by(
            desc(PromptHistory.created_at)
        ).limit(limit).all()

    @staticmethod
    def pin_history_record(db: Session, history_id: int) -> Optional[PromptHistory]:
        """
        Pin a history record
        """
        record = db.query(PromptHistory).filter(PromptHistory.id == history_id).first()
        if record:
            record.is_pinned = 1
            record.pinned_at = datetime.utcnow()
            db.commit()
            db.refresh(record)
        return record

    @staticmethod
    def unpin_history_record(db: Session, history_id: int) -> Optional[PromptHistory]:
        """
        Unpin a history record
        """
        record = db.query(PromptHistory).filter(PromptHistory.id == history_id).first()
        if record:
            record.is_pinned = 0
            record.pinned_at = None
            db.commit()
            db.refresh(record)
        return record

    @staticmethod
    def delete_history_record(db: Session, history_id: int) -> bool:
        """
        Delete a history record (hard delete - only used for legacy compatibility)
        Returns True if deleted, False if not found
        """
        record = db.query(PromptHistory).filter(PromptHistory.id == history_id).first()
        if record:
            db.delete(record)
            db.commit()
            return True
        return False

    @staticmethod
    def list_trash_records(
        db: Session,
        limit: int = 100,
        q: Optional[str] = None
    ) -> List[PromptHistory]:
        """
        List deleted records in trash (latest version per group)

        Args:
            db: Database session
            limit: Max records to return
            q: Search query for title

        Returns:
            List of latest version records per topic group in trash
        """
        # Subquery to get latest version per topic_group in trash
        subquery = db.query(
            PromptHistory.topic_group_id,
            func.max(PromptHistory.version_number).label('max_version')
        ).filter(
            PromptHistory.deleted_at.isnot(None)
        ).group_by(
            PromptHistory.topic_group_id
        ).subquery()

        # Main query: join with subquery to get only latest versions
        query = db.query(PromptHistory).join(
            subquery,
            and_(
                PromptHistory.topic_group_id == subquery.c.topic_group_id,
                PromptHistory.version_number == subquery.c.max_version
            )
        ).filter(
            PromptHistory.deleted_at.isnot(None)
        )

        # Apply search filter if provided
        if q:
            search_pattern = f"%{q}%"
            query = query.filter(PromptHistory.title.like(search_pattern))

        # Order by deleted_at DESC
        query = query.order_by(desc(PromptHistory.deleted_at))

        # Apply limit
        query = query.limit(limit)

        return query.all()

    @staticmethod
    def get_versions_by_group(db: Session, topic_group_id: str) -> List[PromptHistory]:
        """
        Get all versions of a topic group

        Args:
            db: Database session
            topic_group_id: Topic group ID

        Returns:
            List of all versions sorted by version_number ASC
        """
        return db.query(PromptHistory).filter(
            PromptHistory.topic_group_id == topic_group_id
        ).order_by(
            PromptHistory.version_number.asc()
        ).all()

    @staticmethod
    def get_version_count(db: Session, topic_group_id: str) -> int:
        """
        Get count of versions in a topic group

        Args:
            db: Database session
            topic_group_id: Topic group ID

        Returns:
            Number of versions
        """
        return db.query(PromptHistory).filter(
            PromptHistory.topic_group_id == topic_group_id
        ).count()

    @staticmethod
    def rename_history_group(db: Session, topic_group_id: str, new_title: str) -> Optional[PromptHistory]:
        """
        Rename all versions in a topic group

        Args:
            db: Database session
            topic_group_id: Topic group ID
            new_title: New title for all versions

        Returns:
            Latest version record or None if not found
        """
        # Get all versions in group
        records = db.query(PromptHistory).filter(
            PromptHistory.topic_group_id == topic_group_id
        ).all()

        if not records:
            return None

        # Update title and title_normalized for all versions
        new_normalized = normalize_title(new_title)

        for record in records:
            record.title = new_title
            record.title_normalized = new_normalized

        db.commit()

        # Return latest version
        latest = max(records, key=lambda r: r.version_number)
        db.refresh(latest)
        return latest

    @staticmethod
    def soft_delete_history_group(db: Session, topic_group_id: str) -> bool:
        """
        Soft delete all versions in a topic group

        Args:
            db: Database session
            topic_group_id: Topic group ID

        Returns:
            True if deleted, False if not found
        """
        records = db.query(PromptHistory).filter(
            PromptHistory.topic_group_id == topic_group_id,
            PromptHistory.deleted_at.is_(None)
        ).all()

        if not records:
            return False

        now = datetime.utcnow()
        for record in records:
            record.deleted_at = now

        db.commit()
        return True

    @staticmethod
    def permanently_delete_history_group(db: Session, topic_group_id: str) -> bool:
        """
        Permanently delete all versions in a topic group (hard delete from database)

        Args:
            db: Database session
            topic_group_id: Topic group ID

        Returns:
            True if deleted, False if not found
        """
        records = db.query(PromptHistory).filter(
            PromptHistory.topic_group_id == topic_group_id
        ).all()

        if not records:
            return False

        for record in records:
            db.delete(record)

        db.commit()
        return True

    @staticmethod
    def restore_history_group(db: Session, topic_group_id: str) -> bool:
        """
        Restore a topic group from trash (set deleted_at to NULL)

        Args:
            db: Database session
            topic_group_id: Topic group ID

        Returns:
            True if restored, False if not found
        """
        records = db.query(PromptHistory).filter(
            PromptHistory.topic_group_id == topic_group_id,
            PromptHistory.deleted_at.isnot(None)
        ).all()

        if not records:
            return False

        for record in records:
            record.deleted_at = None

        db.commit()
        return True

    @staticmethod
    def favorite_history_group(db: Session, topic_group_id: str) -> Optional[PromptHistory]:
        """
        Favorite all versions in a topic group

        Args:
            db: Database session
            topic_group_id: Topic group ID

        Returns:
            Latest version record or None if not found
        """
        records = db.query(PromptHistory).filter(
            PromptHistory.topic_group_id == topic_group_id
        ).all()

        if not records:
            return None

        now = datetime.utcnow()
        for record in records:
            record.is_favorite = 1
            record.favorite_at = now

        db.commit()

        # Return latest version
        latest = max(records, key=lambda r: r.version_number)
        db.refresh(latest)
        return latest

    @staticmethod
    def unfavorite_history_group(db: Session, topic_group_id: str) -> Optional[PromptHistory]:
        """
        Unfavorite all versions in a topic group

        Args:
            db: Database session
            topic_group_id: Topic group ID

        Returns:
            Latest version record or None if not found
        """
        records = db.query(PromptHistory).filter(
            PromptHistory.topic_group_id == topic_group_id
        ).all()

        if not records:
            return None

        for record in records:
            record.is_favorite = 0
            record.favorite_at = None

        db.commit()

        # Return latest version
        latest = max(records, key=lambda r: r.version_number)
        db.refresh(latest)
        return latest

    @staticmethod
    def update_prompt_content(
        db: Session,
        history_id: int,
        view: str,
        content: str
    ) -> Optional[PromptHistory]:
        """
        Update prompt content for a specific view (raw/preview/overview)

        Args:
            db: Database session
            history_id: History record ID
            view: View type ('raw', 'preview', 'overview')
            content: New content

        Returns:
            Updated record or None if not found
        """
        record = db.query(PromptHistory).filter(PromptHistory.id == history_id).first()

        if not record:
            return None

        # Update based on view type
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
        from_history_id: int,
        feedback: str,
        new_prompt_text: str,
        new_overview_cn: str,
        change_summary_cn: str,
        slug: str,
        output_dir: str,
        model: Optional[str] = None
    ) -> Optional[PromptHistory]:
        """
        Create a new version by regenerating from an existing version

        Args:
            db: Database session
            from_history_id: Original version ID
            feedback: User feedback for regeneration
            new_prompt_text: New prompt text
            new_overview_cn: New overview
            change_summary_cn: Summary of changes
            slug: New slug
            output_dir: New output directory
            model: Model used

        Returns:
            New version record or None if original not found
        """
        # Get original record
        original = db.query(PromptHistory).filter(PromptHistory.id == from_history_id).first()

        if not original:
            return None

        # Get max version number in this group
        max_version = db.query(func.max(PromptHistory.version_number)).filter(
            PromptHistory.topic_group_id == original.topic_group_id
        ).scalar() or 0

        new_version_number = max_version + 1

        # Create new record
        new_record = PromptHistory(
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
            favorite_at=original.favorite_at if original.is_favorite else None
        )

        db.add(new_record)
        db.commit()
        db.refresh(new_record)
        return new_record

    @staticmethod
    def list_favorite_records(
        db: Session,
        limit: int = 100,
        q: Optional[str] = None
    ) -> List[PromptHistory]:
        """
        List favorite records (latest version per group)

        Args:
            db: Database session
            limit: Max records to return
            q: Search query for title

        Returns:
            List of latest version records per topic group that are favorited
        """
        # Subquery to get latest version per topic_group for favorites
        subquery = db.query(
            PromptHistory.topic_group_id,
            func.max(PromptHistory.version_number).label('max_version')
        ).filter(
            PromptHistory.deleted_at.is_(None),
            PromptHistory.is_favorite == 1
        ).group_by(
            PromptHistory.topic_group_id
        ).subquery()

        # Main query: join with subquery to get only latest versions
        query = db.query(PromptHistory).join(
            subquery,
            and_(
                PromptHistory.topic_group_id == subquery.c.topic_group_id,
                PromptHistory.version_number == subquery.c.max_version
            )
        ).filter(
            PromptHistory.deleted_at.is_(None),
            PromptHistory.is_favorite == 1
        )

        # Apply search filter if provided
        if q:
            search_pattern = f"%{q}%"
            query = query.filter(
                or_(
                    PromptHistory.title.like(search_pattern),
                    PromptHistory.slug.like(search_pattern)
                )
            )

        # Order by: favorite_at DESC, then created_at DESC
        query = query.order_by(
            desc(PromptHistory.favorite_at),
            desc(PromptHistory.created_at)
        )

        # Apply limit
        query = query.limit(limit)

        return query.all()
