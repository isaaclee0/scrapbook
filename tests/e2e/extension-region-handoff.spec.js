const { test, expect } = require('@playwright/test');
const path = require('path');

const fixtureUrl = '/tests/e2e/fixtures/extension-handoff.html';
const contentScript = path.join(__dirname, '../../chrome-extension/content.js');

test('sends a completed region directly to the Scrappl handoff', async ({ page }) => {
  await page.goto(fixtureUrl);
  await page.evaluate(() => {
    window.messages = [];
    window.chrome = {
      runtime: {
        sendMessage: async (message) => {
          window.messages.push(message);
          if (message.type === 'CAPTURE_REGION') return { ok: true, dataUrl: 'data:image/png;base64,AA==' };
          if (message.type === 'OPEN_HANDOFF') return { ok: true };
          return { ok: false };
        },
        onMessage: { addListener(listener) { window.extensionListener = listener; } },
      },
    };
  });
  await page.addScriptTag({ path: contentScript });
  await page.evaluate(() => window.extensionListener({ type: 'START_REGION_CAPTURE', pageUrl: location.href, pageTitle: document.title }));
  const overlay = page.locator('.rs-overlay');
  await overlay.hover({ position: { x: 10, y: 10 } });
  await page.mouse.down();
  await page.mouse.move(80, 80);
  await page.mouse.up();
  await page.locator('.rs-use').click();
  const pageUrl = await page.url();
  await expect.poll(() => page.evaluate(() => window.messages.at(-1))).toEqual({
    type: 'OPEN_HANDOFF', dataUrl: 'data:image/png;base64,AA==', pageUrl, pageTitle: 'Extension handoff fixture',
  });
});
