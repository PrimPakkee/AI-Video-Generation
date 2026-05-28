#!/usr/bin/env python3
"""
Database configuration and session management
"""

import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load environment variables
project_root = Path(__file__).parent.parent.parent
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

# Get DATABASE_URL from environment or use default SQLite
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    # Default to SQLite in data/ directory
    data_dir = project_root / 'data'
    data_dir.mkdir(exist_ok=True)
    db_path = data_dir / 'prompt_history.db'
    DATABASE_URL = f'sqlite:///{db_path}'

# Create engine
connect_args = {}
if DATABASE_URL.startswith('sqlite'):
    # SQLite specific settings
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False  # Set to True for SQL debugging
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create declarative base
Base = declarative_base()


def get_db():
    """
    Dependency for FastAPI to get database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database - create all tables and run migrations
    """
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)

    # Run migrations
    from sqlalchemy import inspect, text
    import uuid

    inspector = inspect(engine)

    # Check if prompt_history table exists
    if 'prompt_history' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('prompt_history')]

        # v0.3.1 migrations: Add pin fields if not exist
        if 'is_pinned' not in columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_history ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0'))
                conn.commit()

        if 'pinned_at' not in columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_history ADD COLUMN pinned_at DATETIME'))
                conn.commit()

        # v0.3.2 migrations: Add soft delete and version management fields
        if 'deleted_at' not in columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_history ADD COLUMN deleted_at DATETIME'))
                conn.commit()

        if 'title_normalized' not in columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_history ADD COLUMN title_normalized TEXT'))
                conn.commit()

        if 'topic_group_id' not in columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_history ADD COLUMN topic_group_id VARCHAR(100)'))
                conn.commit()

        if 'version_number' not in columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_history ADD COLUMN version_number INTEGER NOT NULL DEFAULT 1'))
                conn.commit()

        # v0.3.3 migrations: Add favorite fields
        if 'is_favorite' not in columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_history ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0'))
                conn.commit()

        if 'favorite_at' not in columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_history ADD COLUMN favorite_at DATETIME'))
                conn.commit()

        # v0.3.4 migrations: Add overview field
        if 'overview_cn' not in columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_history ADD COLUMN overview_cn TEXT'))
                conn.commit()

        # v0.4.3 migrations: Add editing and regenerate fields
        if 'preview_text' not in columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_history ADD COLUMN preview_text TEXT'))
                conn.commit()

        if 'change_summary_cn' not in columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_history ADD COLUMN change_summary_cn TEXT'))
                conn.commit()

        if 'regenerate_from_history_id' not in columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_history ADD COLUMN regenerate_from_history_id INTEGER'))
                conn.commit()

        if 'regenerate_feedback' not in columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_history ADD COLUMN regenerate_feedback TEXT'))
                conn.commit()

        # Backfill legacy data
        with engine.connect() as conn:
            # Check if there are any records without topic_group_id
            result = conn.execute(text('SELECT COUNT(*) FROM prompt_history WHERE topic_group_id IS NULL'))
            count = result.scalar()

            if count > 0:
                # Get all records without topic_group_id
                result = conn.execute(text('SELECT id, title FROM prompt_history WHERE topic_group_id IS NULL'))
                records = result.fetchall()

                for record_id, title in records:
                    # Generate unique topic_group_id for each legacy record
                    topic_group_id = f"legacy_{str(uuid.uuid4())[:8]}"

                    # Normalize title
                    normalized = normalize_title_for_migration(title)

                    # Update record
                    conn.execute(
                        text('UPDATE prompt_history SET topic_group_id = :group_id, title_normalized = :normalized, version_number = 1 WHERE id = :id'),
                        {'group_id': topic_group_id, 'normalized': normalized, 'id': record_id}
                    )

                conn.commit()

    # v0.4.6 migrations: prompt_reviews table - Add review_schema_version field
    if 'prompt_reviews' in inspector.get_table_names():
        review_columns = [col['name'] for col in inspector.get_columns('prompt_reviews')]

        if 'review_schema_version' not in review_columns:
            with engine.connect() as conn:
                conn.execute(text('ALTER TABLE prompt_reviews ADD COLUMN review_schema_version VARCHAR(50)'))
                conn.execute(text("UPDATE prompt_reviews SET review_schema_version = 'v0.4.5_legacy' WHERE review_schema_version IS NULL"))
                conn.commit()

        # v0.4.6.3 migration: Convert 'active' status to 'completed' for unified state management
        with engine.connect() as conn:
            # Update old 'active' reviews to 'completed'
            result = conn.execute(text("UPDATE prompt_reviews SET status = 'completed' WHERE status = 'active'"))
            updated_count = result.rowcount
            if updated_count > 0:
                print(f"Migrated {updated_count} 'active' reviews to 'completed' status")
            conn.commit()


def normalize_title_for_migration(title: str) -> str:
    """
    Normalize title for migration (simple version)
    """
    if not title:
        return ''
    return title.strip().lower()
