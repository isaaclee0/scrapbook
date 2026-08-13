# Board Pin Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open board pins in a bounded overlay while keeping the board document, loaded cards, active section, masonry state, and scroll position alive and unchanged.

**Architecture:** A parent-side JavaScript controller opens the existing pin editor in a same-origin iframe and represents it with a `?pin=` history entry. The embedded pin reports mutations through a versioned `postMessage` bridge, and the board refreshes only the affected card from a user-scoped JSON endpoint.

**Tech Stack:** Flask 3/Jinja, vanilla JavaScript, existing masonry engine, Python `unittest`, Playwright (`@playwright/test`) with static fixture pages.

## Global Constraints

- Desktop panel: `90vw`, maximum `1200px`, `90vh`, `16px` radius; board visible behind `rgba(0, 0, 0, 0.75)`.
- At `768px` and below, the panel fills the viewport with no radius.
- `/pin/<id>` remains a standalone page and ordinary-link fallback.
- Open overlay URL: `/board/<board-id>?pin=<pin-id>`; preserve unrelated query parameters.
- Embedded iframe URL: `/pin/<pin-id>?embedded=1&board_id=<board-id>`.
- Accept messages only for matching origin, iframe window, namespace `scrappl-pin-overlay`, protocol version `1`, and active pin ID.
- Never reload the board as recovery and never change board viewport width while the overlay is open.
- Board/section cover synchronization, non-board entry points, and a native-DOM editor rewrite are out of scope.
- Keep every database query user-scoped and release connections/cursors in `finally`.

## File Map

| File | Responsibility |
|---|---|
| `app.py` | Embedded-board validation and current pin-card JSON |
| `templates/base.html` | Embedded document marker and hidden shared chrome |
| `templates/pin.html` | Embedded presentation and parent message bridge |
| `templates/board.html` | Overlay shell, controller initialization, card refresh, removal of pixel restoration |
| `static/js/pin-overlay.js` | Overlay lifecycle, history, focus, validation, and recovery |
| `tests/__init__.py`, `tests/test_pin_overlay_routes.py` | Importable route-test package, user scope, embedded validation, and JSON contract tests |
| `tests/e2e/fixtures/*.html` | Deterministic parent/iframe browser fixtures |
| `tests/e2e/pin-overlay.spec.js` | History, scroll, security, mutation, responsive, and recovery tests |
| `playwright.config.js`, `package*.json` | Focused browser-test tooling |

---

### Task 1: Server-side embedded and card contracts

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_pin_overlay_routes.py`
- Modify: `app.py:1914-2002`
- Modify: `app.py` immediately after `view_pin()`

**Interfaces:**
- Produces: `view_pin(pin_id)` accepts `embedded=1&board_id=<int>` and rejects a mismatched board.
- Produces: `GET /api/pin/<int:pin_id>/card` returning `{"success":true,"pin":PinCard}` or safe 404.
- `PinCard`: `id`, `board_id`, `section_id`, `section_name`, `board_name`, `title`, `image_url`, `link`, `link_status`, `cached_filename`, `cached_width`, `cached_height`, `dominant_color_1`, `dominant_color_2`.
- Produces: `POST /update-pin/<int:pin_id>` persists a supplied `image_url` using the same user-scoped update and audit path as title, description, notes, and link.

- [ ] **Step 1: Write route fakes and failing embedded tests**

Create `tests/test_pin_overlay_routes.py` using standard `unittest`, `app.app.test_client()`, `patch.object(app, "get_current_user", return_value=USER)`, and ordered cursor/connection fakes. Define a complete fake pin with ID 42, user 7, and board 9. Add:

```python
def test_embedded_pin_accepts_matching_board(self):
    with patch.object(app_module, "get_db_connection",
                      return_value=FakeConnection([PIN, [], []])):
        response = self.client.get("/pin/42?embedded=1&board_id=9")
    self.assertEqual(response.status_code, 200)

def test_embedded_pin_rejects_different_board(self):
    with patch.object(app_module, "get_db_connection",
                      return_value=FakeConnection([PIN])):
        response = self.client.get("/pin/42?embedded=1&board_id=10")
    self.assertEqual(response.status_code, 404)
```

- [ ] **Step 2: Verify the tests fail**

Run: `python -m unittest tests.test_pin_overlay_routes -v`

Expected: FAIL because embedded mode is neither validated nor rendered.

- [ ] **Step 3: Implement exact embedded parsing**

After fetching `pin`, add:

```python
embedded = request.args.get('embedded') == '1'
expected_board_id = request.args.get('board_id', type=int)
if embedded and (expected_board_id is None or pin['board_id'] != expected_board_id):
    return "Pin not found", 404
