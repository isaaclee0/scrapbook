# Login Page Scrolling Photo Background — Design

**Date:** 2026-07-24
**Status:** Approved

## Problem

The login page (`templates/login.html`) currently has a flat purple gradient
background (`linear-gradient(135deg, #667eea 0%, #764ba2 100%)`). It's liked
visually, but static. The request is to make the background feel like a
demo board of pins scrolling by, evoking the app's actual product (a
Pinterest-like image collector) without being boring.

## Decisions

| Topic | Choice |
|---|---|
| Image source | Bundled placeholder photos shipped as static assets — **not** real user pins/boards |
| Why not real pins | Login page is public/pre-auth; querying real boards would expose private content to anyone who loads the URL without logging in |
| Photo style | Curated Unsplash photos (real photography, not abstract/CSS art or icon tiles) |
| Photo theme | Colorful & eclectic — mixed categories (travel, food, design, nature, fashion), ~16 photos |
| Sourcing | Downloaded once at implementation time, committed to the repo (e.g. `static/images/login-bg/`); no runtime fetch from Unsplash. Exact file list/sources confirmed with the user before download per download-permission policy. |
| Layout | Multiple columns of photo tiles, varying tile heights (masonry-ish, decorative — not the real `masonry.js` engine) |
| Motion | Continuous upward scroll per column, **parallax**: each column at a slightly different speed. Seamless loop via duplicated column content. |
| Column count | 5 columns desktop, 2–3 columns on narrow/mobile viewports (media query breakpoint matching existing responsive behavior) |
| Overlay | Minimal dark scrim over the photo layer (~`rgba(10,10,20,0.15)`) — just enough to keep the whole page from feeling too busy, photos stay vivid |
| Login card | Frosted glass: `background: rgba(255,255,255,0.72)` + `backdrop-filter: blur(10px)` (with `-webkit-` prefix), replacing the current solid white `.login-container` background. `@supports not (backdrop-filter)` fallback to solid white so text stays legible everywhere. |
| Card text/inputs | Unchanged colors (`#333` body text etc.) — verify contrast still passes against the frosted background in testing |
| Reduced motion | `@media (prefers-reduced-motion: reduce)` pauses the column animations (static first frame) |
| Performance | Photos resized/compressed to small thumbnails (e.g. max ~400px wide); same ~16-photo pool reused across all columns and duplicated segments so the browser only downloads each file once |
| Scope | `templates/login.html` only (inline `<style>` + a small inline `<script>`/markup for the column tiles) + new static image assets. No `app.py` route changes, no DB changes. |

## Design

### 1. DOM structure

Inside `<body>`, before `.login-container`, add a fixed full-viewport
background layer:

```html
<div class="bg-scroll" aria-hidden="true">
  <div class="bg-col"> <!-- repeated per column --> 
    <img ...> <!-- repeated per photo, list duplicated once for seamless loop -->
  </div>
  ...
</div>
<div class="bg-overlay"></div>
```

- `.bg-scroll`: `position: fixed; inset: 0; z-index: 0; overflow: hidden; display: flex; gap: 8px; padding: 8px;`
- `.bg-col`: `flex: 1; display: flex; flex-direction: column; gap: 8px; animation: scrollUp linear infinite;` — each column gets its own `animation-duration` (staggered within an 18–28s range) for the parallax feel.
- `.bg-overlay`: `position: fixed; inset: 0; z-index: 1; background: rgba(10,10,20,0.15); pointer-events: none;`
- `.login-container` gets `position: relative; z-index: 2;` and the frosted-glass background (see above), everything else in the card is unchanged.
- `body` background gradient is removed (replaced by the photo layer); keep a plain dark fallback `background-color` on `body` in case images fail to load.

### 2. Animation

```css
@keyframes scrollUp {
  from { transform: translateY(0); }
  to   { transform: translateY(-50%); }
}
```

Each `.bg-col` renders its photo list twice back-to-back (`imgs + imgs`), and
`translateY(-50%)` moves exactly one full copy off-screen before the loop
resets — this is the standard seamless-marquee trick, same as used in the
brainstorm mockups.

```css
@media (prefers-reduced-motion: reduce) {
  .bg-col { animation-play-state: paused; }
}
```

### 3. Responsive columns

- Default (desktop): 5 `.bg-col` elements.
- `@media (max-width: 768px)`: render/show only 2–3 columns (hide the rest via CSS `nth-child` or just emit fewer columns server-side isn't needed — this is a static template, so simplest is CSS `display:none` on the 4th/5th column past a breakpoint, with the remaining columns' `flex:1` naturally filling the width).

### 4. Assets

- New directory `static/images/login-bg/` with ~16 photos, web-optimized
  (compressed JPEG/WebP, resized so the largest dimension is roughly
  400–600px — these render small in a multi-column grid, no need for
  full-res).
- Filenames descriptive but generic (e.g. `login-bg-01.jpg` … `login-bg-16.jpg`)
  since content/attribution isn't tied to real user data.
- Unsplash photos used under the Unsplash License (free to use, no
  attribution required, but we'll keep a short `CREDITS.md` or similar next
  to the assets noting source URLs in case attribution is ever wanted).

### 5. Files

| File | Change |
|---|---|
| `templates/login.html` | Add `.bg-scroll`/`.bg-overlay` markup, CSS (columns, animation, reduced-motion, responsive breakpoint, frosted-glass card + `@supports` fallback), small inline script or server-side Jinja loop to emit the `<img>` tiles per column |
| `static/images/login-bg/*.jpg` (new) | ~16 curated photos |
| `static/images/login-bg/CREDITS.md` (new, optional) | Source attribution list |

## Out of scope

- Real pin/board data on the login page (privacy risk — explicitly rejected)
- A "public board" opt-in flag/feature for future use
- Changing the OTP form UX/logic itself
- Any backend route or DB changes

## Success criteria

1. Login page background shows a multi-column grid of curated photos
   scrolling upward continuously, columns at slightly different speeds.
2. Login card is frosted glass and remains fully legible over any part of
   the scrolling background.
3. Works and looks reasonable on both desktop and mobile widths.
4. Animation pauses for users with `prefers-reduced-motion: reduce`.
5. No dependency on real user data or a live Unsplash API call at runtime.
6. Page load stays fast — total background image payload kept small via
   compressed/resized thumbnails.
