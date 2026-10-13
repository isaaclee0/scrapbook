const { test, expect } = require('@playwright/test');
const fixture = '/tests/e2e/fixtures/pin-gallery.html';
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ1sAAAAASUVORK5CYII=', 'base64');
const image = id => ({ id, image_url: `/original-${id}.png`, display_url: `/display-${id}.png`, preview_url: `/preview-${id}.png`, width: 800, height: 2400, position: id - 1 });

async function prepare(page, options = {}) {
  let images = (options.ids || [1, 2, 3]).map(image);
  const requests = [];
  let fail = options.fail || '';
  let failLoad = options.failLoad;
  await page.route(/\/(original|display|preview)-\d+\.png/, route => {
    options.imageRequests?.push(new URL(route.request().url()).pathname);
    if (options.imageStatus?.(new URL(route.request().url()).pathname) === 404) return route.fulfill({ status:404, body:'Image unavailable' });
    const id = Number(/-(\d+)\.png/.exec(route.request().url())[1]);
    const background = id === 1 ? '#ead6c4' : '#faf8ed';
    const label = id === 1 ? 'Chocolate cake' : `Recipe ${id}`;
    const lines = Array.from({ length: 10 }, (_, i) => `<text x="50" y="${260 + i * 170}" font-size="35" fill="#403c35">${i + 1}. Recipe instructions for the cake</text>`).join('');
    route.fulfill({ contentType:'image/svg+xml', body:`<svg xmlns="http://www.w3.org/2000/svg" width="800" height="2400"><rect width="800" height="2400" fill="${background}"/><text x="50" y="150" font-size="64" fill="#403c35">${label}</text>${lines}</svg>` });
  });
  await page.route('**/api/pin/42/images**', async route => {
    const req = route.request();
    if (req.method() === 'GET' && failLoad) {
      failLoad = false;
      return route.fulfill({ status: 503, json: { success: false, error: 'Gallery temporarily unavailable' } });
    }
    if (req.method() === 'POST') {
      expect(req.headers()['x-csrf-token']).toBe('fixture-token');
      const body = req.url().endsWith('/manage') ? req.postDataJSON() : { upload: req.postData(), replace_id: /name="replace_id"\r\n\r\n(\d+)/.exec(req.postData() || '')?.[1] };
      requests.push(body);
      if (fail && (body.action === fail || body.upload?.includes(fail))) {
        fail = '';
        return route.fulfill({ status: 409, json: { success: false, error: 'Please retry this file or action' } });
      }
      if (body.action === 'cover') images = [images.find(i => i.id === body.image_id), ...images.filter(i => i.id !== body.image_id)];
      else if (body.action === 'remove') images = images.filter(i => i.id !== body.image_id);
      else if (body.action === 'reorder') images = body.image_ids.map(id => images.find(i => i.id === id));
      else if (body.replace_id) images = images.map(i => i.id === Number(body.replace_id) ? { ...i, image_url: '/original-99.png', display_url: '/display-99.png' } : i);
      else images.push(image(4 + images.length));
    }
    return route.fulfill({ json: { success: true, images, image_count: images.length } });
  });
  await page.goto(fixture + (options.query || ''));
  return requests;
}

test('arrows, keyboard and thumbnails wrap without adding history or capturing notes keys', async ({ page }, testInfo) => {
  await prepare(page);
  await expect(page.locator('[data-gallery-position]')).toHaveText('1 / 3');
  await page.getByRole('button', { name: 'Next image', exact: true }).click();
  await expect(page.locator('[data-gallery-position]')).toHaveText('2 / 3');
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('[data-gallery-position]')).toHaveText('3 / 3');
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('[data-gallery-position]')).toHaveText('1 / 3');
  await page.getByRole('button', { name: 'Select image 3', exact: true }).click();
  await expect(page.locator('.pin-image')).toHaveAttribute('src', '/display-3.png');
  await page.screenshot({ path:testInfo.outputPath('gallery-desktop.png'), fullPage:true });
  await page.locator('textarea').fill('recipe notes');
  await page.keyboard.press('ArrowLeft');
  await expect(page.locator('[data-gallery-position]')).toHaveText('3 / 3');
  await expect(page).toHaveURL(fixture);
});

