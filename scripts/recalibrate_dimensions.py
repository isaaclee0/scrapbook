#!/usr/bin/env python3
"""
Recalibrate Image Dimensions

Reads every locally-cached image file from disk using Pillow and writes the
true dimensions back to cached_images.width / cached_images.height — overwriting
whatever was stored before, including wrong values.

Unlike update_image_dimensions.py (which skips pins that already have dims and
fetches from the network), this script is a full ground-truth pass over files
actually present on disk. It never makes network requests.

Designed to handle large collections (100k+ pins):
  - Cursor-based pagination, never loads the full table at once
  - Thread pool for parallel file reads (Pillow only reads image headers)
  - Batched DB writes to minimise round-trips
  - Resumable: re-running skips records whose stored dims are already correct

Usage (inside Docker):
    docker compose exec web python scripts/recalibrate_dimensions.py
    docker compose exec web python scripts/recalibrate_dimensions.py --dry-run
    docker compose exec web python scripts/recalibrate_dimensions.py --board-id 156
    docker compose exec web python scripts/recalibrate_dimensions.py --workers 8
"""

import os
import sys
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow")
    sys.exit(1)

try:
    import mysql.connector
except ImportError:
    print("Error: mysql-connector-python is required.")
    sys.exit(1)


CACHE_DIR = 'static/cached_images'
PAGE_SIZE = 1_000   # rows fetched per DB round-trip
WRITE_BATCH = 500   # updates committed in one transaction


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'db'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME', 'db'),
        charset='utf8mb4',
        collation='utf8mb4_unicode_ci',
        connection_timeout=30,
    )


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def count_eligible(board_id):
    """Return total number of cached_images records to process."""
    db = get_db_connection()
    cur = db.cursor()
    q = """
        SELECT COUNT(DISTINCT ci.id)
        FROM cached_images ci
        JOIN pins p ON p.cached_image_id = ci.id
        WHERE ci.cache_status = 'cached'
          AND ci.cached_filename IS NOT NULL
          AND ci.cached_filename NOT LIKE '%.placeholder'
          AND ci.cached_filename NOT LIKE 'failed\_%'
    """
    params = []
    if board_id:
        q += " AND p.board_id = %s"
        params.append(board_id)
    cur.execute(q, params)
    total = cur.fetchone()[0]
    cur.close()
    db.close()
    return total


def fetch_page(last_id, board_id, db):
    """Fetch the next PAGE_SIZE rows after last_id, ordered by ci.id."""
    cur = db.cursor(dictionary=True)
    q = """
        SELECT ci.id AS cache_id,
               ci.cached_filename,
               ci.width,
               ci.height
        FROM cached_images ci
        JOIN pins p ON p.cached_image_id = ci.id
        WHERE ci.id > %s
          AND ci.cache_status = 'cached'
          AND ci.cached_filename IS NOT NULL
          AND ci.cached_filename NOT LIKE %s
          AND ci.cached_filename NOT LIKE %s
    """
    params = [last_id, '%.placeholder', 'failed\_%']
    if board_id:
        q += " AND p.board_id = %s"
        params.append(board_id)
    q += " GROUP BY ci.id ORDER BY ci.id LIMIT %s"
    params.append(PAGE_SIZE)
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def read_dims(row):
    """
    Open the image header with Pillow (no pixel decode) and return
    (cache_id, width, height, stored_w, stored_h, path, error).
    Pillow's open() is lazy — it reads only the format header, so
    even 150k calls finish in a few minutes.
    """
    cache_id = row['cache_id']
    filename = row['cached_filename']
    path = os.path.join(CACHE_DIR, filename)

    if not os.path.exists(path):
        return cache_id, None, None, row['width'], row['height'], path, 'missing'

    try:
        with Image.open(path) as img:
            w, h = img.size
        return cache_id, w, h, row['width'], row['height'], path, None
    except Exception as e:
        return cache_id, None, None, row['width'], row['height'], path, str(e)


