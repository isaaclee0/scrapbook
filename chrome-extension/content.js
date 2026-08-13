(function () {
  if (window.__scrapbookDialogInjected) return;
  window.__scrapbookDialogInjected = true;

  let root = null;
  let selectRoot = null;
  let dialogCleanup = null;

  function closeDialog() {
    if (root) {
      if (dialogCleanup) dialogCleanup();
      dialogCleanup = null;
      root.remove();
      root = null;
    }
  }

  function closeSelection() {
    if (selectRoot) {
      selectRoot.remove();
      selectRoot = null;
    }
  }

  function fetchImageAsDataUrl(url) {
    return sendToBackground({ type: 'FETCH_IMAGE', srcUrl: url }).then((res) => {
      if (!res.ok) throw new Error('Image fetch failed');
      return res.dataUrl;
    });
  }

  function sendToBackground(message) {
    return chrome.runtime.sendMessage(message);
  }

  function describeError(res) {
    if (res.notConfigured) return 'Not connected — open the extension options to add your Scrappl URL and token.';
    if (res.networkError) return 'Could not reach your Scrappl instance.';
    if (res.status === 401) return "Your Scrappl token isn't valid — check the extension options.";
    return (res.data && res.data.error) || 'Something went wrong.';
  }

  const DIALOG_HTML = `
    <div class="sb-backdrop">
      <div class="sb-dialog">
        <div class="sb-header">
          <h2>Send to Scrappl</h2>
          <button type="button" class="sb-close" aria-label="Close">&times;</button>
        </div>
        <div class="sb-body">
          <div class="sb-preview-wrap">
            <img class="sb-preview" style="display:none;">
            <div class="sb-preview-status">Loading image...</div>
          </div>
          <div class="sb-field">
            <label>Title</label>
            <input type="text" class="sb-title" placeholder="Enter a title...">
          </div>
          <div class="sb-field">
            <label>Board</label>
            <div class="sb-board-picker"></div>
          </div>
          <div class="sb-field">
            <label>Section (optional)</label>
            <div class="sb-section-picker"></div>
          </div>
          <div class="sb-field sb-create-row" hidden>
            <input type="text" class="sb-create-name">
            <button type="button" class="sb-create-submit">Create</button>
            <button type="button" class="sb-create-cancel">Cancel</button>
          </div>
          <div class="sb-field">
            <label>Notes</label>
            <textarea class="sb-notes" placeholder="Add notes..."></textarea>
          </div>
          <div class="sb-status"></div>
        </div>
        <div class="sb-footer">
          <button type="button" class="sb-cancel">Cancel</button>
          <button type="button" class="sb-save" disabled>Save</button>
        </div>
      </div>
    </div>
  `;

  const DIALOG_CSS = `
    .sb-backdrop {
      position: fixed; inset: 0; background: rgba(0,0,0,0.5);
      display: flex; align-items: center; justify-content: center;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .sb-dialog {
      background: white; border-radius: 12px; width: 360px; max-height: 90vh;
      overflow-y: auto; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .sb-header {
      padding: 16px 20px; border-bottom: 1px solid #eee;
      display: flex; justify-content: space-between; align-items: center;
    }
    .sb-header h2 { font-size: 16px; margin: 0; color: #222; }
    .sb-close { background: none; border: none; font-size: 22px; cursor: pointer; color: #666; line-height: 1; }
    .sb-body { padding: 16px 20px; }
    .sb-preview-wrap { margin-bottom: 14px; text-align: center; }
    .sb-preview { max-width: 100%; max-height: 220px; border-radius: 4px; }
    .sb-preview-status { font-size: 12px; color: #666; padding: 20px 0; }
    .sb-field { margin-bottom: 12px; }
    .sb-field label { display: block; margin-bottom: 4px; color: #333; font-size: 12px; font-weight: 600; }
    .sb-field input, .sb-field textarea {
      width: 100%; padding: 10px; border: 2px solid #e1e5e9; border-radius: 8px;
      font-size: 13px; box-sizing: border-box; font-family: inherit;
    }
    .sb-field input:focus, .sb-field textarea:focus {
      outline: none; border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59,130,246,0.1);
    }
    .sb-field textarea { min-height: 60px; resize: vertical; }
    .sb-combobox { position: relative; }
    .sb-combobox-input { width: 100%; padding: 10px; border: 2px solid #e1e5e9; border-radius: 8px; font: inherit; font-size: 13px; box-sizing: border-box; }
    .sb-combobox-input:focus { outline: none; border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59,130,246,0.1); }
    .sb-listbox { position: absolute; z-index: 1; width: 100%; max-height: 180px; overflow-y: auto; margin-top: 4px; padding: 4px; box-sizing: border-box; background: white; border: 1px solid #d7dce1; border-radius: 8px; box-shadow: 0 6px 18px rgba(0,0,0,0.15); }
    .sb-option { width: 100%; padding: 8px 10px; text-align: left; border: 0; border-radius: 5px; background: transparent; color: #222; font: inherit; font-size: 13px; cursor: pointer; }
    .sb-option:hover, .sb-option.sb-option-active { background: #eaf4fb; }
    .sb-option-create { color: #2472a4; font-weight: 600; }
    .sb-listbox-empty { padding: 8px 10px; color: #666; font-size: 13px; }
    .sb-create-row { display: flex; gap: 8px; align-items: center; }
    .sb-create-row input { flex: 1; }
    .sb-create-row button {
      padding: 8px 12px; border-radius: 6px; border: none; background: #3b82f6; color: white; cursor: pointer; font-size: 13px;
    }
    .sb-create-cancel { background: #f5f5f5 !important; border: 1px solid #ddd !important; color: #333 !important; }
    .sb-status { font-size: 12px; min-height: 16px; margin-top: 4px; }
    .sb-status-error { color: #e74c3c; }
    .sb-status-success { color: #16a34a; }
    .sb-footer {
      padding: 14px 20px; border-top: 1px solid #eee;
      display: flex; justify-content: flex-end; gap: 8px;
    }
    .sb-footer button { padding: 8px 16px; border-radius: 4px; cursor: pointer; font-size: 13px; border: none; }
    .sb-cancel { background: #f5f5f5; border: 1px solid #ddd; color: #333; }
    .sb-save { background: #2980b9; color: white; }
    .sb-save:hover:not(:disabled) { background: #2472a4; }
    .sb-save:disabled { background: #ccc; cursor: not-allowed; }
  `;

  const SELECT_HTML = `
    <div class="rs-overlay">
      <div class="rs-hint">Click and drag to select an area · Esc to cancel</div>
      <div class="rs-box"></div>
      <div class="rs-controls">
        <button type="button" class="rs-use">Use this ✓</button>
        <button type="button" class="rs-redo">Redo</button>
        <button type="button" class="rs-cancel">Cancel</button>
      </div>
    </div>
  `;

  const SELECT_CSS = `
    .rs-overlay {
      position: fixed; inset: 0; cursor: crosshair;
      background: rgba(0,0,0,0.15);
    }
    .rs-hint {
      position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
      background: rgba(0,0,0,0.75); color: white; padding: 8px 16px;
      border-radius: 6px; font-size: 13px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      pointer-events: none;
    }
    .rs-box {
      position: fixed; border: 2px dashed #3b82f6; background: rgba(59,130,246,0.12);
      box-sizing: border-box; display: none;
    }
    .rs-controls {
      position: fixed; display: none; gap: 6px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .rs-controls button {
      padding: 6px 12px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px;
    }
    .rs-use { background: #2980b9; color: white; }
    .rs-redo { background: #f5f5f5; border: 1px solid #ddd; color: #333; }
    .rs-cancel { background: #f5f5f5; border: 1px solid #ddd; color: #333; }
  `;

  function createCombobox({ root: pickerRoot, kind, placeholder, createLabel, onSelect, onCreate }) {
    const input = document.createElement('input');
    const listbox = document.createElement('div');
    const listboxId = `sb-${kind}-listbox`;
    let items = [];
    let activeIndex = -1;
    let open = false;
    let selectedId = null;
    let disabled = false;

    input.type = 'text';
    input.className = `sb-combobox-input sb-${kind}-input`;
    input.placeholder = placeholder;
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', listboxId);
    listbox.id = listboxId;
    listbox.className = 'sb-listbox';
    listbox.setAttribute('role', 'listbox');
    listbox.hidden = true;
    pickerRoot.append(input, listbox);

    const sortedItems = (nextItems) => [...(nextItems || [])]
      .map((item) => ({ id: String(item.id), name: String(item.name) }))
      .sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: 'base' }));

    function visibleItems() {
      const query = input.value.trim().toLocaleLowerCase();
      return items.filter((item) => item.name.toLocaleLowerCase().includes(query));
    }

    function options() {
      return [{ id: '__create__', name: createLabel, create: true }, ...visibleItems()];
    }

    function render() {
      const choices = options();
      listbox.innerHTML = '';
      choices.forEach((choice, index) => {
        const option = document.createElement('button');
        option.type = 'button';
        option.id = `${listboxId}-${index}`;
        option.className = `sb-option sb-${kind}-option${choice.create ? ' sb-option-create' : ''}${index === activeIndex ? ' sb-option-active' : ''}`;
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', String(choice.id === selectedId));
        option.textContent = choice.name;
        option.addEventListener('mousedown', (event) => event.preventDefault());
        option.addEventListener('click', () => choose(choice));
        listbox.appendChild(option);
      });
      if (choices.length === 1 && !choices[0].create) {
        listbox.innerHTML = '<div class="sb-listbox-empty">No matches</div>';
      }
      input.setAttribute('aria-activedescendant', activeIndex >= 0 ? `${listboxId}-${activeIndex}` : '');
    }

    function setOpen(nextOpen) {
      const wasOpen = open;
      open = Boolean(nextOpen && !disabled);
      listbox.hidden = !open;
      input.setAttribute('aria-expanded', String(open));
      if (open) {
        if (!wasOpen) activeIndex = -1;
        render();
      }
    }

    function choose(choice) {
      if (choice.create) {
        setOpen(false);
        onCreate();
        return;
      }
      selectedId = choice.id;
      input.value = choice.name;
      setOpen(false);
      onSelect(choice);
    }

    input.addEventListener('focus', () => setOpen(true));
    input.addEventListener('click', () => setOpen(true));
    input.addEventListener('input', () => {
      if (selectedId !== null) {
        selectedId = null;
        onSelect(null);
      }
      setOpen(true);
    });
    input.addEventListener('keydown', (event) => {
      const choices = options();
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        setOpen(true);
        activeIndex = event.key === 'ArrowDown'
          ? Math.min(activeIndex + 1, choices.length - 1)
          : Math.max(activeIndex - 1, 0);
        render();
      } else if (event.key === 'Enter' && open && activeIndex >= 0) {
        event.preventDefault();
        choose(choices[activeIndex]);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
      }
    });
    const onOutsidePointerDown = (event) => {
      if (!event.composedPath().includes(pickerRoot)) setOpen(false);
    };
    document.addEventListener('pointerdown', onOutsidePointerDown, true);

    return {
      input,
      setItems(nextItems) { items = sortedItems(nextItems); render(); },
      setDisabled(nextDisabled, nextPlaceholder) {
        disabled = Boolean(nextDisabled);
        input.disabled = disabled;
        if (nextPlaceholder) input.placeholder = nextPlaceholder;
        if (disabled) setOpen(false);
      },
      setLoading(label) { this.setDisabled(true, label); },
      selectById(id) {
        const item = items.find((candidate) => candidate.id === String(id));
        if (item) {
          selectedId = item.id;
          input.value = item.name;
          render();
        }
      },
      clear() {
        selectedId = null;
        input.value = '';
        render();
      },
      focus() { input.focus(); },
      destroy() { document.removeEventListener('pointerdown', onOutsidePointerDown, true); },
    };
  }

  function openDialog(imageSource, pageUrl, pageTitle) {
    closeDialog();
    closeSelection();

    root = document.createElement('div');
    root.id = 'scrapbook-send-dialog-host';
    root.style.position = 'fixed';
    root.style.inset = '0';
    root.style.zIndex = '2147483647';
    document.body.appendChild(root);

    const shadow = root.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = DIALOG_CSS;
    shadow.appendChild(style);
    const wrapper = document.createElement('div');
    wrapper.innerHTML = DIALOG_HTML;
    shadow.appendChild(wrapper.firstElementChild);

    const els = {
      backdrop: shadow.querySelector('.sb-backdrop'),
      close: shadow.querySelector('.sb-close'),
      cancel: shadow.querySelector('.sb-cancel'),
      save: shadow.querySelector('.sb-save'),
      preview: shadow.querySelector('.sb-preview'),
      previewStatus: shadow.querySelector('.sb-preview-status'),
      title: shadow.querySelector('.sb-title'),
      boardPickerRoot: shadow.querySelector('.sb-board-picker'),
      sectionPickerRoot: shadow.querySelector('.sb-section-picker'),
      createRow: shadow.querySelector('.sb-create-row'),
      createName: shadow.querySelector('.sb-create-name'),
      createSubmit: shadow.querySelector('.sb-create-submit'),
      createCancel: shadow.querySelector('.sb-create-cancel'),
      notes: shadow.querySelector('.sb-notes'),
      status: shadow.querySelector('.sb-status'),
    };

    els.close.addEventListener('click', closeDialog);
    els.cancel.addEventListener('click', closeDialog);
    els.backdrop.addEventListener('click', (e) => {
      if (e.target === els.backdrop) closeDialog();
    });

    const state = { imageDataUrl: null, boardId: null, sectionId: null };

    function updateSaveEnabled() {
      els.save.disabled = !(state.imageDataUrl && els.title.value.trim() && state.boardId);
    }
    els.title.addEventListener('input', updateSaveEnabled);

    if (imageSource.srcUrl) {
      const matchedImg = Array.from(document.images).find(
        (img) => img.src === imageSource.srcUrl || img.currentSrc === imageSource.srcUrl
      );
      els.title.value = (matchedImg && matchedImg.alt) || pageTitle || '';

      fetchImageAsDataUrl(imageSource.srcUrl)
        .then((dataUrl) => {
          state.imageDataUrl = dataUrl;
          els.preview.src = dataUrl;
          els.preview.style.display = 'block';
          els.previewStatus.textContent = '';
          updateSaveEnabled();
        })
        .catch(() => {
          els.previewStatus.textContent = 'Could not load this image.';
        });
    } else {
      els.title.value = pageTitle || '';
      if (imageSource.dataUrl) {
        state.imageDataUrl = imageSource.dataUrl;
        els.preview.src = imageSource.dataUrl;
        els.preview.style.display = 'block';
        els.previewStatus.textContent = '';
        updateSaveEnabled();
      } else {
        els.previewStatus.textContent = 'Could not capture this region.';
      }
    }

    function setError(res) {
      els.status.textContent = describeError(res);
      els.status.className = 'sb-status sb-status-error';
    }

    let boardItems = [];
    let sectionItems = [];
    let creatingKind = null;
    let creationPicker = null;
    let boardPicker;
    let sectionPicker;

    function hideCreateRow() {
      els.createRow.hidden = true;
      creatingKind = null;
      els.createName.value = '';
    }

    function showCreateRow(kind) {
      creatingKind = kind;
      creationPicker = kind === 'board' ? boardPicker : sectionPicker;
      els.createName.placeholder = `New ${kind} name`;
      els.createName.value = '';
      els.createRow.hidden = false;
      els.createName.focus();
    }

    async function selectBoard(item) {
      state.boardId = item ? item.id : null;
      state.sectionId = null;
      sectionItems = [];
      sectionPicker.clear();
      updateSaveEnabled();
      if (!item) {
        sectionPicker.setItems([]);
        sectionPicker.setDisabled(true, 'Select a board first');
        return;
      }
      const requestedBoardId = item.id;
      sectionPicker.setItems([]);
      sectionPicker.setLoading('Loading sections...');
      const res = await sendToBackground({ type: 'LIST_SECTIONS', boardId: requestedBoardId });
      if (state.boardId !== requestedBoardId) return;
      sectionPicker.setDisabled(false, 'Select or search sections...');
      if (!res.ok) {
        setError(res);
        return;
      }
      sectionItems = res.data || [];
      sectionPicker.setItems(sectionItems);
    }

    boardPicker = createCombobox({
      root: els.boardPickerRoot,
      kind: 'board',
      placeholder: 'Select or search boards...',
      createLabel: '+ Create new board',
      onSelect: selectBoard,
      onCreate: () => showCreateRow('board'),
    });
    sectionPicker = createCombobox({
      root: els.sectionPickerRoot,
      kind: 'section',
      placeholder: 'Select or search sections...',
      createLabel: '+ Create new section',
      onSelect: (item) => { state.sectionId = item ? item.id : null; },
      onCreate: () => showCreateRow('section'),
    });
    sectionPicker.setDisabled(true, 'Select a board first');
    dialogCleanup = () => {
      boardPicker.destroy();
      sectionPicker.destroy();
    };

    async function loadBoards() {
      boardPicker.setLoading('Loading boards...');
      const res = await sendToBackground({ type: 'LIST_BOARDS' });
      if (!res.ok) {
        setError(res);
        boardPicker.setDisabled(false, 'Select or search boards...');
        return;
      }
      boardItems = res.data || [];
      boardPicker.setItems(boardItems);
      boardPicker.setDisabled(false, 'Select or search boards...');
    }

    els.createCancel.addEventListener('click', () => {
      hideCreateRow();
      creationPicker.focus();
    });
    els.createName.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        hideCreateRow();
        creationPicker.focus();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        els.createSubmit.click();
      }
    });
    els.createSubmit.addEventListener('click', async () => {
      const name = els.createName.value.trim();
      if (!name || !creatingKind) return;
      els.createSubmit.disabled = true;
      const isBoard = creatingKind === 'board';
      const res = await sendToBackground(isBoard
        ? { type: 'CREATE_BOARD', name }
        : { type: 'CREATE_SECTION', boardId: state.boardId, name });
      els.createSubmit.disabled = false;
      if (!res.ok) {
        setError(res);
        return;
      }
      if (isBoard) {
        const board = { id: res.data.board_id, name: res.data.name };
        boardItems = [...boardItems, board];
        boardPicker.setItems(boardItems);
        boardPicker.selectById(board.id);
        hideCreateRow();
        await selectBoard({ id: String(board.id), name: board.name });
      } else {
        const section = res.data.section;
        sectionItems = [...sectionItems, section];
        sectionPicker.setItems(sectionItems);
        sectionPicker.selectById(section.id);
        state.sectionId = String(section.id);
        hideCreateRow();
      }
    });

    els.save.addEventListener('click', async () => {
      els.save.disabled = true;
      els.status.textContent = 'Saving...';
      els.status.className = 'sb-status';
      const res = await sendToBackground({
        type: 'ADD_PIN',
        payload: {
          title: els.title.value.trim(),
          board_id: state.boardId,
          section_id: state.sectionId,
          notes: els.notes.value.trim(),
          image_url: state.imageDataUrl,
          source_url: pageUrl,
        },
      });
      if (!res.ok) {
        setError(res);
        updateSaveEnabled();
        return;
      }
      els.status.innerHTML = '';
      els.status.className = 'sb-status sb-status-success';
      const successText = document.createElement('span');
      successText.textContent = 'Saved! ';
      const link = document.createElement('a');
      link.href = `${res.baseUrl}/pin/${res.data.pin_id}`;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'View pin';
      link.style.color = '#2980b9';
      els.status.appendChild(successText);
      els.status.appendChild(link);
      setTimeout(closeDialog, 2500);
    });

    loadBoards();
  }

  function startRegionSelection(pageUrl, pageTitle) {
    closeDialog();
    closeSelection();

    selectRoot = document.createElement('div');
    selectRoot.id = 'scrapbook-region-select-host';
    selectRoot.style.position = 'fixed';
    selectRoot.style.inset = '0';
    selectRoot.style.zIndex = '2147483647';
    document.body.appendChild(selectRoot);

    const shadow = selectRoot.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = SELECT_CSS;
    shadow.appendChild(style);
    const wrapper = document.createElement('div');
    wrapper.innerHTML = SELECT_HTML;
    shadow.appendChild(wrapper.firstElementChild);

    const overlay = shadow.querySelector('.rs-overlay');
    const box = shadow.querySelector('.rs-box');
    const controls = shadow.querySelector('.rs-controls');
    const useBtn = shadow.querySelector('.rs-use');
    const redoBtn = shadow.querySelector('.rs-redo');
    const cancelBtn = shadow.querySelector('.rs-cancel');

    let startX = 0;
    let startY = 0;
    let dragging = false;
    let rect = null;

    function cleanup() {
      document.removeEventListener('keydown', onKeyDown, true);
      closeSelection();
    }

    function onKeyDown(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        cleanup();
      }
    }

    function updateBox(curX, curY) {
      const x = Math.min(startX, curX);
      const y = Math.min(startY, curY);
      const w = Math.abs(curX - startX);
      const h = Math.abs(curY - startY);
      box.style.left = `${x}px`;
      box.style.top = `${y}px`;
      box.style.width = `${w}px`;
      box.style.height = `${h}px`;
      rect = { x, y, width: w, height: h };
    }

    function onMouseDown(e) {
      if (e.button !== 0) return;
      dragging = true;
      startX = e.clientX;
      startY = e.clientY;
      controls.style.display = 'none';
      box.style.display = 'block';
      updateBox(e.clientX, e.clientY);
    }

    function onMouseMove(e) {
      if (!dragging) return;
      updateBox(e.clientX, e.clientY);
    }

    function onMouseUp(e) {
      if (!dragging) return;
      dragging = false;
      updateBox(e.clientX, e.clientY);
      if (!rect || rect.width < 4 || rect.height < 4) {
        box.style.display = 'none';
        rect = null;
        return;
      }
      controls.style.left = `${rect.x}px`;
      controls.style.top = `${rect.y + rect.height + 8}px`;
      controls.style.display = 'flex';

      const controlsRect = controls.getBoundingClientRect();
      let adjustedLeft = rect.x;
      let adjustedTop = rect.y + rect.height + 8;

      if (adjustedTop + controlsRect.height > window.innerHeight) {
        adjustedTop = rect.y - controlsRect.height - 8;
      }
      if (adjustedTop < 0) {
        adjustedTop = 8;
      }
      if (adjustedLeft + controlsRect.width > window.innerWidth) {
        adjustedLeft = window.innerWidth - controlsRect.width - 8;
      }
      if (adjustedLeft < 0) {
        adjustedLeft = 8;
      }

      controls.style.left = `${adjustedLeft}px`;
      controls.style.top = `${adjustedTop}px`;
    }

    overlay.addEventListener('mousedown', onMouseDown);
    overlay.addEventListener('mousemove', onMouseMove);
    overlay.addEventListener('mouseup', onMouseUp);
    document.addEventListener('keydown', onKeyDown, true);

    controls.addEventListener('mousedown', (e) => e.stopPropagation());

    cancelBtn.addEventListener('click', cleanup);

    redoBtn.addEventListener('click', () => {
      box.style.display = 'none';
      controls.style.display = 'none';
      rect = null;
    });

    useBtn.addEventListener('click', async () => {
      if (!rect) return;
      controls.style.display = 'none';
      box.style.display = 'none';
      const capturedRect = { ...rect, devicePixelRatio: window.devicePixelRatio || 1 };
      cleanup();
      const res = await sendToBackground({ type: 'CAPTURE_REGION', rect: capturedRect });
      openDialog({ dataUrl: res.ok ? res.dataUrl : null }, pageUrl, pageTitle);
    });
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === 'OPEN_DIALOG') {
      openDialog({ srcUrl: message.srcUrl, dataUrl: message.dataUrl }, message.pageUrl, message.pageTitle);
    } else if (message.type === 'START_REGION_CAPTURE') {
      startRegionSelection(message.pageUrl, message.pageTitle);
    }
  });
})();
