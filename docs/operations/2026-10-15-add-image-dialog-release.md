# Add-image dialog release — 15 October 2026

Released **2.6.3**, Git tag `v2.6.3`, from source commit
`f771b52ac274e25ed1004fda417c5f057ff8c756`.

## Changes

- The gallery plus button opens an add-image dialog with an image URL field,
  clipboard paste, drag-and-drop, and optional upload from the computer.
- Images preview before confirmation. URL errors remain available for retry,
  and keyboard focus stays within the dialog and returns to its opener on close.
- The gallery API accepts validated HTTP(S) image references through its existing
  authenticated and CSRF-protected transaction, preserving cover order and limits.

## Validation

- Clean release copy: 130 browser checks passed across Chromium and WebKit.
- Python suite: 94 tests run, 89 passed, five disposable-MariaDB tests skipped.
- Production health and version checks passed. Deployed application, gallery
  JavaScript, CSS, and template hashes match the tested source.
- Published images support `linux/amd64` and `linux/arm64` with tags `v2.6.3`,
  `2.6.3`, and `latest`.
- Registry manifest:
  `sha256:2710da130d4c4d23d983e6f51f4be0f28338722e6e9dc3c66f93959570fc9a80`.

The [tag-triggered GitHub build](https://github.com/isaaclee0/scrapbook/actions/runs/38657985399)
still failed at Docker Hub login. The documented local build process successfully
built and published this release.
