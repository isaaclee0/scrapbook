const { test, expect } = require('@playwright/test');

const boardUrl = '/tests/e2e/fixtures/pin-overlay-board.html';
const pinFixture = require('path').join(__dirname, 'fixtures/pin-overlay-pin.html');

test.beforeEach(async ({ page }) => {
  await page.route('**/pin/42?embedded=1&board_id=9*', route => route.fulfill({ path: pinFixture }));
  await page.goto(boardUrl);
});

test('opens in-place and reconciles history state', async ({ page }) => {
  await page.locator('.pin-card a').click();
  await expect(page).toHaveURL(/\?pin=42$/);
  await expect(page.locator('#pinOverlay')).toBeVisible();
  await expect(page.locator('#pinOverlayFrame')).toHaveAttribute('src', '/pin/42?embedded=1&board_id=9');
  await page.evaluate(() => {
    history.replaceState(null, '', location.pathname);
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  await expect(page.locator('#pinOverlay')).toBeHidden();
  await page.evaluate(() => {
    history.pushState({ scrapbookPinOverlay: true, pinId: 42 }, '', `${location.pathname}?pin=42`);
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  await expect(page).toHaveURL(/\?pin=42$/);
  await expect(page.locator('#pinOverlay')).toBeVisible();
});

test('leaves modified and non-primary pin links to the browser', async ({ page }) => {
  await page.locator('.pin-card a').click({ modifiers: ['Meta'] });
  await expect(page).toHaveURL(/pin-overlay-board\.html$/);
  await expect(page.locator('#pinOverlay')).toBeHidden();
});

test('rejects forged iframe messages', async ({ page }) => {
  await page.locator('.pin-card a').click();
  await expect(page.locator('#pinOverlay')).toBeVisible();
  await page.evaluate(() => {
    const valid = { source: 'scrappl-pin-overlay', version: 1, type: 'changed', pinId: 42, change: 'updated' };
    window.dispatchEvent(new MessageEvent('message', { data: valid, origin: 'https://evil.example', source: window }));
    window.dispatchEvent(new MessageEvent('message', { data: valid, origin: window.location.origin, source: window }));
    window.dispatchEvent(new MessageEvent('message', { data: { ...valid, version: 2 }, origin: window.location.origin, source: window }));
    window.dispatchEvent(new MessageEvent('message', { data: { ...valid, pinId: 43 }, origin: window.location.origin, source: window }));
  });
  await expect.poll(() => page.evaluate(() => window.refreshCalls)).toEqual([]);
  await expect(page.locator('#pinOverlay')).toBeVisible();
});

test('refreshes once when the matching iframe reports a change and close', async ({ page }) => {
  await page.locator('.pin-card a').click();
  const frame = page.frameLocator('#pinOverlayFrame');
  await frame.locator('#updated').click();
  await frame.locator('#moved').click();
  await frame.locator('#close').click();
  await expect(page.locator('#pinOverlay')).toBeHidden();
  await expect.poll(() => page.evaluate(() => window.refreshCalls)).toEqual([{ pinId: 42, change: 'moved' }]);
});

test('direct query close replaces only pin parameter', async ({ page }) => {
  await page.goto(`${boardUrl}?filter=favorites&pin=42`);
  await expect(page.locator('#pinOverlay')).toBeVisible();
  await page.locator('[data-overlay-close]').click();
  await expect(page).toHaveURL(/\?filter=favorites$/);
  await expect(page.locator('#pinOverlay')).toBeHidden();
});
