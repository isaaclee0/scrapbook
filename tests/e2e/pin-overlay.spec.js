const { test, expect } = require('@playwright/test');

const boardUrl = '/tests/e2e/fixtures/pin-overlay-board.html';
const pinFixture = require('path').join(__dirname, 'fixtures/pin-overlay-pin.html');

test.beforeEach(async ({ page }) => {
  await page.route('**/pin/42?embedded=1&board_id=9*', route => route.fulfill({ path: pinFixture }));
  await page.goto(boardUrl);
});

test('real browser Back closes and Forward reopens the overlay', async ({ page }) => {
  await page.locator('.pin-card a').click();
  await expect(page).toHaveURL(/\?pin=42$/);
  await expect(page.locator('#pinOverlay')).toBeVisible();
  await expect(page.frameLocator('#pinOverlayFrame').locator('#updated')).toBeVisible();
  await page.goBack({ waitUntil: 'commit' });
  await expect(page).toHaveURL(/pin-overlay-board\.html$/);
  await expect(page.locator('#pinOverlay')).toBeHidden();
  await page.goForward({ waitUntil: 'commit' });
  await expect(page).toHaveURL(/\?pin=42$/);
  await expect(page.locator('#pinOverlay')).toBeVisible();
});

test('leaves guarded pin-link interactions to the browser', async ({ page }) => {
  const cases = [
    { button: 1 }, { ctrlKey: true }, { shiftKey: true }, { altKey: true },
    { target: '_blank' }, { download: '' }, { alreadyPrevented: true }
  ];
  for (const guards of cases) {
    const prevented = await page.locator('.pin-card a').evaluate((anchor, guards) => {
      anchor.target = guards.target || '';
      if (guards.download !== undefined) anchor.setAttribute('download', guards.download);
      else anchor.removeAttribute('download');
      const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: guards.button || 0,
        ctrlKey: Boolean(guards.ctrlKey), shiftKey: Boolean(guards.shiftKey), altKey: Boolean(guards.altKey) });
      if (guards.alreadyPrevented) event.preventDefault();
      let seenPrevented;
      const record = current => {
        seenPrevented = current.defaultPrevented;
        current.preventDefault();
      };
      document.getElementById('boardPageContent').addEventListener('click', record, { once: true });
      anchor.dispatchEvent(event);
      return seenPrevented;
    }, guards);
    expect(prevented).toBe(Boolean(guards.alreadyPrevented));
  }
  await expect(page).toHaveURL(/pin-overlay-board\.html$/);
  await expect(page.locator('#pinOverlay')).toBeHidden();
});

test('rejects forged messages even when they use the iframe window source', async ({ page }) => {
  await page.locator('.pin-card a').click();
  await expect(page.locator('#pinOverlay')).toBeVisible();
  await page.evaluate(() => {
    const iframeWindow = document.getElementById('pinOverlayFrame').contentWindow;
    const valid = { source: 'scrappl-pin-overlay', version: 1, type: 'changed', pinId: 42, change: 'updated' };
    const dispatch = (data, origin, source) => window.dispatchEvent(new MessageEvent('message', { data, origin, source }));
    dispatch({ ...valid, type: 'close' }, 'https://evil.example', iframeWindow);
    dispatch({ ...valid, type: 'close' }, location.origin, window);
    dispatch({ ...valid, type: 'close', source: 'wrong-namespace' }, location.origin, iframeWindow);
    dispatch({ ...valid, type: 'close', version: 2 }, location.origin, iframeWindow);
    dispatch({ ...valid, type: 'close', pinId: 43 }, location.origin, iframeWindow);
    dispatch({ ...valid, version: 2 }, location.origin, iframeWindow);
    dispatch({ ...valid, pinId: 43 }, location.origin, iframeWindow);
  });
  await expect.poll(() => page.evaluate(() => window.refreshCalls)).toEqual([]);
  await expect(page.locator('#pinOverlay')).toBeVisible();
});

test('refreshes once and focuses the returned replacement on iframe close', async ({ page }) => {
  await page.locator('.pin-card a').click();
  const frame = page.frameLocator('#pinOverlayFrame');
  await frame.locator('#updated').click();
  await frame.locator('#moved').click();
  await frame.locator('#close').click();
  await expect(page.locator('#pinOverlay')).toBeHidden();
  await expect.poll(() => page.evaluate(() => window.refreshCalls)).toEqual([{ pinId: 42, change: 'moved' }]);
  await expect.poll(() => page.evaluate(() => document.activeElement.id)).toBe('pin-42');
});

test('dirty real browser Back refreshes once and focuses the returned replacement', async ({ page }) => {
  await page.locator('.pin-card a').click();
  await page.frameLocator('#pinOverlayFrame').locator('#updated').click();
  await page.goBack({ waitUntil: 'commit' });
  await expect(page).toHaveURL(/pin-overlay-board\.html$/);
  await expect(page.locator('#pinOverlay')).toBeHidden();
  await expect.poll(() => page.evaluate(() => window.refreshCalls)).toEqual([{ pinId: 42, change: 'updated' }]);
  await expect.poll(() => page.evaluate(() => document.activeElement.id)).toBe('pin-42');
});

test('direct query close replaces only pin parameter', async ({ page }) => {
  await page.goto(`${boardUrl}?filter=favorites&pin=42`);
  await expect(page.locator('#pinOverlay')).toBeVisible();
  await page.locator('[data-overlay-close]').click();
  await expect(page).toHaveURL(/\?filter=favorites$/);
  await expect(page.locator('#pinOverlay')).toBeHidden();
});
