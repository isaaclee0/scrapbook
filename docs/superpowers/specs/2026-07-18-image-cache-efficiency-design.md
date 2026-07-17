# Image Cache Efficiency — Design

**Date:** 2026-07-18
**Status:** Approved

## Problem

`static/cached_images` is 5.6GB across 153k files — big enough that a backup
download of a single-user install doesn't finish. Profiling the folder against
the `cached_images` table showed the per-image processing pipeline itself is
fine (400px, JPEG q70, ~22KB average), but three things are inflating it:

1. **~3.1GB of orphaned legacy files** (32,466 files, avg 94KB, full-resolution
   originals named `md5(image_url).ext` by old import scripts). Every pin's
   `cached_image_id` now points at a modern `{hash16}_low.*` file instead —
   these are unreferenced dead weight in 99.7% of cases.
2. **~2.3GB of unresized raw downloads** (5,370 files >100KB, some multiple MB).
   `_bg_download_and_cache()` in `app.py` — the path triggered when a pin's
   dimensions are reported via `/save-pin-dimensions` — streams the source
   image straight to disk with no resize and no recompression, unlike
   `ImageCacheService._process_image()` which the batch worker uses.
3. **No WebP support.** All output is JPEG. Also as a byproduct of extension
   sniffing in `_generate_cache_filename()`, some files are JPEG-encoded data
   saved under a `.png`/`.webp` name (harmless today since browsers sniff
   content, but sloppy).

Two caching code paths exist and have drifted:
- `ImageCacheService` (`scripts/image_cache_service.py`) — used by the batch
  worker (`scripts/cache_worker.py`) and `/api` triggers in `app.py`. Resizes,
  extracts colors, tracks retries.
- `_bg_download_and_cache()` (`app.py:451`) — used only by
  `/save-pin-dimensions`. Does none of the above.

## Goals

- Stop writing full-resolution images into the display cache.
- Add WebP output for new/reprocessed images (~30% smaller than JPEG q70 at
  equivalent quality).
- Reclaim the ~5.4GB of legacy/oversized files already on disk (locally and
  on the live server), without losing recoverability where a pin has no other
  working cached copy.
- Collapse the two caching code paths into one so this can't drift again.

## Non-goals

- Re-encoding the ~130k already-healthy JPEGs to WebP. They're small
  (avg 22KB); re-encoding a lossy JPEG to WebP compounds artifacts for a
  ~0.6–0.9GB return that isn't worth the churn. Only new captures and files
  the cleanup script actively reprocesses become WebP.
- Changing the `thumbnail`/`medium` quality tiers. They're schema-only today
  (nothing ever requests them) and out of scope for this pass.
- Deleting the full-resolution originals from anywhere other than
  `static/cached_images`. The user already holds a separate full backup
  (`sqldump/`), so these files are not the last copy.

## Design

### 1. WebP output in `ImageCacheService`

`_generate_cache_filename()` (`scripts/image_cache_service.py:287`) drops its
URL-extension sniffing and always returns `{md5(url)[:16]}_{quality}.webp`.