```

Pass `embedded=embedded` to `render_template()`. Standalone rendering must not require `board_id`.

- [ ] **Step 4: Add failing JSON contract tests**

Add a success test that asserts response fields and that the cursor received `(42, 7)`. Add a missing-row test asserting status 404 and `{"error":"Pin not found","success":False}`.

- [ ] **Step 5: Add a failing image-persistence test, then implement the update path**

Add a route test that posts `{"image_url":"/static/images/default_pin.png"}` to `/update-pin/42`, verifies a successful JSON response, and asserts the user-scoped `UPDATE pins SET image_url = %s` parameter list includes the pin ID and user ID. Extend `update_pin()` to sanitize and update `image_url` when present, include it in the select, before/after audit snapshots, and `update_fields`. Run the test first and confirm it fails because `update_pin()` returns `No fields to update`.

- [ ] **Step 6: Implement the card endpoint**

Add a `@login_required` GET route. Select the specified fields with joins to boards, sections, URL health, and cached images; use the same cached-file masking as `get_board_pins()`. The predicate must be `WHERE p.id = %s AND p.user_id = %s`. Return the row under `pin`, return safe JSON 404, and close resources in `finally`.

- [ ] **Step 7: Verify and commit**

Run: `python -m unittest tests.test_pin_overlay_routes -v`

Expected: all tests PASS.

```bash
git add app.py tests/__init__.py tests/test_pin_overlay_routes.py
git commit -m "feat: add embedded pin and card contracts"
```

---

### Task 2: Embedded pin presentation and message bridge

**Files:**
- Modify: `templates/base.html:986-1045,2455-2461`
- Modify: `templates/pin.html:1-284,1198-1207,1421-1528,1682-1950,2109-2190`
- Modify: `tests/test_pin_overlay_routes.py`

**Interfaces:**
- Consumes: Jinja boolean `embedded`.
- Produces: `closePinView()` and `notifyPinOverlay(type, change)`.
- Message: `{source:'scrappl-pin-overlay',version:1,type,pinId,change?}`.

- [ ] **Step 1: Add failing standalone/embedded template tests**

Assert standalone HTML retains `id="mainNav"` and lacks the embedded marker. Assert embedded HTML contains `data-embedded-pin="true"`, `embedded-pin-page`, `scrappl-pin-overlay`, and `closePinView()`.

- [ ] **Step 2: Add embedded chrome and sizing rules**

Mark `body` with `embedded-pin-page`, give the normal content wrapper `id="appContent"`, and hide `#mainNav`, `.fab-container`, and version footer in embedded mode. Remove content padding/min-height/background. In `pin.html`, mark `.pin-lightbox`, remove its embedded backdrop/padding, and make `.pin-content` fill the iframe while retaining mobile behavior.

- [ ] **Step 3: Add the exact bridge**

```javascript
const PIN_OVERLAY_EMBEDDED = {{ embedded|tojson }};
const PIN_OVERLAY_ID = {{ pin.id }};

function notifyPinOverlay(type, change) {
    if (!PIN_OVERLAY_EMBEDDED || window.parent === window) return;
    const message = {source: 'scrappl-pin-overlay', version: 1,
                     type: type, pinId: PIN_OVERLAY_ID};
    if (change) message.change = change;
    window.parent.postMessage(message, window.location.origin);
}

function closePinView() {
    if (PIN_OVERLAY_EMBEDDED) notifyPinOverlay('close');
    else window.history.back();
}

document.addEventListener('DOMContentLoaded', function () {
    notifyPinOverlay('ready');
});
```

Change header X and footer Cancel to `closePinView()`.

- [ ] **Step 4: Report mutations without breaking standalone mode**

After successful title, URL, image, URL-health, description/notes, board move, section move, and deletion requests, notify before reload/navigation. Use `updated` for content/section, `moved` for board, and `deleted` for deletion. In embedded mode, board moves, save-and-close, and deletion use `closePinView()`; standalone redirects remain unchanged. Any remaining reload refreshes only the iframe.

- [ ] **Step 5: Verify and commit**

Run: `python -m unittest tests.test_pin_overlay_routes -v`

Expected: all tests PASS.

```bash
git add templates/base.html templates/pin.html tests/test_pin_overlay_routes.py
git commit -m "feat: add embedded pin message bridge"
```

---

### Task 3: Isolated overlay controller and browser harness

**Files:**
- Create: `static/js/pin-overlay.js`
- Create: `tests/e2e/fixtures/pin-overlay-board.html`
- Create: `tests/e2e/fixtures/pin-overlay-pin.html`
- Create: `tests/e2e/pin-overlay.spec.js`
- Create: `playwright.config.js`
- Modify: `package.json`, `package-lock.json`

