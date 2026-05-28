#!/usr/bin/env python3
"""
Repository layer for AI Review operations
"""

from typing import Optional
from datetime import datetime, timedelta
import json
from sqlalchemy.orm import Session
from .models import PromptReview


class PromptReviewRepository:
    """
    Repository for PromptReview CRUD operations
    """

    @staticmethod
    def get_review_by_history_id(db: Session, history_id: int, schema_version: str = 'v0.4.6.9_strict') -> Optional[PromptReview]:
        """
        Get review for a specific history/version
        Prioritizes: completed > generating > failed > stale
        Returns the latest by updated_at if multiple exist

        Args:
            db: Database session
            history_id: ID of the prompt history record
            schema_version: Target schema version (default: v0.4.6.9_strict)

        Returns:
            PromptReview object or None
        """
        # Get all reviews for this history_id with matching schema version
        reviews = db.query(PromptReview).filter(
            PromptReview.history_id == history_id,
            PromptReview.review_schema_version == schema_version
        ).order_by(PromptReview.updated_at.desc()).all()

        if not reviews:
            return None

        # Prioritize by status: completed > generating > failed > stale
        status_priority = {'completed': 1, 'generating': 2, 'failed': 3, 'stale': 4}

        # Sort by priority, then by updated_at (desc)
        sorted_reviews = sorted(
            reviews,
            key=lambda r: (status_priority.get(r.status, 99), -r.updated_at.timestamp() if r.updated_at else 0)
        )

        return sorted_reviews[0] if sorted_reviews else None

    @staticmethod
    def create_review(
        db: Session,
        history_id: int,
        review_data: dict,
        review_markdown: str = None,
        schema_version: str = 'v0.4.6.9_strict'
    ) -> PromptReview:
        """
        Create a new review record

        Args:
            db: Database session
            history_id: ID of the prompt history record
            review_data: Review data dict (will be stored as JSON)
            review_markdown: Optional markdown format
            schema_version: Review schema version (default: v0.4.6.9_strict)

        Returns:
            Created PromptReview object
        """
        # Extract total_score from review_data
        total_score = review_data.get('total_score', 0)

        review = PromptReview(
            history_id=history_id,
            review_json=json.dumps(review_data, ensure_ascii=False),
            review_markdown=review_markdown,
            total_score=total_score,
            review_schema_version=schema_version,
            status='active',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(review)
        db.commit()
        db.refresh(review)

        return review

    @staticmethod
    def mark_review_stale(db: Session, history_id: int):
        """
        Mark existing review as stale (called when prompt is edited)

        Args:
            db: Database session
            history_id: ID of the prompt history record
        """
        db.query(PromptReview).filter(
            PromptReview.history_id == history_id
        ).update({
            'status': 'stale',
            'updated_at': datetime.utcnow()
        })
        db.commit()

    @staticmethod
    def delete_review(db: Session, history_id: int):
        """
        Delete review for a specific history/version

        Args:
            db: Database session
            history_id: ID of the prompt history record
        """
        db.query(PromptReview).filter(
            PromptReview.history_id == history_id
        ).delete()
        db.commit()

    @staticmethod
    def get_review_json(db: Session, history_id: int, schema_version: str = 'v0.4.6.9_strict') -> Optional[dict]:
        """
        Get review data as dict

        Args:
            db: Database session
            history_id: ID of the prompt history record
            schema_version: Target schema version (default: v0.4.6.9_strict)

        Returns:
            Review data dict or None
        """
        review = PromptReviewRepository.get_review_by_history_id(db, history_id, schema_version)
        if not review:
            return None

        try:
            return json.loads(review.review_json)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def is_review_outdated(db: Session, history_id: int, current_version: str = 'v0.4.6.9_strict') -> bool:
        """
        Check if review needs regeneration due to outdated schema version

        Args:
            db: Database session
            history_id: ID of the prompt history record
            current_version: Current schema version (default: v0.4.6.9_strict)

        Returns:
            True if review is outdated or missing, False otherwise
        """
        review = PromptReviewRepository.get_review_by_history_id(db, history_id, current_version)

        if not review:
            return True  # No review exists

        # Check schema version
        if not review.review_schema_version:
            return True  # Old review without schema version

        if review.review_schema_version != current_version:
            return True  # Different schema version

        return False  # Review is current

    @staticmethod
    def get_review_status(db: Session, history_id: int, current_version: str = 'v0.4.6.9_strict') -> str:
        """
        Get review status for a specific history version
        Also checks for generating timeout (>5 minutes)

        Args:
            db: Database session
            history_id: ID of the prompt history record
            current_version: Current schema version (default: v0.4.6.9_strict)

        Returns:
            Status string: 'none', 'generating', 'completed', 'failed', 'stale'
        """
        review = PromptReviewRepository.get_review_by_history_id(db, history_id, current_version)

        if not review:
            return 'none'

        # Check if stale due to schema version mismatch
        if not review.review_schema_version or review.review_schema_version != current_version:
            return 'stale'

        # Check for generating timeout (>5 minutes)
        if review.status == 'generating':
            timeout_threshold = datetime.utcnow() - timedelta(minutes=5)
            if review.updated_at and review.updated_at < timeout_threshold:
                # Mark as failed due to timeout
                PromptReviewRepository.mark_review_failed(
                    db,
                    history_id,
                    "AI Review generation timed out. Please try again."
                )
                return 'failed'

        # Return actual status
        return review.status

    @staticmethod
    def update_review_status(db: Session, history_id: int, status: str):
        """
        Update review status

        Args:
            db: Database session
            history_id: ID of the prompt history record
            status: New status ('active', 'completed', 'failed', 'stale', 'generating')
        """
        db.query(PromptReview).filter(
            PromptReview.history_id == history_id
        ).update({
            'status': status,
            'updated_at': datetime.utcnow()
        })
        db.commit()

    @staticmethod
    def create_or_get_generating_review(db: Session, history_id: int, schema_version: str = 'v0.4.6.9_strict') -> tuple[PromptReview, bool]:
        """
        Create a placeholder review with 'generating' status or reuse existing one

        Args:
            db: Database session
            history_id: ID of the prompt history record
            schema_version: Review schema version

        Returns:
            Tuple of (review object, should_generate)
            should_generate is True if LLM should be called, False if result already exists
        """
        # Check if review already exists for this schema version
        existing = PromptReviewRepository.get_review_by_history_id(db, history_id, schema_version)

        if existing:
            # If completed, return it without regenerating
            if existing.status == 'completed':
                return (existing, False)

            # If generating and not expired, return it
            if existing.status == 'generating':
                timeout_threshold = datetime.utcnow() - timedelta(minutes=5)
                if existing.updated_at and existing.updated_at >= timeout_threshold:
                    # Still generating, not expired
                    return (existing, False)
                # Expired, will reuse this record for new generation

            # If failed/stale/expired generating, reuse this record
            # Update it to generating status
            db.query(PromptReview).filter(
                PromptReview.id == existing.id
            ).update({
                'status': 'generating',
                'updated_at': datetime.utcnow(),
                'review_schema_version': schema_version
            })
            db.commit()
            db.refresh(existing)
            return (existing, True)

        # No existing review, create new placeholder with generating status
        review = PromptReview(
            history_id=history_id,
            review_json=json.dumps({}),  # Empty placeholder
            review_markdown=None,
            total_score=0,
            review_schema_version=schema_version,
            status='generating',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(review)
        db.commit()
        db.refresh(review)

        return (review, True)

    @staticmethod
    def update_review_with_result(db: Session, history_id: int, review_data: dict, schema_version: str = 'v0.4.6.9_strict'):
        """
        Update existing review with generated result (only updates the latest generating review)

        Args:
            db: Database session
            history_id: ID of the prompt history record
            review_data: Review data dict
            schema_version: Review schema version
        """
        # Get the current generating review for this schema version
        review = db.query(PromptReview).filter(
            PromptReview.history_id == history_id,
            PromptReview.review_schema_version == schema_version,
            PromptReview.status == 'generating'
        ).order_by(PromptReview.updated_at.desc()).first()

        if not review:
            # Fallback: get any review for this history_id and schema
            review = PromptReviewRepository.get_review_by_history_id(db, history_id, schema_version)

        if review:
            total_score = review_data.get('total_score', 0)

            # Update only this specific review record
            db.query(PromptReview).filter(
                PromptReview.id == review.id
            ).update({
                'review_json': json.dumps(review_data, ensure_ascii=False),
                'total_score': total_score,
                'review_schema_version': schema_version,
                'status': 'completed',
                'updated_at': datetime.utcnow()
            })
            db.commit()

    @staticmethod
    def mark_review_failed(db: Session, history_id: int, error_message: str = None, schema_version: str = 'v0.4.6.9_strict'):
        """
        Mark review as failed (only updates the latest generating or failed review)

        Args:
            db: Database session
            history_id: ID of the prompt history record
            error_message: Optional error message
            schema_version: Review schema version
        """
        # Get the current generating or failed review for this schema version
        review = db.query(PromptReview).filter(
            PromptReview.history_id == history_id,
            PromptReview.review_schema_version == schema_version
        ).filter(
            (PromptReview.status == 'generating') | (PromptReview.status == 'failed')
        ).order_by(PromptReview.updated_at.desc()).first()

        if not review:
            # Fallback: get any review for this history_id and schema
            review = PromptReviewRepository.get_review_by_history_id(db, history_id, schema_version)

        if review:
            update_data = {
                'status': 'failed',
                'updated_at': datetime.utcnow()
            }

            # Store error message in review_json if provided
            if error_message:
                update_data['review_json'] = json.dumps({
                    'error': error_message
                }, ensure_ascii=False)

            # Update only this specific review record
            db.query(PromptReview).filter(
                PromptReview.id == review.id
            ).update(update_data)
            db.commit()