`_cache_image()` saves with:
```python
img.save(cached_path, 'WEBP', quality=70, method=6)
```
for both the downloaded-image branch and the video-frame-extraction branch.
`method=6` trades encode time for size (fine — this runs in a background
worker, not a request path). Existing `.jpg` files and their `cached_images`
rows are untouched; the `UNIQUE KEY (original_url, quality_level)` means a
pin whose JPEG already exists simply never gets touched again by the worker
(it only processes rows that aren't `cached`).

### 2. Consolidate the browser-triggered path onto `ImageCacheService`

`_bg_download_and_cache()` (`app.py:451`–`567`, ~120 lines, including the
`_bg_cache_semaphore`) is deleted. In `/save-pin-dimensions`
(`app.py:3406`), the block that spawns
`threading.Thread(target=_bg_download_and_cache, ...)` is replaced with a call
into the same lazily-constructed `ImageCacheService` instance the rest of the
app already uses (there are currently two separate lazy-init blocks for this,
at `app.py:1897` and `app.py:2845` — both become one shared
`_get_cache_service()` helper).

Behavior changes accepted as part of this consolidation:
- The browser-reported `width`/`height` still get written to the pin
  immediately (unchanged — this is what avoids layout shift on the next
  load). The service overwrites them with the actual post-resize dimensions
  once caching completes; same aspect ratio, so no layout impact.
- Downloads now go through the service's retry/backoff bookkeeping
  (`_should_retry`, exponential backoff on failure) instead of unconditionally
  retrying on every page load. This is a strict improvement — it stops
  hammering dead URLs — but is a behavior change worth naming.
- The per-request semaphore (cap of 4 concurrent inline downloads) is
  replaced by the service's own worker pool (6 threads, started lazily).

Net effect: one caching pipeline, one place where resize/format logic lives,
WebP support automatically applies to both entry points.

### 3. One-off cleanup script — `scripts/cache_cleanup.py`

Run manually on each environment (local now, live server after deploy):
```
docker compose exec web python scripts/cache_cleanup.py            # dry run, prints plan
docker compose exec web python scripts/cache_cleanup.py --execute  # applies it
```
Idempotent — safe to re-run; a second run should find nothing left to do.

**Phase 1 — Recover.** For every legacy file matching `^[0-9a-f]{32}\.\w+$`,
compute which pin(s) it belongs to via `md5(pins.image_url) == filename_stem`.
If the pin's current cache state is *not* healthy (no `cached_image_id`, its
`cached_images` row isn't `cache_status='cached'`, its `cached_filename` is a
placeholder, or the referenced file is missing from disk — this last case is
common locally per [[scrapbook-local-dev-quirks]]), process the legacy file
through the same resize/WebP path as `ImageCacheService._process_image` +
save, producing a proper `{hash16}_low.webp`, and upsert/link the
`cached_images` row. This recovers pins whose only surviving copy is the
legacy file (105 such pins by current DB state locally; the live server may
differ).

**Phase 2 — Purge legacy.** Delete every remaining
`^[0-9a-f]{32}\.\w+$` file (i.e., not touched by Phase 1's recovery,
meaning some other pin already has a healthy modern cache for the same URL).
This is the ~3.1GB reclaim.

**Phase 3 — Reprocess oversized.** For every `{hash16}_{quality}.*` file
(skip `_pasted` — user-uploaded images, not derived from a URL — and skip
`.placeholder` dims-only stubs), read its pixel dimensions from the file
header. The decision is dimension-based, not size-based: if the longest side
exceeds the quality tier's cap (400px for `low`, matching `_process_image`),
re-encode through the same resize/WebP path,
update the `cached_images` row's `cached_filename`/`file_size`/`width`/
`height`, and delete the old file. A modern-named file with no matching
`cached_images` row at all (fully orphaned, not just oversized) is deleted
and logged rather than reprocessed.

**Phase 4 — Report.** Per-phase counts (files touched, bytes freed) and a
list of any per-file errors (corrupt image, permission issue, etc. — logged
and skipped, not fatal to the run).

### 4. Verification

- Run the script for real against the local Docker stack (disposable mirror
  of production data per [[scrapbook-local-dev-quirks]]); confirm the
  before/after folder size and file count match the dry-run's printed plan.
- Browser-check a board and search results after the run: recovered pins
  render (no broken-image fallback), reprocessed pins serve `.webp` at the
  same layout size as before (masonry dimensions come from the DB, untouched
  by format changes — see [[scrapbook-masonry-engine]]).
- Manually trigger `/save-pin-dimensions` for a pin with no existing cache
  and confirm the resulting file is a 400px-capped `.webp`, not a raw
  original, exercising the consolidated path end-to-end.

## Expected outcome

Local/live `cached_images` folder: ~5.6GB → roughly 2.5–3GB (exact figure
depends on how many files on the live server turn out oversized/orphaned,
which the dry run will report before anything is deleted). New captures run
~30% smaller via WebP. One caching code path instead of two.
