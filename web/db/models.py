#!/usr/bin/env python3
"""
SQLAlchemy ORM models
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from .database import Base


class PromptHistory(Base):
    """
    Prompt history table - stores all successfully generated prompts
    """
    __tablename__ = "prompt_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # User input and generated slug
    title = Column(String(500), nullable=False, index=True)
    slug = Column(String(200), nullable=False, unique=True, index=True)

    # Generated prompt content
    prompt_text = Column(Text, nullable=False)

    # Output directory path
    output_dir = Column(String(500), nullable=False)

    # Model and mode information
    model = Column(String(100), nullable=True)
    mode = Column(String(100), nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Status (success, failed, etc.)
    status = Column(String(50), nullable=False, default='success')

    # Pin status (v0.3.1+)
    is_pinned = Column(Integer, nullable=False, default=0)  # SQLite uses 0/1 for boolean
    pinned_at = Column(DateTime, nullable=True)

    # Soft delete (v0.3.2+)
    deleted_at = Column(DateTime, nullable=True)

    # Version management (v0.3.2+)
    title_normalized = Column(Text, nullable=True)
    topic_group_id = Column(String(100), nullable=True, index=True)
    version_number = Column(Integer, nullable=False, default=1)

    # Favorite (v0.3.3+)
    is_favorite = Column(Integer, nullable=False, default=0)  # SQLite uses 0/1 for boolean
    favorite_at = Column(DateTime, nullable=True)

    # Overview (v0.3.4+)
    overview_cn = Column(Text, nullable=True)

    # Editing and regenerate (v0.4.3+)
    preview_text = Column(Text, nullable=True)  # User-edited preview content
    change_summary_cn = Column(Text, nullable=True)  # Summary of changes for regenerated versions
    regenerate_from_history_id = Column(Integer, nullable=True)  # ID of version this was regenerated from
    regenerate_feedback = Column(Text, nullable=True)  # User feedback used for regeneration

    # Metadata JSON (reserved for future extensions)
    metadata_json = Column(Text, nullable=True)

    def to_dict(self, include_prompt=False):
        """
        Convert to dictionary for API response
        """
        data = {
            'id': self.id,
            'title': self.title,
            'slug': self.slug,
            'output_dir': self.output_dir,
            'model': self.model,
            'mode': self.mode,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'status': self.status,
            'is_pinned': bool(self.is_pinned),
            'pinned_at': self.pinned_at.isoformat() if self.pinned_at else None,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'topic_group_id': self.topic_group_id,
            'version_number': self.version_number,
            'is_favorite': bool(self.is_favorite),
            'favorite_at': self.favorite_at.isoformat() if self.favorite_at else None,
        }

        if include_prompt:
            data['prompt'] = self.prompt_text
            data['overview_cn'] = self.overview_cn
            data['preview_text'] = self.preview_text
            data['change_summary_cn'] = self.change_summary_cn
            data['regenerate_feedback'] = self.regenerate_feedback
            data['regenerate_from_history_id'] = self.regenerate_from_history_id

        return data

    def __repr__(self):
        return f"<PromptHistory(id={self.id}, title='{self.title[:30]}...', slug='{self.slug}')>"


# Create indexes for common queries
Index('idx_created_at_desc', PromptHistory.created_at.desc())
Index('idx_title_search', PromptHistory.title)


class PromptReview(Base):
    """
    AI Review table - stores quality evaluation for each prompt version
    """
    __tablename__ = "prompt_reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Link to prompt history
    history_id = Column(Integer, nullable=False, index=True)

    # Review content
    review_json = Column(Text, nullable=False)  # Full structured review data
    review_markdown = Column(Text, nullable=True)  # Markdown format for display
    total_score = Column(Integer, nullable=False)  # Total score out of 100

    # Schema version (v0.4.6+)
    review_schema_version = Column(String(50), nullable=True, default='v0.4.6_calibrated')

    # Status
    status = Column(String(50), nullable=False, default='active')  # active, stale

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """
        Convert to dictionary for API response
        """
        return {
            'id': self.id,
            'history_id': self.history_id,
            'review_json': self.review_json,
            'review_markdown': self.review_markdown,
            'total_score': self.total_score,
            'review_schema_version': self.review_schema_version,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<PromptReview(id={self.id}, history_id={self.history_id}, total_score={self.total_score})>"


# Create index for review queries
Index('idx_review_history_id', PromptReview.history_id)
