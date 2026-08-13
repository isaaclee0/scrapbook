const DEFAULT_BASE_URL = 'https://scrappl.com';
const baseUrlInput = document.getElementById('baseUrl');
const statusEl = document.getElementById('status');

function normalizeBaseUrl(value) {
  if (!value || !value.trim()) return DEFAULT_BASE_URL;
  try {
    return new URL(value.trim()).origin;
  } catch (error) {
    return DEFAULT_BASE_URL;
  }
}

async function loadSaved() {
  const { baseUrl } = await chrome.storage.local.get(['baseUrl']);
  baseUrlInput.value = baseUrl || '';
}

document.getElementById('save').addEventListener('click', async () => {
  const baseUrl = normalizeBaseUrl(baseUrlInput.value);
  if (baseUrl === DEFAULT_BASE_URL) {
    await chrome.storage.local.remove('baseUrl');
    baseUrlInput.value = '';
  } else {
    await chrome.storage.local.set({ baseUrl });
    baseUrlInput.value = baseUrl;
  }
  statusEl.textContent = `Next capture will open ${baseUrl}.`;
});

document.getElementById('reset').addEventListener('click', async () => {
  await chrome.storage.local.remove('baseUrl');
  baseUrlInput.value = '';
  statusEl.textContent = 'Next capture will open https://scrappl.com.';
});

window.normalizeBaseUrl = normalizeBaseUrl;
loadSaved();
