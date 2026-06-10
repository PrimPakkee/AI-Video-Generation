#!/usr/bin/env python3
"""
Auth ORM models (v0.6.8)

User account with admin-approval gating. Status transitions:
  pending -> active (via admin approval)
  pending -> rejected (via admin reject)
  active -> rejected (via admin revoke; not yet exposed)
"""

from datetime import datetime
from sqlalchemy import Column, DateTime, Index, Integer, String

from .auth_database import AuthBase


class User(AuthBase):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(320), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)

    # 'pending' | 'active' | 'rejected'
    status = Column(String(20), nullable=False, default='pending', index=True)

    # 0 / 1 — only the founder is 1
    is_admin = Column(Integer, nullable=False, default=0)

    # 0 / 1 — set on founder seed; cleared on first password change
    must_change_password = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    approved_by_user_id = Column(Integer, nullable=True)

    __table_args__ = (
        Index('ix_users_status_created', 'status', 'created_at'),
    )
