# Pin Image Gallery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add related images to a pin, a manually navigated gallery, and board stack indicators.

**Architecture:** Store ordered image records beside each pin and project the cover into existing pin fields. A gallery service owns mutations, upload validation, and persistence; a browser module owns pin navigation. Preserve the existing overlay, notes, creation flows, and audit undo.

**Tech Stack:** Flask, MariaDB, Pillow, vanilla JavaScript/CSS, unittest, Playwright.

## Global Constraints

- The cover is always the first item in the displayed order.
- Notes remain plain text; adding images is a separate interaction.
- Board cards stay on their cover with a stack/count indicator for multiple images.
- Desktop and mobile open the pin normally; no board hover, long-press, or swipe preview.
- No automatic advance inside the opened pin.
- Existing pins and single-image capture flows remain valid.
- Retain uploaded originals and undo references across cache cleanup.
- All mutations require authenticated pin ownership and CSRF checks.
- Defaults: 20 images per pin, 20 MiB per upload, 40 million decoded pixels.

## Interfaces

`GET /api/pin/<id>/images` returns `{success:true, images:[{id,image_url,display_url,preview_url,width,height,position}], image_count:n}`. The ordered first image is the cover. Empty collections display the existing default placeholder.

`POST /api/pin/<id>/images` accepts multipart `file`, optionally `replace_id`, and returns the updated gallery. `POST /api/pin/<id>/images/manage` accepts JSON `{action:'cover'|'remove'|'reorder', image_id?:number, image_ids?:number[]}` and returns the updated gallery. All responses use a meaningful JSON `error` and appropriate HTTP status for failures. IDs are stable; stale or incomplete reorder sets are rejected.

Image originals and previews live under `static/cached_images/gallery/` (inside the existing persistent volume), served through the existing `/cached/<path:filename>` route. Originals are never garbage-collected by cache expiry. Gallery URLs use `/cached/gallery/<opaque-filename>`. Legacy cached sources remain supported and protected while referenced.

### Task 1: Gallery service, schema, and upload storage

**Files:** create `pin_gallery.py`, `tests/test_pin_gallery.py`; modify `migrate.py`, `init.sql`.

**Interfaces:** `ensure_pin_images(cursor, pin)` lazily initializes legacy pins; `list_images(cursor, pin)` produces the ordered API list; `mutate_gallery(cursor, pin, action, image_id=None, image_ids=None, upload=None)` mutates under a caller-held pin row lock, updates cover fields, and returns the API list. `save_upload(file, storage_root, max_bytes, max_pixels)` validates/decode-checks and writes original plus preview, returning image fields. `restore_images(cursor, pin_id, images)` restores stable IDs/order from audit snapshots. `snapshot_images(cursor, pin_id)` returns full stored rows. A `GalleryError` carries message and status.

- [x] Write service tests first. Cover add/replace/reorder/cover/remove, missing/foreign image IDs, stale reorder, default placeholder, repeated legacy initialization, and malformed/oversized uploads. Use real in-memory SQL through a small test adapter where possible.

```python
def test_uploaded_recipe_keeps_readable_original(self):
    image = save_upload(self.recipe_file(), self.storage_root, 20 * 1024 * 1024, 40_000_000)
    self.assertEqual(image['height'], 2400)
    self.assertNotEqual(image['preview_url'], image['image_url'])
```

- [x] Run `.venv/bin/python -m unittest tests.test_pin_gallery` and observe feature failures.
- [x] Implement the related table with pin foreign key, stable ID, image URL, preview URL, dimensions, cache reference, and position. Backfill idempotently, excluding the default placeholder. Lock the pin before initializing/mutating. Preserve order and cover projection atomically; serialize writes and reject stale identifiers. Store originals/previews in the durable gallery directory. Reject non-raster/invalid content, excessive bytes and pixels; use opaque server-generated names and normalize EXIF orientation.
- [x] Rerun service tests, compile changed Python modules, and inspect the diff.

### Task 2: Application integration and retention

**Files:** modify `app.py`, `audit_helpers.py`, `scripts/image_cache_service.py`, `scripts/cache_cleanup.py`; create `tests/test_pin_gallery_routes.py`, `tests/test_gallery_retention.py`.

**Interfaces:** use Task 1 APIs and the HTTP contract above. Board card/list queries add `image_count`; selected image opening uses `image=<stable-id>`.

- [x] Add failing route tests for ownership, CSRF, upload validation, missing pins, selected image search, and successful gallery mutation. Add snapshot/restore and cache-retention regressions.

```python
def test_other_users_pin_has_no_gallery(self):
    response = self.client.get('/api/pin/42/images')
    self.assertEqual(response.status_code, 404)
```

- [x] Run the new targeted tests and observe failures.
- [x] Register authenticated gallery routes and mutation audit events. Initialize newly created pins through the service and route legacy replacement through cover mutation. Add image counts to initial boards, dynamic board loads, and card refresh. Pass selected image identity to Google Lens signed links and validate it against pin ownership. Include gallery snapshots and stable-ID restore in existing delete/undo paths. Protect referenced cache files and local originals from cleanup/reprocessing; guard asynchronous cache updates against a changed cover. Never delete an uploaded original as part of image removal.
- [x] Run Python suites and inspect SQL paths for atomic updates and concurrency.

