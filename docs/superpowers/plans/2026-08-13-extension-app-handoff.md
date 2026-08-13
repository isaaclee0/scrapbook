# Extension-to-App Pin Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open Scrappl immediately after a context-menu image or successful region capture, and prefill the existing Add Pin modal without an API token.

**Architecture:** The extension captures only. It opens a configured Scrappl tab, then uses `chrome.scripting.executeScript` to post the capture in-memory into the app. A shared browser helper validates and temporarily holds a handoff; the authenticated base page consumes it with the existing Add Pin modal. The login page loads the same helper so the payload survives OTP login in origin-scoped session storage.

**Tech Stack:** Flask/Jinja, vanilla JavaScript, Manifest V3, Playwright, Node built-in test runner.

## Global Constraints

- Production destination is exactly `https://scrappl.com`; local/staging use a URL override.
- No API token is created, copied, stored, or sent for this flow.
- Image data is never put in a URL, server request/log, or `chrome.storage.local`.
- Only the app’s Add Pin modal handles boards, sections, and saving.
- A handoff must be a `data:image/...;base64,` value, same-window/same-origin, one-use, and expire after ten minutes.
- Preserve capture mechanics; change only their post-capture destination.
- Never stage unrelated dirty files.

---

### Task 1: Build and test the app-side handoff contract

**Files:**
- Create: `static/js/extension_handoff.js`
- Modify: `templates/base.html:7,1552-1660`
- Modify: `templates/login.html:323`
- Create: `tests/e2e/fixtures/extension-handoff.html`
- Create: `tests/e2e/extension-handoff.spec.js`

**Interfaces:**
- Produces `window.ScrapplExtensionHandoff.receive(event)` and `take()`.
- `receive` takes `{type:'SCRAPPL_EXTENSION_HANDOFF', nonce, imageDataUrl, sourceUrl, title}` and stores a normalized record.
- `take` returns `{imageDataUrl, sourceUrl, title, createdAt}` once, otherwise `null`.
- Base page consumes `take()` and calls its existing Add Pin UI.

- [ ] **Step 1: Write failing browser tests**

Create the fixture:

```html
<!doctype html>
<script src="/static/js/extension_handoff.js"></script>
```

Create `tests/e2e/extension-handoff.spec.js` with these cases:

```js
const { test, expect } = require('@playwright/test');

test('stores a matching image handoff once', async ({ page }) => {
  await page.goto('/tests/e2e/fixtures/extension-handoff.html#scrappl-handoff=n1');
  await page.evaluate(() => window.postMessage({
    type: 'SCRAPPL_EXTENSION_HANDOFF', nonce: 'n1',
    imageDataUrl: 'data:image/png;base64,AA==',
    sourceUrl: 'https://source.test/page', title: 'Source'
  }, location.origin));
  await expect.poll(() => page.evaluate(() => window.ScrapplExtensionHandoff.take()))
    .toMatchObject({ imageDataUrl: 'data:image/png;base64,AA==', sourceUrl: 'https://source.test/page', title: 'Source' });
  await expect(page.evaluate(() => window.ScrapplExtensionHandoff.take())).resolves.toBeNull();
});

test('rejects wrong nonce, non-image content, and expired data', async ({ page }) => {
  await page.goto('/tests/e2e/fixtures/extension-handoff.html#scrappl-handoff=n1');
  await page.evaluate(() => window.postMessage({ type: 'SCRAPPL_EXTENSION_HANDOFF', nonce: 'wrong', imageDataUrl: 'data:text/plain;base64,QQ==', sourceUrl: '', title: '' }, location.origin));
  await expect(page.evaluate(() => window.ScrapplExtensionHandoff.take())).resolves.toBeNull();
  await page.evaluate(() => sessionStorage.setItem('scrappl.extension-handoff.v1', JSON.stringify({ imageDataUrl: 'data:image/png;base64,AA==', sourceUrl: '', title: '', createdAt: Date.now() - 600001 })));
  await expect(page.evaluate(() => window.ScrapplExtensionHandoff.take())).resolves.toBeNull();
});
```

