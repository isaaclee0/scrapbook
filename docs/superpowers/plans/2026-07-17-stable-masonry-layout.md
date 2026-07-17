# Stable Masonry Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pins never move once placed — in board view and search — while keeping the masonry look.

**Architecture:** Replace CSS multi-column masonry (`column-count`, which rebalances every card on any change) with a shared absolute-positioning layout engine (`static/js/masonry.js`). Cards get `left`/`top` positions once, via shortest-column placement; infinite-scroll appends continue from current column heights without touching existing cards. Search additionally gets server-rendered `aspect-ratio` (dimensions added to its SQL queries) and loses all of its "fix heights after image load" JS.

**Tech Stack:** Vanilla JS (no deps), Jinja2 templates, Flask/MariaDB (two-line SQL change). No test framework exists in this repo — verification is via a browser harness (Task 2) and end-to-end checks on the running app (Task 8).

**Spec:** `docs/superpowers/specs/2026-07-17-stable-masonry-design.md`

---

## File map

| File | Change |
|---|---|
| `static/js/masonry.js` | **Create** — shared layout engine |
| `app.py` | Modify — add `ci.width`/`ci.height` to 2 search queries (~lines 1422, 1489) |
| `templates/search.html` | Modify — server aspect-ratio, delete height-correction JS, masonry init/append, CSS |
| `templates/board.html` | Modify — CSS, delete `applyPinSizeFromStorage`, masonry init, filter hook |
| `templates/base.html` | Modify — pin-size slider calls engine instead of `columnCount` (~line 1171) |
| `VERSION` | Modify — bump to 1.13.0 (final task) |

Key invariants the engine relies on (already true for board, made true for search in Tasks 3–4):

- Every `.image-container` gets an inline `aspect-ratio` at render time (real dims capped to height ∈ [w/2, 2w], else `3/4` fallback) and it is **never modified afterwards** — image `onload` only fades in and hides the skeleton.
- Card text uses system fonts (verified: Funnel Display is headings-only), so `offsetHeight` measured at placement time is final.

---

### Task 1: Create the layout engine `static/js/masonry.js`

**Files:**
- Create: `static/js/masonry.js`

- [ ] **Step 1: Create the directory and file with the complete engine**

`static/css/` exists but `static/js/` does not — create it. Write exactly:

```js
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
 * and highlight animations already own the transform property.
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
            var cap = breakpointCap(window.innerWidth);
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
                if (grid.clientWidth !== lastLayoutWidth) layout();
            }, 150);
        });

        return { layout: layout, append: append };
    }

    window.createScrapbookMasonry = createScrapbookMasonry;
})();
```

- [ ] **Step 2: Syntax-check the file**

Run: `node --check static/js/masonry.js`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add static/js/masonry.js
git commit -m "Add stable masonry layout engine (absolute positioning)"
```

---

### Task 2: Browser harness — prove the engine's stability guarantees

No JS test framework exists in this repo; verify the engine against a throwaway harness page **before** wiring it into templates. The harness lives in the session scratchpad, not the repo.

**Files:**
- Create: `<scratchpad>/masonry-harness.html` (throwaway; do not commit)

- [ ] **Step 1: Write the harness**

Copy the engine next to the harness so it can be served over HTTP (the browser pane may not load `file://` URLs):

```bash
cp static/js/masonry.js "<scratchpad>/masonry.js"
```

Then write the harness file (re-copy `masonry.js` after any engine fix):

