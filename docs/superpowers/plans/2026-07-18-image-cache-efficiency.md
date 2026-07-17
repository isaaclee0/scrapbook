# Image Cache Efficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut `static/cached_images` from ~5.6GB to ~2.5–3GB by switching new image caching to WebP, consolidating the two drifted caching code paths onto one pipeline, and running a one-off cleanup script that recovers, purges, and reprocesses existing files.

**Architecture:** `ImageCacheService` (`scripts/image_cache_service.py`) becomes the single place that downloads/resizes/encodes images; `app.py`'s duplicate inline downloader is deleted and its one caller routes through the service instead. A new standalone script, `scripts/cache_cleanup.py`, reuses the service's resize/encode logic to fix up what's already on disk.

**Tech Stack:** Flask, MariaDB (via `mysql.connector`), Pillow 10.1.0 (WEBP support is bundled in its manylinux wheel — verified in Task 1, not assumed), Docker Compose for the dev environment.

**Testing note:** This repo has no automated test suite (no `pytest`/`conftest.py`/test framework in `requirements.txt`). Verification steps in this plan run real commands against the local Docker stack — which mirrors production data per the project's dev-quirks memory — rather than fabricating a test framework that doesn't fit a single-file Flask app with no prior test infrastructure. Each task's "verify" step describes an exact command and exact expected output, same rigor as a test assertion.

---

## Task 1: WebP output in `ImageCacheService`

**Files:**
- Modify: `scripts/image_cache_service.py:287-310` (`_generate_cache_filename`)
- Modify: `scripts/image_cache_service.py:456` (video-frame save)
- Modify: `scripts/image_cache_service.py:490` (regular-image save)

- [ ] **Step 1: Confirm current behavior before changing it**

Run: `docker compose exec -T web python -c "
from scripts.image_cache_service import ImageCacheService
s = ImageCacheService()
print(s._generate_cache_filename('https://example.com/photo.png', 'low'))
"`
Expected: `<16-hex-hash>_low.png` — confirms the current extension-sniffing behavior we're about to remove.

- [ ] **Step 2: Simplify `_generate_cache_filename` to always emit `.webp`**

Replace the full method body (`scripts/image_cache_service.py:287-310`):

```python
    def _generate_cache_filename(self, original_url, quality_level):
        """Generate a unique filename for cached image"""
        url_hash = hashlib.md5(original_url.encode()).hexdigest()[:16]
        return f"{url_hash}_{quality_level}.webp"
```

