# Task 4 Report: Board shell and targeted card synchronization

## Status

Implemented and verified.

## TDD evidence

### RED

Added deterministic Playwright coverage that:

- activates section `7`;
- appends two cards to simulate preserved infinite-scroll state;
- scrolls to the exact nonzero offset `640`;
- opens and closes an unchanged pin and checks exact scroll, active section, card count, zero refreshes, and zero masonry layouts;
- changes pin `42`, closes it, and expects exactly one card request, one `{ pinId: 42, change: 'updated' }` refresh, one masonry layout, the replacement title, and otherwise unchanged board state.

Command:

```text
npm run test:pin-overlay -- --project=chromium --grep "unchanged close|changed close"
```

Observed before integration:

```text
Running 2 tests using 1 worker
✓ unchanged close preserves exact scroll, section, and lazy-loaded cards without layout
✘ changed close refreshes only its card and preserves board state
Expected: 1
Received: 0
1 failed, 1 passed
```

The failing assertion was the missing request to `/api/pin/42/card`, which was the intended unimplemented behavior.

### GREEN and integration finding

After adding the targeted refresh, the card request, replacement, and single layout occurred, but the changed-close test initially exposed a controller integration defect:

```text
Expected scrollY: 640
Received scrollY: 0
```

The Task 3 owner fixed controller focus in commit `7491206dd` by using `preventScroll` with a restoration fallback. No Task 3 production file was changed or committed by this task.

A fresh focused Chromium run then passed both preservation tests. A fresh full Chromium run passed all 11 tests, followed by the required full Chromium and WebKit verification below.

## Implementation

### `templates/board.html`

- Wrapped the unchanged ordinary board markup and existing dialogs in `#boardPageContent`.
- Added an accessible `#pinOverlay` dialog shell with a labelled, bounded panel, titled fullscreen-capable iframe, loading and error states, Retry, Open as Page, and Close controls.
- Added the global desktop bounds (`90vw`, `max-width: 1200px`, `90vh`, `16px` radius, `rgba(0, 0, 0, 0.75)` backdrop) and the full-viewport mobile rule at `768px` and below.
- Did not change `html` or `body` overflow.
- Loaded `static/js/pin-overlay.js`, created `window.pinOverlayController` at the end of board initialization, and synchronized it from the current URL.
- Added `refreshBoardPinCard(pinId, change)`:
  - `deleted` removes only the affected card immediately;
  - updates fetch `/api/pin/<id>/card` and replace only that card;
  - a different returned `board_id` removes only that card;
  - each DOM change invokes `applyCurrentSectionFilter()` exactly once, using its existing single masonry layout;
  - errors retain the current card, show `Pin was saved, but its board card could not be refreshed`, and never reload.
- Removed `saveScrollOnPinClick()`, `restoreScrollPosition()`, all calls, and infinite-scroll listener reattachment.
- Added the active `EventSource` to `processingState`; `stopAllProcessing()` now closes and nulls it before aborting fetches or clearing timers.

### Browser fixture and spec

- Extended the board fixture with section and grid state, lazy-card support, targeted card fetching, filter/layout instrumentation, and replacement card construction.
- Added exact unchanged and dirty preservation tests.
- Preserved and strengthened the existing replacement-focus test with an exact-scroll assertion that covers the controller integration defect found during GREEN.

## Verification

Template parse:

```text
.venv/bin/python3 -c "import app; app.app.jinja_env.get_template('board.html'); print('board template parsed')"
board template parsed
```

The app import emitted the repository's existing Redis/MariaDB-unavailable development messages; template parsing exited `0`.

Route suite:

```text
.venv/bin/python3 -m unittest tests.test_pin_overlay_routes -v
Ran 10 tests in 0.028s
OK
```

Browser suite:

```text
npm run test:pin-overlay
Running 22 tests using 2 workers
22 passed (5.5s)
```

Diff hygiene:

```text
git diff --check
# exit 0, no output
```

## Self-review

- Checked every Task 4 brief item against the final diff.
- Confirmed there are no remaining legacy scroll-save or delayed-restore symbols in `board.html`.
- Confirmed overlay CSS does not toggle document overflow or viewport width.
- Confirmed unchanged close does not fetch or lay out.
- Confirmed update close fetches once, replaces one card, and lays out once.
- Confirmed deletion and cross-board responses cannot trigger a board reload.
- Confirmed all error branches preserve the existing card before showing the required toast.
- Confirmed the external script loads before controller initialization.
- Confirmed tracked SSE cleanup occurs before fetch/timer cleanup.
- Confirmed no unowned application, package, `node_modules`, `test-results`, `AGENTS.md`, or Task 3 report changes are included in this task's staging scope.

## Concerns / follow-up

- No unresolved Task 4 code concern.
- The full Flask board page was not manually exercised against a live MariaDB instance; deterministic browser integration, Jinja parsing, and the route suite are green.
- The working tree contains unrelated dependency artifacts, `test-results`, `AGENTS.md`, and a concurrent Task 3 report modification. They are intentionally left untouched and uncommitted by this task.