### Task 3: Pin gallery and management controls

**Files:** create `static/js/pin-gallery.js`, `static/css/pin-gallery.css`, `tests/e2e/pin-gallery.spec.js`, `tests/e2e/fixtures/pin-gallery.html`; modify `templates/pin.html`.

**Interfaces:** controller consumes the HTTP contract; exposes current image to existing tools and notifies `notifyPinOverlay('changed', 'updated')` after saved mutations. Fullscreen uses the selected original.

- [x] Add failing browser coverage for arrows/keyboard/swipes, selected image opening, uploads/removal/cover/reorder, normal notes paste, and failure recovery.

```javascript
await page.getByRole('button', { name: 'Next image', exact: true }).click();
await expect(page.locator('[data-gallery-position]')).toHaveText('2 / 3');
```

- [x] Run focused Playwright tests and observe missing-gallery failures.
- [x] Implement accessible navigation, visible image count, image-load failure recovery, selected-original fullscreen with enlargement/panning, add area with upload/drop/paste, thumbnails and button-based reorder, cover/replace/remove actions, loading states and per-file failures. Preserve notes input and vertical scrolling. Existing image-specific tools act on selected image. Keep controller code out of the large template.
- [x] Run focused browser tests on Chromium and WebKit, review responsive screenshots.

### Task 4: Board indicators

**Files:** create `static/css/pin-stack.css`, `tests/e2e/pin-stack.spec.js`, `tests/e2e/fixtures/pin-stack.html`; modify `templates/board.html`, `static/js/pin-overlay.js`.

**Interfaces:** board cards provide pin ID, cover URL, and image count. Opening a card uses the ordinary pin overlay and starts on the cover. Board cards never cycle images.

- [x] Cover static board indicators, dynamic and refreshed cards, normal desktop/mobile opening, and metadata safety.

```javascript
const before = await card.boundingBox();
await card.hover();
await page.clock.runFor(5000);
await expect(card.locator('img')).toHaveAttribute('src', coverUrl);
expect(await card.boundingBox()).toEqual(before);
```

- [x] Render stack counts in server and dynamic cards. Preserve optional selected-image deep links without adding per-slide history, and keep ordinary board opening on the cover.
- [x] Run gallery, stack-indicator, and existing overlay tests together; fix integration issues.

### Task 5: Review and completion

**Files:** all changed files; update this plan's checkboxes and the approved design status.

- [x] Review implementation against the full design and resolve gaps. Use a separate reviewer for ownership/retention and browser integration.
- [x] Run `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`, Node extension tests, and the relevant Playwright suites. Inspect gallery desktop/mobile screenshots and verify unchanged card geometry.
- [x] Run `git diff --check`, inspect final changes, commit the feature branch, and report verification plus any environment limits. Leave deployment for the user's release workflow.


## Execution record

- Worktree: `codex/pin-image-gallery`, created from `a0d4553f3` on `main`.
- Gallery originals and 1600px WebP previews are retained inside the existing persistent image volume. Limits are 20 images, 20 MiB per file, and 40 million pixels.
- Replaced legacy mocked image-update tests with real SQL and image-decoding integration tests covering those behaviours plus secondary-image preservation.
- Review found and fixed stale snapshot reads, pre-commit view-cache invalidation, preview-source use, and stale browser metadata writes. Gallery/audit snapshots use locking current reads and scoped READ COMMITTED transactions.
- Final scope follows the user's indicator-only decision: board hover cycling was removed. Navigation is inside the opened pin.
- Final review identified and corrected runtime Docker module packaging, dimension/cache synchronization, cached-image fallback, and readable board/section cover selection.
- Real MariaDB testing exposed pool-wrapper autocommit assignment failing to start transactions. `tx` now calls `start_transaction` explicitly for all callers; pooled default/scoped commit, rollback and release state were verified.
- Python: 69 tests passed (`python -m unittest discover -b -s tests -p 'test_*.py'`). The existing application startup logs unavailable local MySQL/Redis during isolated tests; route tests use controlled databases.
- Extension unit tests: 3 passed (`node --test tests/extension/*.test.js`).
- Full browser suite: 102 passed in Chromium and WebKit (`npx playwright test --reporter=line`). Includes static stack indicators, gallery navigation and image recovery, and existing extension and overlay regressions.
- Actual rendered pin/base templates: desktop/mobile and direct/embedded checks passed in both browser engines; screenshots inspected. Fixed mobile title shrink/close-button clipping and child-frame Escape handling.
- Actual template action checks: board and section cover payloads use a healthy cached source when the original expires, or the original after a missing cache fallback. Four browser checks passed.
- MariaDB 11.6.2: schema initialization and migration reruns, legacy/cache/placeholder backfill, ordered mutations, rollback, delete/restore, concurrent additions and image limits passed. Verified old read-view handling and pooled transaction boundaries. Disposable container and its volume removed.
- Docker runtime COPY staging/import smoke passed with isolated imports for the app, migration, gallery service, retention helper, and cache scripts. A full production image build was not run.
- Deployment is outside this implementation. Normal startup runs the idempotent gallery migration before serving the new routes.
