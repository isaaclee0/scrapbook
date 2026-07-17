# Stable Masonry Layout — Design

**Date:** 2026-07-17
**Status:** Approved

## Problem

Pins slide around and change position as a page loads, in board view (partially
mitigated) and especially in search (heavy movement). The user can never build a
stable mental map of where a pin sits on a board, or scroll back in search to a
pin they saw. The goal: **once a pin is placed on screen it never moves**, while
keeping the masonry look.

### Root causes

1. **CSS multi-column masonry** (`column-count` in `board.html` and
   `search.html`). Multicol *balances* columns: any content change — a height
   correction, or infinite scroll appending pins (board +40/batch, search
   +10/batch) — redistributes every pin across every column. Pins already on
   screen jump between columns. This is inherent to multicol and cannot be fixed
   by height reservation.
2. **Search never knows image sizes.** The search queries (`search()` and
   `search_pins_api()` in `app.py`) do not select `ci.width`/`ci.height`; the
   template reads `pin.final_width`/`final_height`, which do not exist. Every
   card renders at a 150–200 px placeholder height, then
   `correctImageContainerHeight()` resizes it when each image loads. Dozens of
   height changes, each triggering a full multicol rebalance.
3. **Board applies saved column count after first paint.** CSS defaults to 5
   columns; `applyPinSizeFromStorage()` switches to the saved pin-size count at
   `DOMContentLoaded`, causing a whole-page jump on load.

Board view's server-rendered `aspect-ratio` reservation (with 2:1 / 1:2 caps and
3/4 fallback) is sound and is reused by this design.

## Approach

Absolute-positioned masonry (Pinterest-style), chosen over per-column wrapper
divs and over keeping multicol. A pin's position is written once and never
touched again except by an explicit, user-initiated full relayout.

## Design

### 1. Shared layout engine — `static/js/masonry.js`

Vanilla JS module (~100 lines), no dependencies, loaded synchronously (plain
`<script src>`, no `defer`) by `board.html` and `search.html`.

- `#pinsGrid` becomes `position: relative` with a JS-managed explicit `height`.
- Each `.pin-card` is `position: absolute`, `width` set in px to the computed
  column width, positioned via `left`/`top`. **Not** `transform` — the existing
  `.pin-card:hover { transform: translateY(-2px) }` and highlight-pulse `scale`
  animations would conflict.
- API (attached to the grid as `window.scrapbookMasonry` or returned instance):
  - `layout()` — full relayout of all *visible* cards: recompute column count
    and width, reset `colHeights[]`, place every card.
  - `append(cards)` — place only the new cards, continuing from the current
    `colHeights[]`. **Existing pins are never touched.**
- Placement: for each card in DOM order, choose the shortest column;
  `left = col * (colWidth + gap)`, `top = colHeights[col]`;
  `colHeights[col] += cardHeight + gap`. Gap: 16 px (matches current
  `column-gap`/`margin-bottom`).
- Measurement: batched to avoid thrashing — one write pass (set all widths),
  one read pass (`offsetHeight` for all cards, single reflow), one write pass
  (set positions). Heights are accurate at measure time because the image box
  is fixed by server-rendered `aspect-ratio` and card text uses system fonts
  (no web-font swap; Funnel Display is headings/logo only).
- Container height = `max(colHeights)` after every `layout()`/`append()`, so
  document scroll height and the infinite-scroll bottom-distance triggers keep
  working.
- Column count:
  - Board: `min(pinSizeCount, breakpointCap)` where `pinSizeCount` is the
    existing map {1:7, 2:6, 3:5, 4:4, 5:3} from `localStorage.boardPinSize`,
    and `breakpointCap` mirrors the current media queries
    (≤500 px→1, ≤800 px→2, ≤1200 px→3, ≤1600 px→4, wider→no cap, i.e. the
    pin-size count governs). This also fixes the pre-existing quirk where the
    inline `columnCount` style disabled responsiveness on small screens.
  - Search: breakpoint count only (no pin-size control on that page).
