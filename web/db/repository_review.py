#!/usr/bin/env python3
"""
Repository layer for AI Review operations.

v0.6.8: every public method takes ``user_id`` after ``db`` and filters
PromptReview rows by ``user_id``. Combined with PromptHistoryRepository
ownership checks at the API layer, this guarantees a user cannot read or
trigger reviews for another user's history.
"""

from typing import Optional
from datetime import datetime, timedelta
import json
from sqlalchemy.orm import Session
from .models import PromptReview


class PromptReviewRepository:

    @staticmethod
    def get_review_by_history_id(
        db: Session,
        user_id: int,
        history_id: int,
        schema_version: str = 'v0.4.6.9_strict',
    ) -> Optional[PromptReview]:
        reviews = db.query(PromptReview).filter(
            PromptReview.user_id == user_id,
            PromptReview.history_id == history_id,
            PromptReview.review_schema_version == schema_version,
        ).order_by(PromptReview.updated_at.desc()).all()

        if not reviews:
            return None

        status_priority = {'completed': 1, 'generating': 2, 'failed': 3, 'stale': 4}
        sorted_reviews = sorted(
            reviews,
            key=lambda r: (
                status_priority.get(r.status, 99),
                -r.updated_at.timestamp() if r.updated_at else 0,
            ),
        )
        return sorted_reviews[0] if sorted_reviews else None

    @staticmethod
    def create_review(
        db: Session,
        user_id: int,
        history_id: int,
        review_data: dict,
        review_markdown: str = None,
        schema_version: str = 'v0.4.6.9_strict',
    ) -> PromptReview:
        total_score = review_data.get('total_score', 0)
        review = PromptReview(
            user_id=user_id,
            history_id=history_id,
            review_json=json.dumps(review_data, ensure_ascii=False),
            review_markdown=review_markdown,
            total_score=total_score,
            review_schema_version=schema_version,
            status='active',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(review)
        db.commit()
        db.refresh(review)
        return review

    @staticmethod
    def mark_review_stale(db: Session, user_id: int, history_id: int) -> None:
        db.query(PromptReview).filter(
            PromptReview.user_id == user_id,
            PromptReview.history_id == history_id,
        ).update({'status': 'stale', 'updated_at': datetime.utcnow()})
        db.commit()

    @staticmethod
    def delete_review(db: Session, user_id: int, history_id: int) -> None:
        db.query(PromptReview).filter(
            PromptReview.user_id == user_id,
            PromptReview.history_id == history_id,
        ).delete()
        db.commit()

    @staticmethod
    def get_review_json(
        db: Session,
        user_id: int,
        history_id: int,
        schema_version: str = 'v0.4.6.9_strict',
    ) -> Optional[dict]:
        review = PromptReviewRepository.get_review_by_history_id(
            db, user_id, history_id, schema_version
        )
        if not review:
            return None
        try:
            return json.loads(review.review_json)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def is_review_outdated(
        db: Session,
        user_id: int,
        history_id: int,
        current_version: str = 'v0.4.6.9_strict',
    ) -> bool:
        review = PromptReviewRepository.get_review_by_history_id(
            db, user_id, history_id, current_version
        )
        if not review:
            return True
        if not review.review_schema_version:
            return True
        if review.review_schema_version != current_version:
            return True
        return False

    @staticmethod
    def get_review_status(
        db: Session,
        user_id: int,
        history_id: int,
        current_version: str = 'v0.4.6.9_strict',
    ) -> str:
        review = PromptReviewRepository.get_review_by_history_id(
            db, user_id, history_id, current_version
        )
        if not review:
            return 'none'
        if not review.review_schema_version or review.review_schema_version != current_version:
            return 'stale'
        if review.status == 'generating':
            timeout_threshold = datetime.utcnow() - timedelta(minutes=5)
            if review.updated_at and review.updated_at < timeout_threshold:
                PromptReviewRepository.mark_review_failed(
                    db, user_id, history_id,
                    "AI Review generation timed out. Please try again.",
                )
                return 'failed'
        return review.status

    @staticmethod
    def update_review_status(db: Session, user_id: int, history_id: int, status: str) -> None:
        db.query(PromptReview).filter(
            PromptReview.user_id == user_id,
            PromptReview.history_id == history_id,
        ).update({'status': status, 'updated_at': datetime.utcnow()})
        db.commit()

    @staticmethod
    def create_or_get_generating_review(
        db: Session,
        user_id: int,
        history_id: int,
        schema_version: str = 'v0.4.6.9_strict',
    ) -> tuple[PromptReview, bool]:
        existing = PromptReviewRepository.get_review_by_history_id(
            db, user_id, history_id, schema_version
        )
        if existing:
            if existing.status == 'completed':
                return (existing, False)
            if existing.status == 'generating':
                timeout_threshold = datetime.utcnow() - timedelta(minutes=5)
                if existing.updated_at and existing.updated_at >= timeout_threshold:
                    return (existing, False)
            db.query(PromptReview).filter(
                PromptReview.id == existing.id,
            ).update({
                'status': 'generating',
                'updated_at': datetime.utcnow(),
                'review_schema_version': schema_version,
            })
            db.commit()
            db.refresh(existing)
            return (existing, True)

        review = PromptReview(
            user_id=user_id,
            history_id=history_id,
            review_json=json.dumps({}),
            review_markdown=None,
            total_score=0,
            review_schema_version=schema_version,
            status='generating',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(review)
        db.commit()
        db.refresh(review)
        return (review, True)

    @staticmethod
    def update_review_with_result(
        db: Session,
        user_id: int,
        history_id: int,
        review_data: dict,
        schema_version: str = 'v0.4.6.9_strict',
    ) -> None:
        review = db.query(PromptReview).filter(
            PromptReview.user_id == user_id,
            PromptReview.history_id == history_id,
            PromptReview.review_schema_version == schema_version,
            PromptReview.status == 'generating',
        ).order_by(PromptReview.updated_at.desc()).first()

        if not review:
            review = PromptReviewRepository.get_review_by_history_id(
                db, user_id, history_id, schema_version
            )

        if review:
            total_score = review_data.get('total_score', 0)
            db.query(PromptReview).filter(PromptReview.id == review.id).update({
                'review_json': json.dumps(review_data, ensure_ascii=False),
                'total_score': total_score,
                'review_schema_version': schema_version,
                'status': 'completed',
                'updated_at': datetime.utcnow(),
            })
            db.commit()

    @staticmethod
    def mark_review_failed(
        db: Session,
        user_id: int,
        history_id: int,
        error_message: str = None,
        schema_version: str = 'v0.4.6.9_strict',
    ) -> None:
        review = db.query(PromptReview).filter(
            PromptReview.user_id == user_id,
            PromptReview.history_id == history_id,
            PromptReview.review_schema_version == schema_version,
        ).filter(
            (PromptReview.status == 'generating') | (PromptReview.status == 'failed')
        ).order_by(PromptReview.updated_at.desc()).first()

        if not review:
            review = PromptReviewRepository.get_review_by_history_id(
                db, user_id, history_id, schema_version
            )

        if review:
            update_data = {'status': 'failed', 'updated_at': datetime.utcnow()}
            if error_message:
                update_data['review_json'] = json.dumps(
                    {'error': error_message}, ensure_ascii=False
                )
            db.query(PromptReview).filter(PromptReview.id == review.id).update(update_data)
            db.commit()
