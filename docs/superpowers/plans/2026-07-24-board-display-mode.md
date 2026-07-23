# Board "Display Mode" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Normal | Display" toggle to both a board's pin grid (`board.html`) and the home page's Pins feed (`boards.html`) that switches the grid into a dark, title-less, rounded-image gallery view with a subtle scroll-linked parallax effect.

**Architecture:** Pure frontend change. Display mode is a CSS class (`display-mode`) toggled on the existing masonry grid container, plus a small addition to the shared `static/js/masonry.js` engine so each card knows its column (needed for the parallax offset). No new routes, no DB changes, no new pin data — same cards, same pagination, just a skin plus a scroll listener.

**Tech Stack:** Flask/Jinja2 templates, vanilla JS (existing inline `<script>` blocks in `board.html`/`boards.html`), the existing `static/js/masonry.js` engine, `localStorage` for the shared `pinDisplayMode` preference.

**Design doc:** `docs/superpowers/specs/2026-07-24-board-display-mode-design.md`

---

## Verified local-testing facts (use these, don't rediscover them)

- Local dev stack: `docker compose up -d` (already running). Board pages require auth.
- Mint a session JWT and set it via the Browser pane's JS tool (works despite the cookie being `HttpOnly` server-side — that flag only blocks JS from touching an *existing* HttpOnly cookie, not creating a fresh same-named one):
  ```bash
  docker compose exec -T web python -c "from auth_utils import generate_session_token; print(generate_session_token(16, 'isaac@leemail.com.au'))"
  ```
  then in the browser page context: `document.cookie = "session_token=<token>; path=/";`
- User id **16** (isaac@leemail.com.au) owns all boards/pins in the local data copy. User id 2 (shelley@leemail.com.au) owns none — using id 2 will 404 on every board.
- **Board 217** ("Faith", 3171 pins, user 16) is a good populous board for testing infinite scroll and parallax at `http://localhost:8000/board/217`.
- Home page Pins feed: `http://localhost:8000/` → click "Pins" in the Boards|Pins switcher.

---

## File structure

| File | Change |
|---|---|
| `static/js/masonry.js` | Stamp `data-parallax-col` on each card in `place()` — one change, used by both pages' masonry instances |
| `templates/board.html` | Toggle markup near the board title, CSS restyle rules, toggle JS, parallax JS |
| `templates/boards.html` | Toggle markup beneath the Boards\|Pins switcher (shown only in Pins mode), CSS restyle rules, toggle JS, parallax JS |

---

### Task 1: Stamp column index in the masonry engine

**Files:**
- Modify: `static/js/masonry.js:97-113`

- [ ] **Step 1: Add the `data-parallax-col` stamp inside `place()`**

Find:

```js
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
```

Replace with:

```js
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
```

- [ ] **Step 2: Verify via the running board page**

Log in and load a populated board (see the testing facts above), then in the browser page context run:

```js
document.querySelectorAll('#pinsGrid .pin-card[data-parallax-col]').length
```

Expected: a number equal to the number of currently-rendered pin cards (e.g. matches `document.querySelectorAll('#pinsGrid .pin-card').length`) — every visible card got stamped.

- [ ] **Step 3: Commit**

```bash
git add static/js/masonry.js
git commit -m "Stamp column index on masonry cards for scroll-linked parallax"
```

---

### Task 2: `board.html` — toggle + dark restyle (no motion yet)

**Files:**
- Modify: `templates/board.html:598-626` (title row markup)
- Modify: `templates/board.html:560-572` (CSS, before `</style>`)
- Modify: `templates/board.html:1099-1144` (`DOMContentLoaded` handler)
- Modify: `templates/board.html:1144-1146` (new top-level function, between `DOMContentLoaded` and `setupBoardPinsLazyLoad`)

- [ ] **Step 1: Add the toggle markup next to the board title**

Find:

```html
        <div class="mb-6 flex items-center justify-between">
            <div class="flex items-center space-x-3">
                <h1 class="text-3xl font-bold text-gray-900">{{ board.name }}</h1>
                <div class="relative">
                    <button
                        class="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-all duration-200"
                        onclick="toggleBoardSettings()">
                        <i class="fas fa-pencil-alt text-lg"></i>
                    </button>
                    <div id="boardSettingsMenu"
                        class="hidden absolute top-full left-0 mt-2 w-48 bg-white rounded-lg shadow-xl border border-gray-200 py-2 z-50 flex flex-col">
                        <button id="processingStatusBtn" disabled
                            class="px-4 py-2 text-left text-sm text-gray-400 cursor-not-allowed whitespace-nowrap">
                            <span id="processingStatusText">🎨 Ready</span>
                        </button>
                        <button onclick="showRenameBoardModal()"
                            class="px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors whitespace-nowrap">Rename
                            Board</button>
                        <button onclick="showMoveBoardModal()"
                            class="px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors whitespace-nowrap">Convert
                            to Section</button>
                        <button onclick="showDeleteBoardModal()"
                            class="px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 transition-colors whitespace-nowrap">Delete
                            Board</button>
                    </div>
                </div>
            </div>

        </div>
```

