/* Pin image navigation and saved gallery mutations. Notes intentionally stay outside. */
(function () {
    'use strict';
    const root = document.querySelector('[data-pin-gallery]');
    if (!root) return;
    const endpoint = `/api/pin/${root.dataset.pinId}/images`;
    const surface = root.querySelector('.pin-image-container');
    const image = surface.querySelector('.pin-image');
    const title = image.alt;
    const placeholder = '/static/images/default_pin.png';
    let images = [], selectedId = null, busy = false, ready = false;
    let pending = Promise.resolve();
    const missingDisplaySources = new Set();
    const missingThumbnailSources = new Map();
    const requestedId = new URLSearchParams(location.search).get('image');

    root.setAttribute('role', 'region');
    root.setAttribute('aria-label', 'Pin images');
    root.tabIndex = 0;
    const controls = document.createElement('div');
    controls.className = 'gallery-navigation';
    controls.innerHTML = '<button type="button" data-gallery-previous aria-label="Previous image">‹</button><span data-gallery-position aria-live="polite" aria-atomic="true">Loading images…</span><button type="button" data-gallery-next aria-label="Next image">›</button>';
    root.appendChild(controls);
    const thumbs = document.createElement('div');
    thumbs.className = 'gallery-thumbnails';
    thumbs.setAttribute('aria-label', 'Choose an image');
    root.appendChild(thumbs);
    const actions = document.createElement('div');
    actions.className = 'gallery-actions';
    actions.innerHTML = '<button type="button" data-gallery-cover>Make cover</button><button type="button" data-gallery-earlier aria-label="Move image earlier">Move earlier</button><button type="button" data-gallery-later aria-label="Move image later">Move later</button><button type="button" data-gallery-replace>Replace image</button><button type="button" data-gallery-remove>Remove image</button><button type="button" data-gallery-fullscreen>Fullscreen image</button>';
    root.appendChild(actions);
    const add = document.createElement('div');
    add.className = 'gallery-add';
    add.dataset.galleryAdd = '';
    add.tabIndex = 0;
    add.setAttribute('role', 'group');
    add.setAttribute('aria-label', 'Add images: choose files, drop files or paste images here');
    add.innerHTML = '<button type="button" data-gallery-picker>Add images</button><span>Drop files or focus here and paste images</span><input type="file" accept="image/*" multiple data-gallery-files hidden><input type="file" accept="image/*" data-gallery-replacement hidden>';
    root.appendChild(add);
    const uploads = document.createElement('ul');
    uploads.className = 'gallery-upload-results';
    uploads.setAttribute('aria-live', 'polite');
    root.appendChild(uploads);
    const status = document.createElement('div');
    status.className = 'gallery-status';
    status.setAttribute('role', 'status');
    root.appendChild(status);
    const imageError = document.createElement('div');
    imageError.className = 'gallery-image-error';
    imageError.hidden = true;
    imageError.innerHTML = '<span>This image could not load.</span><button type="button">Retry image</button>';
    surface.appendChild(imageError);
    const $ = selector => root.querySelector(selector);
    const current = () => images.find(item => String(item.id) === String(selectedId)) || null;
    const index = () => images.findIndex(item => String(item.id) === String(selectedId));
    const displayKey = item => JSON.stringify([item.id, item.display_url, item.image_url]);
    const readableSource = item => missingDisplaySources.has(displayKey(item)) ? item.image_url : (item.display_url || item.image_url);
    const readableUrl = () => current() ? readableSource(current()) : null;

    function render() {
        const active = current(), position = index();
        const url = active ? readableSource(active) : placeholder;
        if (ready && (image.getAttribute('src') !== url || image.dataset.galleryImageId !== String(active?.id || ''))) {
            imageError.hidden = true;
            image.src = url;
        }
        if (ready) image.dataset.originalUrl = active ? active.image_url : placeholder;
        image.dataset.galleryImageId = active ? active.id : '';
        image.alt = active ? `${title}, image ${position + 1} of ${images.length}` : title;
        $('[data-gallery-position]').textContent = !ready ? 'Loading images…' : images.length ? `${position + 1} / ${images.length}` : 'No images';
        for (const direction of ['previous', 'next']) {
            $(`[data-gallery-${direction}]`).hidden = images.length < 2;
        }
        root.setAttribute('aria-busy', String(busy || !ready));
        $('[data-gallery-cover]').disabled = busy || !ready || position <= 0;
        $('[data-gallery-cover]').textContent = position === 0 ? 'Cover image' : 'Make cover';
        $('[data-gallery-earlier]').disabled = busy || !ready || position <= 1;
        $('[data-gallery-later]').disabled = busy || !ready || position <= 0 || position === images.length - 1;
        for (const action of ['replace', 'remove', 'fullscreen']) $(`[data-gallery-${action}]`).disabled = busy || !ready || !active;
        root.querySelectorAll('.tools-menu button, .fullscreen-btn').forEach(button => {
            button.disabled = busy || !ready || !active;
        });
        $('[data-gallery-picker]').disabled = !ready;
        // Keep keyboard focus on its selected thumbnail when the saved collection changes.
        const focusedId = document.activeElement && document.activeElement.dataset.galleryThumbnail;
        thumbs.replaceChildren();
        images.forEach((item, i) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.dataset.galleryThumbnail = item.id;
            button.setAttribute('aria-label', `Select image ${i + 1}`);
            button.setAttribute('aria-pressed', String(item === active));
            const thumbnail = document.createElement('img');
            const sources = [...new Set([item.preview_url, item.display_url, item.image_url].filter(Boolean))];
            const key = JSON.stringify([item.id, ...sources]);
            if (!missingThumbnailSources.has(key)) missingThumbnailSources.set(key, new Set());
            const failed = missingThumbnailSources.get(key);
            const nextSource = () => sources.find(source => !failed.has(source));
            thumbnail.onerror = () => {
                failed.add(thumbnail.getAttribute('src'));
                const next = nextSource();
                if (next) thumbnail.src = next;
                else { thumbnail.onerror = null; thumbnail.src = placeholder; }
            };
            thumbnail.src = nextSource() || placeholder;
            thumbnail.alt = '';
            thumbnail.loading = 'lazy';
            button.appendChild(thumbnail);
            if (i === 0) {
                const badge = document.createElement('span');
                badge.textContent = 'Cover';
                button.appendChild(badge);
            }
            button.addEventListener('click', () => select(item.id));
            thumbs.appendChild(button);
        });
        if (focusedId) {
            const focused = Array.from(thumbs.children).find(button => button.dataset.galleryThumbnail === focusedId);
            (focused || root).focus({ preventScroll: true });
        }
    }

    function select(id) {
        selectedId = id;
        render();
    }
    function navigate(delta) {
        if (images.length > 1) select(images[(index() + delta + images.length) % images.length].id);
    }
    function apply(data) {
        if (!Array.isArray(data.images)) throw new Error('The gallery response was incomplete. Please retry.');
        const oldPosition = index();
        images = data.images;
        if (!current()) selectedId = images[Math.max(0, Math.min(oldPosition, images.length - 1))]?.id || null;
        ready = true;
        render();
    }
    async function request(url, options) {
        const response = await fetch(url, options);
        let data;
        try { data = await response.json(); }
        catch (_) { throw new Error('Could not read the server response. Please retry.'); }
        if (!response.ok || !data.success) {
            const error = new Error(data.error || 'Could not save images. Please retry.');
            error.status = response.status;
            throw error;
        }
        return data;
    }
    function report(error, retry) {
        status.replaceChildren();
        const message = document.createElement('span');
        message.textContent = error.message;
        status.appendChild(message);
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = 'Retry action';
        button.onclick = () => { status.replaceChildren(); retry(); };
        status.appendChild(button);
    }
    async function load(initial = false) {
        const data = await request(endpoint);
        if (initial) selectedId = requestedId;
        apply(data);
    }
    function enqueue(operation) {
        pending = pending.then(async () => {
            busy = true;
            render();
            try { return await operation(); }
            finally { busy = false; render(); }
        });
        // Each operation handles and displays its own error. Keep the queue alive.
        pending = pending.catch(error => report(error, () => load().catch(next => report(next, () => load()))));
        return pending;
    }
    async function save(url, options) {
        try {
            apply(await request(url, options));
            if (typeof window.notifyPinOverlay === 'function') window.notifyPinOverlay('changed', 'updated');
        } catch (error) {
            if ([404, 409].includes(error.status)) {
                try { await load(); } catch (_) { /* Preserve the last saved gallery if refresh fails. */ }
            }
            throw error;
        }
    }
    function manage(payload) {
        return enqueue(async () => {
            try {
                await save(endpoint + '/manage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                status.replaceChildren();
            } catch (error) { report(error, () => manage(payload)); }
        });
    }
    function reorder(delta) {
        const position = index();
        if (position <= 0 || position + delta <= 0 || position + delta >= images.length) return;
        const ids = images.map(item => item.id);
        [ids[position], ids[position + delta]] = [ids[position + delta], ids[position]];
        manage({ action: 'reorder', image_ids: ids });
    }
    function uploadFiles(files, replaceId = null) {
        Array.from(files).forEach(file => {
            const row = document.createElement('li');
            uploads.appendChild(row);
            const attempt = () => enqueue(async () => {
                row.textContent = `${file.name}: Uploading…`;
                const form = new FormData();
                form.append('file', file);
                if (replaceId !== null) form.append('replace_id', replaceId);
                try {
                    await save(endpoint, { method: 'POST', body: form });
                    row.textContent = `${file.name}: ${replaceId === null ? 'Added' : 'Replaced'}`;
                } catch (error) {
                    row.textContent = `${file.name}: ${error.message} `;
                    const retry = document.createElement('button');
                    retry.type = 'button';
                    retry.textContent = 'Retry';
                    retry.setAttribute('aria-label', `Retry ${file.name}`);
                    retry.onclick = attempt;
                    row.appendChild(retry);
                }
            });
            row.textContent = `${file.name}: Waiting…`;
            attempt();
        });
    }
    function chooseReplacement() {
        if (current() && !busy) $('[data-gallery-replacement]').click();
        document.getElementById('toolsMenu')?.classList.remove('active');
    }
    function removeSelected() {
        if (current() && !busy) return manage({ action: 'remove', image_id: current().id });
    }
    function fullscreen(opener = document.activeElement) {
        const active = current();
        if (!active) return;
        const dialog = document.createElement('dialog');
        dialog.className = 'gallery-fullscreen';
        dialog.setAttribute('aria-label', 'Fullscreen image');
        dialog.innerHTML = '<div class="gallery-fullscreen-toolbar"><button type="button" data-zoom>Enlarge image</button><button type="button" data-close>Close fullscreen</button></div><div class="gallery-fullscreen-viewport"><img alt=""><div class="gallery-fullscreen-error" hidden>Original image could not load. <button type="button">Retry original</button></div></div>';
        const original = dialog.querySelector('img');
        const viewport = dialog.querySelector('.gallery-fullscreen-viewport');
        original.src = active.image_url;
        original.alt = image.alt;
        let enlarged = false, pan = null;
        const zoom = dialog.querySelector('[data-zoom]');
        zoom.onclick = () => {
            enlarged = !enlarged;
            dialog.classList.toggle('is-enlarged', enlarged);
            zoom.textContent = enlarged ? 'Fit image' : 'Enlarge image';
            viewport.scrollTo(0, 0);
        };
        const failed = dialog.querySelector('.gallery-fullscreen-error');
        const fallbackSource = readableSource(active);
        let triedFallback = false;
        original.onerror = () => {
            if (!triedFallback && fallbackSource !== active.image_url) {
                triedFallback = true;
                original.src = fallbackSource;
                return;
            }
            failed.hidden = false;
        };
        original.onload = () => { failed.hidden = true; };
        failed.querySelector('button').onclick = () => {
            failed.hidden = true;
            triedFallback = false;
            original.removeAttribute('src');
            requestAnimationFrame(() => { if (dialog.isConnected && dialog.open) original.src = active.image_url; });
        };
        dialog.querySelector('[data-close]').onclick = () => dialog.close();
        dialog.addEventListener('close', () => { dialog.remove(); if (opener?.isConnected) opener.focus({ preventScroll: true }); });
        viewport.addEventListener('pointerdown', event => {
            if (!enlarged || event.target.closest('button')) return;
            pan = { x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop };
            viewport.setPointerCapture(event.pointerId);
        });
        viewport.addEventListener('pointermove', event => {
            if (!pan) return;
            viewport.scrollLeft = pan.left + pan.x - event.clientX;
            viewport.scrollTop = pan.top + pan.y - event.clientY;
        });
        viewport.addEventListener('pointerup', () => { pan = null; });
        viewport.addEventListener('pointercancel', () => { pan = null; });
        original.draggable = false;
        document.body.appendChild(dialog);
        dialog.showModal();
        dialog.querySelector('[data-close]').focus();
    }

    // Called by the embedded template's document listener before base-page
    // shortcuts. Target handlers have already had a chance to consume Escape.
    function handleEscape(event) {
        if (event.key !== 'Escape' || event.defaultPrevented) return false;
        // Native dialogs close through their own cancel default action. Do not
        // prevent that action or forward the same key to the enclosing pin.
        if (document.querySelector('dialog[open]')) return true;
        const visible = element => element.getClientRects().length > 0 && getComputedStyle(element).visibility !== 'hidden';
        const confirmations = Array.from(document.querySelectorAll('.confirmation-dialog-overlay')).filter(visible);
        if (confirmations.length) {
            event.preventDefault();
            confirmations[confirmations.length - 1].remove();
            return true;
        }
        const modals = Array.from(document.querySelectorAll('.modal')).filter(visible);
        if (modals.length) {
            event.preventDefault();
            const modal = modals[modals.length - 1];
            const cancel = modal.querySelector('.secondary-button, .modal-header .close-button');
            if (cancel) cancel.click();
            else { modal.classList.remove('active'); modal.style.display = 'none'; }
            return true;
        }
        const menus = Array.from(document.querySelectorAll('.tools-menu.active, .board-menu.active, .section-menu.active')).filter(visible);
        if (menus.length) {
            event.preventDefault();
            menus[menus.length - 1].classList.remove('active');
            return true;
        }
        const urlEditor = document.getElementById('urlEdit');
        if (urlEditor && visible(urlEditor)) {
            event.preventDefault();
            if (typeof window.cancelUrlEdit === 'function') window.cancelUrlEdit();
            return true;
        }
        if (event.target.closest('[contenteditable="true"]')) {
            event.preventDefault();
            return true;
        }
        return false;
    }

    $('[data-gallery-previous]').onclick = () => navigate(-1);
    $('[data-gallery-next]').onclick = () => navigate(1);
    $('[data-gallery-cover]').onclick = () => current() && manage({ action: 'cover', image_id: current().id });
    $('[data-gallery-earlier]').onclick = () => reorder(-1);
    $('[data-gallery-later]').onclick = () => reorder(1);
    $('[data-gallery-replace]').onclick = chooseReplacement;
    $('[data-gallery-remove]').onclick = removeSelected;
    $('[data-gallery-fullscreen]').onclick = () => fullscreen($('[data-gallery-fullscreen]'));
    $('[data-gallery-picker]').onclick = () => $('[data-gallery-files]').click();
    $('[data-gallery-files]').onchange = event => { uploadFiles(event.target.files); event.target.value = ''; };
    $('[data-gallery-replacement]').onchange = event => { if (current()) uploadFiles(event.target.files, current().id); event.target.value = ''; };
    add.addEventListener('dragover', event => { event.preventDefault(); add.classList.add('is-dragging'); });
    add.addEventListener('dragleave', () => add.classList.remove('is-dragging'));
    add.addEventListener('drop', event => { event.preventDefault(); add.classList.remove('is-dragging'); if (ready) uploadFiles(event.dataTransfer.files); });
    add.addEventListener('paste', event => {
        const files = Array.from(event.clipboardData?.files || []).filter(file => file.type.startsWith('image/'));
        if (files.length && ready) { event.preventDefault(); uploadFiles(files); }
    });
    root.addEventListener('keydown', event => {
        if (event.target.closest('input, textarea, [contenteditable="true"], [data-gallery-add]')) return;
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); navigate(event.key === 'ArrowLeft' ? -1 : 1); }
    });
    let gesture = null;
    surface.style.touchAction = 'pan-y pinch-zoom';
    surface.addEventListener('pointerdown', event => {
        if (event.pointerType === 'touch' && !event.target.closest('button')) {
            gesture = { id: event.pointerId, x: event.clientX, y: event.clientY };
            if (event.isTrusted) surface.setPointerCapture(event.pointerId);
        }
    });
    surface.addEventListener('pointerup', event => {
        if (!gesture || gesture.id !== event.pointerId) return;
        const dx = event.clientX - gesture.x, dy = event.clientY - gesture.y;
        gesture = null;
        if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy) * 1.5) navigate(dx < 0 ? 1 : -1);
    });
    surface.addEventListener('pointercancel', () => { gesture = null; });
    image.onerror = () => {
        const active = current();
        if (!active) return;
        const display = active.display_url || active.image_url;
        const key = displayKey(active);
        if (image.getAttribute('src') === display && display !== active.image_url && !missingDisplaySources.has(key)) {
            missingDisplaySources.add(key);
            imageError.hidden = true;
            image.src = active.image_url;
            return;
        }
        imageError.hidden = false;
    };
    image.onload = () => { imageError.hidden = true; };
    imageError.querySelector('button').onclick = () => {
        imageError.hidden = true;
        const source = readableUrl() || placeholder;
        const key = current() ? displayKey(current()) : null;
        image.removeAttribute('src');
        requestAnimationFrame(() => {
            if (current() && displayKey(current()) === key && readableUrl() === source) image.src = source;
        });
    };

    window.pinGallery = { current, readableUrl, fullscreen, handleEscape, replace: chooseReplacement, remove: removeSelected, uploadFiles, reload: load,
        async saveImage(value) {
            if (value instanceof Blob) return uploadFiles([value], current()?.id ?? null);
            if (value === placeholder) return removeSelected();
            if (typeof value === 'string' && value.startsWith('data:image/')) {
                const response = await fetch(value);
                uploadFiles([new File([await response.blob()], 'replacement.png', { type: response.headers.get('content-type') || 'image/png' })], current()?.id ?? null);
            }
        }
    };
    render();
    load(true).catch(error => { root.setAttribute('aria-busy', 'false'); $('[data-gallery-position]').textContent = 'Images unavailable'; report(error, () => load(true).catch(next => report(next, () => load(true)))); });
})();
