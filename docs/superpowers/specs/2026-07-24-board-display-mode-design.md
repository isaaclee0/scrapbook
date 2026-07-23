# Board "Display Mode" — Design

**Date:** 2026-07-24
**Status:** Approved

## Problem

The login page's scrolling photo background (dark background, title-less
rounded-corner images) turned out well enough that the user wants the same
visual treatment available inside the app itself: a way to switch a pin
grid from the normal card view (white cards, title, section badge/board
link) into a "display mode" — dark background, images only, with a subtle
parallax effect as the user scrolls to browse. This applies both to a
single board's pin grid (`board.html`) and to the home page's "Pins" feed
(`boards.html`, the random-pins view added by the home-view-switcher
feature) — not to the home page's "Boards" gallery, which shows board
thumbnails rather than individual pins.

## Decisions

| Topic | Choice |
|---|---|
| Scope | `templates/board.html` (board pin grid) and `templates/boards.html` (home page "Pins" feed only, not "Boards" gallery) — search is untouched |
| Rendering engine | Reuse the existing `static/js/masonry.js` absolute-position engine and existing pin data/pagination — display mode is a CSS/behavior skin on the same grid, not a parallel view |
| Parallax mechanism | Scroll-linked (columns shift slightly relative to actual page scroll position), **not** an ambient auto-looping animation like the login page — the user is actively browsing/clicking real pins here |
| Toggle UI | Segmented pill switcher ("Normal \| Display"). On `board.html`, it sits in the board toolbar next to the pin-size slider. On `boards.html`, a second copy sits directly beneath the existing Boards\|Pins switcher, and is only shown while Pins mode is active (hidden in Boards mode, since board thumbnails aren't pins) |
| Persistence | Global `localStorage` key `pinDisplayMode` (`'normal' \| 'display'`, default `'normal'`), same pattern as `boardPinSize`/`homeView` — **one choice shared** across every board page and the home Pins feed |
| Dark-mode extent | Only the pin grid itself goes dark (`#pinsGrid` on `board.html`, `#homePinsGrid` on `boards.html`); nav bar, board title/section-filter circles, and the Boards\|Pins switcher itself stay in the normal light theme |
| Column count | Display mode respects each page's existing pin-size slider (`boardPinSize` on both pages, 3–7 columns) — no separate/fixed column count |
| Titles/metadata | `.pin-info` hidden in display mode on both grids — on `board.html` this also means separately hiding `.section-badge`/`.source-link-icon` (overlay elements outside `.pin-info`); on `boards.html`, `.pin-info` already contains both the title *and* the "go to board" link, so hiding it alone is sufficient — no separate overlay elements to hide there |
| Card chrome | `.pin-card` loses white background/box-shadow in display mode (becomes just the rounded image, already 12px radius); hover-lift transform disabled (conflicts with parallax transform, and there's no title to reveal) |
| Interactions preserved | Pin click → same plain `<a href>` navigation to pin detail (no modal exists today, nothing to change); section-circle filtering; infinite scroll/pagination |
| Accessibility | Parallax transforms skipped under `prefers-reduced-motion: reduce`, consistent with the login page |

## Design

### 1. Toggle & persistence

A segmented pill control (visually matching the existing Boards/Pins home
switcher pattern) is added in two places, each independently rendered
(this codebase's established pattern — the pin-size slider is already
duplicated the same way between `base.html` and `boards.html`):

**`board.html`** — in the board toolbar, near the pin-size slider:

```html
<div class="pin-display-switcher" role="group" aria-label="Pin display mode">
    <button type="button" data-mode="normal" class="pin-display-btn active">Normal</button>
    <button type="button" data-mode="display" class="pin-display-btn">Display</button>
</div>
```

**`boards.html`** — identical markup/class names, placed directly beneath
the existing `.home-view-switcher` (Boards\|Pins pill), inside the same
toolbar area as `#pinsToolbar`. It's shown/hidden alongside the rest of
`#pinsToolbar`'s Pins-only controls (the existing `showHomeView()`
function already toggles `#pinsToolbar`'s visibility when switching
between Boards/Pins — no new visibility logic needed beyond adding this
control inside that existing container).

- On `DOMContentLoaded` (each page independently), read
  `localStorage.pinDisplayMode` (default `'normal'`) and apply it
  immediately (add/remove `display-mode` class on the page's grid
  container — `#pinsGrid` or `#homePinsGrid` — set the correct button
  `.active`) before the grid's first `layout()` call, so there's no flash
  of the wrong style.
- Clicking a pill button updates `localStorage.pinDisplayMode`, toggles
  the grid's `display-mode` class, updates that page's button active
  state, and starts/stops the parallax scroll listener (section 3). No
  re-fetch, no page reload, no change to which pins are loaded.
- On `boards.html` specifically: switching from Pins → Boards mode does
  *not* clear or change `pinDisplayMode` — it's simply not applicable
  while viewing board thumbnails. Switching back to Pins mode (or loading
  any board page) immediately reflects whatever `pinDisplayMode` is
  currently set to.

### 2. Visual restyle (CSS, scoped under `.display-mode`)

Applied identically to both grids via a shared selector list (each
template keeps its own copy in its own `<style>` block, per this file's
existing single-file-template convention):

```css
#pinsGrid.display-mode,
#homePinsGrid.display-mode {
    background-color: #1a1a2e;
    border-radius: 12px;
    padding: 8px;
}
#pinsGrid.display-mode .pin-card,
#homePinsGrid.display-mode .pin-card {
    background: transparent;
    box-shadow: none;
}
#pinsGrid.display-mode .pin-card:hover,
#homePinsGrid.display-mode .pin-card:hover {
    transform: none;
    box-shadow: none;
}
#pinsGrid.display-mode .pin-info,
#homePinsGrid.display-mode .pin-info {
    display: none;
}
/* board.html only — these overlay elements don't exist on homePinsGrid cards */
#pinsGrid.display-mode .section-badge,
#pinsGrid.display-mode .source-link-icon {
    display: none;
}
```

(In practice this CSS is split across the two templates' own `<style>`
blocks — shown combined here for clarity.) `.image-container` and
`.pin-image` keep their existing `border-radius` from the current card
styling (already 12px on both grids) — no new rounding rules needed. The
skeleton-loader shimmer is unaffected on either grid (still shown while an
image loads).

### 3. Scroll-linked parallax

`masonry.js`'s `layout()` function already determines which column each
card occupies internally (for absolute positioning). It's extended to also
stamp a `data-parallax-col` attribute on each card during layout:

```js
// inside layout(), where per-card column index is already known:
card.dataset.parallaxCol = columnIndex;
```

A new scroll handler (added only while display mode is active, removed
when switched off) reads `window.scrollY` and applies a small
per-column-weighted vertical offset via `transform: translateY(...)`:

```js
function applyParallax() {
    if (!pinsGrid.classList.contains('display-mode')) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const scrollY = window.scrollY;
    const cards = pinsGrid.querySelectorAll('.pin-card[data-parallax-col]');
    cards.forEach(function (card) {
        const col = parseInt(card.dataset.parallaxCol, 10) || 0;
        const speed = 0.015 + (col % 3) * 0.01; // small, staggered per column
        const offset = Math.max(-24, Math.min(24, scrollY * speed * (col % 2 === 0 ? 1 : -1)));
        card.style.transform = 'translateY(' + offset + 'px)';
    });
}
window.addEventListener('scroll', throttledApplyParallax, { passive: true });
```

Throttled the same way the existing infinite-scroll handler is
(`board.html`'s existing 200ms-throttle pattern). The offset is capped
(±24px) so it always reads as subtle depth, never as content jumping
around or overlapping neighboring rows. This is a `transform`, which is
purely visual — it never touches the `top`/`left` values the masonry
engine uses for actual layout, so it can't desync positions or break
infinite-scroll appending.

Newly-appended cards (from infinite scroll, or from the home Pins feed's
own pagination) get `data-parallax-col` stamped the same way, since they
go through the same `layout()`/append path as existing cards. Because
`static/js/masonry.js` is a single shared module instantiated separately
by each page (`window.scrapbookMasonry` on `board.html`,
`window.homePinsMasonry` on `boards.html`), this one engine change covers
both grids automatically — no per-page masonry logic to duplicate.

The scroll-listener wiring itself (start/stop on toggle, the
`applyParallax` function) is duplicated once per template, same as the
toggle markup — each page attaches it to its own grid element and its own
toggle buttons. On `boards.html`, the listener additionally only runs
while Pins mode is the active home view (checking the same visibility
state `showHomeView()` already tracks) — no point computing parallax
offsets for a grid that's currently `display: none`.

### 4. Compatibility

- Pin-size slider (`boardPinSize`, columns 3–7), section-circle filtering
  (board.html) / Boards↔Pins switching (boards.html), and infinite scroll
  are all untouched on both pages — display mode is a class + a scroll
  listener layered on the exact same grid and pin data.
- Pin click behavior is unchanged on both grids (`<a href="/pin/<id>">`,
  full page navigation, no modal exists today).
- Toggling display mode on/off does not re-fetch or re-render pins on
  either page; it's a pure style/behavior change on already-rendered DOM.
- Turning on display mode while on `board.html`, then navigating to the
  home page and switching to Pins mode (or vice versa), shows the home
  Pins feed already in display mode too — same shared `localStorage` key,
  read independently by each page on load.

### 5. Files

| File | Change |
|---|---|
| `templates/board.html` | Add toggle markup + CSS (`display-mode` rules) + toggle JS (localStorage read/write, class toggle, start/stop parallax listener) |
| `templates/boards.html` | Same additions as `board.html`, scoped to `#homePinsGrid` and placed beneath the existing Boards\|Pins switcher inside `#pinsToolbar` |
| `static/js/masonry.js` | Stamp `data-parallax-col` on each card during `layout()` — shared by both pages' masonry instances, changed once |

## Out of scope

- Per-board or per-page persistence (it's a single global preference
  shared across `board.html` and `boards.html`'s Pins feed)
- A separate/fixed column count for display mode
- Display mode for the home page's "Boards" gallery (board thumbnails, not
  pins) or for search results
- Dimming or restyling the nav bar, board title, section-filter circles,
  or the Boards\|Pins switcher itself
- Any dark theme elsewhere in the app (pin detail page, etc.)
- A modal/lightbox pin viewer (not part of this change; pins still open
  via normal navigation)

## Success criteria

1. A "Normal | Display" toggle switches a pin grid between the current
   card view and a dark, title-less, rounded-image gallery view, with no
   page reload — available both on a board page and on the home page's
   Pins feed (placed beneath the Boards\|Pins switcher there, hidden while
   Boards mode is active).
2. The choice persists across boards, the home Pins feed, and page loads
   via a single shared `localStorage` key.
3. While in display mode, scrolling produces a subtle, staggered
   per-column parallax offset that never causes cards to overlap or jump,
   and is skipped under `prefers-reduced-motion`.
4. Pin-size slider, section filtering / Boards↔Pins switching, infinite
   scroll, and pin-click navigation all continue to work identically in
   both modes on both pages.
5. Only `templates/board.html`, `templates/boards.html`, and
   `static/js/masonry.js` change; no other page's appearance or behavior
   is affected.
