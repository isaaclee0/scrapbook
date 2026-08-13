const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function loadBackground(storage = {}) {
  let messageHandler;
  let tabUpdateHandler;
  const createdTabs = [];
  const injected = [];
  let nextTabId = 10;
  const chrome = {
    contextMenus: { create() {}, onClicked: { addListener() {} } },
    action: { onClicked: { addListener() {} } },
    commands: { onCommand: { addListener() {} } },
    runtime: {
      onInstalled: { addListener() {} },
      onMessage: { addListener(handler) { messageHandler = handler; } },
      onMessageExternal: { addListener() {} },
      sendMessage() {},
    },
    storage: { local: { async get() { return storage; } } },
    tabs: {
      async create(options) {
        const tab = { id: nextTabId++, ...options };
        createdTabs.push(tab);
        return tab;
      },
      onUpdated: {
        addListener(handler) { tabUpdateHandler = handler; },
        removeListener(handler) { if (tabUpdateHandler === handler) tabUpdateHandler = undefined; },
      },
    },
    scripting: { async executeScript(options) { injected.push(options); } },
  };
  const source = fs.readFileSync(path.join(__dirname, '../../chrome-extension/background.js'), 'utf8');
  vm.runInNewContext(source, {
    chrome,
    console,
    URL,
    Uint8Array,
    crypto: { getRandomValues(bytes) { bytes.fill(1); return bytes; } },
    fetch: async () => { throw new Error('not used'); },
    OffscreenCanvas: class {},
    createImageBitmap: async () => ({}),
    btoa: (value) => Buffer.from(value, 'binary').toString('base64'),
  });
  return {
    call(message) {
      return new Promise((resolve) => messageHandler(message, {}, resolve));
    },
    createdTabs,
    injected,
    tabUpdated(tabId, changeInfo, tab) {
      return tabUpdateHandler(tabId, changeInfo, tab);
    },
  };
}

test('opens the default Scrappl tab and injects an image handoff', async () => {
  const subject = loadBackground();
  const config = await subject.call({ type: 'GET_CONFIG' });
  assert.equal(config.ok, true);
  assert.equal(config.baseUrl, 'https://scrappl.com');

  const response = await subject.call({
    type: 'OPEN_HANDOFF',
    dataUrl: 'data:image/png;base64,AA==',
    pageUrl: 'https://source.test/p',
    pageTitle: 'Source',
  });
  assert.equal(response.ok, true);
  assert.match(subject.createdTabs[0].url, /^https:\/\/scrappl\.com\/#scrappl-handoff=/);

  await subject.tabUpdated(subject.createdTabs[0].id, { status: 'complete' }, subject.createdTabs[0]);
  assert.equal(subject.injected[0].args[0].imageDataUrl, 'data:image/png;base64,AA==');
  assert.equal(subject.injected[0].args[0].sourceUrl, 'https://source.test/p');
});

test('uses a normalized development override and refuses non-image handoffs', async () => {
  const subject = loadBackground({ baseUrl: 'http://localhost:8000/' });
  const config = await subject.call({ type: 'GET_CONFIG' });
  assert.equal(config.ok, true);
  assert.equal(config.baseUrl, 'http://localhost:8000');
  const response = await subject.call({ type: 'OPEN_HANDOFF', dataUrl: 'data:text/plain;base64,QQ==' });
  assert.equal(response.ok, false);
  assert.equal(response.error, 'Invalid image data');
  assert.equal(subject.createdTabs.length, 0);
});
