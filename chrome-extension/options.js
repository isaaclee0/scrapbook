const baseUrlInput = document.getElementById('baseUrl');
const tokenInput = document.getElementById('token');
const statusEl = document.getElementById('status');

async function loadSaved() {
  const { baseUrl, token } = await chrome.storage.local.get(['baseUrl', 'token']);
  if (baseUrl) baseUrlInput.value = baseUrl;
  if (token) tokenInput.value = token;
}

document.getElementById('save').addEventListener('click', async () => {
  const baseUrl = baseUrlInput.value.trim().replace(/\/+$/, '');
  const token = tokenInput.value.trim();
  await chrome.storage.local.set({ baseUrl, token });
  statusEl.textContent = 'Saved.';
  setTimeout(() => { statusEl.textContent = ''; }, 2000);
});

loadSaved();
