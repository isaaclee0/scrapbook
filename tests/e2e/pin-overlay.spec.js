const { test, expect } = require('@playwright/test');

const boardUrl = '/tests/e2e/fixtures/pin-overlay-board.html';
const pinFixture = require('path').join(__dirname, 'fixtures/pin-overlay-pin.html');

async function waitForDirtyChange(page, change) {
  await expect.poll(() => page.evaluate(expected => Object.keys(sessionStorage)
    .some(key => sessionStorage.getItem(key).includes(`"change":"${expected}"`)), change)).toBe(true);
}

async function preparePreservedBoardState(page) {
  await page.locator('.section-circle[data-section-id="7"]').click();
  await page.evaluate(() => {
    const grid = document.getElementById('pinsGrid');
    for (const id of [43, 44]) {
      const card = document.createElement('article');
      card.id = `pin-${id}`;
      card.className = 'pin-card';
      card.dataset.pinId = String(id);
      card.dataset.sectionId = '7';
      card.textContent = `Lazy-loaded pin ${id}`;
      grid.appendChild(card);
    }
    window.scrollTo(0, 640);
  });
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(640);
  return page.evaluate(() => ({
    scrollY: window.scrollY,
    activeSection: document.querySelector('.section-circle.active').dataset.sectionId,
    cardCount: document.querySelectorAll('.pin-card').length
  }));
}

test.beforeEach(async ({ page }) => {
  await page.route('**/pin/42?embedded=1&board_id=9*', route => route.fulfill({ path: pinFixture }));
  await page.route('**/api/pin/42/card', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      success: true,
      pin: {
        id: 42,
        board_id: 9,
        section_id: 7,
        title: 'Refreshed pin 42'
      }
    })
  }));
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

test('clean close paths restore focus outside the hidden overlay', async ({ page }) => {
  const closePaths = [
    async () => page.locator('[data-overlay-close]').click(),
    async () => page.keyboard.press('Escape'),
    async () => page.locator('#pinOverlay').click({ position: { x: 1, y: 1 } }),
    async () => page.frameLocator('#pinOverlayFrame').locator('#close').click()
  ];
  for (const closeOverlay of closePaths) {
    await page.goto(boardUrl);
    await page.locator('#pin-42-link').click();
    await closeOverlay();
    await expect(page.locator('#pinOverlay')).toBeHidden();
    await expect.poll(() => page.evaluate(() => document.activeElement.id)).toBe('pin-42-link');
  }
});

test('clean real browser Back restores focus to the opener', async ({ page }) => {
  await page.locator('#pin-42-link').click();
  await page.goBack({ waitUntil: 'commit' });
  await expect(page.locator('#pinOverlay')).toBeHidden();
  await expect.poll(() => page.evaluate(() => document.activeElement.id)).toBe('pin-42-link');
});

test('modal overlay keeps keyboard focus out of the inert board until close', async ({ page }) => {
  await page.locator('#pin-42-link').click();
  await expect(page.locator('#pinOverlay')).toHaveAttribute('data-state', 'open');
  await expect(page.locator('#boardPageContent')).toHaveAttribute('inert', '');
  await expect(page.locator('#boardPageContent')).toHaveAttribute('aria-hidden', 'true');
  await expect.poll(() => page.evaluate(() => document.activeElement.id)).toBe('pinOverlayFrame');
  await page.locator('#board-secondary-link').focus();
  await expect.poll(() => page.evaluate(() => document.activeElement.id)).not.toBe('board-secondary-link');

  for (let index = 0; index < 8; index += 1) {
    await page.keyboard.press(index % 2 === 0 ? 'Tab' : 'Shift+Tab');
    expect(await page.evaluate(() =>
      !document.getElementById('boardPageContent').contains(document.activeElement))).toBe(true);
  }

  await page.locator('[data-overlay-close]').click();
  await expect(page.locator('#pinOverlay')).toBeHidden();
  await expect(page.locator('#boardPageContent')).not.toHaveAttribute('inert');
  await expect(page.locator('#boardPageContent')).not.toHaveAttribute('aria-hidden');
  await expect.poll(() => page.evaluate(() => document.activeElement.id)).toBe('pin-42-link');
  await page.locator('#board-secondary-link').focus();
  await expect.poll(() => page.evaluate(() => document.activeElement.id)).toBe('board-secondary-link');
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#section-7$/);
});