```html
<title>masonry harness</title>
<style>
    #pinsGrid { padding: 20px; position: relative; background: #eee; }
    .pin-card { position: absolute; top: 0; left: 0; visibility: hidden;
                background: teal; color: white; border-radius: 8px; }
    #pinsGrid.masonry-ready .pin-card { visibility: visible; }
    .image-container { width: 100%; }
</style>
<div id="pinsGrid"></div>
<script src="masonry.js"></script>
<script>
    const grid = document.getElementById('pinsGrid');
    const ratios = [[3,4],[16,9],[1,1],[2,3],[4,5],[9,16],[3,2],[1,2]];
    function makeCard(i) {
        const div = document.createElement('div');
        div.className = 'pin-card';
        const [w,h] = ratios[i % ratios.length];
        div.innerHTML = `<div class="image-container" style="aspect-ratio:${w}/${h};"></div><div style="padding:12px">pin ${i}</div>`;
        div.dataset.i = i;
        return div;
    }
    for (let i = 0; i < 30; i++) grid.appendChild(makeCard(i));

    const masonry = window.createScrapbookMasonry(grid, {});
    masonry.layout();

    function snapshot() {
        const map = {};
        grid.querySelectorAll('.pin-card').forEach(c => {
            map[c.dataset.i] = c.style.left + '|' + c.style.top;
        });
        return map;
    }

    const results = {};

    // 1. Determinism: layout() twice => identical positions.
    const s1 = snapshot();
    masonry.layout();
    const s2 = snapshot();
    results.deterministic = JSON.stringify(s1) === JSON.stringify(s2);

    // 2. Append never moves existing cards.
    const before = snapshot();
    const newCards = [];
    for (let i = 30; i < 45; i++) { const c = makeCard(i); grid.appendChild(c); newCards.push(c); }
    masonry.append(newCards);
    const after = snapshot();
    results.appendStable = Object.keys(before).every(k => before[k] === after[k]);
    results.appendedPlaced = newCards.every(c => c.style.top !== '' && c.style.width !== '');

    // 3. No overlaps: every pair of cards in the same column is disjoint.
    const rects = [...grid.querySelectorAll('.pin-card')].map(c => c.getBoundingClientRect());
    results.noOverlap = rects.every((a, i) => rects.every((b, j) => i === j ||
        a.right <= b.left + 0.5 || b.right <= a.left + 0.5 ||
        a.bottom <= b.top + 0.5 || b.bottom <= a.top + 0.5));

    // 4. Grid height covers the tallest column.
    const maxBottom = Math.max(...rects.map(r => r.bottom));
    results.heightCovers = grid.getBoundingClientRect().bottom >= maxBottom - 0.5;

    console.log('HARNESS RESULTS ' + JSON.stringify(results));
</script>
```

- [ ] **Step 2: Run it in the browser pane and check results**

Serve the scratchpad (`python3 -m http.server 8765 --directory "<scratchpad>"` via Bash `run_in_background`), open `http://localhost:8765/masonry-harness.html` with `mcp__Claude_Browser__preview_start`, then `read_console_messages`.

Expected console line: `HARNESS RESULTS {"deterministic":true,"appendStable":true,"appendedPlaced":true,"noOverlap":true,"heightCovers":true}`

Also take a screenshot: cards should look like a masonry wall (staggered columns, 16px gutters, no gaps at top).

- [ ] **Step 3: Resize checks**

Use `mcp__Claude_Browser__resize_window` to width 700 (expect 2 columns) and 1300 (expect 4 with default options → capped 4? width 1300 ≤1600 → cap 4, requested 5 → 4 columns). Verify via screenshot after each resize. Then run in `javascript_tool`:

```js
// Height-only resize must NOT move cards (simulates mobile URL bar):
const before = [...document.querySelectorAll('.pin-card')].map(c => c.style.top);
window.dispatchEvent(new Event('resize')); // width unchanged
await new Promise(r => setTimeout(r, 300));
const after = [...document.querySelectorAll('.pin-card')].map(c => c.style.top);
JSON.stringify(before) === JSON.stringify(after)
```
Expected: `true`

If any check fails: fix `static/js/masonry.js`, re-run the harness, and amend the Task 1 commit (`git commit --amend --no-edit` after `git add static/js/masonry.js`).

---

### Task 3: Search queries return image dimensions

**Files:**
- Modify: `app.py:1422-1432` (`search()` pin query)
- Modify: `app.py:1489-1499` (`search_pins_api()` pin query)

- [ ] **Step 1: Add dimension columns to the `search()` pin query**

In `search()`, change the SELECT list of `pin_sql` from:

```python
            SELECT p.*, b.name as board_name, s.name as section_name,
                   ci.cached_filename, ci.cache_status
```

to:

```python
            SELECT p.*, b.name as board_name, s.name as section_name,
                   ci.cached_filename, ci.cache_status,
                   ci.width as cached_width, ci.height as cached_height
```

- [ ] **Step 2: Make the identical change in `search_pins_api()`**

Same two-line SELECT header appears in `search_pins_api()` (~line 1490) — apply the identical replacement. (The `LEFT JOIN cached_images ci ... AND ci.cache_status = 'cached'` join means dimensions are NULL for uncached pins; the templates fall back to `3/4` for those.)