test('selected original opens fullscreen with zoom and focus restoration', async ({ page }) => {
  await prepare(page, { query: '?image=2' });
  await expect(page.locator('[data-gallery-position]')).toHaveText('2 / 3');
  await page.getByRole('button', { name: 'Fullscreen image' }).click();
  await expect(page.getByRole('dialog').locator('img')).toHaveAttribute('src', '/original-2.png');
  await page.getByRole('button', { name: 'Enlarge image' }).click();
  await expect(page.getByRole('button', { name: 'Fit image' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Fullscreen image' })).toBeFocused();
  await expect(page.locator('[data-gallery-position]')).toHaveText('2 / 3');
});

test('cover is explicit and reorder keeps cover first, selection survives and failures retry', async ({ page }) => {
  const requests = await prepare(page, { query: '?image=3', fail: 'cover' });
  await page.getByRole('button', { name: 'Move image earlier' }).click();
  await expect(page.locator('[data-gallery-position]')).toHaveText('2 / 3');
  await expect(page.getByRole('button', { name: 'Move image earlier' })).toBeDisabled();
  await page.getByRole('button', { name: 'Make cover' }).click();
  await expect(page.getByText('Please retry this file or action', { exact: true })).toBeVisible();
  await expect(page.locator('[data-gallery-position]')).toHaveText('2 / 3');
  await page.getByRole('button', { name: 'Retry action' }).click();
  await expect(page.locator('[data-gallery-position]')).toHaveText('1 / 3');
  await page.getByRole('button', { name: 'Remove image', exact: true }).click();
  await expect(page.locator('[data-gallery-position]')).toHaveText('1 / 2');
  expect(requests[0].image_ids).toEqual([1, 3, 2]);
  expect(await page.evaluate(() => window.notifications.length)).toBe(3);
});

test('multi-file add reports failures per file and retries, replacement preserves identity', async ({ page }) => {
  await prepare(page, { fail: 'bad.png', query: '?image=2' });
  await page.locator('[data-gallery-files]').setInputFiles([{ name: 'bad.png', mimeType: 'image/png', buffer: png }, { name: 'good.png', mimeType: 'image/png', buffer: png }]);
  await expect(page.getByText('good.png: Added', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry bad.png' })).toBeVisible();
  await page.getByRole('button', { name: 'Retry bad.png' }).click();
  await expect(page.getByText('bad.png: Added', { exact: true })).toBeVisible();
  await expect(page.locator('[data-gallery-position]')).toHaveText('2 / 5');
  await page.locator('[data-gallery-replacement]').setInputFiles({ name: 'replace.png', mimeType: 'image/png', buffer: png });
  await expect(page.locator('.pin-image')).toHaveAttribute('src', '/display-99.png');
  await expect(page.locator('[data-gallery-position]')).toHaveText('2 / 5');
});

test('paste is scoped to add area, drop adds files, horizontal swipe leaves vertical gestures alone', async ({ page }) => {
  const requests = await prepare(page);
  await page.locator('textarea').evaluate(el => { const data = new DataTransfer(); data.items.add(new File(['paste'], 'note.png', {type:'image/png'})); el.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, clipboardData: data })); });
  expect(requests).toHaveLength(0);
  await page.locator('[data-gallery-add]').evaluate(el => { const data = new DataTransfer(); data.items.add(new File(['paste'], 'paste.png', {type:'image/png'})); el.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, clipboardData: data })); });
  await expect(page.getByText('paste.png: Added', { exact: true })).toBeVisible();
  await page.locator('[data-gallery-add]').evaluate(el => { const data = new DataTransfer(); data.items.add(new File(['drop'], 'drop.png', {type:'image/png'})); el.dispatchEvent(new DragEvent('drop', { bubbles: true, dataTransfer: data })); });
  await expect(page.getByText('drop.png: Added', { exact: true })).toBeVisible();
  const surface = page.locator('.pin-image-container');
  const swipe = async (dx, dy) => surface.evaluate((el, delta) => { el.dispatchEvent(new PointerEvent('pointerdown', { bubbles:true, pointerId:1, pointerType:'touch', clientX:200, clientY:200 })); el.dispatchEvent(new PointerEvent('pointerup', { bubbles:true, pointerId:1, pointerType:'touch', clientX:200+delta[0], clientY:200+delta[1] })); }, [dx, dy]);
  await swipe(5, 90);
  await expect(page.locator('[data-gallery-position]')).toHaveText('1 / 5');
  await swipe(-90, 5);
  await expect(page.locator('[data-gallery-position]')).toHaveText('2 / 5');
});