- [ ] **Step 2: Run RED**

```bash
npx playwright test tests/e2e/extension-handoff.spec.js --project=chromium
```

Expected: FAIL because the helper does not exist.

- [ ] **Step 3: Implement the receiver and prefill boundary**

Create the helper with:

```js
const HANDOFF_TYPE = 'SCRAPPL_EXTENSION_HANDOFF';
const STORAGE_KEY = 'scrappl.extension-handoff.v1';
const TTL_MS = 600000;
const isImageDataUrl = value => typeof value === 'string' && /^data:image\/[a-z0-9.+-]+;base64,/i.test(value);
const expectedNonce = () => new URLSearchParams(location.hash.slice(1)).get('scrappl-handoff');
```

`receive(event)` must require `event.source === window`, `event.origin === location.origin`, the exact type, a nonce, and a valid image data URL. When a nonce is in the fragment, it must match. Login redirects lose the fragment, so a valid same-origin message on the login page is retained. Store `{imageDataUrl, sourceUrl: String(...), title: String(...), createdAt: Date.now()}` in `sessionStorage`, erase the fragment with `history.replaceState`, and dispatch `scrappl:extension-handoff`.

`take()` parses the record, validates the image and ten-minute TTL, removes it in every outcome, and returns it only when valid. Register one `message` listener and expose both methods.

Load this helper before inline scripts in `base.html` and `login.html`. Refactor `setupAddContentModal()` to publish `window.setAddContentImage(dataUrl)`, which updates its closure’s `currentImageUrl`, `contentType`, preview, and save state. Add `prefillExtensionHandoff()` after `showAddContentDialog()`: it takes one handoff, opens the modal, sets `#content-input` to the source URL and `#title-input` to title, calls `setAddContentImage`, then `updateSaveButton`. Invoke it on page initialization and on `scrappl:extension-handoff`. Login needs only the shared helper; its current gallery redirect loads the consumer.

- [ ] **Step 4: Run GREEN and commit**

```bash
npx playwright test tests/e2e/extension-handoff.spec.js --project=chromium
git add static/js/extension_handoff.js templates/base.html templates/login.html tests/e2e/fixtures/extension-handoff.html tests/e2e/extension-handoff.spec.js
git commit -m "feat: receive extension pin handoffs in app"
```

Expected: tests pass, including one-time, MIME, nonce, and expiry coverage.

### Task 2: Replace the injected extension form with a new-tab handoff

**Files:**
- Modify: `chrome-extension/background.js`
- Modify: `chrome-extension/content.js`
- Create: `tests/extension/background-handoff.test.js`
- Create: `tests/e2e/extension-region-handoff.spec.js`
- Delete: `tests/e2e/extension-picker.spec.js`
- Delete: `tests/e2e/fixtures/extension-dialog.html`

**Interfaces:**
- Produces `OPEN_HANDOFF {dataUrl, pageUrl, pageTitle}`.
- Produces `openScrapplHandoff({dataUrl, pageUrl, pageTitle}) -> Promise<{ok, error?}>`.
- Region selection emits `OPEN_HANDOFF` after `CAPTURE_REGION` succeeds.

- [ ] **Step 1: Write failing tests**

Use `node:test`, `node:assert/strict`, and `vm` in `tests/extension/background-handoff.test.js` to load real `background.js` under mocked Chrome APIs. Capture the message listener, then assert:

