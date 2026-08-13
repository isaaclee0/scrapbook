# Pin overlay final-fix report

Date: 2026-08-13
Workspace: `/Users/isaaclee/scrapbook/scrapbook` on `main` by explicit user request

## Scope

Addressed the final whole-feature review findings only:

1. Persist file-upload `data:image/...` replacements through the existing pasted-image storage path, link the pin to the new cache row, and clear stale cache references for ordinary image replacements.
2. Isolate all non-overlay application UI (global navigation, normal content, floating controls, modals, scripts/footer wrapper) with `inert` and `aria-hidden` while the board overlay is open.
3. Distinguish overlay history entries pushed by the current controller instance from markers left by a reloaded/previous document.
4. Show the parent close control only during loading/error recovery; use the embedded editor's close control once its `ready` handshake succeeds.

No unrelated files were changed or reverted. Existing dirty/untracked `AGENTS.md`, Node modules, generated CSS, test results, and prior task report artifacts were preserved.

## Root-cause evidence

### Uploaded image replacement

`changeImage()` reads the selected file into a data URL and sends it to `POST /update-pin/<id>`. The route previously ran all supplied image values through `sanitize_url()`, whose explicit `data:image/` branch returns an empty string. The route nevertheless returned success. Additionally, pin and card rendering prefer `cached_filename`, so retaining the previous `cached_image_id` could continue to display the old cached image even if the source changed.

The existing `save_pasted_image()` path already writes the decoded file under `static/cached_images`, creates the cache record when supported, and returns `('/cached/<filename>', cached_image_id)`. `update_pin()` now uses that path for data images after the user-scoped pin lookup, updates `image_url`, `cached_image_id`, and `uses_cached_image` together, and clears the old cache reference for non-data image changes. The existing embedded mutation notification then triggers the board card endpoint refresh, whose returned cache filename/source renders the replacement.

### Modal isolation

The controller previously applied `inert`/`aria-hidden` only to `#boardPageContent`. In production, global navigation and floating action controls are siblings supplied by `base.html`, so they remained exposed to keyboard and assistive technology. `base.html` now provides `#appBackgroundContent` around all ordinary application chrome and a separate `page_overlay` block after it. The board shell renders in that outside block, and the controller isolates the full background wrapper while retaining `boardContent` for delegated pin-click handling and focus fallback.

### History provenance

The controller previously classified any state with `scrapbookPinOverlay: true` as locally pushed. A browser reload preserves that state, so the new document incorrectly used `history.back()` on close. Each controller now generates a fresh token and includes it in pushed state; only the exact token/pin pair is local. Direct/old entries close with `replaceState`, remove only overlay-owned state keys and the `pin` query parameter, and preserve unrelated state/query data.

### Duplicate close controls

The parent close button previously stayed visible after the iframe editor was ready, directly overlaying the editor's own X. `setView('open')` now hides the parent button. Loading and error states show it, preserving a recovery close path when no usable child editor exists.

## TDD red evidence

### Route regression

Command:

```text
.venv/bin/python3 -m unittest tests.test_pin_overlay_routes.PinOverlayRouteTests.test_update_pin_persists_uploaded_data_image_and_replaces_cached_reference -v
```

Observed failure before production changes:

```text
FAIL
AssertionError: Expected 'save_pasted_image' to be called once. Called 0 times.
Ran 1 test ... FAILED (failures=1)
```

This proved the regression reached the real update route and failed specifically because the data-image persistence path was not invoked.

### Browser regressions

Command (Chromium and WebKit):

```text
npm run test:pin-overlay -- --grep "production wrapper|controller recreated|ready editor"
```

Initial sandbox attempt could not bind the local Playwright server (`PermissionError: [Errno 1] Operation not permitted` on port 4173), so the same command was rerun with the approved local-server escalation.

Observed failures before controller/template changes: 6 failed (all three scenarios in both browsers):

- `#appBackgroundContent` had no `inert` attribute.
- Recreated controller close left `?pin=42` because it called the stubbed `history.back()`.
- `[data-overlay-close]` remained visible after the editor reached `open`.

## Green evidence

Targeted route:

```text
.venv/bin/python3 -m unittest tests.test_pin_overlay_routes.PinOverlayRouteTests.test_update_pin_persists_uploaded_data_image_and_replaces_cached_reference -v
Ran 1 test ... OK
```

Targeted browser scenarios:

```text
npm run test:pin-overlay -- --grep "production wrapper|controller recreated|ready editor"
6 passed (Chromium and WebKit)
```

Complete focused route suite:

```text
.venv/bin/python3 -m unittest tests.test_pin_overlay_routes -v
Ran 12 tests ... OK
```

Complete focused browser suite:

```text
npm run test:pin-overlay
48 passed (12.1s), Chromium and WebKit
```

Template parse:

```text
.venv/bin/python3 - <<'PY'
from pathlib import Path
from jinja2 import Environment
for name in ('templates/base.html', 'templates/board.html', 'templates/pin.html'):
    Environment().parse(Path(name).read_text())
    print(f'parsed {name}')
PY
parsed templates/base.html
parsed templates/board.html
parsed templates/pin.html
```

Whitespace validation:

```text
git diff --check
# exit 0, no output
```

## Files changed

- `app.py`
- `templates/base.html`
- `templates/board.html`
- `static/js/pin-overlay.js`
- `tests/test_pin_overlay_routes.py`
- `tests/e2e/fixtures/pin-overlay-board.html`
- `tests/e2e/pin-overlay.spec.js`
- `.superpowers/sdd/2026-08-13-pin-overlay/final-fix-report.md`

`templates/pin.html` required no final code edit: its existing `changeImage()`/`saveImage()` flow sends the data URL, emits `changed: updated` on success, and its embedded header already supplies the child close control. The final fix is at the persistence boundary and parent visibility state.

## Self-review

- Data-image storage occurs only after the current user's pin is found.
- The pin update remains user-scoped (`WHERE id = %s AND user_id = %s`).
- New cached image ID and display URL are changed in the same pin update; ordinary replacements explicitly clear stale cache linkage.
- Overlay remains outside the inert wrapper in production and in the browser fixture.
- Click interception remains scoped to `boardContent`; broadening accessibility isolation does not broaden navigation interception.
- Controller tokens are document/controller-local and never inferred solely from the public marker.
- Replace-close preserves unrelated URL parameters and non-overlay history state.
- Parent X is present for idle/loading/error transitions and hidden only for a ready editor.
- Existing Back/Forward, direct query, mutation refresh, scroll/focus, recovery, message validation, and responsive scenarios remained green across both browser engines.

## Remaining concerns

- Route test startup logs show the repository's existing best-effort Redis/MariaDB initialization warnings because no local services are running; the isolated fake-backed tests still complete successfully.
- Verification is automated against the route fakes and deterministic Playwright fixture; no live MariaDB/manual production browser session was required for this final review wave.