test('unchanged close preserves exact scroll, section, and lazy-loaded cards without layout', async ({ page }) => {
  const before = await preparePreservedBoardState(page);
  await page.locator('#pin-42-link').evaluate(anchor => window.overlayController.open(42, anchor));
  await expect(page.locator('#pinOverlay')).toBeVisible();
  await page.locator('[data-overlay-close]').click();
  await expect(page.locator('#pinOverlay')).toBeHidden();

  await expect.poll(() => page.evaluate(() => ({
    scrollY: window.scrollY,
    activeSection: document.querySelector('.section-circle.active').dataset.sectionId,
    cardCount: document.querySelectorAll('.pin-card').length,
    refreshCalls: window.refreshCalls,
    layoutCalls: window.layoutCalls
  }))).toEqual({ ...before, refreshCalls: [], layoutCalls: [] });
});

test('changed close refreshes only its card and preserves board state', async ({ page }) => {
  let cardRequests = 0;
  await page.route('**/api/pin/42/card', async route => {
    cardRequests += 1;
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        pin: {
          id: 42,
          board_id: 9,
          section_id: 7,
          section_name: 'Section 7',
          board_name: 'Fixture board',
          title: 'Updated pin 42',
          image_url: '/static/images/default_pin.png',
          link: null,
          link_status: null,
          cached_filename: null,
          cached_width: null,
          cached_height: null,
          dominant_color_1: null,
          dominant_color_2: null
        }
      })
    });
  });
  const before = await preparePreservedBoardState(page);
  await page.locator('#pin-42-link').evaluate(anchor => window.overlayController.open(42, anchor));
  const frame = page.frameLocator('#pinOverlayFrame');
  await frame.locator('#updated').click();
  await frame.locator('#close').click();
  await expect(page.locator('#pinOverlay')).toBeHidden();

  await expect.poll(() => cardRequests).toBe(1);
  await expect.poll(() => page.evaluate(() => ({
    scrollY: window.scrollY,
    activeSection: document.querySelector('.section-circle.active').dataset.sectionId,
    cardCount: document.querySelectorAll('.pin-card').length,
    refreshCalls: window.refreshCalls,
    layoutCalls: window.layoutCalls,
    cardText: document.getElementById('pin-42').textContent.trim()
  }))).toEqual({
    ...before,
    refreshCalls: [{ pinId: 42, change: 'updated' }],
    layoutCalls: ['layout'],
    cardText: 'Updated pin 42'
  });
});