Replace the blank line between the two `</div>` tags so the closing looks like this (everything above `</div>\n\n        </div>` is unchanged — only the blank line gets replaced):

```html
        <div class="mb-6 flex items-center justify-between">
            <div class="flex items-center space-x-3">
                <h1 class="text-3xl font-bold text-gray-900">{{ board.name }}</h1>
                <div class="relative">
                    <button
                        class="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-all duration-200"
                        onclick="toggleBoardSettings()">
                        <i class="fas fa-pencil-alt text-lg"></i>
                    </button>
                    <div id="boardSettingsMenu"
                        class="hidden absolute top-full left-0 mt-2 w-48 bg-white rounded-lg shadow-xl border border-gray-200 py-2 z-50 flex flex-col">
                        <button id="processingStatusBtn" disabled
                            class="px-4 py-2 text-left text-sm text-gray-400 cursor-not-allowed whitespace-nowrap">
                            <span id="processingStatusText">🎨 Ready</span>
                        </button>
                        <button onclick="showRenameBoardModal()"
                            class="px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors whitespace-nowrap">Rename
                            Board</button>
                        <button onclick="showMoveBoardModal()"
                            class="px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors whitespace-nowrap">Convert
                            to Section</button>
                        <button onclick="showDeleteBoardModal()"
                            class="px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 transition-colors whitespace-nowrap">Delete
                            Board</button>
                    </div>
                </div>
            </div>

            <div class="pin-display-switcher" role="group" aria-label="Pin display mode">
                <button type="button" data-mode="normal" class="pin-display-btn active">Normal</button>
                <button type="button" data-mode="display" class="pin-display-btn">Display</button>
            </div>
        </div>
```

- [ ] **Step 2: Add the CSS**

Find (the end of the `<style>` block):

```css
    .board-input:focus {
        outline: none;
        border-color: #007bff;
    }
</style>
```

Replace with:

```css
    .board-input:focus {
        outline: none;
        border-color: #007bff;
    }

    .pin-display-switcher {
        display: inline-flex;
        background: #e5e7eb;
        border-radius: 8px;
        padding: 3px;
        gap: 2px;
    }
    .pin-display-btn {
        border: none;
        background: transparent;
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 600;
        color: #6b7280;
        cursor: pointer;
        transition: all 0.15s;
    }
    .pin-display-btn:hover {
        color: #374151;
    }
    .pin-display-btn.active {
        background: white;
        color: #111827;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
    }

    #pinsGrid.display-mode {
        background-color: #1a1a2e;
        border-radius: 12px;
        padding: 8px;
    }
    #pinsGrid.display-mode .pin-card {
        background: transparent;
        box-shadow: none;
    }
    #pinsGrid.display-mode .pin-card:not([data-colors-extracted="true"]) {
        background: transparent;
        border: none;
    }
    #pinsGrid.display-mode .pin-card:hover {
        transform: none;
        box-shadow: none;
    }
    #pinsGrid.display-mode .pin-info {
        display: none;
    }
    #pinsGrid.display-mode .image-container > span {
        display: none;
    }
</style>
```

Note on the last rule: the section-name badge (e.g. `{{ pin.section_name }}`) is rendered as a plain `<span class="absolute top-2 left-2 ...">` directly inside `.image-container` — it has no dedicated class of its own (the `.section-badge`/`.source-link-icon` CSS rules that already exist earlier in this file are unused dead code, not applied to any element in this template — confirmed by grepping the file for those class names in markup and finding no matches). `.image-container > span` is what actually reaches the badge.

- [ ] **Step 3: Add the toggle JS**

Find (immediately after the `DOMContentLoaded` handler closes, before the infinite-scroll comment):

```js
        // Start automatic processing after board loads
        setTimeout(() => {
            startAutomaticProcessing();
        }, 1000);
    }
});

    // Infinite scroll for loading more pins on board page
    function setupBoardPinsLazyLoad(initialCount, totalCount) {
```

Replace with:

```js
        // Start automatic processing after board loads
        setTimeout(() => {
            startAutomaticProcessing();
        }, 1000);
    }
});

    function getPinDisplayMode() {
        return localStorage.getItem('pinDisplayMode') === 'display' ? 'display' : 'normal';
    }

    // Infinite scroll for loading more pins on board page
    function setupBoardPinsLazyLoad(initialCount, totalCount) {
```

Now find the top of the `DOMContentLoaded` handler:

```js
    // Initialize the board
    document.addEventListener('DOMContentLoaded', function () {
        initializeSectionFiltering();
        initializeBoardManagement();
```

Replace with:

