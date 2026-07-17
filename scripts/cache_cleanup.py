#!/usr/bin/env python3
"""
One-off cleanup for static/cached_images.

Three things, in order:
  1. Recover: pins whose only surviving cached copy is a legacy
     full-resolution file (named md5(image_url).ext by old import
     scripts) get that file resized/re-encoded to a proper 400px WebP.
  2. Purge legacy: every other legacy full-resolution file is deleted —
     the pin that used it already has a healthy modern-format cache.
  3. Reprocess: any modern-named ({hash16}_{quality}.ext) file whose
     actual pixel dimensions exceed its quality tier's cap gets
     re-encoded down to WebP; modern-named files with no matching
     cached_images row at all are deleted as orphaned.

Idempotent — safe to re-run; a second run should find nothing left to do.
Dry-run by default; pass --execute to actually change anything.

Usage:
    docker compose exec web python scripts/cache_cleanup.py            # dry run
    docker compose exec web python scripts/cache_cleanup.py --execute  # apply
"""

import argparse
import hashlib
import io
import logging
import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from app import get_db_connection
from scripts.image_cache_service import ImageCacheService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [cleanup] %(message)s',
)
logger = logging.getLogger('cache_cleanup')

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'static', 'cached_images',
)

LEGACY_RE = re.compile(r'^([0-9a-f]{32})\.\w+$')
MODERN_RE = re.compile(r'^([0-9a-f]{16})_(\w+)\.(\w+)$')

QUALITY_MAX_SIDE = {
    'thumbnail': 150,
    'low': 400,
    'medium': 800,
}


