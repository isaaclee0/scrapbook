(function () {
  'use strict';

  var MESSAGE_SOURCE = 'scrappl-pin-overlay';
  var MESSAGE_VERSION = 1;

  window.createPinOverlayController = function createPinOverlayController(options) {
    if (!options || !options.root || !options.boardContent) {
      throw new Error('Pin overlay requires root and boardContent elements');
    }

    var root = options.root;
    var boardContent = options.boardContent;
    var iframe = root.querySelector('iframe');
    var closeButton = root.querySelector('[data-overlay-close]');
    var retryButton = root.querySelector('[data-overlay-retry]');
    var openPageLink = root.querySelector('[data-overlay-open-page]');
    var readyTimeoutMs = options.readyTimeoutMs || 8000;
    var state = { pinId: null, dirtyChange: null, opener: null, pushed: false, readyTimer: null };

    function pinFromLocation() {
      var value = new URL(window.location.href).searchParams.get('pin');
      return value && /^\d+$/.test(value) ? Number(value) : null;
    }

    function urlFor(pinId, includePin) {
      var url = new URL(window.location.href);
      if (includePin) url.searchParams.set('pin', String(pinId));
      else url.searchParams.delete('pin');
      return url.pathname + (url.search || '') + url.hash;
    }

    function clearReadyTimer() {
      if (state.readyTimer) window.clearTimeout(state.readyTimer);
      state.readyTimer = null;
    }

    function setView(view) {
      root.dataset.state = view;
      root.hidden = view === 'idle';
      root.setAttribute('aria-hidden', String(view === 'idle'));
    }

    function focusOpener() {
      var target = state.opener && document.contains(state.opener) ? state.opener : boardContent;
      if (target && typeof target.focus === 'function') target.focus();
    }

    function showError() {
      if (state.pinId !== null) setView('error');
    }

    function load(pinId) {
      clearReadyTimer();
      setView('loading');
      iframe.src = '/pin/' + encodeURIComponent(pinId) + '?embedded=1&board_id=' + encodeURIComponent(options.boardId);
      openPageLink.href = '/pin/' + encodeURIComponent(pinId);
      state.readyTimer = window.setTimeout(showError, readyTimeoutMs);
    }

    function reveal(pinId, pushed) {
      if (!pinId) return;
      if (state.pinId === pinId && !root.hidden) return;
      state.pinId = pinId;
      state.dirtyChange = null;
      state.pushed = Boolean(pushed);
      load(pinId);
    }

    function hide() {
      clearReadyTimer();
      state.pinId = null;
      state.dirtyChange = null;
      state.pushed = false;
      setView('idle');
      focusOpener();
      state.opener = null;
    }

    function finishClose() {
      var pinId = state.pinId;
      var change = state.dirtyChange;
      if (!pinId) return;
      if (change) {
        Promise.resolve(options.refreshPinCard(pinId, change)).catch(function () {
          if (typeof options.showToast === 'function') options.showToast('Could not refresh pin');
        });
      }
      if (state.pushed) {
        // WebKit does not reliably complete same-document traversal while an
        // iframe is loading, so close the visual state before traversal.
        hide();
        window.history.back();
      }
      else {
        window.history.replaceState(window.history.state, '', urlFor(pinId, false));
        hide();
      }
    }

    function open(pinId, opener) {
      var numericPinId = Number(pinId);
      if (!Number.isInteger(numericPinId) || numericPinId <= 0) return;
      state.opener = opener || document.activeElement;
      if (pinFromLocation() !== numericPinId) {
        window.history.pushState({ scrapbookPinOverlay: true, pinId: numericPinId }, '', urlFor(numericPinId, true));
        reveal(numericPinId, true);
      } else reveal(numericPinId, Boolean(window.history.state && window.history.state.scrapbookPinOverlay));
    }

    function close() {
      finishClose();
    }

    function syncFromLocation() {
      var pinId = pinFromLocation();
      if (pinId) reveal(pinId, Boolean(window.history.state && window.history.state.scrapbookPinOverlay));
      else if (state.pinId !== null) hide();
    }

    function onBoardClick(event) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      var anchor = event.target.closest('a[href]');
      if (!anchor || !boardContent.contains(anchor) || anchor.target || anchor.hasAttribute('download')) return;
      var url = new URL(anchor.href, window.location.href);
      var match = url.pathname.match(/^\/pin\/(\d+)$/);
      if (!match || url.origin !== window.location.origin) return;
      event.preventDefault();
      open(Number(match[1]), anchor);
    }

    function onMessage(event) {
      var data = event.data;
      if (!data || event.origin !== window.location.origin || event.source !== iframe.contentWindow ||
          data.source !== MESSAGE_SOURCE || data.version !== MESSAGE_VERSION || data.pinId !== state.pinId) return;
      if (data.type === 'ready') {
        clearReadyTimer();
        setView('open');
      } else if (data.type === 'changed' && ['updated', 'moved', 'deleted'].indexOf(data.change) !== -1) {
        state.dirtyChange = data.change;
      } else if (data.type === 'close') close();
    }

    function onKeydown(event) {
      if (event.key === 'Escape' && !root.hidden) close();
    }

    function onRootClick(event) {
      if (event.target === root) close();
    }

    function retry() {
      if (state.pinId !== null) load(state.pinId);
    }

    boardContent.addEventListener('click', onBoardClick);
    window.addEventListener('popstate', syncFromLocation);
    window.addEventListener('message', onMessage);
    document.addEventListener('keydown', onKeydown);
    root.addEventListener('click', onRootClick);
    if (closeButton) closeButton.addEventListener('click', close);
    if (retryButton) retryButton.addEventListener('click', retry);

    return {
      open: open,
      close: close,
      syncFromLocation: syncFromLocation,
      destroy: function () {
        clearReadyTimer();
        boardContent.removeEventListener('click', onBoardClick);
        window.removeEventListener('popstate', syncFromLocation);
        window.removeEventListener('message', onMessage);
        document.removeEventListener('keydown', onKeydown);
        root.removeEventListener('click', onRootClick);
        if (closeButton) closeButton.removeEventListener('click', close);
        if (retryButton) retryButton.removeEventListener('click', retry);
        hide();
      }
    };
  };
}());
