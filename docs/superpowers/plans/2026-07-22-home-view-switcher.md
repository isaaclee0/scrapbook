# Home View Switcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Boards / Pins home switcher with last-used default in `localStorage`, and a seeded random-pins feed with ~1.5-screen initial load plus infinite scroll.

**Architecture:** Keep `GET /` → `boards.html`. Client toggles between the existing boards gallery and a new pins masonry fed by `GET /api/random-pins` (seeded deterministic order). Preference key: `localStorage.homeView`.

**Tech Stack:** Flask, MariaDB, Jinja2, existing `static/js/masonry.js`, vanilla JS (mirror `board.html` infinite scroll).

**Spec:** `docs/superpowers/specs/2026-07-22-home-view-switcher-design.md`

---

## File map

| File | Change |
|---|---|
| `app.py` | Add `GET /api/random-pins` near other pin APIs (~line 2754) |
| `templates/boards.html` | Switcher UI, pins grid container, mode + feed JS |
| `static/js/masonry.js` | Reuse unchanged |
| `VERSION` | Bump patch/minor as appropriate at end |

---

### Task 1: Random pins API

**Files:** `app.py`

- [ ] **Step 1: Add route** `GET /api/random-pins` with `@login_required`

Accept query params: `seed` (int, required; if missing generate server-side random and return it), `offset` (default 0), `limit` (default 40, cap 200).

- [ ] **Step 2: Query**

Mirror the `cached_images` join / fallback pattern from `get_board_pins()` (~2754). Filter `WHERE p.user_id = %s`. Order with a deterministic seeded expression, e.g.:

```sql
ORDER BY CRC32(CONCAT(p.id, '-', %s)), p.id
LIMIT %s OFFSET %s
```

Also `SELECT COUNT(*)` for `total`. Return JSON:

```json
{
  "success": true,
  "pins": [...],
  "total": 123,
  "offset": 0,
  "limit": 40,
  "seed": 987654321,
  "has_more": true
}
```

Pin objects must include fields needed by board pin cards: `id`, `title`, `image_url`, `section_id`, `section_name`, `board_name`, `dominant_color_1/2`, `cached_filename`, `cached_width`, `cached_height`.

- [ ] **Step 3: Manual check**

With the app running and logged in:

```bash
curl -s -b cookies.txt 'http://localhost:8000/api/random-pins?seed=42&offset=0&limit=5' | head
```

Confirm stable order for the same seed across two calls, and different order for a different seed.

---

### Task 2: Home toolbar switcher + dual containers

**Files:** `templates/boards.html`

- [ ] **Step 1: Add segmented control** in `.sort-container` on the right, before/with existing controls (design choice C):

```html
<div class="home-view-switcher" role="group" aria-label="Home view">
  <button type="button" data-view="boards" class="home-view-btn active">Boards</button>
  <button type="button" data-view="pins" class="home-view-btn">Pins</button>
</div>
```

Style as a compact segmented control consistent with existing gray toolbar chrome (no new design system).

- [ ] **Step 2: Wrap boards toolbar controls** (size slider, cog, sort) in a container `#boardsToolbar` that can be shown/hidden.

- [ ] **Step 3: Add pins container** after `#boardsGallery`:

```html
<div id="homePinsView" class="hidden">
  <div id="homePinsEmpty" class="hidden">No pins yet</div>
  <div class="masonry-grid" id="homePinsGrid"></div>
</div>
```

Include `masonry.js` and enough CSS for `.pin-card` / `.masonry-grid` (copy the minimal rules from `board.html` if not already global).

---

### Task 3: Mode switching + preference

**Files:** `templates/boards.html` (inline script)

- [ ] **Step 1: Helpers**

```js
const HOME_VIEW_KEY = 'homeView';
function getHomeView() {
  const v = localStorage.getItem(HOME_VIEW_KEY);
  return v === 'pins' ? 'pins' : 'boards';
}
function setHomeView(view) {
  localStorage.setItem(HOME_VIEW_KEY, view === 'pins' ? 'pins' : 'boards');
}
```

- [ ] **Step 2: `showHomeView(view, { persist })`**

- Toggle active class on switcher buttons.
- Boards: show `#boardsGallery` + `#boardsToolbar`; hide `#homePinsView`; tear down pins scroll listener if any.
- Pins: hide boards gallery/toolbar; show `#homePinsView`; call `startPinsFeed()` (new seed every entry).
- If `persist !== false`, write `localStorage`.

- [ ] **Step 3: Wire clicks + initial load**

On `DOMContentLoaded` (or immediately if script is at bottom): `showHomeView(getHomeView(), { persist: false })`. Button clicks call `showHomeView(view)`.

---

### Task 4: Pins feed (1.5 screens + infinite scroll)

**Files:** `templates/boards.html`

- [ ] **Step 1: Adapt pin card builder** from `board.html` `createBoardPinCard` (~1205). Prefer showing board name badge when useful (optional: use `board_name` in place of/in addition to `section_name`). Keep aspect-ratio caps identical.

- [ ] **Step 2: Init masonry** on `#homePinsGrid` via `createScrapbookMasonry`, using the same column-count function as board pages (`boardPinSize` map + breakpoint cap).

- [ ] **Step 3: Estimate initial limit**

```js
function estimatePinsForScreens(screens) {
  // columnCount × ceil(viewportHeight / estimatedRowHeight) × screens
  // estimate row height from pin width × ~1.3 (portrait bias) + text
}
```

Target ~1.5 screens; clamp to a sensible min/max (e.g. 12–80).

- [ ] **Step 4: `startPinsFeed()`**

- Clear grid; new `seed = Math.floor(Math.random() * 2**31)`.
- `offset = 0`; fetch first page; append cards; `masonry.layout()` then `append` for later pages as board does.
- If `total === 0`, show empty state.
- Attach throttled scroll listener (500px from bottom, batch limit 40) matching `setupBoardPinsLazyLoad`.
- When a page returns empty / `!has_more` but user still scrolling and `total > 0`, generate new seed, reset offset to 0, continue (avoid immediate re-fetch loop: only reshuffle once per exhaustion).

- [ ] **Step 5: Switching back**

Boards → Pins always calls `startPinsFeed()` fresh. Pins → Boards only toggles visibility.

---

### Task 5: Verify end-to-end

- [ ] Boards default on a clean profile (`localStorage` cleared).
- [ ] Switch to Pins → ~1.5 screens load; scroll loads more; no duplicates until full pass.
- [ ] Reload → Pins still default.
- [ ] Switch to Boards → reload → Boards default.
- [ ] Empty library (or test user with 0 pins) shows empty state.
- [ ] Pin click opens `/pin/<id>`.
- [ ] Mobile: switcher usable; masonry columns respect breakpoints.

- [ ] Bump `VERSION` if the project convention requires it for user-facing features.

---

## Done when

All success criteria in the spec are met; no DB migration; `/random` unchanged.
