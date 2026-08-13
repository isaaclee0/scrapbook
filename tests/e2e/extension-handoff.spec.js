const { test, expect } = require('@playwright/test');

test('stores a matching image handoff once', async ({ page }) => {
  await page.goto('/tests/e2e/fixtures/extension-handoff.html#scrappl-handoff=n1');
  await page.evaluate(() => window.postMessage({
    type: 'SCRAPPL_EXTENSION_HANDOFF',
    nonce: 'n1',
    imageDataUrl: 'data:image/png;base64,AA==',
    sourceUrl: 'https://source.test/page',
    title: 'Source',
  }, location.origin));

  await expect.poll(() => page.evaluate(() => window.ScrapplExtensionHandoff.take()))
    .toMatchObject({
      imageDataUrl: 'data:image/png;base64,AA==',
      sourceUrl: 'https://source.test/page',
      title: 'Source',
    });
  await expect(page.evaluate(() => window.ScrapplExtensionHandoff.take())).resolves.toBeNull();
});

test('rejects invalid and expired handoffs', async ({ page }) => {
  await page.goto('/tests/e2e/fixtures/extension-handoff.html#scrappl-handoff=n1');
  await page.evaluate(() => window.postMessage({
    type: 'SCRAPPL_EXTENSION_HANDOFF',
    nonce: 'wrong',
    imageDataUrl: 'data:text/plain;base64,QQ==',
    sourceUrl: '',
    title: '',
  }, location.origin));

  await expect(page.evaluate(() => window.ScrapplExtensionHandoff.take())).resolves.toBeNull();
  await page.evaluate(() => sessionStorage.setItem('scrappl.extension-handoff.v1', JSON.stringify({
    imageDataUrl: 'data:image/png;base64,AA==', sourceUrl: '', title: '', createdAt: Date.now() - 600001,
  })));
  await expect(page.evaluate(() => window.ScrapplExtensionHandoff.take())).resolves.toBeNull();
});
