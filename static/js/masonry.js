/**
 * Stable masonry layout engine for pin grids (board + search).
 *
 * Replaces CSS multi-column masonry, which rebalances every card across all
 * columns whenever content is appended or a height changes — the cause of
 * pins jumping around during image load and infinite scroll.
 *
 * Guarantees:
 *  - A placed card is never repositioned except by an explicit layout().
 *  - append() places new cards below existing ones without touching them.
 *  - layout() is deterministic: same cards, same DOM order, same grid width
 *    in => identical positions out.
 *
 * Cards are positioned with left/top, NOT transform — the .pin-card hover
 * and highlight animations, plus display-mode's scroll-linked parallax
 * (board.html/boards.html), already own the transform property.
 */
(function () {
    'use strict';

    var GAP = 16; // px — matches the old column-gap / card margin-bottom

    // Mirrors the old #pinsGrid media-query breakpoints.
    function breakpointCap(viewportWidth) {
        if (viewportWidth <= 500) return 1;
        if (viewportWidth <= 800) return 2;
        if (viewportWidth <= 1200) return 3;
        if (viewportWidth <= 1600) return 4;
        return Infinity;
    }

    function createScrapbookMasonry(grid, options) {
        options = options || {};

        var colHeights = []; // per-column content height incl. trailing gap
        var colWidth = 0;
        var pad = { left: 0, right: 0, top: 0, bottom: 0 };
        var borderBox = true;
        var lastLayoutWidth = -1;
        var lastDocWidth = -1;

        // Viewport width for breakpoints. documentElement.clientWidth (not
        // window.innerWidth) so the cap and the resize guard read the same
        // source that grid measurements come from — innerWidth can lag the
        // layout viewport during emulated/rotating resizes, which would bake
        // a stale column cap into an otherwise-correct layout.
        function docWidth() {
            return document.documentElement.clientWidth;
        }

        function readBoxMetrics() {
            var cs = window.getComputedStyle(grid);
            pad.left = parseFloat(cs.paddingLeft) || 0;
            pad.right = parseFloat(cs.paddingRight) || 0;
            pad.top = parseFloat(cs.paddingTop) || 0;
            pad.bottom = parseFloat(cs.paddingBottom) || 0;
            borderBox = cs.boxSizing !== 'content-box';
        }

        function columnCount() {
            var requested = options.columnCount ? options.columnCount() : 5;
            var cap = breakpointCap(docWidth());
            return Math.max(1, Math.min(requested, cap));
        }

        function visibleCards() {
            return Array.prototype.filter.call(grid.children, function (el) {
                return el.classList.contains('pin-card') && el.style.display !== 'none';
            });
        }

        function shortestColumn() {
            var best = 0;
            for (var i = 1; i < colHeights.length; i++) {
                if (colHeights[i] < colHeights[best]) best = i;
            }
            return best;
        }

        function syncGridHeight() {
            var max = 0;
            for (var i = 0; i < colHeights.length; i++) {
                if (colHeights[i] > max) max = colHeights[i];
            }
            if (max === 0) {
                // No visible cards: let in-flow content (e.g. the board's
                // "section is empty" message) size the grid naturally.
                grid.style.height = '';
                return;
            }
            var content = max - GAP; // drop the trailing gap
            grid.style.height = (borderBox ? content + pad.top + pad.bottom : content) + 'px';
        }

        // Place cards into the current colHeights state. Batched into one
        // write pass (widths), one read pass (heights — single reflow), and
        // one write pass (positions), so large batches don't thrash layout.
        function place(cards) {
            var i;
            for (i = 0; i < cards.length; i++) {
                cards[i].style.width = colWidth + 'px';
            }
            var heights = [];
            for (i = 0; i < cards.length; i++) {
                heights.push(cards[i].offsetHeight);
            }
            for (i = 0; i < cards.length; i++) {
                var col = shortestColumn();
                cards[i].dataset.parallaxCol = col;
                cards[i].style.left = (pad.left + col * (colWidth + GAP)) + 'px';
                cards[i].style.top = (pad.top + colHeights[col]) + 'px';
                colHeights[col] += heights[i] + GAP;
            }
            syncGridHeight();
        }

        // Full relayout of all visible cards. Only called for user-initiated
        // changes (viewport width change, pin-size change, section filter) —
        // never from image load handlers.
        function layout() {
            readBoxMetrics();
            var count = columnCount();
            var inner = grid.clientWidth - pad.left - pad.right;
            colWidth = Math.floor((inner - (count - 1) * GAP) / count);
            colHeights = [];
            for (var i = 0; i < count; i++) colHeights.push(0);
            place(visibleCards());
            lastLayoutWidth = grid.clientWidth;
            lastDocWidth = docWidth();
            grid.classList.add('masonry-ready');
        }

        // Place only newCards, continuing from current column heights.
        // Existing cards are never touched.
        function append(newCards) {
            var cards = Array.prototype.filter.call(newCards, function (el) {
                return el.style.display !== 'none';
            });
            place(cards);
        }

        // Relayout on real width changes only. Mobile browsers fire resize
        // when the URL bar shows/hides during scroll — a height-only change
        // must not move pins, so compare widths.
        var resizeTimer = null;
        window.addEventListener('resize', function () {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () {
                // Grid width drives column width; document width drives the
                // breakpoint cap (the grid can be clamped by its container
                // while the viewport keeps growing). Relayout if either moved.
                if (grid.clientWidth !== lastLayoutWidth || docWidth() !== lastDocWidth) layout();
            }, 150);
        });

        return { layout: layout, append: append };
    }

    window.createScrapbookMasonry = createScrapbookMasonry;
})();
