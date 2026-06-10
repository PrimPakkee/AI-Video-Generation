#!/usr/bin/env python3
"""
Auth database configuration and session management (v0.6.8)

Independent SQLite database for users at data/auth.db. Strictly isolated
from prompt_history.db and video_history.db so the auth schema never
mixes with content tables.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

project_root = Path(__file__).parent.parent.parent
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

AUTH_DATABASE_URL = os.getenv('AUTH_DATABASE_URL')

if not AUTH_DATABASE_URL:
    data_dir = project_root / 'data'
    data_dir.mkdir(exist_ok=True)
    auth_db_path = data_dir / 'auth.db'
    AUTH_DATABASE_URL = f'sqlite:///{auth_db_path}'

auth_connect_args = {}
if AUTH_DATABASE_URL.startswith('sqlite'):
    auth_connect_args = {"check_same_thread": False}

auth_engine = create_engine(
    AUTH_DATABASE_URL,
    connect_args=auth_connect_args,
    echo=False,
)

AuthSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=auth_engine)

# Independent declarative base. Auth tables MUST live only in auth.db.
AuthBase = declarative_base()


def get_auth_db():
    """FastAPI dependency for an Auth database session."""
    db = AuthSessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_auth_db():
    """Initialize auth database — create users table if missing."""
    from . import auth_models  # noqa: F401  (registers User on AuthBase)

    AuthBase.metadata.create_all(bind=auth_engine)