- [ ] **Step 3: Sanity-check**

Run: `python -c "import ast; ast.parse(open('app.py').read())" && grep -c "ci.width as cached_width" app.py`
Expected: `2`

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Return cached image dimensions from search queries"
```

---

### Task 4: search.html — server-rendered aspect ratio, no post-load corrections

**Files:**
- Modify: `templates/search.html`

- [ ] **Step 1: Replace the head script (lines 4–37)**

Replace the entire `correctImageContainerHeight` `<script>` block at the top of the content block with the dimension reporter (same as board.html):

```html
<script>
    // Reports dimensions of externally-loaded images to the server so they
    // can be cached and stored. NEVER modifies the rendered aspect-ratio —
    // the server-rendered value is the single source of truth, which is what
    // keeps the masonry layout from shifting after image load.
    function reportImageDimensions(imgElement) {
        if (!imgElement || !imgElement.naturalWidth || !imgElement.naturalHeight) return;
        const isExternal = !imgElement.src.startsWith(window.location.origin + '/cached/');
        if (!isExternal) return;
        const pinCard = imgElement.closest('.pin-card');
        const pinId = pinCard?.getAttribute('data-pin-id');
        if (!pinId) return;
        fetch(`/save-pin-dimensions/${pinId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                width: imgElement.naturalWidth,
                height: imgElement.naturalHeight
            }),
            keepalive: true
        }).catch(() => {});
    }
</script>
```

- [ ] **Step 2: Update the Jinja pin card (lines ~79–118)**

In the `{% for pin in matching_pins %}` card:

a. Replace the data attributes `data-image-width="{{ pin.final_width or '' }}"` and `data-image-height="{{ pin.final_height or '' }}"` with:

```html
                 data-cached-width="{{ pin.cached_width or '' }}"
                 data-cached-height="{{ pin.cached_height or '' }}"
```

b. Replace the plain `<div class="relative overflow-hidden image-container">` with the aspect-ratio version (identical caps to board.html):

```html
                    {% if pin.cached_width and pin.cached_height %}
                    {% set pw = pin.cached_width | int %}
                    {% set ph_capped = [pin.cached_height | int, pw * 2] | min %}
                    {% set ph = [ph_capped, pw // 2] | max %}
                    <div class="relative overflow-hidden image-container" style="aspect-ratio: {{ pw }}/{{ ph }};">
                    {% else %}
                    <div class="relative overflow-hidden image-container" style="aspect-ratio: 3/4;">
                    {% endif %}
```

c. In both `<img>` tags (cached and non-cached), replace `correctImageContainerHeight(this);` in the `onload` attribute with `reportImageDimensions(this);` so they read:

```
onload="this.classList.add('loaded'); this.previousElementSibling.style.display='none'; reportImageDimensions(this);"
```

(`onerror` handlers stay unchanged.)

- [ ] **Step 3: Replace the masonry CSS (lines ~247–280 and the image rules)**

a. Replace the `#pinsGrid` rule and its four `@media` blocks with:

```css
/* Stable masonry: absolutely positioned cards laid out by /static/js/masonry.js.
   See docs/superpowers/specs/2026-07-17-stable-masonry-design.md */
#pinsGrid {
    padding: 20px;
    position: relative;
}
```

b. Replace the `.pin-card` rule (`display: inline-block; width: 100%; margin-bottom: 16px; ...`) with:

```css
.pin-card {
    display: block;
    position: absolute;
    top: 0;
    left: 0;
    /* Hidden until the first layout() positions the cards */
    visibility: hidden;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    transition: transform 0.2s, box-shadow 0.2s;
    background: white;
    contain: layout style;
}

#pinsGrid.masonry-ready .pin-card {
    visibility: visible;
}
```

c. In `.image-container`, replace the comment line `/* Height will be set by JavaScript based on image dimensions */` and `min-height: 150px;` with (matching board.html):

```css
    /* Height driven by CSS aspect-ratio set inline per-pin — never JS */
    min-height: 150px;
    max-height: 500px;
```

d. In `.pin-image`, delete the line `max-height: 400px; /* Prevent images from loading too large initially */` (the aspect-ratio container now bounds the image; a 400px cap would leave a gap under tall images).

- [ ] **Step 4: Delete the correction/reservation JS**

In the bottom `<script>` block delete these functions entirely: `reserveImageSpace()` and `correctContainerHeight()` — and in the `DOMContentLoaded` handler delete the `reserveImageSpace();` call and its comment. (`waitForLayoutStabilization` and `handlePinHighlighting` stay.)

- [ ] **Step 5: Hook infinite scroll into the engine**

In `loadMorePins()`, replace:

```js
                // Append new pins to the grid
                data.pins.forEach(pin => {
                    const pinCard = createPinCard(pin);
                    pinsGrid.appendChild(pinCard);
                });
                
                currentPinOffset += data.pins.length;
                hasMorePins = data.has_more;
                
                // Reserve space for new images
                setTimeout(() => reserveImageSpace(), 100);
```

with:

```js
                // Append new pins to the grid; the masonry engine places them
                // below existing pins without moving anything already on screen.
                const newCards = [];
                data.pins.forEach(pin => {
                    const pinCard = createPinCard(pin);
                    pinsGrid.appendChild(pinCard);
                    newCards.push(pinCard);
                });

                currentPinOffset += data.pins.length;
                hasMorePins = data.has_more;

                if (window.scrapbookMasonry) window.scrapbookMasonry.append(newCards);
```

- [ ] **Step 6: Update `createPinCard()`**

a. Replace the two data-attribute lines:

```js
    div.setAttribute('data-image-width', pin.final_width || '');
    div.setAttribute('data-image-height', pin.final_height || '');
```

with:

```js
    div.setAttribute('data-cached-width', pin.cached_width || '');
    div.setAttribute('data-cached-height', pin.cached_height || '');
```

b. Before the `div.innerHTML = ...` assignment, insert the aspect-ratio computation (same caps as the Jinja template and board.html):

```js
    // Server-provided dimensions drive a fixed aspect-ratio box — the single
    // source of truth for layout. Same caps as the Jinja template (height
    // clamped to [w/2, 2w]); 3/4 portrait fallback when dims are unknown.
    let aspectRatio = '3/4';
    const pw = parseInt(pin.cached_width);
    const ph = parseInt(pin.cached_height);
    if (pw > 0 && ph > 0) {
        const phCapped = Math.min(ph, pw * 2);
        const phFinal = Math.max(phCapped, Math.floor(pw / 2));
        aspectRatio = `${pw}/${phFinal}`;
    }
```

c. In the template string, change `<div class="relative overflow-hidden image-container">` to:

```js
            <div class="relative overflow-hidden image-container" style="aspect-ratio: ${aspectRatio};">
```

d. In the `<img>` `onload` attribute inside the template string, replace `correctImageContainerHeight(this);` with `reportImageDimensions(this);`.

- [ ] **Step 7: Initialize the engine right after the grid markup**

Immediately after the `</div>` that closes `<div class="masonry-grid" id="pinsGrid">` (before the `searchLoadingIndicator` div), insert:

```html
        <script src="{{ url_for('static', filename='js/masonry.js') }}"></script>
        <script>
            // Runs synchronously during parsing so the first paint already
            // shows final positions (cards are visibility:hidden until then).
            (function () {
                var grid = document.getElementById('pinsGrid');
                if (grid && window.createScrapbookMasonry) {
                    window.scrapbookMasonry = window.createScrapbookMasonry(grid, {});
                    window.scrapbookMasonry.layout();
                }
            })();
        </script>
```

(Search has no pin-size control, so the engine's default of 5 columns capped by the breakpoints reproduces the old media queries exactly.)

- [ ] **Step 8: Confirm nothing references the deleted functions**

Run: `grep -n "correctImageContainerHeight\|reserveImageSpace\|correctContainerHeight\|final_width\|final_height" templates/search.html`
Expected: no output.

- [ ] **Step 9: Commit**

```bash
git add templates/search.html
git commit -m "Search: server-rendered aspect ratios + stable masonry engine"
```

---

### Task 5: board.html — swap multicol for the engine

**Files:**
- Modify: `templates/board.html`

- [ ] **Step 1: Replace the masonry CSS (lines ~467–512)**

Replace the `#pinsGrid` rule, its four `@media (max-width: ...)` blocks, and the `.pin-card` rule with:

```css
    /* Stable masonry: absolutely positioned cards laid out by /static/js/masonry.js.
       See docs/superpowers/specs/2026-07-17-stable-masonry-design.md */
    #pinsGrid {
        padding: 20px;
        position: relative;
    }

    .pin-card {
        display: block;
        position: absolute;
        top: 0;
        left: 0;
        /* Hidden until the first layout() positions the cards */
        visibility: hidden;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        transition: transform 0.2s, box-shadow 0.2s;
        background: white;
        /* Contain layout to prevent shifts from propagating to other cards */
        contain: layout style;
    }

    #pinsGrid.masonry-ready .pin-card {
        visibility: visible;
    }
```

(Removed: `column-count`/`column-gap`, `break-inside: avoid`, `display: inline-block`, `width: 100%`, `margin-bottom: 16px`, `position: relative` — the engine sets width/position; gap is the engine's `GAP`.)

- [ ] **Step 2: Initialize the engine right after the grid markup**

Immediately after the `</div>` that closes `<div class="masonry-grid" id="pinsGrid">` (line ~158), insert:

```html
    <script src="{{ url_for('static', filename='js/masonry.js') }}"></script>
    <script>
        // Runs synchronously during parsing so the first paint already shows
        // final positions — this also replaces the old post-paint
        // applyPinSizeFromStorage() column switch (saved pin size is read
        // *before* the first layout).
        (function () {
            var grid = document.getElementById('pinsGrid');
            if (grid && window.createScrapbookMasonry) {
                window.scrapbookMasonry = window.createScrapbookMasonry(grid, {
                    // Saved pin size drives column count (Tiny=7 … Huge=3),
                    // capped by viewport breakpoints inside the engine.
                    columnCount: function () {
                        var size = parseInt(localStorage.getItem('boardPinSize'), 10) || 3;
                        return { 1: 7, 2: 6, 3: 5, 4: 4, 5: 3 }[size] || 5;
                    }
                });
                window.scrapbookMasonry.layout();
            }
        })();
    </script>
```

- [ ] **Step 3: Delete `applyPinSizeFromStorage`**

Delete the whole `applyPinSizeFromStorage()` function (lines ~1097–1124) **and** its call + comment in the `DOMContentLoaded` handler (lines ~1128–1129):

```js
        // Apply pin size immediately from localStorage before any layout operations
        applyPinSizeFromStorage();
```

(The `--pin-width` CSS variable it also set is still maintained by `updatePinSize()` in base.html.)

- [ ] **Step 4: Relayout at the end of `applyCurrentSectionFilter()`**

At the very end of `applyCurrentSectionFilter()` (line ~2185, after the `if (shownCount === 0 ...) { ... } else { ... }` block, still inside the function), add:

```js
        // Re-place visible cards after visibility changed. Deterministic:
        // when nothing changed (e.g. filter 'all' after an infinite-scroll
        // append), existing cards resolve to identical positions and only
        // new cards gain positions.
        if (window.scrapbookMasonry) window.scrapbookMasonry.layout();
```

This single hook covers both section switching (including `fetchSectionPins` appends) and the board's infinite scroll, because `setupBoardPinsLazyLoad` already calls `applyCurrentSectionFilter()` after appending each batch (line ~1211).

- [ ] **Step 5: Confirm no dangling references**

Run: `grep -n "applyPinSizeFromStorage\|columnCount" templates/board.html`
Expected: only the `columnCount:` option inside the new init script from Step 2.

- [ ] **Step 6: Commit**

```bash
git add templates/board.html
git commit -m "Board: swap CSS multicol for stable masonry engine"
```

---

### Task 6: base.html — pin-size slider drives the engine

**Files:**
- Modify: `templates/base.html:1171-1184`

- [ ] **Step 1: Replace the columnCount block in `updatePinSize()`**

Replace:

```js
                    // For masonry layout: adjust column count based on size
                    // Smaller size = more columns, larger size = fewer columns
                    const pinsGrid = document.getElementById('pinsGrid');
                    if (pinsGrid) {
                        const columnCounts = {
                            1: 7,  // Tiny - most columns
                            2: 6,  // Small
                            3: 5,  // Medium (default)
                            4: 4,  // Large
                            5: 3   // Huge - fewest columns
                        };
                        const columnCount = columnCounts[sizeLevel];
                        pinsGrid.style.columnCount = columnCount;
                    }
```

with:

```js
                    // Masonry pages: relayout with the new pin size (the
                    // engine reads boardPinSize from localStorage, which was
                    // just saved above).
                    if (window.scrapbookMasonry) {
                        window.scrapbookMasonry.layout();
                    }
```

(The `--pin-width` fallback block below it stays. The initial `updatePinSize()` call at DOMContentLoaded becomes an idempotent relayout — same inputs, same positions.)

- [ ] **Step 2: Confirm no other columnCount writers remain**

Run: `grep -rn "style.columnCount\|columnCount =" templates/`
Expected: no output (the `columnCount:` option key in board.html's init is not matched by these patterns).

- [ ] **Step 3: Commit**

```bash
git add templates/base.html
git commit -m "Pin-size slider triggers masonry relayout instead of columnCount"
```

---

### Task 7: Static review of the integrated templates

- [ ] **Step 1: Render-check the templates compile**

Run: `python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))
for t in ['board.html', 'search.html', 'base.html']:
    env.get_template(t)
    print(t, 'OK')
"`
Expected: three `OK` lines (catches Jinja syntax errors; runtime vars aren't evaluated).

- [ ] **Step 2: Grep the stability invariants**

```bash
grep -n "column-count" templates/board.html templates/search.html   # expect: none
grep -c "aspect-ratio" templates/search.html                        # expect: >= 3 (Jinja if/else + createPinCard)
grep -n "masonry.js" templates/board.html templates/search.html     # expect: one hit each
```

- [ ] **Step 3: Commit (only if fixes were needed)**

---

### Task 8: End-to-end verification on the running app

Start the app (`docker compose up -d` if `.env` exists, else `./dev.sh` — check `dev.sh` for the local run recipe; DB required). Then drive it in the browser pane. If neither works on this machine, report the blocker instead of skipping.

- [ ] **Step 1: Board view — zero layout shift after first paint**

Navigate to a board with many pins. In `javascript_tool`, install a CLS observer as early as possible, then reload and read it after the page settles:

```js
// run right after navigation:
window.__cls = 0;
new PerformanceObserver(list => {
    for (const e of list.getEntries()) if (!e.hadRecentInput) window.__cls += e.value;
}).observe({ type: 'layout-shift', buffered: true });
```

After images finish loading: `window.__cls` — Expected: `< 0.02` (essentially zero; the buffered flag captures shifts from before the observer ran).

- [ ] **Step 2: Board infinite scroll — existing pins do not move**

```js
const before = new Map([...document.querySelectorAll('.pin-card')]
    .map(c => [c.id, c.getBoundingClientRect().top + window.scrollY + '|' + c.getBoundingClientRect().left]));
window.scrollTo(0, document.body.scrollHeight); // triggers a 40-pin batch
await new Promise(r => setTimeout(r, 2500));
const moved = [...before].filter(([id, pos]) => {
    const el = document.getElementById(id);
    if (!el) return true;
    const r = el.getBoundingClientRect();
    return (r.top + window.scrollY + '|' + r.left) !== pos;
});
moved.length
```
Expected: `0` (and more `.pin-card` elements exist than before).

- [ ] **Step 3: Search — same two checks**

Search for a term with >10 results (so infinite scroll fires). Repeat Steps 1–2 on `/search?q=...`. Expected: CLS < 0.02; `moved.length === 0` after a scroll-triggered batch of 10.

- [ ] **Step 4: Interactions**

- Change pin size via the slider on a board → one clean redistribution, no drift afterwards.
- Click a section circle → filtered pins redistribute; click "All" → original layout returns (determinism).
- Resize browser window across a breakpoint → one redistribution.
- Open a search result's "Take me to board" (`?highlight=`) link → page scrolls to and pulses the right pin.
- Navigate into a pin and back → scroll position restored to the same pins.
- Board with pins lacking cached dimensions (3/4 fallback) → still no movement on image load.
- Search with no results → empty-state message renders (no JS errors from missing grid).

Check `read_console_messages(onlyErrors: true)` after each flow — expect no errors.

- [ ] **Step 5: Fix anything found, commit fixes individually**

---

### Task 9: Version bump and wrap-up

**Files:**
- Modify: `VERSION`

- [ ] **Step 1: Bump version**

`VERSION` currently reads `1.12.2`. Write `1.13.0` (new feature).

- [ ] **Step 2: Commit**

```bash
git add VERSION
git commit -m "Stable masonry layout for board and search; bump to 1.13.0"
```

- [ ] **Step 3: Use superpowers:verification-before-completion, then superpowers:finishing-a-development-branch**
