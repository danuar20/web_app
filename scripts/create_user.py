"""
create_user.py — CLI tool to create users in webapp_db.

Usage:
    python scripts/create_user.py --username <name> --password <pass> [--role viewer|admin] [--max-session 5]

Examples:
    # Create a viewer (default)
    python scripts/create_user.py --username john --password secret123

    # Create an admin
    python scripts/create_user.py --username sysadmin --password Str0ng!Pass --role admin
"""
import os
import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from werkzeug.security import generate_password_hash
from app.db.db_webapp import get_connection


def main():
    parser = argparse.ArgumentParser(
        description="Create a user in webapp_db."
    )
    parser.add_argument("--username",    required=True,  help="Login username")
    parser.add_argument("--password",    required=True,  help="Plain-text password (will be hashed)")
    parser.add_argument("--role",        default="viewer", choices=["viewer", "admin"],
                        help="User role: 'viewer' (default) or 'admin'")
    parser.add_argument("--max-session", type=int, default=5,
                        help="Max concurrent sessions allowed (default: 5)")
    args = parser.parse_args()

    hashed = generate_password_hash(args.password)

    conn = get_connection()
    cur  = conn.cursor()

    try:
        cur.execute(
            """
            INSERT INTO users (username, password, role, is_active, failed_attempts, max_session)
            VALUES (%s, %s, %s, TRUE, 0, %s)
            """,
            (args.username, hashed, args.role, args.max_session)
        )
        conn.commit()
        print(f"[OK] User '{args.username}' created with role='{args.role}', max_session={args.max_session}")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Failed to create user: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()