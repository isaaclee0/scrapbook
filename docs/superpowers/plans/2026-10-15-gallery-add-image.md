# Gallery Add Image Implementation Plan

> Execute inline using superpowers:executing-plans with test-driven development.

**Goal:** The gallery plus button opens a compact box for an image URL, pasted
images, dropped images, or optional uploads from the computer.

**Design:** A native modal dialog preserves the compact gallery layout. The URL
field receives focus, and image paste works anywhere inside the dialog. A preview
appears before the explicit Add image action. Cancel/Escape restores focus to the
plus button without closing the pin. Failed saves leave a retryable error. Keep
direct paste/drop into the gallery and the existing three-second success toast.

**Architecture:** Extend the existing authenticated, CSRF-protected image POST
route to accept an `image_url` form field alongside its current upload path.
Validate a complete HTTP(S) image URL and store the remote reference through the
same gallery mutation/audit transaction; no server-side fetching is introduced.
The browser checks the image preview. Keep the existing cover and image limits.

**Files:** `static/js/pin-gallery.js`, `static/css/pin-gallery.css`, the gallery
POST handler in `app.py`, `tests/e2e/pin-gallery.spec.js`, and a new
`tests/test_gallery_image_urls.py` reusing the SQLite integration fixture.

**Constraints:** Work locally; preserve unrelated authentication edits. No new
dependencies, production content changes, or deployment in this iteration.

## Tasks

- [x] Add regression tests for opening/closing/focus, image URL preview/save and
  errors, paste/upload/drop previews and explicit confirmation, mobile bounds,
  and server URL validation/ownership/CSRF/limits/audit/cover preservation.
- [x] Run the new tests and observe missing-dialog / unsupported-URL failures.
- [x] Extend `upload_pin_image` with the URL alternative. Reject missing/invalid
  HTTP(S) URLs, credentials, whitespace/control characters, and URLs over 2048
  characters before mutation. Retain existing multipart upload handling.
- [x] Implement dialog previews with object-URL cleanup, normal text paste and
  image paste handling, native focus containment, cancel/Escape, and pending-save
  protection. Submit through the existing serialized save queue and show toast.
- [x] Style the dialog to match the gallery and fit a 390px viewport.
- [x] Run gallery browser and Python regression tests; inspect the actual local
  pin visually and leave the dialog open for review.


## Verification

- New browser test initially failed because the dialog was absent; new URL API
  tests failed with the old upload-only response.
- Final gallery/overlay/board-card suite: 118 passed across Chromium and WebKit.
- Full Python suite in local Docker: 105 run, 100 passed, five disposable-MariaDB
  checks skipped. Includes the pre-existing local authentication work.
- Actual local pin: URL preview, save, and persistence after reload verified.
  Removed only the temporary fourth image, preserving the three original images.
- Desktop and 390px mobile layouts inspected. The local dialog remains open for
  review; no version bump, commit, or deployment was performed in this iteration.
