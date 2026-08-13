const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function loadOptions() {
  const elements = new Map();
  for (const id of ['baseUrl', 'save', 'reset', 'status']) {
    elements.set(id, { value: '', textContent: '', addEventListener() {} });
  }
  const context = {
    URL,
    setTimeout,
    document: { getElementById(id) { return elements.get(id); } },
    chrome: { storage: { local: { get: async () => ({}), set: async () => {}, remove: async () => {} } } },
  };
  context.window = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../chrome-extension/options.js'), 'utf8'), context);
  return context;
}

test('normalizes the production default and local development URL', () => {
  const { normalizeBaseUrl } = loadOptions();
  assert.equal(normalizeBaseUrl(''), 'https://scrappl.com');
  assert.equal(normalizeBaseUrl('http://localhost:8000/'), 'http://localhost:8000');
  assert.equal(normalizeBaseUrl('not a url'), 'https://scrappl.com');
});
