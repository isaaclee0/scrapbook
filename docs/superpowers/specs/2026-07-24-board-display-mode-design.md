# Board "Display Mode" — Design

**Date:** 2026-07-24
**Status:** Approved

## Problem

The login page's scrolling photo background (dark background, title-less
rounded-corner images) turned out well enough that the user wants the same
visual treatment available inside the app itself: a way to switch a board's
pin grid from the normal card view (white cards, title, section badge) into
a "display mode" — dark background, images only, with a subtle parallax
effect as the user scrolls to browse.

## Decisions

| Topic | Choice |
|---|---|
| Scope | `templates/board.html` only — boards gallery (home) and search are untouched |
| Rendering engine | Reuse the existing `static/js/masonry.js` absolute-position engine and existing pin data/pagination — display mode is a CSS/behavior skin on the same grid, not a parallel view |
| Parallax mechanism | Scroll-linked (columns shift slightly relative to actual page scroll position), **not** an ambient auto-looping animation like the login page — the user is actively browsing/clicking real pins here |
| Toggle UI | Segmented pill switcher ("Normal \| Display") in the board toolbar, next to the existing pin-size slider |
| Persistence | Global `localStorage` key `pinDisplayMode` (`'normal' \| 'display'`, default `'normal'`), same pattern as `boardPinSize`/`homeView` — one choice applies to every board |
| Dark-mode extent | Only the pin grid (`#pinsGrid`) goes dark; nav bar, board title, and section-filter circles stay in the normal light theme |
| Column count | Display mode respects the existing pin-size slider (`boardPinSize`, 3–7 columns) — no separate/fixed column count |
| Titles/metadata | `.pin-info` (title), `.section-badge`, `.source-link-icon` hidden in display mode; no new elements added |
| Card chrome | `.pin-card` loses white background/box-shadow in display mode (becomes just the rounded image, already 12px radius); hover-lift transform disabled (conflicts with parallax transform, and there's no title to reveal) |
| Interactions preserved | Pin click → same plain `<a href>` navigation to pin detail (no modal exists today, nothing to change); section-circle filtering; infinite scroll/pagination |
| Accessibility | Parallax transforms skipped under `prefers-reduced-motion: reduce`, consistent with the login page |

## Design

### 1. Toggle & persistence

A segmented pill control (visually matching the existing Boards/Pins home
switcher pattern) is added to the board toolbar area, near the pin-size
slider:

```html
<div class="pin-display-switcher" role="group" aria-label="Pin display mode">
    <button type="button" data-mode="normal" class="pin-display-btn active">Normal</button>
    <button type="button" data-mode="display" class="pin-display-btn">Display</button>
</div>
```

- On `DOMContentLoaded`, read `localStorage.pinDisplayMode` (default
  `'normal'`) and apply it immediately (add/remove `display-mode` class on
  `#pinsGrid`, set the correct button `.active`) before the grid's first
  `layout()` call, so there's no flash of the wrong style.
- Clicking a pill button updates `localStorage.pinDisplayMode`, toggles the
  `#pinsGrid.display-mode` class, updates button active state, and
  starts/stops the parallax scroll listener (section 3). No re-fetch, no
  page reload, no change to which pins are loaded.

### 2. Visual restyle (CSS, scoped under `#pinsGrid.display-mode`)

```css
#pinsGrid.display-mode {
    background-color: #1a1a2e;
    border-radius: 12px;
    padding: 8px;
}
#pinsGrid.display-mode .pin-card {
    background: transparent;
    box-shadow: none;
}
#pinsGrid.display-mode .pin-card:hover {
    transform: none;
    box-shadow: none;
}
#pinsGrid.display-mode .pin-info,
#pinsGrid.display-mode .section-badge,
#pinsGrid.display-mode .source-link-icon {
    display: none;
}
```

`.image-container` and `.pin-image` keep their existing `border-radius`
from the current card styling (already 12px) — no new rounding rules
needed. The skeleton-loader shimmer is unaffected (still shown while an
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

Newly-appended cards (from infinite scroll) get `data-parallax-col`
stamped the same way, since they go through the same `layout()`/append
path as existing cards.

### 4. Compatibility

- Pin-size slider (`boardPinSize`, columns 3–7), section-circle filtering,
  and infinite scroll are all untouched — display mode is a class + a
  scroll listener layered on the exact same grid and pin data.
- Pin click behavior is unchanged (`<a href="/pin/<id>">`, full page
  navigation, no modal exists today).
- Toggling display mode on/off does not re-fetch or re-render pins; it's a
  pure style/behavior change on already-rendered DOM.

### 5. Files

| File | Change |
|---|---|
| `templates/board.html` | Add toggle markup + CSS (`display-mode` rules) + toggle JS (localStorage read/write, class toggle, start/stop parallax listener) |
| `static/js/masonry.js` | Stamp `data-parallax-col` on each card during `layout()` |

## Out of scope

- Per-board persistence (it's a single global preference)
- A separate/fixed column count for display mode
- Dimming or restyling the nav bar, board title, or section-filter circles
- Any dark theme outside the pin grid, or elsewhere in the app (boards
  gallery, search, pin detail page)
- A modal/lightbox pin viewer (not part of this change; pins still open
  via normal navigation)

## Success criteria

1. A "Normal | Display" toggle in the board toolbar switches the pin grid
   between the current card view and a dark, title-less, rounded-image
   gallery view, with no page reload.
2. The choice persists across boards and page loads via `localStorage`.
3. While in display mode, scrolling produces a subtle, staggered
   per-column parallax offset that never causes cards to overlap or jump,
   and is skipped under `prefers-reduced-motion`.
4. Pin-size slider, section filtering, infinite scroll, and pin-click
   navigation all continue to work identically in both modes.
5. Only `templates/board.html` and `static/js/masonry.js` change; no other
   page's appearance or behavior is affected.
