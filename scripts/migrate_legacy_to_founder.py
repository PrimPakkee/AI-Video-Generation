#!/usr/bin/env python3
"""
v0.6.8 — One-shot legacy backfill.

Sets user_id = founder.id on every existing prompt_history, prompt_reviews,
video_history, and video_jobs row that has user_id IS NULL. Idempotent — rerun
prints "0 rows updated" when there's nothing left to do.

Run AFTER scripts/create_founder.py and BEFORE the v0.6.8 server is exposed
to non-founder users.
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from sqlalchemy import text  # noqa: E402

from web.db import (  # noqa: E402
    AuthSessionLocal,
    UserRepository,
    auth_engine,
    engine as prompt_engine,
    init_auth_db,
    init_db,
    init_video_db,
    video_engine,
)


def _backfill(eng, table: str, founder_id: int) -> int:
    with eng.begin() as conn:
        result = conn.execute(
            text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),
            {"uid": founder_id},
        )
        return result.rowcount or 0


def main() -> int:
    init_auth_db()
    init_db()
    init_video_db()

    db = AuthSessionLocal()
    try:
        admins = [u for u in UserRepository.list_all(db) if u.is_admin == 1]
        if not admins:
            print(
                "ERROR: No admin user found. Run "
                "`python -m scripts.create_founder --email ...` first."
            )
            return 2
        # Founder = lowest-id admin (the seeded one).
        founder = sorted(admins, key=lambda u: u.id)[0]
    finally:
        db.close()

    print(f"Backfilling legacy rows to founder id={founder.id} ({founder.email})...")

    counts = {
        "prompt_history": _backfill(prompt_engine, "prompt_history", founder.id),
        "prompt_reviews": _backfill(prompt_engine, "prompt_reviews", founder.id),
        "video_history":  _backfill(video_engine,  "video_history",  founder.id),
        "video_jobs":     _backfill(video_engine,  "video_jobs",     founder.id),
    }

    for table, n in counts.items():
        print(f"  {table}: {n} row(s) updated")

    total = sum(counts.values())
    if total == 0:
        print("Nothing to backfill. (Already done, or fresh DB.)")
    else:
        print(f"Done — {total} row(s) total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