test('empty galleries have no placeholder attachment and added images enable tools', async ({ page }) => {
  await prepare(page, { ids: [] });
  await expect(page.locator('[data-gallery-position]')).toHaveText('No images');
  await expect(page.getByRole('button', { name: 'Next image', exact: true })).toBeHidden();
  await expect(page.getByRole('button', { name: 'Remove image', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Set as board image', exact: true })).toBeDisabled();
  await page.locator('[data-gallery-files]').setInputFiles({ name: 'first.png', mimeType:'image/png', buffer:png });
  await expect(page.locator('[data-gallery-position]')).toHaveText('1 / 1');
  await expect(page.getByRole('button', { name: 'Set as board image', exact: true })).toBeEnabled();
});

test('missing display cache and thumbnail fall back to the selected original once', async ({ page }) => {
  const requests=[];
  await prepare(page, { imageRequests:requests, imageStatus:url=>['/display-1.png','/preview-1.png'].includes(url)?404:200 });
  await expect(page.locator('.pin-image')).toHaveAttribute('src','/original-1.png');
  await expect.poll(()=>page.locator('.pin-image').evaluate(el=>el.complete && el.naturalWidth>0)).toBe(true);
  await expect(page.getByRole('button',{name:'Retry image',exact:true})).toBeHidden();
  await expect(page.getByRole('button',{name:'Select image 1',exact:true}).locator('img')).toHaveAttribute('src','/original-1.png');
  expect(await page.evaluate(()=>window.pinGallery.readableUrl())).toBe('/original-1.png');
  await page.getByRole('button',{name:'Next image',exact:true}).click();
  await page.getByRole('button',{name:'Previous image',exact:true}).click();
  await expect(page.locator('.pin-image')).toHaveAttribute('src','/original-1.png');
  expect(requests.filter(url=>url==='/display-1.png').length).toBeLessThanOrEqual(2);
  await page.locator('[data-gallery-replacement]').setInputFiles({ name:'fresh.png', mimeType:'image/png', buffer:png });
  await expect(page.locator('.pin-image')).toHaveAttribute('src','/display-99.png');
  expect(await page.evaluate(()=>window.pinGallery.readableUrl())).toBe('/display-99.png');
});

test('failed cache and original show local error while navigation and original retry remain usable', async ({ page }) => {
  let originalHealthy=false;
  const requests=[];
  await prepare(page, { imageRequests:requests, imageStatus:url=>url==='/display-1.png'||(url==='/original-1.png'&&!originalHealthy)?404:200 });
  await expect(page.getByRole('button',{name:'Retry image',exact:true})).toBeVisible();
  await expect(page.locator('.pin-image')).toHaveAttribute('src','/original-1.png');
  await page.getByRole('button',{name:'Next image',exact:true}).click();
  await expect(page.locator('.pin-image')).toHaveAttribute('src','/display-2.png');
  await expect(page.getByRole('button',{name:'Retry image',exact:true})).toBeHidden();
  await page.getByRole('button',{name:'Previous image',exact:true}).click();
  await expect(page.getByRole('button',{name:'Retry image',exact:true})).toBeVisible();
  originalHealthy=true;
  await page.getByRole('button',{name:'Retry image',exact:true}).click();
  await expect.poll(()=>page.locator('.pin-image').evaluate(el=>el.complete && el.naturalWidth>0)).toBe(true);
  await expect(page.getByRole('button',{name:'Retry image',exact:true})).toBeHidden();
  await expect(page.locator('.pin-image')).toHaveAttribute('src','/original-1.png');
  expect(requests.filter(url=>url==='/display-1.png')).toHaveLength(1);
});

test('readable cover source preserves a healthy cache when the original has expired', async ({ page }) => {
  await prepare(page,{imageStatus:url=>url==='/original-1.png'?404:200});
  await expect.poll(()=>page.locator('.pin-image').evaluate(el=>el.complete && el.naturalWidth>0)).toBe(true);
  expect(await page.evaluate(()=>window.pinGallery.readableUrl())).toBe('/display-1.png');
  await page.getByRole('button',{name:'Fullscreen image',exact:true}).click();
  await expect(page.getByRole('dialog').locator('img')).toHaveAttribute('src','/display-1.png');
  await expect.poll(()=>page.getByRole('dialog').locator('img').evaluate(el=>el.complete && el.naturalWidth>0)).toBe(true);
  await expect(page.getByRole('button',{name:'Retry original',exact:true})).toBeHidden();
});

test('fullscreen source failures retry original first and recover without closing the selected image',async({page})=>{
  let originalHealthy=false;
  await prepare(page,{imageStatus:url=>['/display-1.png','/preview-1.png'].includes(url)||(url==='/original-1.png'&&!originalHealthy)?404:200});
  await expect(page.getByRole('button',{name:'Retry image',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Fullscreen image',exact:true}).click();
  await expect(page.getByRole('button',{name:'Retry original',exact:true})).toBeVisible();
  originalHealthy=true;
  await page.getByRole('button',{name:'Retry original',exact:true}).click();
  await expect.poll(()=>page.getByRole('dialog').locator('img').evaluate(el=>el.complete && el.naturalWidth>0)).toBe(true);
  await expect(page.getByRole('button',{name:'Retry original',exact:true})).toBeHidden();
  await expect(page.getByRole('dialog').locator('img')).toHaveAttribute('src','/original-1.png');
  await page.keyboard.press('Escape');
  await expect(page.locator('[data-gallery-position]')).toHaveText('1 / 3');
});

test('failed initial fetch retains the existing cover and offers recovery', async ({ page }) => {
  await page.route('**/tests/e2e/fixtures/pin-gallery.html', async route => {
    const html = require('fs').readFileSync(require('path').join(__dirname, 'fixtures/pin-gallery.html'), 'utf8');
    await route.fulfill({ contentType: 'text/html', body: html.replace('src="/static/images/default_pin.png"', 'src="/display-1.png"') });
  });
  await prepare(page, { failLoad: true });
  await expect(page.getByText('Gallery temporarily unavailable', { exact: true })).toBeVisible();
  await expect(page.locator('.pin-image')).toHaveAttribute('src', '/display-1.png');
  await page.getByRole('button', { name: 'Retry action' }).click();
  await expect(page.locator('[data-gallery-position]')).toHaveText('1 / 3');
  expect(await page.evaluate(() => window.notifications.length)).toBe(0);
});

test('mobile layout fits, and enlarged recipes scroll and pan', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await prepare(page, { query: '?image=2' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('gallery-mobile.png'), fullPage:true });
  await page.getByRole('button', { name:'Fullscreen image' }).click();
  await page.getByRole('button', { name:'Enlarge image' }).click();
  const viewport = page.locator('.gallery-fullscreen-viewport');
  await expect.poll(() => viewport.evaluate(el => el.scrollHeight > el.clientHeight && el.scrollWidth > el.clientWidth)).toBe(true);
  await viewport.evaluate(el => el.scrollTo(100, 300));
  await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBe(300);
  await page.mouse.move(200, 300);
  await page.mouse.down();
  await page.mouse.move(150, 250);
  await page.mouse.up();
  await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBeGreaterThan(300);
  await page.screenshot({ path: testInfo.outputPath('gallery-fullscreen-mobile.png') });
});

test('embedded Escape consumes fullscreen and confirmation before forwarding close, respecting inner handlers', async ({ page }) => {
  await prepare(page);
  await page.getByRole('button', { name: 'Fullscreen image', exact:true }).click();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(await page.evaluate(()=>window.escapeCloseCount)).toBe(0);
  await page.evaluate(()=>{const confirmation=document.createElement('div');confirmation.className='confirmation-dialog-overlay';confirmation.textContent='Confirm removal';document.body.appendChild(confirmation)});
  await page.keyboard.press('Escape');
  await expect(page.locator('.confirmation-dialog-overlay')).toHaveCount(0);
  expect(await page.evaluate(()=>window.escapeCloseCount)).toBe(0);
  await page.locator('textarea').evaluate(el=>{el.addEventListener('keydown',event=>event.preventDefault(),{once:true});el.focus()});
  await page.keyboard.press('Escape');
  expect(await page.evaluate(()=>window.escapeCloseCount)).toBe(0);
  await page.keyboard.press('Escape');
  expect(await page.evaluate(()=>window.escapeCloseCount)).toBe(1);
});
