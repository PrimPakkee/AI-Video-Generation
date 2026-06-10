#!/usr/bin/env python3
"""
v0.6.8 — One-shot founder seed.

Creates the single admin user that legacy data will be backfilled to. The
default password is printed to stdout exactly once; first login forces a
password change.

Usage:
    python -m scripts.create_founder --email you@example.com

Idempotent: refuses to re-seed if any admin already exists.
"""

from __future__ import annotations

import argparse
import secrets
import string
import sys
from pathlib import Path

# Allow `python -m scripts.create_founder` and direct `python scripts/create_founder.py`
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from web.db import (  # noqa: E402
    AuthSessionLocal,
    UserRepository,
    init_auth_db,
)
from web.auth import hash_password  # noqa: E402


def _generate_default_password(length: int = 14) -> str:
    """A printable, no-ambiguous-character default password."""
    alphabet = string.ascii_letters + string.digits
    # Avoid 0/O and 1/l/I confusion
    alphabet = alphabet.translate(str.maketrans('', '', '0O1lI'))
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the founder user.")
    parser.add_argument("--email", required=True, help="Founder email.")
    parser.add_argument(
        "--password",
        default=None,
        help=(
            "Optional. If omitted, a strong default is generated and printed "
            "ONCE. First login will force a password change either way."
        ),
    )
    args = parser.parse_args()

    init_auth_db()

    db = AuthSessionLocal()
    try:
        if UserRepository.has_any_admin(db):
            print(
                "ERROR: An admin user already exists. Refusing to re-seed.\n"
                "If you really need to reset the founder, drop data/auth.db "
                "manually and rerun."
            )
            return 2

        existing = UserRepository.get_by_email(db, args.email)
        if existing is not None:
            print(
                f"ERROR: A user with email {existing.email} already exists "
                f"(id={existing.id}, status={existing.status}). Refusing to "
                "promote/replace via this script."
            )
            return 2

        password = args.password or _generate_default_password()
        user = UserRepository.create_founder(
            db,
            email=args.email,
            password_hash=hash_password(password),
        )
        print("Founder created.")
        print(f"  id:       {user.id}")
        print(f"  email:    {user.email}")
        print(f"  password: {password}")
        print(
            "First login will force you to change this password. Save it "
            "now if you used --password; otherwise this is your only chance "
            "to copy it."
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
