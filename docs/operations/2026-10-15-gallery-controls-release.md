# Gallery controls release — 15 October 2026

Released **2.6.2**. Source commit: `f0a4bf3426dc75637af2aee938fab9ecfcf58cdf`;
Git tag: `v2.6.2`.

## Changes

- Compact gallery footer with small thumbnails, navigation, add-image button,
  and an image-actions menu, leaving more room for the main image.
- File drop and clipboard paste on the gallery, with a brief upload confirmation
  overlay that disappears after three seconds. Failed uploads retain a retry action.
- Standalone pin close/cancel falls back to the board when there is no previous
  in-app page; embedded pins retain their existing close behavior.
- Versioned gallery CSS and JavaScript URLs prevent stale assets after release.

## Validation

- 118 Playwright checks passed across Chromium and WebKit.
- Python suite: 90 tests run, 85 passed and five disposable-MariaDB tests skipped.
- 16 focused route tests passed after adding versioned asset URLs.
- Published images support `linux/amd64` and `linux/arm64`.
- Deployed gallery JavaScript, CSS, and template hashes match the tested release.
- Live health and version checks passed.

The [tag-triggered GitHub build](https://github.com/isaaclee0/scrapbook/actions/runs/38643576625)
failed at Docker Hub login. The release was successfully built and published
through the documented local build process.
