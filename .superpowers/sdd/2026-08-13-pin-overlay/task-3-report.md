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
- The fixture synchronizes history through URL/state plus a `popstate` event.
  This avoids WebKit waiting indefinitely for Playwright's navigation waiter
  on a same-document history traversal while still exercising the controller's
  real `popstate` handler. The controller itself uses native `pushState` and
  `history.back` as required.
