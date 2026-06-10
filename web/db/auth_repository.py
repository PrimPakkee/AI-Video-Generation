#!/usr/bin/env python3
"""
Auth repository (v0.6.8) — user CRUD + approval transitions.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from .auth_models import User


class UserRepository:

    @staticmethod
    def get_by_id(db: Session, user_id: int) -> Optional[User]:
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def get_by_email(db: Session, email: str) -> Optional[User]:
        normalized = (email or "").strip().lower()
        if not normalized:
            return None
        return db.query(User).filter(User.email == normalized).first()

    @staticmethod
    def create_pending(db: Session, email: str, password_hash: str) -> User:
        user = User(
            email=(email or "").strip().lower(),
            password_hash=password_hash,
            status='pending',
            is_admin=0,
            must_change_password=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def create_founder(db: Session, email: str, password_hash: str) -> User:
        user = User(
            email=(email or "").strip().lower(),
            password_hash=password_hash,
            status='active',
            is_admin=1,
            must_change_password=1,
            approved_at=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def list_pending(db: Session) -> List[User]:
        return (
            db.query(User)
            .filter(User.status == 'pending')
            .order_by(User.created_at.asc())
            .all()
        )

    @staticmethod
    def list_all(db: Session) -> List[User]:
        return db.query(User).order_by(User.created_at.asc()).all()

    @staticmethod
    def approve(db: Session, user_id: int, approver_id: int) -> Optional[User]:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or user.status == 'active':
            return user
        user.status = 'active'
        user.approved_at = datetime.utcnow()
        user.approved_by_user_id = approver_id
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def reject(db: Session, user_id: int) -> Optional[User]:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None
        user.status = 'rejected'
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def set_password(db: Session, user_id: int, new_hash: str) -> Optional[User]:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None
        user.password_hash = new_hash
        user.must_change_password = 0
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def has_any_admin(db: Session) -> bool:
        return db.query(User).filter(User.is_admin == 1).count() > 0