```js
    // Initialize the board
    document.addEventListener('DOMContentLoaded', function () {
        initializeSectionFiltering();
        initializeBoardManagement();

        (function () {
            var displayMode = getPinDisplayMode();
            document.querySelectorAll('.pin-display-btn').forEach(function (btn) {
                btn.classList.toggle('active', btn.getAttribute('data-mode') === displayMode);
                btn.addEventListener('click', function () {
                    var mode = btn.getAttribute('data-mode');
                    localStorage.setItem('pinDisplayMode', mode);
                    document.querySelectorAll('.pin-display-btn').forEach(function (b) {
                        b.classList.toggle('active', b === btn);
                    });
                    var pinsGrid = document.getElementById('pinsGrid');
                    if (pinsGrid) pinsGrid.classList.toggle('display-mode', mode === 'display');
                });
            });
        })();
```

Note: `getPinDisplayMode()` is defined further down in the file (Step 3 above), but that's fine — function declarations are hoisted, so it's callable from `DOMContentLoaded` regardless of source order.

- [ ] **Step 4: Also apply the class before the very first paint**

The grid is server-rendered with pins already in the HTML, so without this the page would flash white-card mode for an instant before `DOMContentLoaded` fires. Find the synchronous masonry-init IIFE:

```html
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

Replace with:

```html
    <script>
        // Runs synchronously during parsing so the first paint already shows
        // final positions — this also replaces the old post-paint
        // applyPinSizeFromStorage() column switch (saved pin size is read
        // *before* the first layout).
        (function () {
            var grid = document.getElementById('pinsGrid');
            if (grid && localStorage.getItem('pinDisplayMode') === 'display') {
                grid.classList.add('display-mode');
            }
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

- [ ] **Step 5: Verify in the browser**

Log in (see testing facts) and load `http://localhost:8000/board/217`. Confirm:
- A "Normal | Display" pill sits to the right of the board title.
- Clicking "Display" immediately turns the grid dark navy, hides pin titles and section badges, and cards lose their white background/shadow/hover-lift — no page reload, no network request beyond what already happens.
- Clicking "Normal" reverts it.
- Reload the page after leaving it on "Display" — it should load already in display mode (no flash of the white-card layout).

- [ ] **Step 6: Commit**

```bash
git add templates/board.html
git commit -m "Add pin display-mode toggle and dark restyle to board page"
```

---

### Task 3: `board.html` — scroll-linked parallax

**Files:**
- Modify: `templates/board.html` (new functions + extend the toggle click handler from Task 2)

- [ ] **Step 1: Add the parallax functions**

Find (added in Task 2, Step 3):

```js
    function getPinDisplayMode() {
        return localStorage.getItem('pinDisplayMode') === 'display' ? 'display' : 'normal';
    }

    // Infinite scroll for loading more pins on board page
    function setupBoardPinsLazyLoad(initialCount, totalCount) {
```

Replace with:

```js
    function getPinDisplayMode() {
        return localStorage.getItem('pinDisplayMode') === 'display' ? 'display' : 'normal';
    }

    var pinDisplayParallaxHandler = null;
    var pinDisplayParallaxThrottle = null;

    // Offsets each display-mode card by a small amount based on how far its
    // center sits from the viewport's vertical center, varying slightly per
    // column. Uses each card's live position (not raw scrollY), so the
    // effect stays perceptible throughout an arbitrarily long/infinite-
    // scrolling page instead of saturating near the top.
    function applyPinDisplayParallax() {
        var pinsGrid = document.getElementById('pinsGrid');
        if (!pinsGrid || !pinsGrid.classList.contains('display-mode')) return;
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
        var viewportCenter = window.innerHeight / 2;
        var cards = pinsGrid.querySelectorAll('.pin-card[data-parallax-col]');
        for (var i = 0; i < cards.length; i++) {
            var card = cards[i];
            var col = parseInt(card.dataset.parallaxCol, 10) || 0;
            var speed = 0.03 + (col % 3) * 0.015;
            var rect = card.getBoundingClientRect();
            var cardCenter = rect.top + rect.height / 2;
            var offset = Math.max(-18, Math.min(18, (viewportCenter - cardCenter) * speed));
            card.style.transform = 'translateY(' + offset.toFixed(1) + 'px)';
        }
    }

    function startPinDisplayParallax() {
        if (pinDisplayParallaxHandler) return;
        pinDisplayParallaxHandler = function () {
            if (pinDisplayParallaxThrottle) return;
            pinDisplayParallaxThrottle = setTimeout(function () {
                pinDisplayParallaxThrottle = null;
                applyPinDisplayParallax();
            }, 200);
        };
        window.addEventListener('scroll', pinDisplayParallaxHandler, { passive: true });
        applyPinDisplayParallax();
    }

    function stopPinDisplayParallax() {
        if (pinDisplayParallaxHandler) {
            window.removeEventListener('scroll', pinDisplayParallaxHandler);
            pinDisplayParallaxHandler = null;
        }
        if (pinDisplayParallaxThrottle) {
            clearTimeout(pinDisplayParallaxThrottle);
            pinDisplayParallaxThrottle = null;
        }
        var pinsGrid = document.getElementById('pinsGrid');
        if (pinsGrid) {
            var cards = pinsGrid.querySelectorAll('.pin-card[data-parallax-col]');
            for (var i = 0; i < cards.length; i++) {
                cards[i].style.transform = '';
            }
        }
    }

    // Infinite scroll for loading more pins on board page
    function setupBoardPinsLazyLoad(initialCount, totalCount) {
```

- [ ] **Step 2: Wire start/stop into the toggle handler and initial load**

Find the toggle-wiring IIFE added in Task 2:

```js
        (function () {
            var displayMode = getPinDisplayMode();
            document.querySelectorAll('.pin-display-btn').forEach(function (btn) {
                btn.classList.toggle('active', btn.getAttribute('data-mode') === displayMode);
                btn.addEventListener('click', function () {
                    var mode = btn.getAttribute('data-mode');
                    localStorage.setItem('pinDisplayMode', mode);
                    document.querySelectorAll('.pin-display-btn').forEach(function (b) {
                        b.classList.toggle('active', b === btn);
                    });
                    var pinsGrid = document.getElementById('pinsGrid');
                    if (pinsGrid) pinsGrid.classList.toggle('display-mode', mode === 'display');
                });
            });
        })();
```

Replace with:

```js
        (function () {
            var displayMode = getPinDisplayMode();
            document.querySelectorAll('.pin-display-btn').forEach(function (btn) {
                btn.classList.toggle('active', btn.getAttribute('data-mode') === displayMode);
                btn.addEventListener('click', function () {
                    var mode = btn.getAttribute('data-mode');
                    localStorage.setItem('pinDisplayMode', mode);
                    document.querySelectorAll('.pin-display-btn').forEach(function (b) {
                        b.classList.toggle('active', b === btn);
                    });
                    var pinsGrid = document.getElementById('pinsGrid');
                    if (pinsGrid) pinsGrid.classList.toggle('display-mode', mode === 'display');
                    if (mode === 'display') {
                        startPinDisplayParallax();
                    } else {
                        stopPinDisplayParallax();
                    }
                });
            });
            if (displayMode === 'display') {
                startPinDisplayParallax();
            }
        })();
```

- [ ] **Step 3: Verify motion in the browser**

Load `http://localhost:8000/board/217` (populous board, good for scrolling) already in display mode (or switch to it). Then:

- Read `document.querySelector('#pinsGrid .pin-card[data-parallax-col]').style.transform` before and after scrolling — confirm it changes and is a small `translateY(...)` value (not empty, not huge).
- Scroll down a substantial amount (this board has 3000+ pins) and confirm the offset keeps varying (not stuck at a capped value) — sample the transform of a card at two very different scroll depths (e.g. near the top vs. after scrolling several thousand pixels) and confirm both show a small, non-zero, non-identical offset relative to their own on-screen position.
- Toggle back to "Normal" and confirm `style.transform` is cleared back to `''` on cards, and that scrolling no longer changes anything (listener removed).
- Confirm cards never visually overlap or jump during scrolling — the offset is capped at ±18px, well under the 16px inter-card gap plus card size, so it should never look broken.

- [ ] **Step 4: Commit**

```bash
git add templates/board.html
git commit -m "Add scroll-linked parallax to board page display mode"
```

---

### Task 4: `boards.html` — toggle + dark restyle (no motion yet)

**Files:**
- Modify: `templates/boards.html:42-45` (toggle markup)
- Modify: `templates/boards.html:490-499` (CSS, before `</style>`)
- Modify: `templates/boards.html:641-647` (toggle JS + wiring)
- Modify: `templates/boards.html:726-758` (`showHomeView()`)

- [ ] **Step 1: Add the toggle markup beneath the Boards\|Pins switcher**

Find:

```html
        <div class="home-view-switcher" role="group" aria-label="Home view">
            <button type="button" data-view="boards" class="home-view-btn active">Boards</button>
            <button type="button" data-view="pins" class="home-view-btn">Pins</button>
        </div>
```

Replace with:

```html
        <div class="home-view-stack">
            <div class="home-view-switcher" role="group" aria-label="Home view">
                <button type="button" data-view="boards" class="home-view-btn active">Boards</button>
                <button type="button" data-view="pins" class="home-view-btn">Pins</button>
            </div>
            <div class="pin-display-switcher hidden" id="pinDisplaySwitcher" role="group" aria-label="Pin display mode">
                <button type="button" data-mode="normal" class="pin-display-btn active">Normal</button>
                <button type="button" data-mode="display" class="pin-display-btn">Display</button>
            </div>
        </div>
```

`#pinDisplaySwitcher` starts `hidden` because the page's default view is Boards mode — `showHomeView()` (Step 4 below) takes over from there.

- [ ] **Step 2: Add the CSS**

Find (the end of the `<style>` block):

```css
        .home-pins-empty {
            text-align: center;
            padding: 80px 20px;
            color: #6b7280;
            font-size: 16px;
        }
        .hidden {
            display: none !important;
        }
    </style>
```

Replace with:

```css
        .home-pins-empty {
            text-align: center;
            padding: 80px 20px;
            color: #6b7280;
            font-size: 16px;
        }
        .hidden {
            display: none !important;
        }

        .home-view-stack {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 6px;
        }
        .pin-display-switcher {
            display: inline-flex;
            background: #e5e7eb;
            border-radius: 8px;
            padding: 3px;
            gap: 2px;
        }
        .pin-display-btn {
            border: none;
            background: transparent;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            color: #6b7280;
            cursor: pointer;
            transition: all 0.15s;
        }
        .pin-display-btn:hover {
            color: #374151;
        }
        .pin-display-btn.active {
            background: white;
            color: #111827;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
        }

        #homePinsGrid.display-mode {
            background-color: #1a1a2e;
            border-radius: 12px;
            padding: 8px;
        }
        #homePinsGrid.display-mode .pin-card {
            background: transparent;
            box-shadow: none;
        }
        #homePinsGrid.display-mode .pin-card:not([data-colors-extracted="true"]) {
            background: transparent;
            border: none;
        }
        #homePinsGrid.display-mode .pin-card:hover {
            transform: none;
            box-shadow: none;
        }
        #homePinsGrid.display-mode .pin-info {
            display: none;
        }
    </style>
```

(No badge-hiding rule is needed here — confirmed `createHomePinCard()` never renders a section badge; `.pin-info` already contains both the title and the "go to board" link, so hiding it alone covers everything.)

- [ ] **Step 3: Add the toggle JS**

Find:

```js
            // Home view switcher
            document.querySelectorAll('.home-view-btn').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    showHomeView(btn.getAttribute('data-view'));
                });
            });
            showHomeView(getHomeView(), { persist: false });
        });
```

Replace with:

```js
            // Home view switcher
            document.querySelectorAll('.home-view-btn').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    showHomeView(btn.getAttribute('data-view'));
                });
            });

            // Pin display mode (Normal/Display) - shared preference with board.html
            (function () {
                var displayMode = getPinDisplayMode();
                document.querySelectorAll('.pin-display-btn').forEach(function (btn) {
                    btn.classList.toggle('active', btn.getAttribute('data-mode') === displayMode);
                    btn.addEventListener('click', function () {
                        var mode = btn.getAttribute('data-mode');
                        localStorage.setItem('pinDisplayMode', mode);
                        document.querySelectorAll('.pin-display-btn').forEach(function (b) {
                            b.classList.toggle('active', b === btn);
                        });
                        var homePinsGrid = document.getElementById('homePinsGrid');
                        if (homePinsGrid) homePinsGrid.classList.toggle('display-mode', mode === 'display');
                    });
                });
                var homePinsGrid = document.getElementById('homePinsGrid');
                if (homePinsGrid && displayMode === 'display') {
                    homePinsGrid.classList.add('display-mode');
                }
            })();

            showHomeView(getHomeView(), { persist: false });
        });
```

Now add the `getPinDisplayMode()` helper itself. Find:

```js
        function pinColumnCount() {
            var size = parseInt(localStorage.getItem('boardPinSize'), 10) || 3;
            return { 1: 7, 2: 6, 3: 5, 4: 4, 5: 3 }[size] || 5;
        }
```

Replace with:

```js
        function pinColumnCount() {
            var size = parseInt(localStorage.getItem('boardPinSize'), 10) || 3;
            return { 1: 7, 2: 6, 3: 5, 4: 4, 5: 3 }[size] || 5;
        }

        function getPinDisplayMode() {
            return localStorage.getItem('pinDisplayMode') === 'display' ? 'display' : 'normal';
        }
```

(This is defined later in the file than where it's first called in the `DOMContentLoaded` handler above — fine, function declarations are hoisted.)

- [ ] **Step 4: Show/hide the toggle alongside the rest of the Pins-only controls**

Find:

```js
        function showHomeView(view, options) {
            options = options || {};
            const persist = options.persist !== false;
            const mode = view === 'pins' ? 'pins' : 'boards';

            document.querySelectorAll('.home-view-btn').forEach(function (btn) {
                btn.classList.toggle('active', btn.getAttribute('data-view') === mode);
            });

            const boardsGallery = document.getElementById('boardsGallery');
            const boardsToolbar = document.getElementById('boardsToolbar');
            const sortBoards = document.getElementById('sortBoards');
            const pinsToolbar = document.getElementById('pinsToolbar');
            const homePinsView = document.getElementById('homePinsView');

            if (mode === 'boards') {
                if (boardsGallery) boardsGallery.classList.remove('hidden');
                if (boardsToolbar) boardsToolbar.classList.remove('hidden');
                if (sortBoards) sortBoards.classList.remove('hidden');
                if (pinsToolbar) pinsToolbar.classList.add('hidden');
                if (homePinsView) homePinsView.classList.add('hidden');
                teardownPinsScroll();
            } else {
                if (boardsGallery) boardsGallery.classList.add('hidden');
                if (boardsToolbar) boardsToolbar.classList.add('hidden');
                if (sortBoards) sortBoards.classList.add('hidden');
                if (pinsToolbar) pinsToolbar.classList.remove('hidden');
                if (homePinsView) homePinsView.classList.remove('hidden');
                startPinsFeed();
            }

            if (persist) setHomeView(mode);
        }
```

Replace with:

```js
        function showHomeView(view, options) {
            options = options || {};
            const persist = options.persist !== false;
            const mode = view === 'pins' ? 'pins' : 'boards';

            document.querySelectorAll('.home-view-btn').forEach(function (btn) {
                btn.classList.toggle('active', btn.getAttribute('data-view') === mode);
            });

            const boardsGallery = document.getElementById('boardsGallery');
            const boardsToolbar = document.getElementById('boardsToolbar');
            const sortBoards = document.getElementById('sortBoards');
            const pinsToolbar = document.getElementById('pinsToolbar');
            const homePinsView = document.getElementById('homePinsView');
            const pinDisplaySwitcher = document.getElementById('pinDisplaySwitcher');

            if (mode === 'boards') {
                if (boardsGallery) boardsGallery.classList.remove('hidden');
                if (boardsToolbar) boardsToolbar.classList.remove('hidden');
                if (sortBoards) sortBoards.classList.remove('hidden');
                if (pinsToolbar) pinsToolbar.classList.add('hidden');
                if (homePinsView) homePinsView.classList.add('hidden');
                if (pinDisplaySwitcher) pinDisplaySwitcher.classList.add('hidden');
                teardownPinsScroll();
            } else {
                if (boardsGallery) boardsGallery.classList.add('hidden');
                if (boardsToolbar) boardsToolbar.classList.add('hidden');
                if (sortBoards) sortBoards.classList.add('hidden');
                if (pinsToolbar) pinsToolbar.classList.remove('hidden');
                if (homePinsView) homePinsView.classList.remove('hidden');
                if (pinDisplaySwitcher) pinDisplaySwitcher.classList.remove('hidden');
                startPinsFeed();
            }

            if (persist) setHomeView(mode);
        }
```

- [ ] **Step 5: Verify in the browser**

Load `http://localhost:8000/`. Confirm:
- In Boards mode (the default), no "Normal | Display" pill is visible.
- Click "Pins" — the pill appears beneath the Boards\|Pins switcher.
- Click "Display" — the pins feed goes dark, titles and "go to board" links disappear, cards lose white background/shadow/hover-lift.
- Click "Boards" — both the pins feed and the display-mode pill disappear (back to board thumbnails).
- Click "Pins" again — still shows the dark gallery (display mode persisted).
- Reload the page from a fresh URL while it was last left in Pins + Display mode — confirm it opens back into Pins mode with Display already active (matches existing `homeView`/`pinDisplayMode` persistence).

- [ ] **Step 6: Commit**

```bash
git add templates/boards.html
git commit -m "Add pin display-mode toggle and dark restyle to home Pins feed"
```

---

### Task 5: `boards.html` — scroll-linked parallax

**Files:**
- Modify: `templates/boards.html` (new functions + extend `showHomeView()` and the toggle click handler from Task 4)

- [ ] **Step 1: Add the parallax functions**

Find:

```js
        function getPinDisplayMode() {
            return localStorage.getItem('pinDisplayMode') === 'display' ? 'display' : 'normal';
        }
```

Replace with:

```js
        function getPinDisplayMode() {
            return localStorage.getItem('pinDisplayMode') === 'display' ? 'display' : 'normal';
        }

        var homePinDisplayParallaxHandler = null;
        var homePinDisplayParallaxThrottle = null;

        // Same technique as board.html's parallax (viewport-relative, not
        // raw scrollY, so it stays perceptible through arbitrarily long
        // infinite-scroll feeds).
        function applyHomePinDisplayParallax() {
            var homePinsGrid = document.getElementById('homePinsGrid');
            if (!homePinsGrid || !homePinsGrid.classList.contains('display-mode')) return;
            if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
            var viewportCenter = window.innerHeight / 2;
            var cards = homePinsGrid.querySelectorAll('.pin-card[data-parallax-col]');
            for (var i = 0; i < cards.length; i++) {
                var card = cards[i];
                var col = parseInt(card.dataset.parallaxCol, 10) || 0;
                var speed = 0.03 + (col % 3) * 0.015;
                var rect = card.getBoundingClientRect();
                var cardCenter = rect.top + rect.height / 2;
                var offset = Math.max(-18, Math.min(18, (viewportCenter - cardCenter) * speed));
                card.style.transform = 'translateY(' + offset.toFixed(1) + 'px)';
            }
        }

        function startHomePinDisplayParallax() {
            if (homePinDisplayParallaxHandler) return;
            homePinDisplayParallaxHandler = function () {
                if (homePinDisplayParallaxThrottle) return;
                homePinDisplayParallaxThrottle = setTimeout(function () {
                    homePinDisplayParallaxThrottle = null;
                    applyHomePinDisplayParallax();
                }, 200);
            };
            window.addEventListener('scroll', homePinDisplayParallaxHandler, { passive: true });
            applyHomePinDisplayParallax();
        }

        function stopHomePinDisplayParallax() {
            if (homePinDisplayParallaxHandler) {
                window.removeEventListener('scroll', homePinDisplayParallaxHandler);
                homePinDisplayParallaxHandler = null;
            }
            if (homePinDisplayParallaxThrottle) {
                clearTimeout(homePinDisplayParallaxThrottle);
                homePinDisplayParallaxThrottle = null;
            }
            var homePinsGrid = document.getElementById('homePinsGrid');
            if (homePinsGrid) {
                var cards = homePinsGrid.querySelectorAll('.pin-card[data-parallax-col]');
                for (var i = 0; i < cards.length; i++) {
                    cards[i].style.transform = '';
                }
            }
        }
```

This uses distinct names (`homePinDisplayParallaxHandler`/`Throttle`, `startHomePinDisplayParallax`/`stopHomePinDisplayParallax`) — deliberately not reusing `homePinsState.scrollHandler`/`scrollThrottle`, which already belong to the unrelated infinite-scroll-pagination logic in `setupPinsInfiniteScroll()`/`teardownPinsScroll()`. Reusing those fields would silently break pagination's own scroll listener bookkeeping.

- [ ] **Step 2: Wire start/stop into the toggle click handler**

Find (added in Task 4, Step 3):

```js
            // Pin display mode (Normal/Display) - shared preference with board.html
            (function () {
                var displayMode = getPinDisplayMode();
                document.querySelectorAll('.pin-display-btn').forEach(function (btn) {
                    btn.classList.toggle('active', btn.getAttribute('data-mode') === displayMode);
                    btn.addEventListener('click', function () {
                        var mode = btn.getAttribute('data-mode');
                        localStorage.setItem('pinDisplayMode', mode);
                        document.querySelectorAll('.pin-display-btn').forEach(function (b) {
                            b.classList.toggle('active', b === btn);
                        });
                        var homePinsGrid = document.getElementById('homePinsGrid');
                        if (homePinsGrid) homePinsGrid.classList.toggle('display-mode', mode === 'display');
                    });
                });
                var homePinsGrid = document.getElementById('homePinsGrid');
                if (homePinsGrid && displayMode === 'display') {
                    homePinsGrid.classList.add('display-mode');
                }
            })();
```

Replace with:

```js
            // Pin display mode (Normal/Display) - shared preference with board.html
            (function () {
                var displayMode = getPinDisplayMode();
                document.querySelectorAll('.pin-display-btn').forEach(function (btn) {
                    btn.classList.toggle('active', btn.getAttribute('data-mode') === displayMode);
                    btn.addEventListener('click', function () {
                        var mode = btn.getAttribute('data-mode');
                        localStorage.setItem('pinDisplayMode', mode);
                        document.querySelectorAll('.pin-display-btn').forEach(function (b) {
                            b.classList.toggle('active', b === btn);
                        });
                        var homePinsGrid = document.getElementById('homePinsGrid');
                        if (homePinsGrid) homePinsGrid.classList.toggle('display-mode', mode === 'display');
                        if (mode === 'display' && getHomeView() === 'pins') {
                            startHomePinDisplayParallax();
                        } else {
                            stopHomePinDisplayParallax();
                        }
                    });
                });
                var homePinsGrid = document.getElementById('homePinsGrid');
                if (homePinsGrid && displayMode === 'display') {
                    homePinsGrid.classList.add('display-mode');
                }
            })();
```

- [ ] **Step 3: Start/stop parallax when switching between Boards and Pins**

Find (from Task 4, Step 4):

```js
            if (mode === 'boards') {
                if (boardsGallery) boardsGallery.classList.remove('hidden');
                if (boardsToolbar) boardsToolbar.classList.remove('hidden');
                if (sortBoards) sortBoards.classList.remove('hidden');
                if (pinsToolbar) pinsToolbar.classList.add('hidden');
                if (homePinsView) homePinsView.classList.add('hidden');
                if (pinDisplaySwitcher) pinDisplaySwitcher.classList.add('hidden');
                teardownPinsScroll();
            } else {
                if (boardsGallery) boardsGallery.classList.add('hidden');
                if (boardsToolbar) boardsToolbar.classList.add('hidden');
                if (sortBoards) sortBoards.classList.add('hidden');
                if (pinsToolbar) pinsToolbar.classList.remove('hidden');
                if (homePinsView) homePinsView.classList.remove('hidden');
                if (pinDisplaySwitcher) pinDisplaySwitcher.classList.remove('hidden');
                startPinsFeed();
            }
```

Replace with:

```js
            if (mode === 'boards') {
                if (boardsGallery) boardsGallery.classList.remove('hidden');
                if (boardsToolbar) boardsToolbar.classList.remove('hidden');
                if (sortBoards) sortBoards.classList.remove('hidden');
                if (pinsToolbar) pinsToolbar.classList.add('hidden');
                if (homePinsView) homePinsView.classList.add('hidden');
                if (pinDisplaySwitcher) pinDisplaySwitcher.classList.add('hidden');
                teardownPinsScroll();
                stopHomePinDisplayParallax();
            } else {
                if (boardsGallery) boardsGallery.classList.add('hidden');
                if (boardsToolbar) boardsToolbar.classList.add('hidden');
                if (sortBoards) sortBoards.classList.add('hidden');
                if (pinsToolbar) pinsToolbar.classList.remove('hidden');
                if (homePinsView) homePinsView.classList.remove('hidden');
                if (pinDisplaySwitcher) pinDisplaySwitcher.classList.remove('hidden');
                startPinsFeed();
                if (getPinDisplayMode() === 'display') {
                    startHomePinDisplayParallax();
                }
            }
```

- [ ] **Step 4: Verify motion in the browser**

Load `http://localhost:8000/`, switch to Pins mode, switch Display on. Then:

- Scroll and confirm `document.querySelector('#homePinsGrid .pin-card[data-parallax-col]').style.transform` changes to small, varying `translateY(...)` values.
- Switch to Boards mode — confirm no console errors and no lingering scroll listener (check via `getEventListeners` if available, or simply confirm scrolling on the Boards gallery doesn't trigger any errors and CPU stays idle — informally, just confirm nothing breaks).
- Switch back to Pins mode — confirm parallax resumes (this path re-fetches a fresh random pin set via `startPinsFeed()`, so also confirm the new cards get `data-parallax-col` stamped and respond to scroll).
- Toggle "Normal" while in Pins mode — confirm the listener stops and transforms reset to `''`.

- [ ] **Step 5: Commit**

```bash
git add templates/boards.html
git commit -m "Add scroll-linked parallax to home Pins feed display mode"
```

---

### Task 6: Full manual verification pass

**Files:** none (verification only)

- [ ] **Step 1: Cross-page persistence**

On `board.html` (`http://localhost:8000/board/217`), switch to Display mode. Navigate to the home page and switch to Pins mode — confirm it's already in Display mode (shared `localStorage.pinDisplayMode`). Switch it to Normal on the home page, then go back to the board page and reload — confirm it's back to Normal there too.

- [ ] **Step 2: Existing functionality still works, in both modes, on both pages**

On `board.html`:
- Pin-size slider (top nav) still changes column count in both Normal and Display mode.
- Section-circle filtering still works in both modes (switch sections, confirm the grid updates; the previously-hidden cards regain `data-parallax-col` when filtered back in, since `applyCurrentSectionFilter()` triggers a relayout through the existing engine).
- Scroll to the bottom of board 217 (3000+ pins) — infinite scroll still loads more pins in both modes, and newly-appended cards in Display mode already show the dark/title-less styling and respond to parallax scroll.
- Click a pin — still navigates to the pin detail page in both modes.

On `boards.html` (home page):
- Pin-size slider (Pins mode) still changes column count in both Normal and Display mode.
- Scroll to the bottom of the Pins feed — infinite scroll still loads more random pins in both modes.
- Click a pin — still navigates to the pin detail page.
- The "go to board" link/pill (visible only in Normal mode, since it's inside `.pin-info`) still navigates correctly when clicked in Normal mode.

- [ ] **Step 3: Mobile width check**

Resize to ~375px wide on both pages, in Display mode. Confirm the toggle pill(s) remain visible and usable, the grid still reads reasonably (fewer columns via the existing pin-size/breakpoint behavior — unchanged by this feature), and there's no horizontal overflow.

- [ ] **Step 4: Console/network check**

On both pages, in both modes, confirm no new console errors and no unexpected network requests (`read_console_messages` / `read_network_requests` with `onlyErrors`/error filters) introduced by this change.

- [ ] **Step 5: Report results**

Note any visual issues found (e.g. a specific pin's colors clashing with the dark background, jank at very fast scroll speed) — these are small CSS/JS follow-ups on the same two files, not new tasks against other parts of the app.
