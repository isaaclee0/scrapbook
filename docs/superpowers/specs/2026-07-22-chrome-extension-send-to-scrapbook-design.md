# "Send to Scrapbook" Chrome Extension — Design

**Date:** 2026-07-22
**Status:** Approved

## Problem

Adding a pin currently requires opening the Scrapbook web app and using the
"Add New Content" dialog. There's no way to save an image while browsing
elsewhere without copying a URL and switching tabs. We want a Chrome
extension: right-click any image on any page → "Send to Scrapbook" → a pin
form appears on that page, styled like the app's own dialog, letting you pick
(or create) a board/section and save without leaving the page.

This is a two-part change: a small, additive slice of backend work in this
repo (token auth for non-browser clients), and a new, separate Chrome
extension project that consumes it.

## Decisions

| Topic | Choice |
|---|---|
| Scope | Right-click on `<img>` elements only; no page/selection capture |
| Auth | Personal Access Token (Bearer), generated in Scrapbook settings |
| Instance addressing | Single fixed base URL (public/VPN domain), entered once in extension options |
| Image capture | Background service worker fetches image bytes (`credentials: 'include'`, browser's cookie jar for that origin) → base64 data URL → reuses existing `data:image/` upload path. **Corrected during implementation** — see note below. |
| CORS strategy | `host_permissions: ["<all_urls>"]` declared upfront (unpacked personal extension, not Web Store) |
| Dialog placement | Centered modal, restyled copy of `add_content.html`'s dialog, injected via Shadow DOM |
| Board/section creation | Can create a new board inline from the dialog; sections are pick-only (new board = no sections yet) |
| Network calls | Made from the background service worker only, never the content script |
| Token storage | `chrome.storage.local` (device-local, not `sync`) |
| Distribution | Loaded unpacked; not published to Chrome Web Store |
| Out of scope (v1) | Multi-account/multi-instance, page/selection capture, new-section creation from extension, Web Store listing |

## Design

### 1. Backend changes (this repo)

**New table** `api_tokens`:

```sql
CREATE TABLE api_tokens (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  name VARCHAR(100) NOT NULL,
  token_hash CHAR(64) NOT NULL,      -- SHA-256 hex of the token
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  last_used_at TIMESTAMP NULL,
  revoked_at TIMESTAMP NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);
```

Added via `migrate.py`, following the repo's existing idempotent-migration
pattern and `TIMESTAMP`-column convention (matches `users`, `cached_images`,
`url_health`).

**Settings UI**: there's no Settings page in the app today, so this adds a new
one — a minimal `/settings` route + template with an "API Tokens" section:
generate a named token (shown once in plaintext, e.g. `sb_pat_<32 random
chars>`, only the SHA-256 hash is persisted), list existing tokens with
created/last-used dates, revoke button. `login_required`, cookie-auth only
(no reason for this page itself to accept bearer tokens).

**Auth layer** (`auth_utils.py` / `app.py`):
- `get_current_user()` gains a bearer-token path: if `Authorization: Bearer
  <token>` is present, hash it, look up a non-revoked row in `api_tokens`,
  resolve the user, and update `last_used_at`. Falls back to the existing
  cookie/JWT check when no bearer header is present — today's web app auth is
  unchanged.
- `login_required`'s JSON-vs-redirect branch currently only returns JSON for
  paths under `/api/*` or JSON `POST/PUT/DELETE` bodies; a `GET
  /get-sections/<id>` with a missing/invalid token would otherwise redirect to
  the login page (HTML), which an extension can't act on. Extend the check:
  also return JSON whenever the request carries an `Authorization` header.
- `require_csrf`: skip the CSRF check when the request authenticated via
  bearer token. CSRF defends cookie-based sessions specifically; it doesn't
  apply to token auth.

**Reused endpoints** (no behavioral changes beyond the auth layer above):
- `GET /api/boards` — list boards for the board picker.
- `GET /get-sections/<board_id>` — populate the section picker.
- `POST /create-board` — inline "+ New board" creation.
- `POST /add-pin` — create the pin, including `data:image/` payloads via the
  existing `save_pasted_image` path, and the existing post-commit dimension
  calculation / cache-queueing side effects.

No new endpoints, no changes to pin-creation logic itself.

### 2. Extension architecture (new project)

Manifest V3. `permissions: ["contextMenus", "storage", "scripting"]`,
`host_permissions: ["<all_urls>"]`.

- **Background service worker** (`background.js`)
  - Registers the context menu item (`contexts: ["image"]`) on install.
  - On click: `chrome.scripting.executeScript` injects the content script
    into the current tab, passing `srcUrl` (the image), plus the page's URL
    and title.
  - Holds the Personal Access Token (read from `chrome.storage.local`) and
    performs every network call to the Scrapbook instance — `GET
    /api/boards`, `GET /get-sections/:id`, `POST /create-board`, `POST
    /add-pin` — relayed to/from the content script via
    `chrome.runtime.sendMessage`. The token never reaches the page or the
    content script.
  - **Also fetches the right-clicked image itself** (`FETCH_IMAGE` message,
    `fetch(srcUrl, {credentials: 'include'})` → `arrayBuffer` → manual
    base64 encoding via `btoa` → data URL). See correction note below for
    why this lives here and not in the content script.

- **Content script** (injected on demand, not persistent)
  - Renders the modal in a Shadow DOM root so host-page CSS can't leak in or
    out.
  - Requests the image as a data URL from the background script (rather
    than fetching it itself — see correction note below).
  - Requests the board list from background on open; on board select,
    requests sections for that board.
  - Title defaults to the image's `alt` text, falling back to page title;
    both editable.

**Correction made during implementation (Task 12 code review):** the
original design above had the *content script* fetch the image directly, on
the theory that this would use "the page's own cookies/session" for
hotlink-protected or session-gated images. This turned out to be based on an
outdated assumption. As of Chrome 85–87, Manifest V3 removed content
scripts' ability to bypass CORS — a content-script `fetch()` is subject to
the exact same CORS restrictions as the host page itself, and only extension
pages (background service worker, popup, options page) retain the
CORS-bypass privilege for origins covered by `host_permissions`
([chromium.org](https://www.chromium.org/Home/chromium-security/extension-content-script-fetches/)).
Since most ordinary websites' images have no `Access-Control-Allow-Origin`
header, a content-script fetch would have failed for a large fraction of
real-world images — breaking the extension's primary use case. The fix:
the background service worker fetches the image instead (exempt from CORS
via `host_permissions: ["<all_urls>"]`), using `credentials: 'include'` to
still pick up the browser's stored cookies for that image's origin —
preserving the original intent (hotlink-protected/session-gated images
still work) via the browser's shared cookie jar rather than literally "the
page's own fetch." A second, related correction: MV3 service workers don't
reliably support `FileReader`, so the background-side blob→data-URL
conversion uses `response.arrayBuffer()` + manual `btoa()` base64 encoding
instead of `FileReader.readAsDataURL()`.

- **Options page**: Scrapbook base URL + Personal Access Token fields, saved
  to `chrome.storage.local`.

### 3. Dialog UI

Reuses `add_content.html`'s visual language (white rounded card, `#2980b9`
save button, `#e1e5e9` input borders, same header/footer layout) trimmed to:
image preview, title, board select (with a `+ New board...` entry that swaps
the select for a text input + Create button), section select, notes. Centered
over the page with a dimmed backdrop, matching the app's existing dialog
position — no anchored-popover positioning logic needed.

### 4. End-to-end flow

1. Right-click an image → "Send to Scrapbook."
2. Content script injects, shows the modal in a loading state, starts the
   image fetch, and asks background for the board list in parallel.
3. Pick a board (or create one) → sections populate (empty for a new board).
   Title/notes editable. Save enabled once image + title + board are all
   present (mirrors the existing dialog's `updateSaveButton` gating).
4. Save → content script messages background with `{title, board_id,
   section_id, notes, image_dataurl, source_url}` → background `POST
   /add-pin` with the bearer token.
5. Success: brief confirmation with a "View pin" link (opens the pin in a new
   tab), modal closes.

### 5. Error handling

| Condition | Behavior |
|---|---|
| No token configured | Modal shows "Not connected" + link to open the options page; no network call attempted |
| Token invalid/revoked (401) | "Your Scrapbook token isn't valid — check the extension options"; no silent retry |
| Instance unreachable | Generic connection error with a Retry button |
| Image fetch fails | Inline error in the preview area; Save stays disabled until resolved |

### 6. Files

| Repo | File | Change |
|---|---|---|
| `scrapbook` | `migrate.py` | Add `api_tokens` table migration |
| `scrapbook` | `auth_utils.py` | Bearer-token lookup/validation, hashing helper |
| `scrapbook` | `app.py` | Wire bearer auth into `get_current_user`/`login_required`, CSRF skip in `require_csrf`, new `/settings` route (token generate/list/revoke) |
| `scrapbook` | `templates/settings.html` | New template: API Tokens section |
| new extension repo | `manifest.json`, `background.js`, `content.js`, `options.html`/`options.js`, dialog CSS | Full extension implementation |

## Out of scope

- Multiple accounts / multiple Scrapbook instances per extension install.
- Right-click on selected text or whole-page capture.
- Creating new sections from the extension (board creation only).
- Publishing to the Chrome Web Store.
- Syncing the token across devices (deliberately `storage.local`, not `sync`).

## Success criteria

1. Right-clicking an image on an arbitrary site and choosing "Send to
   Scrapbook" opens a styled modal on that page within ~1s.
2. A pin can be saved to an existing board/section, or to a newly-created
   board, without leaving the page.
3. Saved pins are indistinguishable in the app from pins added via the web
   dialog (same image caching, dimension calculation, audit log entries).
4. An invalid/missing token produces a clear in-modal message, never a silent
   failure or an HTML login-page redirect.
5. Revoking a token in Scrapbook settings immediately invalidates the
   extension's access.