def _process_and_save(service, image_bytes, quality_level, dest_path):
    """Resize + encode as WebP via the same pipeline ImageCacheService
    uses. Takes bytes (not a path) so it's always safe to write to
    dest_path even when dest_path is the same file we just read —
    the source is fully buffered in memory before any write happens."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        img = service._process_image(img, quality_level)
        img.save(dest_path, 'WEBP', quality=70, method=6)
        width, height = img.size
    file_size = os.path.getsize(dest_path)
    return file_size, width, height


def recover_legacy(cursor, service, execute, stats):
    """Phase 1: recover pins whose only surviving cache copy is a legacy
    full-resolution file. Returns the set of legacy md5 stems this phase
    claimed, so Phase 2 doesn't also count them as redundant-purge
    candidates (which would double-count in dry-run mode, since nothing
    is actually deleted until --execute)."""
    legacy_files = {}
    for name in os.listdir(CACHE_DIR):
        m = LEGACY_RE.match(name)
        if m:
            legacy_files[m.group(1)] = name

    if not legacy_files:
        logger.info("Phase 1 (recover): no legacy files found")
        return set()

    cursor.execute("""
        SELECT p.id AS pin_id, p.image_url, ci.cache_status, ci.cached_filename
          FROM pins p
          LEFT JOIN cached_images ci ON p.cached_image_id = ci.id
         WHERE p.image_url LIKE 'http%%'
    """)
    pins = cursor.fetchall()

    claimed_stems = set()
    for pin in pins:
        stem = hashlib.md5(pin['image_url'].encode()).hexdigest()
        legacy_name = legacy_files.get(stem)
        if not legacy_name:
            continue

        healthy = (
            pin['cache_status'] == 'cached'
            and pin['cached_filename']
            and not pin['cached_filename'].endswith('.placeholder')
            and os.path.exists(os.path.join(CACHE_DIR, pin['cached_filename']))
        )
        if healthy:
            continue  # redundant — Phase 2 will purge the legacy file

        claimed_stems.add(stem)
        legacy_path = os.path.join(CACHE_DIR, legacy_name)
        legacy_size = os.path.getsize(legacy_path)
        new_filename = f"{stem[:16]}_low.webp"
        new_path = os.path.join(CACHE_DIR, new_filename)

        stats['recover_count'] += 1
        stats['recover_old_bytes'] += legacy_size
        logger.info(f"RECOVER pin {pin['pin_id']}: {legacy_name} ({legacy_size} bytes) -> {new_filename}")

        if not execute:
            continue

        try:
            with open(legacy_path, 'rb') as f:
                data = f.read()
            new_size, width, height = _process_and_save(service, data, 'low', new_path)
        except Exception as e:
            logger.error(f"Failed to recover pin {pin['pin_id']} from {legacy_name}: {e}")
            stats['errors'] += 1
            continue

        stats['recover_new_bytes'] += new_size

        cursor.execute("""
            INSERT INTO cached_images
                (original_url, cached_filename, file_size, width, height, quality_level, cache_status)
            VALUES (%s, %s, %s, %s, %s, 'low', 'cached')
            ON DUPLICATE KEY UPDATE
                cached_filename = VALUES(cached_filename),
                file_size       = VALUES(file_size),
                width           = VALUES(width),
                height          = VALUES(height),
                cache_status    = 'cached',
                updated_at      = NOW()
        """, (pin['image_url'], new_filename, new_size, width, height))
        cache_id = cursor.lastrowid

        cursor.execute(
            "UPDATE pins SET cached_image_id=%s, uses_cached_image=TRUE WHERE id=%s",
            (cache_id, pin['pin_id']),
        )

        try:
            os.remove(legacy_path)
        except OSError as e:
            logger.error(f"Failed to remove migrated legacy file {legacy_path}: {e}")

    return claimed_stems


def purge_legacy(execute, recovered_stems, stats):
    """Phase 2: delete every legacy full-resolution file not claimed by
    Phase 1 (i.e. the pin that used it already has a healthy modern-format
    cache, or the file has no owning pin at all)."""
    for name in sorted(os.listdir(CACHE_DIR)):
        m = LEGACY_RE.match(name)
        if not m or m.group(1) in recovered_stems:
            continue
        path = os.path.join(CACHE_DIR, name)
        size = os.path.getsize(path)
        stats['purge_legacy_count'] += 1
        stats['purge_legacy_bytes'] += size
        logger.info(f"PURGE legacy {name} ({size} bytes)")
        if execute:
            try:
                os.remove(path)
            except OSError as e:
                logger.error(f"Failed to remove {path}: {e}")
                stats['errors'] += 1


def reprocess_oversized(cursor, service, execute, stats):
    """Phase 3: re-encode oversized modern-named files down to the
    correct size in WebP; delete modern-named files with no DB row at
    all (fully orphaned, not just oversized)."""
    cursor.execute("SELECT id, cached_filename FROM cached_images WHERE cached_filename IS NOT NULL")
    filename_to_id = {row['cached_filename']: row['id'] for row in cursor.fetchall()}

    for name in sorted(os.listdir(CACHE_DIR)):
        m = MODERN_RE.match(name)
        if not m:
            continue
        url_hash, quality_level, _ext = m.groups()
        if quality_level not in QUALITY_MAX_SIDE:
            continue  # e.g. _pasted (user uploads) or _dims_only.placeholder stubs

        path = os.path.join(CACHE_DIR, name)
        row_id = filename_to_id.get(name)

        if row_id is None:
            size = os.path.getsize(path)
            stats['purge_orphan_count'] += 1
            stats['purge_orphan_bytes'] += size
            logger.info(f"PURGE orphaned {name} ({size} bytes, no DB row)")
            if execute:
                try:
                    os.remove(path)
                except OSError as e:
                    logger.error(f"Failed to remove {path}: {e}")
                    stats['errors'] += 1
            continue

        try:
            with open(path, 'rb') as f:
                data = f.read()
            with Image.open(io.BytesIO(data)) as img:
                width, height = img.size
        except Exception as e:
            logger.error(f"Cannot read dimensions for {name}: {e}")
            stats['errors'] += 1
            continue

        max_side = QUALITY_MAX_SIDE[quality_level]
        if max(width, height) <= max_side:
            continue  # already within the size cap — leave existing JPEGs
                      # alone (only oversized files get reprocessed; see
                      # design doc Non-goals)

        old_size = len(data)
        new_filename = f"{url_hash}_{quality_level}.webp"
        new_path = os.path.join(CACHE_DIR, new_filename)

        stats['reprocess_count'] += 1
        stats['reprocess_old_bytes'] += old_size
        logger.info(f"REPROCESS {name} ({width}x{height}, {old_size} bytes) -> {new_filename}")

        if not execute:
            continue

        try:
            new_size, new_width, new_height = _process_and_save(service, data, quality_level, new_path)
        except Exception as e:
            logger.error(f"Failed to reprocess {name}: {e}")
            stats['errors'] += 1
            continue

        stats['reprocess_new_bytes'] += new_size

        cursor.execute("""
            UPDATE cached_images
               SET cached_filename=%s, file_size=%s, width=%s, height=%s, updated_at=NOW()
             WHERE id=%s
        """, (new_filename, new_size, new_width, new_height, row_id))

        if new_path != path:
            try:
                os.remove(path)
            except OSError as e:
                logger.error(f"Failed to remove old file {path}: {e}")


def print_report(stats, execute):
    logger.info("=" * 60)
    logger.info("CACHE CLEANUP REPORT (%s)", "EXECUTED" if execute else "DRY RUN")
    logger.info(
        "Phase 1 recover:  %d pins, %.1f MB source -> %s",
        stats['recover_count'], stats['recover_old_bytes'] / 1e6,
        f"{stats['recover_new_bytes'] / 1e6:.1f} MB" if execute else "unknown until --execute",
    )
    logger.info(
        "Phase 2 purge (redundant legacy): %d files, %.1f MB freed",
        stats['purge_legacy_count'], stats['purge_legacy_bytes'] / 1e6,
    )
    logger.info(
        "Phase 3 reprocess (oversized):    %d files, %.1f MB source -> %s",
        stats['reprocess_count'], stats['reprocess_old_bytes'] / 1e6,
        f"{stats['reprocess_new_bytes'] / 1e6:.1f} MB" if execute else "unknown until --execute",
    )
    logger.info(
        "Phase 3 purge (orphaned modern):  %d files, %.1f MB freed",
        stats['purge_orphan_count'], stats['purge_orphan_bytes'] / 1e6,
    )
    logger.info("Errors: %d", stats['errors'])

    guaranteed = stats['purge_legacy_bytes'] + stats['purge_orphan_bytes']
    if execute:
        total = (
            guaranteed
            + (stats['recover_old_bytes'] - stats['recover_new_bytes'])
            + (stats['reprocess_old_bytes'] - stats['reprocess_new_bytes'])
        )
        logger.info("Total freed: %.1f MB", total / 1e6)
    else:
        logger.info(
            "Guaranteed floor from purge phases alone: %.1f MB. "
            "Recover/reprocess savings depend on re-encoded size — "
            "re-run with --execute to see the real total.",
            guaranteed / 1e6,
        )


def main():
    parser = argparse.ArgumentParser(description='Reclaim space in static/cached_images')
    parser.add_argument('--execute', action='store_true', help='Apply changes. Without this flag, only prints the plan.')
    args = parser.parse_args()
    execute = args.execute

    if not execute:
        logger.info("DRY RUN — no files or database rows will be changed. Pass --execute to apply.")

    service = ImageCacheService(cache_dir=CACHE_DIR)
    stats = {
        'recover_count': 0, 'recover_old_bytes': 0, 'recover_new_bytes': 0,
        'purge_legacy_count': 0, 'purge_legacy_bytes': 0,
        'reprocess_count': 0, 'reprocess_old_bytes': 0, 'reprocess_new_bytes': 0,
        'purge_orphan_count': 0, 'purge_orphan_bytes': 0,
        'errors': 0,
    }

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        recovered_stems = recover_legacy(cursor, service, execute, stats)
        db.commit()
        purge_legacy(execute, recovered_stems, stats)
        reprocess_oversized(cursor, service, execute, stats)
        db.commit()
    finally:
        cursor.close()
        db.close()

    print_report(stats, execute)


if __name__ == '__main__':
    main()