def flush_writes(pending, db, dry_run):
    """Commit a batch of (cache_id, w, h) updates."""
    if not pending or dry_run:
        return
    cur = db.cursor()
    cur.executemany(
        "UPDATE cached_images SET width=%s, height=%s, updated_at=NOW() WHERE id=%s",
        [(w, h, cid) for cid, w, h in pending],
    )
    db.commit()
    cur.close()


def run(dry_run=False, board_id=None, workers=4):
    log("Recalibrate Image Dimensions")
    log("=" * 52)
    if dry_run:
        log("DRY RUN — no changes will be written")

    total = count_eligible(board_id)
    log(f"Eligible cached_images records: {total:,}")
    if total == 0:
        log("Nothing to do.")
        return

    stats = dict(updated=0, already_ok=0, missing=0, errors=0)
    start = time.monotonic()
    last_id = 0
    processed = 0
    pending_writes = []  # [(cache_id, w, h)]

    write_db = get_db_connection()  # dedicated connection for writes

    def eta(done):
        elapsed = time.monotonic() - start
        if done == 0:
            return '?'
        rate = done / elapsed
        remaining = (total - done) / rate
        return str(timedelta(seconds=int(remaining)))

    while True:
        read_db = get_db_connection()
        page = fetch_page(last_id, board_id, read_db)
        read_db.close()

        if not page:
            break

        last_id = page[-1]['cache_id']

        # Parallel file reads — Pillow only touches the image header
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(read_dims, row): row for row in page}
            for future in as_completed(futures):
                cache_id, w, h, stored_w, stored_h, path, err = future.result()
                processed += 1

                if err == 'missing':
                    stats['missing'] += 1
                    continue
                if err:
                    stats['errors'] += 1
                    log(f"  ERROR {os.path.basename(path)}: {err}")
                    continue

                if w == (stored_w or 0) and h == (stored_h or 0):
                    stats['already_ok'] += 1
                    continue

                if dry_run:
                    log(f"  WOULD FIX id={cache_id} "
                        f"{stored_w or 0}×{stored_h or 0} → {w}×{h}")
                else:
                    pending_writes.append((cache_id, w, h))
                stats['updated'] += 1

        # Flush writes after each page (≤ PAGE_SIZE rows)
        if len(pending_writes) >= WRITE_BATCH:
            flush_writes(pending_writes, write_db, dry_run)
            pending_writes.clear()

        if processed % 5_000 == 0 or processed == total:
            elapsed = time.monotonic() - start
            rate = processed / elapsed if elapsed else 0
            log(f"  {processed:>7,}/{total:,}  "
                f"({rate:.0f}/s)  ETA {eta(processed)}  "
                f"fixed={stats['updated']:,}")

    # Final flush
    flush_writes(pending_writes, write_db, dry_run)
    write_db.close()

    elapsed = time.monotonic() - start
    log("=" * 52)
    log(f"Done in {elapsed:.1f}s  ({processed/elapsed:.0f} records/sec)")
    log(f"  Fixed (wrong stored dims) : {stats['updated']:,}")
    log(f"  Already correct           : {stats['already_ok']:,}")
    log(f"  File missing on disk      : {stats['missing']:,}")
    log(f"  Read errors               : {stats['errors']:,}")
    if dry_run and stats['updated']:
        log(f"\nRe-run without --dry-run to apply {stats['updated']:,} corrections.")


def main():
    parser = argparse.ArgumentParser(
        description='Recalibrate all cached image dimensions from disk files'
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would change without writing to DB')
    parser.add_argument('--board-id', type=int,
                        help='Only process pins from this board')
    parser.add_argument('--workers', type=int, default=4,
                        help='Parallel file-read threads (default: 4)')
    args = parser.parse_args()
    run(dry_run=args.dry_run, board_id=args.board_id, workers=args.workers)


if __name__ == '__main__':
    main()
