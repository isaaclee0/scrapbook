# Task 3: Isolated overlay controller and browser harness

## Delivered

- Added dependency-free `window.createPinOverlayController(options)` in
  `static/js/pin-overlay.js` with in-place link interception, query/history
  synchronization, iframe loading states, message validation, dirty refresh,
  focus restoration, retry/open-page controls, and teardown.
- Added deterministic static board and embedded-pin fixtures plus a focused
  Playwright suite covering history-state synchronization, link preservation,
  forged-message rejection, dirty mutation refresh, and direct-query close.
- Added Playwright configuration for Chromium and WebKit with a static server,
  plus `npm run test:pin-overlay` and the `@playwright/test` dev dependency.

## Red / green evidence

1. **RED** — after the tests/fixtures were added and before the controller
   existed, `npm run test:pin-overlay` failed as expected: the static server
   returned `404 /static/js/pin-overlay.js`; WebKit immediately failed and
   Chromium timed out waiting for the missing controller-driven overlay.
2. **GREEN** — after implementing the controller and correcting same-document
   history-state reconciliation, `npm run test:pin-overlay` passed:

   ```text
   10 passed (2.5s)
   ```

   This includes all five specifications in Chromium and WebKit.

## Commands run

```text
npm install --save-dev @playwright/test
npx playwright install chromium webkit
npm run test:pin-overlay                  # red: controller script 404
npm run test:pin-overlay                  # green: 10 passed (2.5s)
```

The dependency/browser downloads and the local port-binding test run required
approved escalation because the sandbox blocks registry/browser networking and
listening on port 4173.

## Files changed

- `package.json`, `package-lock.json`
- `playwright.config.js`
- `static/js/pin-overlay.js`
- `tests/e2e/fixtures/pin-overlay-board.html`
- `tests/e2e/fixtures/pin-overlay-pin.html`
- `tests/e2e/pin-overlay.spec.js`

## Concerns

- The static fixture’s intentional modified-click test can produce a harmless
  static-server `404 /pin/42` request; it verifies that the controller leaves
  modified clicks to the browser rather than intercepting them.
- The fixture uses real browser Back and Forward in both engines. Its embedded
  page is served through Playwright route fulfillment so the harness remains
  deterministic without requiring a running Flask application.

## Fix round 1: review findings

### Red evidence

The browser harness was changed before controller code to use real
`page.goBack()` and `page.goForward()` rather than synthetic `popstate`.

- WebKit then failed at `page.goBack()` waiting for a same-document commit;
  Back remained on the overlay `?pin=42` history entry. This exposed the child
  iframe navigation being appended to the joint session history after the
  parent `pushState`.
- The new dirty Back test failed in Chromium with `window.refreshCalls` still
  empty after Back. This proved the old `syncFromLocation()` close path cleared
  dirty state without refreshing.

### Green implementation

- Child navigation now uses `iframe.contentWindow.location.replace(...)`.
  It replaces the frame's document rather than appending a child history entry,
  so the parent overlay `pushState` is the actual Back target.
- Native Back/Forward is now tested in Chromium and WebKit. Back removes the
  query and hides the overlay; Forward restores the query and reopens it.
  No synthetic `popstate` is dispatched in the history test.
- Valid mutations persist a short-lived pending refresh in `sessionStorage`.
  This lets a dirty Back refresh once after either a normal `popstate` or a
  browser document restoration. Non-history close paths await
  `refreshPinCard`, then focus its returned replacement; fallback focus avoids
  detached cards.
- Forged-message coverage now independently validates wrong origin, source,
  namespace, version, and pin ID, including forged `close` messages. The
  version/pin cases use the expected iframe window source.
- Click-guard coverage now verifies middle, Ctrl, Shift, Alt, target,
  download, and already-prevented interactions are not intercepted.

### Fix-round verification

```text
npm run test:pin-overlay
12 passed (3.0s)
```

Both Chromium and WebKit passed the real history, dirty Back refresh/focus,
message-validation, guarded-click, direct-close, and iframe-close scenarios.

## Fix round 2: close focus and failed refresh recovery

### Red evidence

Tests were added before changing the controller for all clean close controls
(X, Escape, backdrop, and iframe close), real browser Back, and a persisted
dirty refresh that rejects.

```text
npm run test:pin-overlay
14 passed, 4 failed (15.8s)
```

The new clean-close test failed in Chromium and WebKit with no active element
ID after the overlay hid. The rejected persisted-refresh test also failed:
there was no toast in Chromium and neither engine moved focus to the board
fallback. A follow-up run after adding the rejection catch exposed browser
focus restoration racing the immediate fallback focus, which was corrected by
queueing fallback focus after navigation restoration.

### Green implementation

- Clean history-backed closes restore connected opener focus before native
  history traversal. X, Escape, backdrop, and iframe close share that path.
- Persisted refresh rejection now catches, emits `Could not refresh pin`, and
  schedules focus to the connected board-content fallback after history focus
  restoration. The fallback lookup also handles a board DOM instance that was
  replaced during history restoration.
- The fixture marks board content as programmatically focusable and can force
  `refreshPinCard` rejection deterministically.

### Fix-round verification

```text
npm run test:pin-overlay
18 passed (4.3s)
```

Chromium and WebKit both cover real Back/Forward, all clean close focus paths,
dirty refresh focus, and failed persisted refresh toast/fallback recovery.
