# Home View Switcher (Boards / Random Pins) — Design

**Date:** 2026-07-22  
**Status:** Approved

## Problem

The home page (`/`) is only a board gallery. Users also want a “random pins”
home experience — roughly 1.5 viewports of pins, with infinite scroll — and a
way to switch between the two views, with the last choice remembered as the
default.

## Decisions

| Topic | Choice |
|---|---|
| Architecture | Single home page; client-side view toggle (Approach 1) |
| Default behavior | Last-used view wins (switching auto-saves) |
| Preference storage | `localStorage` key `homeView` (`boards` \| `pins`); default `boards` |
| Random semantics | Seeded shuffle per Pins session; no repeats until exhausted, then new seed |
| Switcher placement | Right side, grouped with existing toolbar controls |
| Persistence across devices | Out of scope |
| Separate `/pins` URL | Out of scope |
| DB migration | None |

## Design

### 1. UX

Home remains `GET /` → `gallery()` → `boards.html`.

A segmented control **Boards | Pins** sits on the right of the existing
`.sort-container`, grouped with size/sort/layout controls.

- **Boards mode:** current gallery + board size slider, sort select, layout cog.
- **Pins mode:** hide board-only controls; show a masonry pin grid (reuse board
  pin-card / `masonry.js` patterns). Pin sizing uses the existing global
  `boardPinSize` control from `base.html`.
- Choosing a mode immediately switches the visible content and writes
  `localStorage.homeView`.
- On load, read `homeView`. If `pins`, hide boards, show pins grid, fetch the
  first batch. A brief boards flash is acceptable when Pins is the saved default.

### 2. Random pins API

```
GET /api/random-pins?seed=<int>&offset=<int>&limit=<int>
```

- `@login_required`; scoped to `user_id`.
- Cap `limit` (same spirit as board pins API, e.g. max 200).
- Order pins with a deterministic hash of `(pin_id, seed)` so pagination is
  stable for a given seed (e.g. `ORDER BY CRC32(CONCAT(p.id, '-', %s))` or
  equivalent MariaDB-safe expression).
- Return the same pin shape as `/api/board/<id>/pins` (including
  `cached_filename`, dimensions, board/section names) so the client can reuse
  card builders.
- Response includes `pins`, `total`, `has_more` (or equivalent).
- When `offset >= total`, return empty `pins` / `has_more: false`. Client
  starts a new seed and continues (full-pass reshuffle).

Do not change the existing `/random` single-pin redirect.

### 3. Client feed behavior

- Entering Pins mode (including initial load when default is Pins) generates a
  new random `seed`.
- Initial `limit` ≈ 1.5 viewports: estimate from viewport height, pin column
  width, and column count (same sizing model as board masonry).
- Scroll near bottom → next page with same seed / next offset (mirror
  `board.html` / `search.html` infinite scroll).
- Boards → Pins: new seed + fresh fetch; do not restore prior Pins scroll.
- Pins → Boards: show the already-rendered boards gallery; no refetch.
- Zero pins: empty state (“No pins yet”), not an infinite spinner.

### 4. Files

| File | Change |
|---|---|
| `app.py` | Add `GET /api/random-pins` |
| `templates/boards.html` | Switcher, pins container, mode JS, infinite scroll |
| `static/js/masonry.js` | Reuse as-is |
| Board/search pin-card JS patterns | Copy/adapt into boards.html (or shared helper if trivial) |

### 5. Out of scope

- Cookie / SSR of the default view (no FOUC fix)
- Server-side user preference column
- Dedicated `/pins` route
- Changing `/random`

## Success criteria

1. User can switch Boards ↔ Pins from the home toolbar.
2. Last selection is the default on the next visit (same browser).
3. Pins mode loads ~1.5 screens, then more on scroll, without repeating pins
   until the library is exhausted for that seed.
4. Pin cards behave like board pins (masonry layout, click → pin detail).