test('leaves guarded pin-link interactions to the browser', async ({ page }) => {
  const cases = [
    { button: 1 }, { metaKey: true }, { ctrlKey: true }, { shiftKey: true }, { altKey: true },
    { target: '_blank' }, { download: '' }, { alreadyPrevented: true }
  ];
  for (const guards of cases) {
    const prevented = await page.locator('.pin-card a').evaluate((anchor, guards) => {
      anchor.target = guards.target || '';
      if (guards.download !== undefined) anchor.setAttribute('download', guards.download);
      else anchor.removeAttribute('download');
      const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: guards.button || 0,
        metaKey: Boolean(guards.metaKey), ctrlKey: Boolean(guards.ctrlKey),
        shiftKey: Boolean(guards.shiftKey), altKey: Boolean(guards.altKey) });
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

test('production-shaped refreshed card focuses its link without scrolling', async ({ page }) => {
  await page.evaluate(() => window.scrollTo(0, 640));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(640);
  await page.locator('#pin-42-link').evaluate(anchor => window.overlayController.open(42, anchor));
  const frame = page.frameLocator('#pinOverlayFrame');
  await frame.locator('#updated').click();
  await frame.locator('#moved').click();
  await frame.locator('#close').click();
  await expect(page.locator('#pinOverlay')).toBeHidden();
  await expect.poll(() => page.evaluate(() => window.refreshCalls)).toEqual([{ pinId: 42, change: 'moved' }]);
  await expect(page.locator('#pin-42')).not.toHaveAttribute('tabindex');
  await expect.poll(() => page.evaluate(() => document.activeElement.id)).toBe('pin-42-link');
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(640);
});

test('dirty real browser Back refreshes once and focuses the returned replacement', async ({ page }) => {
  await page.locator('.pin-card a').click();
  await page.frameLocator('#pinOverlayFrame').locator('#updated').click();
  await waitForDirtyChange(page, 'updated');
  await page.goBack({ waitUntil: 'commit' });
  await expect(page).toHaveURL(/pin-overlay-board\.html$/);
  await expect(page.locator('#pinOverlay')).toBeHidden();
  await expect.poll(() => page.evaluate(() => window.refreshCalls)).toEqual([{ pinId: 42, change: 'updated' }]);
  await expect.poll(() => page.evaluate(() => document.activeElement.id)).toBe('pin-42-link');
});

test('rejected persisted refresh toasts and focuses board fallback without reload', async ({ page }) => {
  await page.goto(`${boardUrl}?refreshFails=1`);
  await page.locator('#pin-42-link').click();
  await page.frameLocator('#pinOverlayFrame').locator('#updated').click();
  await waitForDirtyChange(page, 'updated');
  await page.goBack({ waitUntil: 'commit' });
  await expect(page.locator('#pinOverlay')).toBeHidden();
  await expect.poll(() => page.evaluate(() => window.toastCalls)).toEqual(['Could not refresh pin']);
  await expect.poll(() => page.evaluate(() => document.activeElement.id)).toBe('boardPageContent');
});

test('direct query close replaces only pin parameter', async ({ page }) => {
  await page.goto(`${boardUrl}?filter=favorites&pin=42`);
  await expect(page.locator('#pinOverlay')).toBeVisible();
  const historyLength = await page.evaluate(() => history.length);
  await page.locator('[data-overlay-close]').click();
  await expect(page).toHaveURL(/\?filter=favorites$/);
  await expect(page.locator('#pinOverlay')).toBeHidden();
  expect(await page.evaluate(() => history.length)).toBe(historyLength);
});

test('timeout offers retry and retry keeps embed parameters with a generation counter', async ({ page }) => {
  const requests = [];
  await page.unroute('**/pin/42?embedded=1&board_id=9*');
  await page.route('**/pin/42?embedded=1&board_id=9*', async route => {
    requests.push(route.request().url());
    if (new URL(route.request().url()).searchParams.get('_retry') === '2') {
      await route.fulfill({ path: pinFixture });
    } else {
      await route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Never ready</title>' });
    }
  });

  await page.locator('#pin-42-link').click();
  await expect(page.locator('#pinOverlay')).toHaveAttribute('data-state', 'error');
  await expect(page.locator('[data-overlay-open-page]')).toHaveAttribute('href', '/pin/42');
  await page.locator('[data-overlay-retry]').click();
  await expect(page.locator('#pinOverlay')).toHaveAttribute('data-state', 'error');
  await page.locator('[data-overlay-retry]').click();

  await expect(page.locator('#pinOverlay')).toHaveAttribute('data-state', 'open');
  expect(requests.map(request => {
    const url = new URL(request);
    return {
      embedded: url.searchParams.get('embedded'),
      boardId: url.searchParams.get('board_id'),
      retry: url.searchParams.get('_retry')
    };
  })).toEqual([
    { embedded: '1', boardId: '9', retry: null },
    { embedded: '1', boardId: '9', retry: '1' },
    { embedded: '1', boardId: '9', retry: '2' }
  ]);
});

test('a valid ready message arriving after timeout recovers the overlay', async ({ page }) => {
  await page.unroute('**/pin/42?embedded=1&board_id=9*');
  await page.route('**/pin/42?embedded=1&board_id=9*', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><title>Late editor</title>'
  }));
  await page.locator('#pin-42-link').click();
  await expect(page.locator('#pinOverlay')).toHaveAttribute('data-state', 'error');

  await page.evaluate(() => {
    const frame = document.getElementById('pinOverlayFrame');
    window.dispatchEvent(new MessageEvent('message', {
      origin: window.location.origin,
      source: frame.contentWindow,
      data: { source: 'scrappl-pin-overlay', version: 1, type: 'ready', pinId: 42 }
    }));
  });

  await expect(page.locator('#pinOverlay')).toHaveAttribute('data-state', 'open');
  await expect.poll(() => page.evaluate(() => document.activeElement.id)).toBe('pinOverlayFrame');
});

test('Open as Page leaves recovery mode for the standalone pin URL', async ({ page }) => {
  await page.unroute('**/pin/42?embedded=1&board_id=9*');
  await page.route('**/pin/42?embedded=1&board_id=9*', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><title>Never ready</title>'
  }));
  await page.route('**/pin/42', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><title>Standalone pin</title><h1>Standalone pin</h1>'
  }));
  await page.locator('#pin-42-link').click();
  await expect(page.locator('#pinOverlay')).toHaveAttribute('data-state', 'error');

  await page.locator('[data-overlay-open-page]').click();

  await expect(page).toHaveURL(/\/pin\/42$/);
  await expect(page.getByRole('heading', { name: 'Standalone pin' })).toBeVisible();
});

