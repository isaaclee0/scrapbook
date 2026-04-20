#!/usr/bin/env python3
"""Delete audit_log rows older than AUDIT_RETENTION_DAYS (default 30).

Intended to be run from cron, e.g. daily:
    docker compose exec web python scripts/audit_cleanup.py
"""

import os
import sys
import mysql.connector

RETENTION_DAYS = int(os.getenv('AUDIT_RETENTION_DAYS', 30))


def main() -> int:
    conn = mysql.connector.connect(
        host=os.getenv('DB_HOST', 'db'),
        user=os.getenv('DB_USER', 'db'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME', 'db'),
        charset='utf8mb4',
        collation='utf8mb4_unicode_ci',
    )
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM audit_log WHERE created_at < DATE_SUB(NOW(), INTERVAL %s DAY)",
            (RETENTION_DAYS,),
        )
        deleted = cursor.rowcount
        conn.commit()
        print(f"Deleted {deleted} audit_log rows older than {RETENTION_DAYS} days")
        return 0
    except mysql.connector.Error as err:
        print(f"audit_cleanup failed: {err}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