- Full `layout()` runs **only** on:
  - real viewport width change (debounced ~150 ms, and skipped when
    `grid.clientWidth` is unchanged — guards against mobile URL-bar
    show/hide firing resize during scroll),
  - pin-size change (board),
  - section-filter change (board; hidden cards are excluded from layout).
- Initial layout runs **synchronously from an inline `<script>` immediately
  after the grid markup**, so the first paint already shows final positions —
  no flash of unpositioned content and no post-paint column-count switch.

### 2. Search: know sizes up front, never correct after render

- Add `ci.width AS cached_width, ci.height AS cached_height` to both search
  pin queries (`search()` and `search_pins_api()` in `app.py`).
- `search.html` renders `aspect-ratio` server-side on `.image-container` with
  the identical capping rules as `board.html` (height clamped to [w/2, 2w];
  `3/4` fallback when unknown), in both the Jinja loop and `createPinCard()`.
- **Delete** `correctImageContainerHeight()`, `reserveImageSpace()`,
  `correctContainerHeight()` and every call to them. `onload` handlers only
  add `.loaded`, hide the skeleton, and call `reportImageDimensions()`
  (ported from `board.html`) so externally-loaded images backfill their
  dimensions via `/save-pin-dimensions/<pin_id>` for future visits.
- The rendered aspect-ratio is never modified after render — same rule board
  view already follows.

### 3. Template/CSS changes (both views)

- Remove `column-count` rules, `break-inside: avoid`, and card
  `margin-bottom` (gap handled by the engine); add
  `.masonry-grid { position: relative; }` and
  `.masonry-grid .pin-card { position: absolute; top: 0; left: 0; }`.
- Keep: skeleton loaders, dominant-color gradients, hover effects, highlight
  pulse, `contain: layout style`, `.image-container` min/max height clamps
  (deterministic at measure time).
- Board: `setupBoardPinsLazyLoad` appends batch cards via `append()`;
  `applyPinSizeFromStorage()`'s columnCount logic is replaced by the engine
  config; the pin-size slider handler in `base.html` calls the engine instead
  of setting `columnCount`; section filtering calls `layout()` after toggling
  visibility.
- Search: infinite scroll appends via `append()`; the
  `setTimeout(reserveImageSpace, 100)` call is removed.
- `pins.html` and `boards.html` use regular CSS grid (not masonry) and are
  unaffected.

### 4. Behavior notes / trade-offs

- Placement order becomes roughly left-to-right (shortest column) instead of
  multicol's down-each-column order — a one-time visual change. Layout is
  deterministic: same pins + same viewport width ⇒ identical layout every
  visit, which is what makes "I know where that pin is" possible.
- Scroll restore (`restoreScrollPosition`) and `?highlight=` scrolling become
  reliable because layout is final at first paint;
  `waitForLayoutStabilization()` now stabilizes on its first check and is left
  in place (simplification optional, not required).
- No-JS fallback is not a goal (the app is already JS-dependent).

## Error handling

- Image `onerror` swaps to the default pin image inside the fixed
  aspect-ratio box — no layout effect (unchanged behavior).
- Pins with no stored dimensions render at the fixed 3/4 fallback and stay
  there; `reportImageDimensions()` backfills for next visit.
- If `masonry.js` fails to load, cards would overlap at top-left; acceptable
  (same class of failure as any missing script today), no special handling.

## Testing / verification

Drive the real app in a browser:

1. **CLS instrumentation:** `PerformanceObserver` on `layout-shift` — assert
   cumulative shift ≈ 0 after first paint on board and search (with cache
   disabled / throttled network so images arrive late).
2. **Append stability:** record `getBoundingClientRect()` of all visible pins,
   trigger an infinite-scroll batch, assert zero delta on pre-existing pins
   (board and search).
3. **Interaction relayouts:** resize across breakpoints, change pin size,
   toggle section filters — layout redistributes once per action, no drift.
4. **Flows:** `?highlight=` scroll-to-pin in board and search; scroll restore
   on back-navigation; "no results" search; pins without cached dimensions.