test('backdrop wheel and touchmove cannot scroll the inert board', async ({ page }) => {
  await page.evaluate(() => window.scrollTo(0, 640));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(640);
  await page.locator('#pin-42-link').evaluate(anchor => window.overlayController.open(42, anchor));
  await expect(page.locator('#pinOverlay')).toHaveAttribute('data-state', 'open');

  await page.mouse.move(1, 1);
  await page.mouse.wheel(0, 500);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(640);
  expect(await page.locator('#pinOverlay').evaluate(root => {
    const event = new Event('touchmove', { bubbles: true, cancelable: true });
    root.dispatchEvent(event);
    return event.defaultPrevented;
  })).toBe(true);
});

test('deleting the opener focuses the nearest remaining pin without scrolling', async ({ page }) => {
  await page.evaluate(() => {
    const card = document.createElement('article');
    card.id = 'pin-43';
    card.className = 'pin-card';
    card.dataset.pinId = '43';
    card.innerHTML = '<a id="pin-43-link" href="/pin/43">Open pin 43</a>';
    document.getElementById('pinsGrid').appendChild(card);
    window.scrollTo(0, 640);
  });
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(640);
  await page.locator('#pin-42-link').evaluate(anchor => window.overlayController.open(42, anchor));
  await page.frameLocator('#pinOverlayFrame').locator('#deleted').click();
  await page.frameLocator('#pinOverlayFrame').locator('#close').click();

  await expect(page.locator('#pinOverlay')).toBeHidden();
  await expect.poll(() => page.evaluate(() => window.refreshCalls)).toEqual([{ pinId: 42, change: 'deleted' }]);
  await expect.poll(() => page.evaluate(() => document.activeElement.id)).toBe('pin-43-link');
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(640);
});

test('overlay panel stays bounded on desktop and fills a 390px viewport', async ({ page }) => {
  await page.locator('#pin-42-link').click();
  const desktop = await page.locator('#pinOverlayPanel').boundingBox();
  const desktopViewport = page.viewportSize();
  expect(desktop.x).toBeGreaterThanOrEqual(0);
  expect(desktop.y).toBeGreaterThanOrEqual(0);
  expect(desktop.x + desktop.width).toBeLessThanOrEqual(desktopViewport.width);
  expect(desktop.y + desktop.height).toBeLessThanOrEqual(desktopViewport.height);

  await page.setViewportSize({ width: 390, height: 720 });
  const mobile = await page.locator('#pinOverlayPanel').boundingBox();
  expect(mobile).toEqual({ x: 0, y: 0, width: 390, height: 720 });
});