**Interfaces:**
- Produces: `window.createPinOverlayController(options)` returning `{open,close,syncFromLocation,destroy}`.
- Options: `{boardId,root,boardContent,refreshPinCard,showToast,readyTimeoutMs}`.
- `refreshPinCard(pinId, change)` returns `Promise<HTMLElement|null>`.

- [ ] **Step 1: Install and configure focused browser testing**

Run:

```bash
npm install --save-dev @playwright/test
npx playwright install chromium webkit
```

Add `"test:pin-overlay": "playwright test tests/e2e/pin-overlay.spec.js"`. Configure Chromium and WebKit plus a web server running `python3 -m http.server 4173 --directory .` at base URL `http://127.0.0.1:4173`.

- [ ] **Step 2: Create deterministic fixtures**

The board fixture contains a tall spacer, `#pin-42.pin-card` with an ordinary `/pin/42` anchor, overlay shell elements, and a stub refresh callback recording calls in `window.refreshCalls`. The iframe fixture sends the exact `ready`, `close`, and `changed` messages and provides buttons for `updated`, `moved`, and `deleted`. In `beforeEach`, intercept `**/pin/42?embedded=1&board_id=9*` with `page.route()` and fulfill it from the pin fixture so the static server exercises a successful same-origin iframe load.

- [ ] **Step 3: Write failing history and validation tests**

```javascript
await page.goto('/tests/e2e/fixtures/pin-overlay-board.html');
await page.locator('.pin-card a').click();
await expect(page).toHaveURL(/\?pin=42$/);
await expect(page.locator('#pinOverlay')).toBeVisible();
await page.goBack();
await expect(page.locator('#pinOverlay')).toBeHidden();
await page.goForward();
await expect(page.locator('#pinOverlay')).toBeVisible();
```

Dispatch forged message events with wrong origin, window, version, and pin ID; assert they neither close nor dirty the overlay.

- [ ] **Step 4: Verify failure**

Run: `npm run test:pin-overlay`

Expected: FAIL because the controller does not exist.

- [ ] **Step 5: Implement the minimal controller**

Use a dependency-free IIFE and state `{pinId,dirtyChange,opener,pushed,readyTimer}`. Intercept only unmodified primary clicks within `boardContent`; preserve modified/middle/target/download/default-prevented behavior. Update only the `pin` query key. Set iframe source to `/pin/<id>?embedded=1&board_id=<boardId>`, Open as Page to `/pin/<id>`, push `{scrapbookPinOverlay:true,pinId}`, reconcile `popstate`, and use replace-state close for directly loaded query entries.

Validate message origin, `iframe.contentWindow`, namespace, version, and pin. Refresh once on dirty close, focus the opener/fallback, cancel stale timers, and remove listeners in `destroy()`.

- [ ] **Step 6: Verify and commit**

Run: `npm run test:pin-overlay`

Expected: Chromium and WebKit PASS.

```bash
git add package.json package-lock.json playwright.config.js static/js/pin-overlay.js tests/e2e
git commit -m "feat: add pin overlay controller"
```

---

### Task 4: Board shell and targeted card synchronization

**Files:**
- Modify: `templates/board.html:629-819,1017-1025,1168-1242,1300-1479,2141-2319`
- Modify: `tests/e2e/fixtures/pin-overlay-board.html`
- Modify: `tests/e2e/pin-overlay.spec.js`

**Interfaces:**
- Consumes: `createPinOverlayController()` and `/api/pin/<id>/card`.
- Produces: `refreshBoardPinCard(pinId, change) -> Promise<HTMLElement|null>`.

- [ ] **Step 1: Add failing preservation and dirty-refresh tests**

Scroll to a nonzero offset, activate a section, append cards to simulate infinite scroll, open/close, and assert exact `scrollY`, active section, and card count. Assert no refresh/layout for unchanged close and one `{pinId:42,change:'updated'}` refresh for changed close.

- [ ] **Step 2: Add the bounded shell**

Wrap ordinary content in `#boardPageContent`. Add `#pinOverlay` after it with `hidden`, dialog semantics, backdrop, bounded `#pinOverlayPanel`, iframe `title="Pin details"` and `allow="fullscreen"`, plus loading/error blocks and Retry/Open/Close controls. Add desktop/mobile CSS from Global Constraints. Do not toggle `html`/`body` overflow.

- [ ] **Step 3: Initialize the controller**

Load `static/js/pin-overlay.js`. At the end of board initialization:

