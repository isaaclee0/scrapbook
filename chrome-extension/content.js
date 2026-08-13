(function () {
  if (window.__scrapplRegionSelectionInjected) return;
  window.__scrapplRegionSelectionInjected = true;

  let selectRoot = null;

  function sendToBackground(message) {
    return chrome.runtime.sendMessage(message);
  }

  function closeSelection() {
    if (selectRoot) {
      selectRoot.remove();
      selectRoot = null;
    }
  }

  const SELECT_HTML = `
    <div class="rs-overlay">
      <div class="rs-hint">Click and drag to select an area · Esc to cancel</div>
      <div class="rs-box"></div>
      <div class="rs-controls">
        <button type="button" class="rs-use">Use this ✓</button>
        <button type="button" class="rs-redo">Redo</button>
        <button type="button" class="rs-cancel">Cancel</button>
      </div>
      <div class="rs-error" role="alert"></div>
    </div>`;

  const SELECT_CSS = `
    .rs-overlay { position: fixed; inset: 0; cursor: crosshair; background: rgba(0,0,0,.15); }
    .rs-hint { position: fixed; top: 16px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,.75); color: #fff; padding: 8px 16px; border-radius: 6px; font: 13px -apple-system, BlinkMacSystemFont, sans-serif; pointer-events: none; }
    .rs-box { position: fixed; display: none; border: 2px dashed #3b82f6; background: rgba(59,130,246,.12); box-sizing: border-box; }
    .rs-controls { position: fixed; display: none; gap: 6px; font: 13px -apple-system, BlinkMacSystemFont, sans-serif; }
    .rs-controls button { padding: 6px 12px; border: 0; border-radius: 6px; cursor: pointer; }
    .rs-use { background: #2980b9; color: #fff; } .rs-redo, .rs-cancel { background: #f5f5f5; color: #333; }
    .rs-error { position: fixed; top: 52px; left: 50%; transform: translateX(-50%); color: #fff; background: #b91c1c; border-radius: 6px; padding: 8px 12px; display: none; font: 13px -apple-system, BlinkMacSystemFont, sans-serif; }
  `;

  function startRegionSelection(pageUrl, pageTitle) {
    closeSelection();
    selectRoot = document.createElement('div');
    selectRoot.id = 'scrapbook-region-select-host';
    selectRoot.style.cssText = 'position:fixed;inset:0;z-index:2147483647';
    document.body.appendChild(selectRoot);
    const shadow = selectRoot.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = SELECT_CSS;
    shadow.append(style);
    const wrapper = document.createElement('div');
    wrapper.innerHTML = SELECT_HTML;
    shadow.append(wrapper.firstElementChild);

    const overlay = shadow.querySelector('.rs-overlay');
    const box = shadow.querySelector('.rs-box');
    const controls = shadow.querySelector('.rs-controls');
    const error = shadow.querySelector('.rs-error');
    let startX; let startY; let dragging = false; let rect = null;
    const cleanup = () => { document.removeEventListener('keydown', onKeyDown, true); closeSelection(); };
    const onKeyDown = (event) => { if (event.key === 'Escape') { event.preventDefault(); cleanup(); } };
    const updateBox = (x, y) => {
      const left = Math.min(startX, x); const top = Math.min(startY, y);
      rect = { x: left, y: top, width: Math.abs(x - startX), height: Math.abs(y - startY) };
      Object.assign(box.style, { display: 'block', left: `${rect.x}px`, top: `${rect.y}px`, width: `${rect.width}px`, height: `${rect.height}px` });
    };
    overlay.addEventListener('mousedown', (event) => {
      if (event.button !== 0) return;
      dragging = true; startX = event.clientX; startY = event.clientY; controls.style.display = 'none'; error.style.display = 'none'; updateBox(startX, startY);
    });
    overlay.addEventListener('mousemove', (event) => { if (dragging) updateBox(event.clientX, event.clientY); });
    overlay.addEventListener('mouseup', (event) => {
      if (!dragging) return;
      dragging = false; updateBox(event.clientX, event.clientY);
      if (rect.width < 4 || rect.height < 4) { box.style.display = 'none'; rect = null; return; }
      Object.assign(controls.style, { display: 'flex', left: `${rect.x}px`, top: `${Math.min(rect.y + rect.height + 8, window.innerHeight - 40)}px` });
    });
    shadow.querySelector('.rs-cancel').addEventListener('click', cleanup);
    shadow.querySelector('.rs-redo').addEventListener('click', () => { box.style.display = 'none'; controls.style.display = 'none'; rect = null; });
    controls.addEventListener('mousedown', (event) => event.stopPropagation());
    shadow.querySelector('.rs-use').addEventListener('click', async () => {
      if (!rect) return;
      controls.style.display = 'none';
      const crop = await sendToBackground({ type: 'CAPTURE_REGION', rect: { ...rect, devicePixelRatio: window.devicePixelRatio || 1 } });
      const handoff = crop.ok && await sendToBackground({ type: 'OPEN_HANDOFF', dataUrl: crop.dataUrl, pageUrl, pageTitle });
      if (handoff && handoff.ok) cleanup();
      else { error.textContent = 'Could not send this capture to Scrappl.'; error.style.display = 'block'; controls.style.display = 'flex'; }
    });
    document.addEventListener('keydown', onKeyDown, true);
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === 'START_REGION_CAPTURE') startRegionSelection(message.pageUrl, message.pageTitle);
  });
})();
