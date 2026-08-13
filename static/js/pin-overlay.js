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
    var state = {
      pinId: null,
      dirtyChange: null,
      opener: null,
      pushed: false,
      readyTimer: null,
      retryCounter: 0,
      pendingFocusTarget: null
    };

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
      var isIdle = view === 'idle';
      root.dataset.state = view;
      root.hidden = isIdle;
      root.setAttribute('aria-hidden', String(isIdle));
      if (isIdle) {
        boardContent.removeAttribute('inert');
        boardContent.removeAttribute('aria-hidden');
      } else {
        boardContent.setAttribute('inert', '');
        boardContent.setAttribute('aria-hidden', 'true');
      }
    }

    function isVisibleFocusTarget(target) {
      if (!target || !document.contains(target) || typeof target.focus !== 'function') return false;
      if (target.disabled || (target.closest && target.closest('[hidden]'))) return false;
      var style = window.getComputedStyle(target);
      return style.display !== 'none' && style.visibility !== 'hidden' && style.visibility !== 'collapse' &&
        target.getClientRects().length > 0;
    }

    function focusWithoutScroll(target) {
      if (!isVisibleFocusTarget(target)) return false;
      var scrollX = window.scrollX;
      var scrollY = window.scrollY;
      try {
        target.focus({ preventScroll: true });
      } catch (error) {
        target.focus();
      }
      if (window.scrollX !== scrollX || window.scrollY !== scrollY) window.scrollTo(scrollX, scrollY);
      return document.activeElement === target;
    }

    function focusAfterClose(replacement, opener, recoveryTarget) {
      var fallback = document.contains(boardContent) ? boardContent :
        document.getElementById('boardPageContent') || document.body;
      var candidates = [replacement, opener, recoveryTarget, fallback];
      for (var index = 0; index < candidates.length; index += 1) {
        if (candidates[index] === fallback && fallback && !fallback.hasAttribute('tabindex')) {
          fallback.setAttribute('tabindex', '-1');
        }
        if (candidates.indexOf(candidates[index]) === index && focusWithoutScroll(candidates[index])) return;
      }
    }

    function nearbyPinFocusTarget(opener) {
      var grid = document.getElementById('pinsGrid');
      var card = opener && typeof opener.closest === 'function' ? opener.closest('.pin-card, [data-pin-id]') : null;
      if (!grid || !card || !grid.contains(card)) return null;
      var cards = Array.prototype.slice.call(grid.querySelectorAll('.pin-card, [data-pin-id]'));
      var index = cards.indexOf(card);
      var candidates = index === -1 ? [] : cards.slice(index + 1).concat(cards.slice(0, index).reverse());
      for (var candidateIndex = 0; candidateIndex < candidates.length; candidateIndex += 1) {
        var focusable = candidates[candidateIndex].matches('a[href], button, [tabindex]') ? candidates[candidateIndex] :
          candidates[candidateIndex].querySelector('a[href], button, [tabindex]');
        if (isVisibleFocusTarget(focusable)) return focusable;
      }
      if (!grid.hasAttribute('tabindex')) grid.setAttribute('tabindex', '-1');
      return grid;
    }

    function focusFallbackAfterNavigation() {
      window.setTimeout(function () {
        focusAfterClose(null, null);
      }, 0);
    }

    function restoreScrollPosition(scrollX, scrollY) {
      if (window.scrollX !== scrollX || window.scrollY !== scrollY) window.scrollTo(scrollX, scrollY);
    }

    function refreshAndFocus(pinId, change, opener) {
      if (!change) {
        focusAfterClose(null, opener);
        return;
      }
      var recoveryTarget = nearbyPinFocusTarget(opener);
      var scrollX = window.scrollX;
      var scrollY = window.scrollY;
      window.sessionStorage.removeItem(pendingRefreshKey());
      Promise.resolve(options.refreshPinCard(pinId, change)).then(function (replacement) {
        focusAfterClose(replacement, opener, recoveryTarget);
        restoreScrollPosition(scrollX, scrollY);
      }).catch(function () {
        if (typeof options.showToast === 'function') options.showToast('Could not refresh pin');
        focusFallbackAfterNavigation();
      });
    }

    function consumePendingRefresh() {
      var saved = window.sessionStorage.getItem(pendingRefreshKey());
      if (!saved) return;
      var recoveryTarget = state.pendingFocusTarget;
      var scrollX = window.scrollX;
      var scrollY = window.scrollY;
      state.pendingFocusTarget = null;
      window.sessionStorage.removeItem(pendingRefreshKey());
      try {
        var pending = JSON.parse(saved);
        if (pending && Number.isInteger(pending.pinId) && ['updated', 'moved', 'deleted'].indexOf(pending.change) !== -1) {
          Promise.resolve(options.refreshPinCard(pending.pinId, pending.change)).then(function (replacement) {
            focusAfterClose(replacement, null, recoveryTarget);
            restoreScrollPosition(scrollX, scrollY);
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
      var embeddedUrl = new URL('/pin/' + encodeURIComponent(pinId), window.location.origin);
      embeddedUrl.searchParams.set('embedded', '1');
      embeddedUrl.searchParams.set('board_id', String(options.boardId));
      if (state.retryCounter > 0) embeddedUrl.searchParams.set('_retry', String(state.retryCounter));
      // Replacing the child location avoids adding a joint-session-history
      // entry after the board's overlay entry.
      iframe.contentWindow.location.replace(embeddedUrl.pathname + embeddedUrl.search);
      openPageLink.href = '/pin/' + encodeURIComponent(pinId);
      state.readyTimer = window.setTimeout(showError, readyTimeoutMs);
    }

    function reveal(pinId, pushed) {
      if (!pinId) return;
      if (state.pinId === pinId && !root.hidden) return;
      state.pinId = pinId;
      state.dirtyChange = null;
      state.pushed = Boolean(pushed);
      state.retryCounter = 0;
      load(pinId);
    }

    function hide() {
      clearReadyTimer();
      state.pinId = null;
      state.dirtyChange = null;
      state.pushed = false;
      state.retryCounter = 0;
      setView('idle');
      state.opener = null;
    }

    function finishClose(navigation) {
      var pinId = state.pinId;
      var change = state.dirtyChange;
      var opener = state.opener;
      if (!pinId) return;
      if (navigation === 'back' && change) {
        state.pendingFocusTarget = nearbyPinFocusTarget(opener);
      }
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
        focusWithoutScroll(iframe);
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

    function onBackdropScroll(event) {
      if (root.hidden) return;
      var path = typeof event.composedPath === 'function' ? event.composedPath() : [];
      if (event.target !== iframe && path.indexOf(iframe) === -1) event.preventDefault();
    }

    function retry() {
      if (state.pinId !== null) {
        state.retryCounter += 1;
        load(state.pinId);
      }
    }

    boardContent.addEventListener('click', onBoardClick);
    window.addEventListener('popstate', syncFromLocation);
    window.addEventListener('message', onMessage);
    document.addEventListener('keydown', onKeydown);
    root.addEventListener('click', onRootClick);
    root.addEventListener('wheel', onBackdropScroll, { passive: false });
    root.addEventListener('touchmove', onBackdropScroll, { passive: false });
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
        root.removeEventListener('wheel', onBackdropScroll);
        root.removeEventListener('touchmove', onBackdropScroll);
        if (closeButton) closeButton.removeEventListener('click', close);
        if (retryButton) retryButton.removeEventListener('click', retry);
        hide();
      }
    };
  };
}());