```javascript
window.pinOverlayController = window.createPinOverlayController({
    boardId: Number(getBoardId()),
    root: document.getElementById('pinOverlay'),
    boardContent: document.getElementById('boardPageContent'),
    refreshPinCard: refreshBoardPinCard,
    showToast: window.showToast,
    readyTimeoutMs: 8000
});
window.pinOverlayController.syncFromLocation();
```

- [ ] **Step 4: Implement targeted refresh**

For `deleted`, immediately remove `#pin-<id>`. Otherwise fetch `/api/pin/<id>/card`; if the returned board differs, remove the card, else replace it using `createBoardPinCard(data.pin)`. Call `applyCurrentSectionFilter()` after a DOM change so its existing one masonry layout applies. On error, leave the card, show `Pin was saved, but its board card could not be refreshed`, and never reload.

- [ ] **Step 5: Remove legacy restoration and close SSE correctly**

Delete `saveScrollOnPinClick()`, `restoreScrollPosition()`, all calls, and infinite-scroll listener reattachment. Add `eventSource:null` to `processingState`; in `stopAllProcessing()`, close and null it before clearing fetches/timers.

- [ ] **Step 6: Verify and commit**

```bash
python -m unittest tests.test_pin_overlay_routes -v
npm run test:pin-overlay
```

Expected: all tests PASS.

```bash
git add templates/board.html tests/e2e
git commit -m "feat: integrate pin overlay with boards"
```

---

### Task 5: Accessibility, recovery, and mutation audit

**Files:**
- Modify: `static/js/pin-overlay.js`
- Modify: `templates/pin.html`
- Modify: `tests/e2e/pin-overlay.spec.js`
- Modify: `tests/test_pin_overlay_routes.py`

**Interfaces:**
- Completes all prior interfaces without adding a new public API.

- [ ] **Step 1: Add failing edge-behavior tests**

Cover Retry, Open as Page, timeout error, late valid `ready`, focus return, backdrop, Escape, Command/Ctrl-click preservation, desktop panel bounds, and 390px full-viewport bounds. Load the fixture directly with `?pin=42`, assert it opens automatically, then close it and assert the query is removed with replace-state without leaving the board URL.

- [ ] **Step 2: Implement recovery and focus**

After `ready`, focus the iframe. While open set/remove `inert` and `aria-hidden` on board content, prevent backdrop wheel/touch scrolling, and restore focus after card replacement or to grid/nearest-card after deletion. Retry retains embedded parameters and adds `_retry=<counter>` while resetting the ready timer.

- [ ] **Step 3: Audit every mutation success path**

Search `pin.html` for `fetch(`, `window.location`, `location.reload`, and `history.back`. Ensure every card-affecting success reports exactly `updated`, `moved`, or `deleted` before close/reload; all embedded board navigations use `closePinView()`; standalone behavior remains unchanged. Add template assertions for namespace and close abstraction.

- [ ] **Step 4: Verify and manually exercise the regression**

Run:

```bash
python -m unittest tests.test_pin_overlay_routes -v
npm run test:pin-overlay
git diff --check
```

With Docker dev running, verify Chrome and Safari: scroll beyond 40 pins, select a section, open a pin, change browser tabs, return, close, and confirm exact scroll/cards/filter. Exercise title, URL, image, section, board move, delete, fullscreen, Back, Forward, Escape, backdrop, direct query, modified click, and widths 768px/390px.

- [ ] **Step 5: Commit**

```bash
git add static/js/pin-overlay.js templates/pin.html tests/e2e/pin-overlay.spec.js tests/test_pin_overlay_routes.py
git commit -m "test: harden pin overlay behavior"
```

---

### Task 6: Final regression verification

**Files:**
- Verify only; edit solely to correct a discovered overlay regression.

**Interfaces:**
- Verifies `docs/superpowers/specs/2026-08-13-pin-overlay-design.md` completely.

- [ ] **Step 1: Run the complete focused suite**

```bash
python -m unittest tests.test_pin_overlay_routes -v
npm run test:pin-overlay
npm run build:css
git diff --check
```

Expected: tests PASS, CSS builds, and diff check is clean.

- [ ] **Step 2: Inspect scope and success criteria**

Run: `git status --short`. Preserve unrelated changes and the user's untracked `AGENTS.md`. Confirm the board never unloads, sizing matches, tab switching retains state, history/direct links work, dirty cards synchronize, forged messages are ignored, and failures stay local.

- [ ] **Step 3: Commit only if verification required a correction**

Stage only the exact corrected feature files, then run:

```bash
git commit -m "fix: complete pin overlay verification"
```