This removes the `urlparse`/extension-sniffing block entirely — `urlparse` and `urljoin` are still used elsewhere in the file (`_headers_for_url` doesn't use them, but check before removing the import). Run `grep -n "urlparse\|urljoin" scripts/image_cache_service.py` after this edit — if no calls remain outside the changed method, remove the now-unused `from urllib.parse import urlparse, urljoin` import at the top of the file (line 13). If any remain, leave the import.

- [ ] **Step 3: Switch both `img.save()` calls from JPEG to WebP**

At `scripts/image_cache_service.py:456` (inside the video-frame branch of `_cache_image`):

```python
        img.save(cached_path, 'WEBP', quality=70, method=6)
```
(replaces `img.save(cached_path, 'JPEG', quality=70, optimize=True)`)

At `scripts/image_cache_service.py:490` (inside the regular-image branch of `_cache_image`):

```python
        img.save(cached_path, 'WEBP', quality=70, method=6)
```
(replaces the identical `img.save(cached_path, 'JPEG', quality=70, optimize=True)` line — these are two separate occurrences in two different branches; edit both, not just the first match.)

`method=6` is Pillow's slowest/smallest WebP encode setting — acceptable since this always runs in a background worker thread, never in a request path.

- [ ] **Step 4: Verify the new filename format and that Pillow can actually write WebP in this container**

Run: `docker compose exec -T web python -c "
from scripts.image_cache_service import ImageCacheService
s = ImageCacheService()
print(s._generate_cache_filename('https://example.com/photo.png', 'low'))
from PIL import Image
img = Image.new('RGB', (10, 10), (255, 0, 0))
img.save('/tmp/webp_check.webp', 'WEBP', quality=70, method=6)
print('WebP write OK, size:', __import__('os').path.getsize('/tmp/webp_check.webp'))
"`
Expected: first line ends in `_low.webp`; second line prints a small positive byte count (confirms Pillow's WebP encoder works in this image — Pillow 10.1.0 bundles libwebp in its wheel, but this is worth confirming rather than assuming).

- [ ] **Step 5: End-to-end check — cache one real pin and confirm a `.webp` file lands on disk**

Find an uncached pin and cache it directly through the service:
```
docker compose exec -T web python -c "
from app import get_db_connection
from scripts.image_cache_service import ImageCacheService
db = get_db_connection()
cur = db.cursor(dictionary=True)
cur.execute('''
    SELECT p.id, p.image_url FROM pins p
    LEFT JOIN cached_images ci ON p.cached_image_id = ci.id
    WHERE p.image_url LIKE \"http%%\" AND (ci.cache_status IS NULL OR ci.cache_status != \"cached\")
    LIMIT 1
''')
pin = cur.fetchone()
cur.close(); db.close()
print('Testing with pin', pin['id'], pin['image_url'][:60])
s = ImageCacheService()
cache_id = s._cache_image(pin['id'], pin['image_url'], 'low')
print('cache_id:', cache_id)
"
```
Expected: prints a pin id/URL, then a non-`None` `cache_id`. Then run `docker compose exec -T web sh -c "ls -la static/cached_images/*_low.webp | tail -1"` and confirm the newest `_low.webp` file exists with a size in the 5–60KB range typical of a 400px-capped image.

- [ ] **Step 6: Commit**

```bash
git add scripts/image_cache_service.py
git commit -m "Switch ImageCacheService output to WebP"
```

---

## Task 2: Consolidate the browser-triggered caching path onto `ImageCacheService`

**Files:**
- Modify: `app.py:441-568` (delete `_bg_download_and_cache` and its semaphore)
- Modify: `app.py:1895-1905` (`add_pin` — use shared helper)
- Modify: `app.py:2818-2850` (singleton globals — add shared helper, use it in `cache_images`)
- Modify: `app.py:3477-3486` (`/save-pin-dimensions` — route through the service instead of the deleted function)

- [ ] **Step 1: Confirm no other references to the code being deleted**

Run: `grep -n "_bg_download_and_cache\|_bg_cache_semaphore" app.py`
Expected: exactly 4 matches — the semaphore definition, the function definition, the `.acquire()`/`.release()` calls inside it, and the one call site in `/save-pin-dimensions`. If anything else references these names, stop and investigate before deleting.

- [ ] **Step 2: Delete `_bg_download_and_cache` and its semaphore**

Remove this entire block from `app.py` (currently lines 441–568, the comment header through the trailing blank line before `def get_db_connection():`):

```python
# ---------------------------------------------------------------------------
# Background image caching
# Triggered when the browser successfully loads an image from an external URL.
# Downloads the file to static/cached_images/ in a daemon thread so the pin
# serves locally on all future page loads.
# ---------------------------------------------------------------------------

# Cap concurrent background downloads so a busy board doesn't flood outbound.
_bg_cache_semaphore = threading.Semaphore(4)

def _bg_download_and_cache(pin_id, image_url, width, height, cache_id, board_id=None):
    ...
    [full existing body, through the closing `finally: _bg_cache_semaphore.release()`]
```

After deletion, `app.py` should go directly from the block before line 441 to `def get_db_connection():`.

- [ ] **Step 3: Add a shared `_get_cache_service()` helper next to the existing singleton globals**

At `app.py:2818-2821`, where the globals currently read:

```python
# Global singleton for image cache service to prevent thread accumulation
_image_cache_service = None
_image_cache_lock = threading.Lock()
_image_caching_in_progress = False
```

add a helper function immediately after:

```python
# Global singleton for image cache service to prevent thread accumulation
_image_cache_service = None
_image_cache_lock = threading.Lock()
_image_caching_in_progress = False

def _get_cache_service():
    """Lazily construct the shared ImageCacheService singleton."""
    global _image_cache_service
    with _image_cache_lock:
        if _image_cache_service is None:
            from scripts.image_cache_service import ImageCacheService
            _image_cache_service = ImageCacheService()
        return _image_cache_service
```

(This is safe to call from functions defined earlier in the file, like `add_pin` — Python resolves the reference at call time, after the whole module has loaded.)

- [ ] **Step 4: Use the helper in `add_pin`**

Replace `app.py:1895-1905`:

```python
        if image_url.startswith('http'):
            try:
                global _image_cache_service
                with _image_cache_lock:
                    if _image_cache_service is None:
                        from scripts.image_cache_service import ImageCacheService
                        _image_cache_service = ImageCacheService()
                    cache_service = _image_cache_service
                cache_service.queue_image_for_caching(pin_id, image_url, 'low', board_id)
            except Exception as e:
                print(f"Failed to queue image for caching: {e}")
```

with:

```python
        if image_url.startswith('http'):
            try:
                cache_service = _get_cache_service()
                cache_service.queue_image_for_caching(pin_id, image_url, 'low', board_id)
            except Exception as e:
                print(f"Failed to queue image for caching: {e}")
```

- [ ] **Step 5: Use the helper in `cache_images`**

Replace `app.py:2844-2850`:

```python
        # Import and use the image cache service (singleton)
        from scripts.image_cache_service import ImageCacheService
        
        with _image_cache_lock:
            if _image_cache_service is None:
                _image_cache_service = ImageCacheService()
            cache_service = _image_cache_service
```

with:

```python
        cache_service = _get_cache_service()
```

- [ ] **Step 6: Route `/save-pin-dimensions` through the service**

Replace `app.py:3477-3486`:

```python
        # Kick off a background download if the file isn't already on disk.
        # The thread updates cached_images + pins once complete, so future
        # page loads serve from /cached/ and never touch the external URL.
        if not already_cached and image_url.startswith('http'):
            t = threading.Thread(
                target=_bg_download_and_cache,
                args=(pin_id, image_url, width, height, cache_id, board_id),
                daemon=True
            )
            t.start()
```

with:

```python
        # Queue a background caching job if the file isn't already on disk.
        # ImageCacheService resizes/encodes and updates cached_images + pins
        # once complete, so future page loads serve from /cached/ and never
        # touch the external URL. The service looks up the pending row we
        # just wrote above by (image_url, quality_level='low'), so cache_id
        # doesn't need to be passed explicitly.
        if not already_cached and image_url.startswith('http'):
            try:
                cache_service = _get_cache_service()
                cache_service.queue_image_for_caching(pin_id, image_url, 'low', board_id)
            except Exception as e:
                print(f"Failed to queue image for caching: {e}")
```

- [ ] **Step 7: Verify the module still imports cleanly**

Run: `docker compose exec -T web python -c "import app; print('OK')"`
Expected: `OK` with no traceback. This catches leftover references to the deleted names or indentation mistakes from the edits above.

- [ ] **Step 8: Restart the web container and verify `/save-pin-dimensions` end-to-end**

Run: `docker compose up -d --no-deps web`

Then, using a pin with no cached image (same query pattern as Task 1 Step 5) and a valid session cookie (see the project's dev-quirks memory for minting one without a real OTP), POST to `/save-pin-dimensions/<pin_id>` with `{"width": 600, "height": 400}` and confirm:
1. The HTTP response is `{"success": true}`.
2. Within a few seconds, `docker compose logs web --tail 50` shows the pin being cached (the service's own `logger.info` calls, e.g. `"Downloading image: ..."` / `"Cached image: ..."`).
3. `SELECT cached_filename, cache_status FROM cached_images WHERE id = (SELECT cached_image_id FROM pins WHERE id = <pin_id>)` shows a `_low.webp` filename and `cache_status = 'cached'`.
4. The file exists: `docker compose exec -T web test -f static/cached_images/<that filename> && echo EXISTS`.

- [ ] **Step 9: Commit**

```bash
git add app.py
git commit -m "Consolidate browser-triggered image caching onto ImageCacheService"
```

---

## Task 3: Write the cleanup script — `scripts/cache_cleanup.py`

**Files:**
- Create: `scripts/cache_cleanup.py`

- [ ] **Step 1: Write the full script**

```python
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
```

- [ ] **Step 2: Verify the script imports and argparses cleanly**

Run: `docker compose exec -T web python scripts/cache_cleanup.py --help`
Expected: argparse usage output listing `--execute`, no traceback.

- [ ] **Step 3: Commit**

```bash
git add scripts/cache_cleanup.py
git commit -m "Add one-off cleanup script for static/cached_images"
```

---

## Task 4: Run the cleanup against the local mirror and verify

**Files:** none (operational task — runs the script from Task 3 against the local Docker stack, which mirrors production data)

- [ ] **Step 1: Baseline the local cache folder**

Run: `docker compose exec -T web sh -c "du -sh static/cached_images && ls static/cached_images | wc -l"`
Record the output (should match the ~5.6GB / ~153k files this plan was scoped against, modulo whatever changed since).

- [ ] **Step 2: Dry run and read the plan before touching anything**

Run: `docker compose exec -T web python scripts/cache_cleanup.py 2>&1 | tail -20`
Expected: the `CACHE CLEANUP REPORT (DRY RUN)` block with non-zero counts in Phase 1 (recover, roughly 100+ pins locally per the folder/DB drift noted in the project's dev-quirks memory) and Phase 2 (purge, tens of thousands of files, multiple GB). Read through it — if the recover/purge counts look wildly different from what earlier analysis found (~105 recover, ~32k purge), stop and investigate before running `--execute`, since that would mean either the folder or DB changed unexpectedly since this plan was written.

- [ ] **Step 3: Execute for real**

Run: `docker compose exec -T web python scripts/cache_cleanup.py --execute 2>&1 | tee /tmp/cleanup_run.log | tail -20`
Expected: the `CACHE CLEANUP REPORT (EXECUTED)` block with a concrete `Total freed` figure. `Errors: 0` ideally — if not, grep `/tmp/cleanup_run.log` for `ERROR` lines and check whether they're a handful of genuinely corrupt files (acceptable, script logs and skips them) or something systemic (stop and investigate).

- [ ] **Step 4: Confirm the folder actually shrank**

Run: `docker compose exec -T web sh -c "du -sh static/cached_images && ls static/cached_images | wc -l"`
Expected: total size dropped to roughly 2.5–3GB (down from the Step 1 baseline), file count dropped by roughly the sum of Phase 2 + Phase 3-orphan counts (recovered/reprocessed files are 1-for-1 replacements, not net removals, so they don't change the count).

- [ ] **Step 5: Confirm no legacy files remain**

Run: `docker compose exec -T web sh -c "ls static/cached_images | grep -vE '^[0-9a-f]{16}_' | wc -l"`
Expected: `0`.

- [ ] **Step 6: Browser-check a board and search results**

Restart the web container to pick up Task 1/2's code changes if not already running with them (`docker compose up -d --no-deps web`), then open a board in the browser pane and confirm:
1. Pins render normally — no broken-image icons where there weren't any before.
2. Network tab / page source shows `/cached/<hash>_low.webp` URLs for at least some pins (confirms the format switch took effect for newly-touched files).
3. Layout is stable (masonry positions match pre-cleanup — dimensions in the DB were only updated to the *actual* post-resize values, which share the same aspect ratio, so this should be a non-event, but confirm per this project's masonry-engine invariants memory).

Repeat the same check on the search page (`/search?q=<something with matches>`).

- [ ] **Step 7: Re-run the dry run once more to confirm idempotency**

Run: `docker compose exec -T web python scripts/cache_cleanup.py 2>&1 | tail -20`
Expected: all counts are `0` — nothing left for the script to do. This is the key idempotency guarantee promised in the script's docstring; if any phase still reports work, the phase's "already handled" check has a bug.

- [ ] **Step 8: Note the live-server rollout separately**

This task only covers the local Docker mirror. Running the same two commands (dry run, then `--execute`) against the live server is a separate, deliberate operational step the user performs after deploying Tasks 1–3's code changes — not part of this plan's automated steps, since it touches production data and the user asked to run it "when it restarts with a change we make here."

---
