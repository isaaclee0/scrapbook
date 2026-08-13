const MENU_ID = 'send-to-scrapbook';
const DEFAULT_BASE_URL = 'https://scrappl.com';

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: 'Send to Scrappl',
    contexts: ['image'],
  });
});

async function getConfig() {
  const { baseUrl } = await chrome.storage.local.get(['baseUrl']);
  try {
    return { baseUrl: new URL((baseUrl || DEFAULT_BASE_URL).trim()).origin };
  } catch (error) {
    return { baseUrl: DEFAULT_BASE_URL };
  }
}

function isImageDataUrl(value) {
  return typeof value === 'string' && /^data:image\/[a-z0-9.+-]+;base64,/i.test(value);
}

function newNonce() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function openScrapplHandoff({ dataUrl, pageUrl, pageTitle }) {
  if (!isImageDataUrl(dataUrl)) return { ok: false, error: 'Invalid image data' };

  const { baseUrl } = await getConfig();
  const nonce = newNonce();
  const tab = await chrome.tabs.create({
    url: `${baseUrl}/#scrappl-handoff=${nonce}`,
    active: true,
  });
  const expectedOrigin = new URL(baseUrl).origin;

  const onUpdated = async (tabId, changeInfo, updatedTab) => {
    if (tabId !== tab.id || changeInfo.status !== 'complete') return;
    const currentUrl = (updatedTab && updatedTab.url) || tab.url;
    if (!currentUrl || new URL(currentUrl).origin !== expectedOrigin) {
      chrome.tabs.onUpdated.removeListener(onUpdated);
      return;
    }
    chrome.tabs.onUpdated.removeListener(onUpdated);
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (handoff) => window.postMessage({ type: 'SCRAPPL_EXTENSION_HANDOFF', ...handoff }, window.location.origin),
        args: [{
          nonce,
          imageDataUrl: dataUrl,
          sourceUrl: pageUrl || '',
          title: pageTitle || '',
        }],
      });
    } catch (error) {
      console.warn('[scrappl] failed to deliver handoff', error);
    }
  };
  chrome.tabs.onUpdated.addListener(onUpdated);
  return { ok: true };
}

async function fetchImageAsDataUrl(url) {
  try {
    const response = await fetch(url, { credentials: 'include' });
    if (!response.ok) return { ok: false, status: response.status };
    const contentType = response.headers.get('Content-Type') || 'image/png';
    const buffer = await response.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = '';
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
    }
    return { ok: true, dataUrl: `data:${contentType};base64,${btoa(binary)}` };
  } catch (error) {
    console.warn('[scrappl] image fetch failed', error);
    return { ok: false, networkError: true };
  }
}

async function captureAndCropRegion(rect) {
  let dataUrl;
  try {
    dataUrl = await chrome.tabs.captureVisibleTab({ format: 'png' });
    const captureBlob = await (await fetch(dataUrl)).blob();
    const bitmap = await createImageBitmap(captureBlob);
    const scale = rect.devicePixelRatio || 1;
    const canvas = new OffscreenCanvas(Math.round(rect.width * scale), Math.round(rect.height * scale));
    const ctx = canvas.getContext('2d');
    ctx.drawImage(bitmap, Math.round(rect.x * scale), Math.round(rect.y * scale),
      Math.round(rect.width * scale), Math.round(rect.height * scale), 0, 0,
      Math.round(rect.width * scale), Math.round(rect.height * scale));
    const bytes = new Uint8Array(await (await canvas.convertToBlob({ type: 'image/png' })).arrayBuffer());
    let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return { ok: true, dataUrl: `data:image/png;base64,${btoa(binary)}` };
  } catch (error) {
    console.warn('[scrappl] region crop failed', error);
    return { ok: false, captureError: true };
  }
}

async function injectRegionCapture(tab) {
  if (!tab || !tab.id) return;
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content.js'] });
    chrome.tabs.sendMessage(tab.id, { type: 'START_REGION_CAPTURE', pageUrl: tab.url, pageTitle: tab.title });
  } catch (error) {
    console.error('[scrappl] failed to start region capture', error);
  }
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID || !tab || !tab.id) return;
  const image = await fetchImageAsDataUrl(info.srcUrl);
  if (image.ok) await openScrapplHandoff({ dataUrl: image.dataUrl, pageUrl: tab.url, pageTitle: tab.title });
});

chrome.action.onClicked.addListener(injectRegionCapture);
chrome.commands.onCommand.addListener((command, tab) => {
  if (command === 'capture-region') injectRegionCapture(tab);
});

async function handleMessage(message) {
  switch (message.type) {
    case 'GET_CONFIG': return { ok: true, ...(await getConfig()) };
    case 'OPEN_HANDOFF': return openScrapplHandoff(message);
    case 'FETCH_IMAGE': return fetchImageAsDataUrl(message.srcUrl);
    case 'CAPTURE_REGION': return captureAndCropRegion(message.rect);
    default: return { ok: false, error: `Unknown message type: ${message.type}` };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message).then(sendResponse);
  return true;
});
