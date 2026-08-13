const { test, expect } = require('@playwright/test');
const path = require('path');

const fixtureUrl = '/tests/e2e/fixtures/extension-dialog.html';
const contentScript = path.join(__dirname, '../../chrome-extension/content.js');

async function openExtensionDialog(page, responses = {}, imageSource = {}) {
  await page.goto(fixtureUrl);
  await page.evaluate((customResponses) => {
    window.extensionMessages = [];
    window.extensionResponses = {
      LIST_BOARDS: {
        ok: true,
        data: [
          { id: 3, name: 'zebra' },
          { id: 1, name: 'Alpha' },
          { id: 2, name: 'beta' },
        ],
      },
      LIST_SECTIONS: { ok: true, data: [] },
      ...customResponses,
    };
    window.chrome = {
      runtime: {
        sendMessage: async (message) => {
          window.extensionMessages.push(message);
          return window.extensionResponses[message.type];
        },
        onMessage: {
          addListener(listener) {
            window.extensionMessageListener = listener;
          },
        },
      },
    };
  }, responses);
  await page.addScriptTag({ path: contentScript });
  await page.evaluate((source) => window.extensionMessageListener({
    type: 'OPEN_DIALOG',
    pageUrl: location.href,
    pageTitle: document.title,
    ...source,
  }), imageSource);
  await expect(page.locator('.sb-board-input')).toBeEnabled();
}

test('opens the full alphabetized board list with creation first', async ({ page }) => {
  await openExtensionDialog(page);
  await page.locator('.sb-board-input').click();

  await expect(page.locator('.sb-board-option')).toHaveText([
    '+ Create new board', 'Alpha', 'beta', 'zebra',
  ]);
});

test('filters boards case-insensitively while keeping creation first', async ({ page }) => {
  await openExtensionDialog(page);
  await page.locator('.sb-board-input').fill('BE');

  await expect(page.locator('.sb-board-option')).toHaveText([
    '+ Create new board', 'beta',
  ]);
});

test('scrolls a long board list without scrolling the dialog away from its field', async ({ page }) => {
  const boards = Array.from({ length: 40 }, (_, index) => ({
    id: index + 1,
    name: `Board ${String(index + 1).padStart(2, '0')}`,
  }));
  await openExtensionDialog(page, { LIST_BOARDS: { ok: true, data: boards } });
  await page.locator('.sb-board-input').click();
  const listbox = page.locator('.sb-board-picker .sb-listbox');
  await expect.poll(() => listbox.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  const before = await page.evaluate(() => document.getElementById('scrapbook-send-dialog-host').shadowRoot
    .querySelector('.sb-dialog').scrollTop);

  await listbox.hover();
  await page.mouse.wheel(0, 300);

  await expect.poll(() => listbox.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  await expect.poll(() => page.evaluate(() => document.getElementById('scrapbook-send-dialog-host').shadowRoot
    .querySelector('.sb-dialog').scrollTop)).toBe(before);
});

test('contains wheel scrolling inside the long board list at its edge', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 400 });
  const boards = Array.from({ length: 40 }, (_, index) => ({
    id: index + 1,
    name: `Board ${String(index + 1).padStart(2, '0')}`,
  }));
  await openExtensionDialog(page, { LIST_BOARDS: { ok: true, data: boards } });
  await page.locator('.sb-board-input').click();
  const listbox = page.locator('.sb-board-picker .sb-listbox');
  await listbox.hover();
  await listbox.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  const dialogScrollTop = await page.evaluate(() => document.getElementById('scrapbook-send-dialog-host').shadowRoot
    .querySelector('.sb-dialog').scrollTop);

  await page.mouse.wheel(0, 300);

  await expect.poll(() => page.evaluate(() => document.getElementById('scrapbook-send-dialog-host').shadowRoot
    .querySelector('.sb-dialog').scrollTop)).toBe(dialogScrollTop);
});

test('keeps long board results in the dialog flow instead of overlaying later fields', async ({ page }) => {
  const boards = Array.from({ length: 40 }, (_, index) => ({
    id: index + 1,
    name: `Board ${String(index + 1).padStart(2, '0')}`,
  }));
  await openExtensionDialog(page, { LIST_BOARDS: { ok: true, data: boards } });
  await page.locator('.sb-board-input').click();
  const listBox = await page.locator('.sb-board-picker .sb-listbox').boundingBox();
  const sectionPicker = await page.locator('.sb-section-picker').boundingBox();

  expect(sectionPicker.y).toBeGreaterThanOrEqual(listBox.y + listBox.height);
});

