#!/usr/bin/env python3
"""
AI Review Cleanup Script (v0.4.9)

Goal:
    Mark stuck `generating` reviews as `failed` so the UI can recover.
    Default mode is dry-run; nothing is written unless --apply is passed.

Usage:
    # Preview only (no DB writes)
    python scripts/cleanup_ai_reviews.py --dry-run

    # Apply with database backup
    python scripts/cleanup_ai_reviews.py --apply --backup

    # Custom timeout threshold (default 5 minutes)
    python scripts/cleanup_ai_reviews.py --apply --max-age-minutes 10

Notes:
    - Does NOT touch completed reviews.
    - Does NOT modify the schema or drop tables.
    - Backups are written to data/backups/.
"""

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "prompt_history.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"

CLEANUP_ERROR_MESSAGE = (
    "stale generating review timed out by cleanup script"
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Clean up stuck AI Review records (dry-run by default)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying the database (default).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply the changes. Mutually exclusive with --dry-run.",
    )
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=5,
        help="Maximum age (minutes) before a generating review is considered stuck. Default: 5.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Backup the database file before applying changes.",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=str(DEFAULT_DB_PATH),
        help=f"Path to SQLite DB. Default: {DEFAULT_DB_PATH}",
    )
    return parser.parse_args()


def parse_iso_datetime(value):
    """Parse SQLite-stored datetime string into a naive UTC datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        cleaned = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is not None:
            dt = dt.astimezone(tz=None).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def find_stuck_generating_reviews(conn, max_age_minutes):
    """Return a list of review rows that are stuck in 'generating' status."""
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, history_id, status, updated_at, created_at
        FROM prompt_reviews
        WHERE status = 'generating'
        ORDER BY id ASC
        """
    )
    rows = cursor.fetchall()
    stuck = []
    for review_id, history_id, status, updated_at, created_at in rows:
        ref_dt = parse_iso_datetime(updated_at) or parse_iso_datetime(created_at)
        if ref_dt is None:
            # Unparseable timestamp – treat as stuck so the UI can recover.
            stuck.append((review_id, history_id, status, updated_at, created_at))
            continue
        if ref_dt < cutoff:
            stuck.append((review_id, history_id, status, updated_at, created_at))
    return stuck


def backup_database(db_path: Path) -> Path:
    """Copy db file to data/backups/ with a timestamped name."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    target = BACKUP_DIR / f"prompt_history_before_review_cleanup_{stamp}.db"
    shutil.copy2(db_path, target)
    return target


def apply_cleanup(conn, stuck_rows):
    """Mark stuck rows as 'failed' with an explanatory error message."""
    cursor = conn.cursor()
    now_iso = datetime.utcnow().isoformat()
    updated = 0
    for review_id, history_id, *_ in stuck_rows:
        error_envelope = json.dumps(
            {"error": CLEANUP_ERROR_MESSAGE},
            ensure_ascii=False,
        )
        cursor.execute(
            """
            UPDATE prompt_reviews
            SET status = 'failed',
                review_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (error_envelope, now_iso, review_id),
        )
        updated += cursor.rowcount
    conn.commit()
    return updated


def main():
    args = parse_args()

    if args.apply and args.dry_run:
        print("[ERROR] --apply and --dry-run cannot be used together.", file=sys.stderr)
        sys.exit(2)

    # Default behavior: dry-run unless --apply is provided.
    is_apply = bool(args.apply)
    is_dry_run = not is_apply

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"[ERROR] Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    print("=" * 72)
    print("AI Review Cleanup Script (v0.4.9)")
    print("=" * 72)
    print(f"  Database         : {db_path}")
    print(f"  Mode             : {'APPLY' if is_apply else 'DRY-RUN'}")
    print(f"  Max age (minutes): {args.max_age_minutes}")
    print(f"  Backup requested : {bool(args.backup)}")
    print("=" * 72)

    conn = sqlite3.connect(str(db_path))
    try:
        stuck = find_stuck_generating_reviews(conn, args.max_age_minutes)

        if not stuck:
            print("\n[OK] No stuck 'generating' reviews found. Nothing to do.")
            return 0

        print(f"\n[INFO] Found {len(stuck)} stuck 'generating' review(s):")
        for review_id, history_id, status, updated_at, created_at in stuck:
            print(
                f"  - review_id={review_id} history_id={history_id} "
                f"status={status} updated_at={updated_at} created_at={created_at}"
            )

        if is_dry_run:
            print(
                "\n[DRY-RUN] No changes written. "
                "Re-run with --apply (and optionally --backup) to clean up."
            )
            return 0

        # APPLY path
        if args.backup:
            backup_path = backup_database(db_path)
            print(f"\n[BACKUP] Database backed up to: {backup_path}")
        else:
            print(
                "\n[WARN] --backup not supplied. Proceeding without a DB backup. "
                "Press Ctrl+C within 3 seconds to abort."
            )
            try:
                import time
                time.sleep(3)
            except KeyboardInterrupt:
                print("\n[ABORTED] User interrupted before applying changes.")
                return 130

        updated = apply_cleanup(conn, stuck)
        print(f"\n[OK] Marked {updated} review record(s) as 'failed'.")
        print(f"      Error message stored: {CLEANUP_ERROR_MESSAGE!r}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