```js
assert.deepEqual(await handler({ type: 'GET_CONFIG' }), { ok: true, baseUrl: 'https://scrappl.com' });
await handler({ type: 'OPEN_HANDOFF', dataUrl: 'data:image/png;base64,AA==', pageUrl: 'https://source.test/p', pageTitle: 'Source' });
assert.equal(createdTabs[0].url.startsWith('https://scrappl.com/#scrappl-handoff='), true);
await tabsUpdated(createdTabs[0].id, { status: 'complete', url: createdTabs[0].url });
assert.equal(injected[0].args[0].imageDataUrl, 'data:image/png;base64,AA==');
assert.equal(injected[0].args[0].sourceUrl, 'https://source.test/p');
```

Also test `http://localhost:8000/` normalizes to `http://localhost:8000` and non-image input creates no tab.

Create a Playwright region test that injects `content.js`, stubs `CAPTURE_REGION` to return a data URL, confirms a small drag and click on **Use this**, and asserts the final runtime message is:

```js
{ type: 'OPEN_HANDOFF', dataUrl: 'data:image/png;base64,AA==', pageUrl: location.href, pageTitle: document.title }
```

- [ ] **Step 2: Run RED**

```bash
node --test tests/extension/background-handoff.test.js
npx playwright test tests/e2e/extension-region-handoff.spec.js --project=chromium
```

Expected: FAIL because neither handoff behavior exists.

- [ ] **Step 3: Implement the handoff**

In `background.js`, replace token configuration with:

```js
const DEFAULT_BASE_URL = 'https://scrappl.com';
async function getConfig() {
  const { baseUrl } = await chrome.storage.local.get(['baseUrl']);
  try { return { baseUrl: new URL((baseUrl || DEFAULT_BASE_URL).trim()).origin }; }
  catch { return { baseUrl: DEFAULT_BASE_URL }; }
}
```

Delete `apiFetch`, board/section/create/add-pin cases, Bearer headers, and `onMessageExternal`. Retain `FETCH_IMAGE` and `CAPTURE_REGION`.

Create a 16-byte hexadecimal nonce from `crypto.getRandomValues`. For a valid image data URL, `openScrapplHandoff` opens `baseUrl + '/#scrappl-handoff=' + nonce`; wait for that tab’s first complete load on the configured origin; then inject:

```js
chrome.scripting.executeScript({
  target: { tabId },
  func: handoff => window.postMessage({ type: 'SCRAPPL_EXTENSION_HANDOFF', ...handoff }, window.location.origin),
  args: [{ nonce, imageDataUrl: dataUrl, sourceUrl: pageUrl || '', title: pageTitle || '' }]
});
```

Always remove the temporary tab-update listener after success or failure. `GET_CONFIG` returns only `{ok:true, baseUrl}`, and `OPEN_HANDOFF` calls this function.

The image context menu fetches its image and calls `openScrapplHandoff`, never injecting UI into the source page. Remove the entire dialog component from `content.js`; retain only the selection overlay. A successful crop sends `OPEN_HANDOFF`; retain the overlay and show an error when crop or handoff fails.

- [ ] **Step 4: Run GREEN and commit**

```bash
node --check chrome-extension/background.js
node --check chrome-extension/content.js
node --test tests/extension/background-handoff.test.js
npx playwright test tests/e2e/extension-region-handoff.spec.js --project=chromium
git add chrome-extension/background.js chrome-extension/content.js tests/extension/background-handoff.test.js tests/e2e/extension-region-handoff.spec.js
git rm tests/e2e/extension-picker.spec.js tests/e2e/fixtures/extension-dialog.html
git commit -m "feat(extension): hand off captures to Scrappl"
```

Expected: all pass; no source-page board/section UI remains.

### Task 3: Simplify settings, package, and settings-page integration

**Files:**
- Modify: `chrome-extension/manifest.json`
- Modify: `chrome-extension/options.html`
- Modify: `chrome-extension/options.js`
- Modify: `chrome-extension/README.md`
- Modify: `templates/settings.html:20-245`
- Create: `tests/extension/options.test.js`
- Modify: `package.json`

**Interfaces:**
- Produces `normalizeBaseUrl(value) -> string`.
- Reads/writes only `chrome.storage.local.baseUrl`.