test('selects a board with the keyboard and closes without changing it', async ({ page }) => {
  await openExtensionDialog(page);
  const board = page.locator('.sb-board-input');
  await board.click();
  await board.press('ArrowDown');
  await board.press('ArrowDown');
  await board.press('Enter');

  await expect(board).toHaveValue('Alpha');
  await expect(board).toHaveAttribute('aria-expanded', 'false');
  await board.press('ArrowDown');
  await board.press('Escape');
  await expect(board).toHaveValue('Alpha');
});

test('editing a selected board clears its ID and disables save', async ({ page }) => {
  await openExtensionDialog(page, {}, { dataUrl: 'data:image/png;base64,AA==' });
  const board = page.locator('.sb-board-input');
  await board.click();
  await page.getByRole('option', { name: 'Alpha', exact: true }).click();
  const saveDisabled = () => page.evaluate(() => document
    .getElementById('scrapbook-send-dialog-host').shadowRoot
    .querySelector('.sb-save').disabled);
  await expect.poll(saveDisabled).toBe(false);

  await board.fill('Alph');
  await expect.poll(saveDisabled).toBe(true);
});

test('enables an alphabetized section picker only after selecting a board', async ({ page }) => {
  await openExtensionDialog(page, {
    LIST_SECTIONS: {
      ok: true,
      data: [{ id: 12, name: 'Winter' }, { id: 11, name: 'autumn' }],
    },
  });
  const section = page.locator('.sb-section-input');
  await expect(section).toBeDisabled();
  await expect(page.locator('.sb-create-row')).toBeHidden();

  await page.locator('.sb-board-input').click();
  await page.getByRole('option', { name: 'Alpha', exact: true }).click();
  await expect(section).toBeEnabled();
  await section.click();
  await expect(page.locator('.sb-section-option')).toHaveText([
    '+ Create new section', 'autumn', 'Winter',
  ]);
});

test('creates and selects a new board and section', async ({ page }) => {
  await openExtensionDialog(page, {
    CREATE_BOARD: { ok: true, data: { board_id: 4, name: 'Delta' } },
    CREATE_SECTION: {
      ok: true,
      data: { success: true, section: { id: 21, name: 'Ideas', board_id: 4 } },
    },
  });
  await page.locator('.sb-board-input').click();
  await page.getByRole('option', { name: '+ Create new board' }).click();
  await page.locator('.sb-create-name').fill('  Delta  ');
  await page.locator('.sb-create-submit').click();
  await expect(page.locator('.sb-board-input')).toHaveValue('Delta');
  await expect.poll(() => page.evaluate(() => window.extensionMessages
    .find((message) => message.type === 'CREATE_BOARD')))
    .toEqual({ type: 'CREATE_BOARD', name: 'Delta' });

  await page.locator('.sb-section-input').click();
  await page.getByRole('option', { name: '+ Create new section' }).click();
  await page.locator('.sb-create-name').fill('Ideas');
  await page.locator('.sb-create-name').press('Enter');
  await expect(page.locator('.sb-section-input')).toHaveValue('Ideas');
  await expect.poll(() => page.evaluate(() => window.extensionMessages
    .find((message) => message.type === 'CREATE_SECTION')))
    .toEqual({ type: 'CREATE_SECTION', boardId: '4', name: 'Ideas' });
});

test('submits selected board and section IDs', async ({ page }) => {
  await openExtensionDialog(page, {
    LIST_SECTIONS: { ok: true, data: [{ id: 21, name: 'Ideas' }] },
    ADD_PIN: { ok: true, baseUrl: 'https://scrappl.test', data: { pin_id: 99 } },
  }, { dataUrl: 'data:image/png;base64,AA==' });
  await page.locator('.sb-board-input').click();
  await page.getByRole('option', { name: 'Alpha', exact: true }).click();
  await page.locator('.sb-section-input').click();
  await page.getByRole('option', { name: 'Ideas', exact: true }).click();
  await page.evaluate(() => document.getElementById('scrapbook-send-dialog-host').shadowRoot
    .querySelector('.sb-save').click());

  await expect.poll(() => page.evaluate(() => window.extensionMessages
    .find((message) => message.type === 'ADD_PIN').payload))
    .toMatchObject({ board_id: '1', section_id: '21' });
});
