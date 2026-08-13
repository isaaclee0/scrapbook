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

    function pendingRefreshKey() {
      var url = new URL(window.location.href);
      url.searchParams.delete('pin');
      return 'scrappl.pin-overlay.refresh:' + url.pathname + url.search;
    }

    function persistDirtyChange(pinId, change) {
      window.sessionStorage.setItem(pendingRefreshKey(), JSON.stringify({ pinId: pinId, change: change }));
    }

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

    function focusAfterClose(replacement, opener) {
      var fallback = document.contains(boardContent) ? boardContent :
        document.getElementById('boardPageContent') || document.body;
      var target = replacement && document.contains(replacement) ? replacement :
        (opener && document.contains(opener) ? opener : fallback);
      if (target && typeof target.focus === 'function') {
        var scrollX = window.scrollX;
        var scrollY = window.scrollY;
        try {
          target.focus({ preventScroll: true });
        } catch (error) {
          target.focus();
        }
        if (window.scrollX !== scrollX || window.scrollY !== scrollY) window.scrollTo(scrollX, scrollY);
      }
    }

    function focusFallbackAfterNavigation() {
      window.setTimeout(function () {
        focusAfterClose(null, null);
      }, 0);
    }

    function refreshAndFocus(pinId, change, opener) {
      if (!change) {
        focusAfterClose(null, opener);
        return;
      }
      window.sessionStorage.removeItem(pendingRefreshKey());
      Promise.resolve(options.refreshPinCard(pinId, change)).then(function (replacement) {
        focusAfterClose(replacement, opener);
      }).catch(function () {
        if (typeof options.showToast === 'function') options.showToast('Could not refresh pin');
        focusFallbackAfterNavigation();
      });
    }

    function consumePendingRefresh() {
      var saved = window.sessionStorage.getItem(pendingRefreshKey());
      if (!saved) return;
      window.sessionStorage.removeItem(pendingRefreshKey());
      try {
        var pending = JSON.parse(saved);
        if (pending && Number.isInteger(pending.pinId) && ['updated', 'moved', 'deleted'].indexOf(pending.change) !== -1) {
          Promise.resolve(options.refreshPinCard(pending.pinId, pending.change)).then(function (replacement) {
            focusAfterClose(replacement, null);
          }).catch(function () {
            if (typeof options.showToast === 'function') options.showToast('Could not refresh pin');
            focusFallbackAfterNavigation();
          });
        }
      } catch (error) {
        // Discard malformed state written by an older page.
      }
    }

    function showError() {
      if (state.pinId !== null) setView('error');
    }

    function load(pinId) {
      clearReadyTimer();
      setView('loading');
      var embeddedUrl = '/pin/' + encodeURIComponent(pinId) + '?embedded=1&board_id=' + encodeURIComponent(options.boardId);
      // Replacing the child location avoids adding a joint-session-history
      // entry after the board's overlay entry.
      iframe.contentWindow.location.replace(embeddedUrl);
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
      state.opener = null;
    }

    function finishClose(navigation) {
      var pinId = state.pinId;
      var change = state.dirtyChange;
      var opener = state.opener;
      if (!pinId) return;
      hide();
      if (navigation === 'back') {
        if (!change) focusAfterClose(null, opener);
        window.history.back();
      }
      else if (navigation === 'replace') window.history.replaceState(window.history.state, '', urlFor(pinId, false));
      if (navigation !== 'back') refreshAndFocus(pinId, change, opener);
    }

    function open(pinId, opener) {
      var numericPinId = Number(pinId);
      if (!Number.isInteger(numericPinId) || numericPinId <= 0) return;
      state.opener = opener || document.activeElement;
      if (pinFromLocation() !== numericPinId) {
        // Navigate the child first so its session-history entry belongs to the
        // board URL; the parent push must remain the most recent entry.
        reveal(numericPinId, false);
        window.history.pushState({ scrapbookPinOverlay: true, pinId: numericPinId }, '', urlFor(numericPinId, true));
        state.pushed = true;
      } else reveal(numericPinId, Boolean(window.history.state && window.history.state.scrapbookPinOverlay));
    }

    function close() {
      finishClose(state.pushed ? 'back' : 'replace');
    }

    function syncFromLocation() {
      var pinId = pinFromLocation();
      if (pinId) reveal(pinId, Boolean(window.history.state && window.history.state.scrapbookPinOverlay));
      else if (state.pinId !== null) finishClose('none');
      else consumePendingRefresh();
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
        persistDirtyChange(state.pinId, data.change);
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
