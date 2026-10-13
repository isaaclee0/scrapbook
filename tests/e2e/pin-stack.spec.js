const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const fixture = '/tests/e2e/fixtures/pin-stack.html';
const boardSource = () => fs.readFileSync(path.join(__dirname, '../../templates/board.html'), 'utf8');

test.beforeEach(async ({ page }) => {
  await page.route('**/*.svg', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="1200"><rect width="400" height="1200" fill="red"/></svg>' }));
  await page.route('**/api/pin/42/images', route => route.fulfill({ json: { success: true, image_count: 3, images: [
    { id: 101, image_url: '/cover.svg' }, { id: 102, preview_url: '/recipe.svg' }, { id: 103, preview_url: '/wide.svg' }
  ] } }));
  await page.route('**/pin/42?embedded=1&board_id=9*', route => route.fulfill({ path: path.join(__dirname, 'fixtures/pin-overlay-pin.html') }));
  await page.clock.install();
  await page.goto(fixture);
});

test('stack indicator stays static during hover and opens the cover', async ({ page }) => {
  const galleryRequests = [];
  page.on('request', request => { if (request.url().includes('/api/pin/42/images')) galleryRequests.push(request.url()); });
  const card = page.locator('#pin-42');
  const before = await card.boundingBox();
  await card.hover();
  await page.clock.runFor(6500);
  await expect(card.locator('[data-gallery-count]')).toHaveText('3');
  await expect(card.locator('[data-gallery-count]')).toHaveAttribute('aria-label', '3 images');
  await expect(card.locator('.pin-image')).toHaveAttribute('src', '/cover.svg');
  await expect(card.locator('a')).toHaveAttribute('href', '/pin/42');
  expect(await card.boundingBox()).toEqual(before);
  expect(galleryRequests).toEqual([]);
  await card.locator('a').click();
  await expect(page).toHaveURL(/\?pin=42$/);
  await expect(page.locator('[data-overlay-open-page]')).toHaveAttribute('href', '/pin/42');
});

test('dynamic and refreshed cards show the saved count and preview-sized cover', async ({ page }) => {
  const source = boardSource();
  const functions = source.slice(source.indexOf('    function createBoardPinCard(pin) {'), source.indexOf('    // Single source of truth for the container aspect-ratio.'));
  await page.route('**/api/pin/46/card', route => route.fulfill({ json: { success: true, pin: {
    id: 46, board_id: 9, image_count: 4, title: 'Updated', image_url: '/cover.svg', cover_preview_url: '/small.svg'
  } } }));
  await page.evaluate(functions => {
    window.escapeHtml = value => String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
    window.getBoardId = () => 9;
    window.applyCurrentSectionFilter = window.reportImageDimensions = () => {};
    window.eval(functions);
    [1, 3].forEach(image_count => document.getElementById('pinsGrid').appendChild(window.createBoardPinCard({ id: 43 + image_count, title: 'Dynamic', image_count, image_url: '/cover.svg', cover_preview_url: '/small.svg' })));
  }, functions);
  await expect(page.locator('#pin-46 [data-gallery-count]')).toHaveText('3');
  await expect(page.locator('#pin-46 .pin-image')).toHaveAttribute('src', '/small.svg');
  await expect(page.locator('#pin-46 .pin-image')).toHaveAttribute('data-original-url', '/cover.svg');
  await expect(page.locator('#pin-44 [data-gallery-count]')).toHaveCount(0);
  await page.evaluate(() => window.refreshBoardPinCard(46, 'updated'));
  await expect(page.locator('#pin-46 [data-gallery-count]')).toHaveText('4');
  await expect(page.locator('#pin-46 a')).toHaveAttribute('href', '/pin/46');
});

test.describe('mobile board', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  test('stack indicator is visible and tapping opens the cover', async ({ page }) => {
    await expect(page.locator('[data-gallery-count]')).toBeVisible();
    await page.locator('#pin-42 a').tap();
    await expect(page).toHaveURL(/\?pin=42$/);
    await expect(page.locator('[data-overlay-open-page]')).toHaveAttribute('href', '/pin/42');
  });
});

test('cache deltas ignore the previous cover after a gallery change', async ({ page }) => {
  const source = boardSource();
  const handlers = source.slice(source.indexOf('    function updateCachedPinsInDOM('), source.indexOf('    function startColorExtraction('));
  await page.evaluate(handlers => {
    window.devLog = () => {};
    window.eval(handlers);
    window.updateCachedPinsInDOM([{ id: 42, cached_filename: 'old.webp', image_url: '/old.svg' }]);
    window.updateExtractedPinsInDOM([{ id: 42, color1: '#abcdef', color2: '#fedcba', image_url: '/old.svg' }]);
  }, handlers);
  await expect(page.locator('#pin-42 .pin-image')).toHaveAttribute('src', '/cover.svg');
  expect(await page.locator('#pin-42').evaluate(node => node.style.getPropertyValue('--dominant-color'))).toBe('#123456');
});

test('dimension and colour reports identify the measured cover', async ({ page }) => {
  const requests = [];
  await page.route('**/save-pin-*/*', route => {
    requests.push({ pathname: new URL(route.request().url()).pathname, data: route.request().postDataJSON() });
    return route.fulfill({ json: { success: true } });
  });
  const source = boardSource();
  const dimensionStart = source.indexOf('    function reportImageDimensions(');
  const dimensions = source.slice(dimensionStart, source.indexOf('</script>', dimensionStart));
  const colorStart = source.indexOf('    function saveColorsToDatabase(');
  const colors = source.slice(colorStart, source.indexOf('    function checkAndStartUrlHealthChecking', colorStart));
  await page.locator('.pin-image').evaluate(image => { Object.defineProperty(image, 'naturalWidth', { value: 400 }); Object.defineProperty(image, 'naturalHeight', { value: 1200 }); });
  await page.evaluate(({ dimensions, colors }) => {
    window.devLog = window.devWarn = () => {};
    window.eval(dimensions + colors);
    window.reportImageDimensions(document.querySelector('.pin-image'));
    window.saveColorsToDatabase(42, '#abcdef', '#fedcba', '/cover.svg');
  }, { dimensions, colors });
  await expect.poll(() => requests.slice().sort((a, b) => a.pathname.localeCompare(b.pathname))).toEqual([
    { pathname: '/save-pin-colors/42', data: { dominant_color_1: '#abcdef', dominant_color_2: '#fedcba', image_url: '/cover.svg' } },
    { pathname: '/save-pin-dimensions/42', data: { width: 400, height: 1200, image_url: '/cover.svg' } }
  ]);
});
