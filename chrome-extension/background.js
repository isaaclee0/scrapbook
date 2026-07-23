const MENU_ID = 'send-to-scrapbook';

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: 'Send to Scrappl',
    contexts: ['image'],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID || !tab || !tab.id) return;
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content.js'],
    });
    chrome.tabs.sendMessage(tab.id, {
      type: 'OPEN_DIALOG',
      srcUrl: info.srcUrl,
      pageUrl: tab.url,
      pageTitle: tab.title,
    });
  } catch (err) {
    console.error('[scrapbook] failed to inject content script', err);
  }
});

async function triggerRegionCapture(tab) {
  if (!tab || !tab.id) return;
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content.js'],
    });
    chrome.tabs.sendMessage(tab.id, {
      type: 'START_REGION_CAPTURE',
      pageUrl: tab.url,
      pageTitle: tab.title,
    });
  } catch (err) {
    console.error('[scrapbook] failed to start region capture', err);
  }
}

chrome.action.onClicked.addListener(triggerRegionCapture);

chrome.commands.onCommand.addListener((command, tab) => {
  if (command === 'capture-region') {
    triggerRegionCapture(tab);
  }
});

async function getConfig() {
  const { baseUrl, token } = await chrome.storage.local.get(['baseUrl', 'token']);
  return { baseUrl: (baseUrl || '').replace(/\/+$/, ''), token: token || '' };
}

async function apiFetch(path, options = {}) {
  const { baseUrl, token } = await getConfig();
  if (!baseUrl || !token) {
    return { ok: false, notConfigured: true };
  }
  let response;
  try {
    response = await fetch(baseUrl + path, {
      ...options,
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
    });
  } catch (err) {
    console.warn('[scrapbook] fetch failed', err);
    return { ok: false, networkError: true };
  }
  let data = null;
  try {
    data = await response.json();
  } catch (err) {
    console.warn('[scrapbook] non-JSON response', response.status, err);
    // non-JSON body, leave data null
  }
  return { ok: response.ok, status: response.status, data };
}

async function fetchImageAsDataUrl(url) {
  let response;
  try {
    response = await fetch(url, { credentials: 'include' });
  } catch (err) {
    console.warn('[scrapbook] image fetch failed', err);
    return { ok: false, networkError: true };
  }
  if (!response.ok) {
    return { ok: false, status: response.status };
  }
  const contentType = response.headers.get('Content-Type') || 'image/png';
  const buffer = await response.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
  }
  const base64 = btoa(binary);
  return { ok: true, dataUrl: `data:${contentType};base64,${base64}` };
}

async function captureAndCropRegion(rect) {
  let dataUrl;
  try {
    dataUrl = await chrome.tabs.captureVisibleTab({ format: 'png' });
  } catch (err) {
    console.warn('[scrapbook] captureVisibleTab failed', err);
    return { ok: false, captureError: true };
  }
  try {
    const captureResponse = await fetch(dataUrl);
    const captureBlob = await captureResponse.blob();
    const bitmap = await createImageBitmap(captureBlob);

    const scale = rect.devicePixelRatio || 1;
    const sx = Math.round(rect.x * scale);
    const sy = Math.round(rect.y * scale);
    const sw = Math.round(rect.width * scale);
    const sh = Math.round(rect.height * scale);

    const canvas = new OffscreenCanvas(sw, sh);
    const ctx = canvas.getContext('2d');
    ctx.drawImage(bitmap, sx, sy, sw, sh, 0, 0, sw, sh);

    const croppedBlob = await canvas.convertToBlob({ type: 'image/png' });
    const buffer = await croppedBlob.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = '';
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
    }
    const base64 = btoa(binary);
    return { ok: true, dataUrl: `data:image/png;base64,${base64}` };
  } catch (err) {
    console.warn('[scrapbook] region crop failed', err);
    return { ok: false, captureError: true };
  }
}

async function handleMessage(message) {
  switch (message.type) {
    case 'GET_CONFIG': {
      const { baseUrl, token } = await getConfig();
      return { ok: true, configured: Boolean(baseUrl && token) };
    }
    case 'LIST_BOARDS':
      return apiFetch('/api/boards');
    case 'LIST_SECTIONS':
      return apiFetch(`/get-sections/${message.boardId}`);
    case 'CREATE_BOARD':
      return apiFetch('/create-board', {
        method: 'POST',
        body: JSON.stringify({ name: message.name }),
      });
    case 'ADD_PIN': {
      const { baseUrl } = await getConfig();
      const result = await apiFetch('/add-pin', {
        method: 'POST',
        body: JSON.stringify(message.payload),
      });
      return { ...result, baseUrl };
    }
    case 'FETCH_IMAGE':
      return fetchImageAsDataUrl(message.srcUrl);
    case 'CAPTURE_REGION':
      return captureAndCropRegion(message.rect);
    default:
      return { ok: false, error: `Unknown message type: ${message.type}` };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message).then(sendResponse);
  return true; // keep the message channel open for the async response
});

chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  if (!sender.origin || !sender.url) {
    sendResponse({ ok: false, error: 'Missing sender origin' });
    return false;
  }
  if (typeof message !== 'object' || message === null) {
    sendResponse({ ok: false, error: 'Invalid message' });
    return false;
  }
  if (message.type !== 'CONNECT') {
    sendResponse({ ok: false, error: `Unknown message type: ${message.type}` });
    return false;
  }
  if (!message.baseUrl || !message.token) {
    sendResponse({ ok: false, error: 'baseUrl and token are required' });
    return false;
  }
  // Defense in depth beyond manifest-level externally_connectable scoping:
  // only accept a baseUrl that matches the origin the message actually came
  // from. This stops a page from asking us to store a DIFFERENT baseUrl
  // than the one it's actually serving from.
  let requestedOrigin;
  try {
    requestedOrigin = new URL(message.baseUrl).origin;
  } catch (err) {
    sendResponse({ ok: false, error: 'Invalid baseUrl' });
    return false;
  }
  if (requestedOrigin !== sender.origin) {
    console.warn('[scrapbook] rejected CONNECT: baseUrl origin does not match sender origin', requestedOrigin, sender.origin);
    sendResponse({ ok: false, error: 'baseUrl does not match sender origin' });
    return false;
  }
  chrome.storage.local.set({ baseUrl: message.baseUrl.replace(/\/+$/, ''), token: message.token }, () => {
    sendResponse({ ok: true });
  });
  return true; // keep the message channel open for the async storage.set callback
});