- [ ] **Step 1: Write failing options tests**

With a mocked storage API and minimal DOM, assert:

```js
assert.equal(normalizeBaseUrl(''), 'https://scrappl.com');
assert.equal(normalizeBaseUrl('http://localhost:8000/'), 'http://localhost:8000');
assert.equal(normalizeBaseUrl('not a url'), 'https://scrappl.com');
```

Also assert no stored override leaves the field blank, Save writes only `{baseUrl:'http://localhost:8000'}`, and **Use Scrappl.com** removes `baseUrl`.

- [ ] **Step 2: Run RED**

```bash
node --test tests/extension/options.test.js
```

Expected: FAIL because options still require a token.

- [ ] **Step 3: Implement settings cleanup**

Set manifest version `1.4.0`; retain its stable `key`; remove `externally_connectable`. Replace option controls with optional **Scrappl URL for development**, Save, and **Use Scrappl.com**. Implement:

```js
const DEFAULT_BASE_URL = 'https://scrappl.com';
function normalizeBaseUrl(value) {
  if (!value.trim()) return DEFAULT_BASE_URL;
  try { return new URL(value.trim()).origin; }
  catch { return DEFAULT_BASE_URL; }
}
```

Store an override only if it differs from the default; otherwise remove it. Remove token copy, fields, storage, and automatic connection code. Remove only extension-specific **Connect Extension** controls and handlers from `templates/settings.html`; retain personal token management for any other consumer. Update README to say the extension works immediately and the URL field is only for local/staging.

- [ ] **Step 4: Run GREEN and commit**

```bash
node --check chrome-extension/options.js
node --test tests/extension/options.test.js
python3 -m json.tool chrome-extension/manifest.json >/dev/null
git add chrome-extension/manifest.json chrome-extension/options.html chrome-extension/options.js chrome-extension/README.md templates/settings.html tests/extension/options.test.js package.json
git commit -m "feat(extension): remove token setup"
```

Expected: valid manifest and options tests show no token persistence.

### Task 4: Verify regression safety and real browser behavior

**Files:**
- Modify only failures found in this task.

- [ ] **Step 1: Run automated verification**

```bash
node --check chrome-extension/background.js
node --check chrome-extension/content.js
node --check chrome-extension/options.js
node --test tests/extension/background-handoff.test.js tests/extension/options.test.js
npx playwright test tests/e2e/extension-handoff.spec.js tests/e2e/extension-region-handoff.spec.js --project=chromium
pytest -q tests/test_pin_overlay_routes.py
git diff --check
```

Add a `test:extension` script for the two new browser specs and rerun it. Expected: all commands exit 0.

- [ ] **Step 2: Manual acceptance test**

1. Reload the unpacked extension and confirm version `1.4.0`.
2. While authenticated at `https://scrappl.com`, right-click a public image; confirm a new app tab opens immediately with image, page URL, and editable title in Add Pin.
3. Capture a region via the toolbar; confirm the same outcome.
4. Create/select a board and section in the app modal, save, and confirm the source URL persists.
5. Set `http://localhost:8000` in options and confirm handoff uses it.
6. Log out locally, trigger a handoff, complete OTP login, and confirm the original draft opens after redirect.

- [ ] **Step 3: Commit only regression fixes**

```bash
git status --short
git add static/js/extension_handoff.js templates/base.html templates/login.html chrome-extension/background.js chrome-extension/content.js chrome-extension/manifest.json chrome-extension/options.html chrome-extension/options.js chrome-extension/README.md templates/settings.html tests/e2e/extension-handoff.spec.js tests/e2e/extension-region-handoff.spec.js tests/extension/background-handoff.test.js tests/extension/options.test.js package.json
git commit -m "test: cover extension handoff regressions"
```

Do not commit generated files, `node_modules`, CSS output, prior reports, or unrelated untracked files.
