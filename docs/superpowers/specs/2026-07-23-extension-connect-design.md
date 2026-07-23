# Extension Download & One-Click Connect — Design

**Date:** 2026-07-23
**Status:** Approved

## Problem

The Chrome extension currently requires manual setup: find the extension's
source folder on disk, load it unpacked, generate a token in Scrapbook's
Settings, copy the URL and token by hand into the extension's options page.
Every step is a chance to mistype something. We want Settings to offer a
one-click path: download the extension, then a single "Connect Extension"
button that configures it — URL and token both — with no manual typing.

## Decisions

| Topic | Choice |
|---|---|
| Distribution | Backend zips the extension repo's current source on request; no Chrome Web Store publishing |
| Zip source of truth | Read directly from the extension repo's files at request time (bind-mounted into the container), not a vendored copy — avoids drift |
| URL hand-off | Fully automatic via `chrome.runtime.sendMessage` (Chrome's website-to-extension messaging API) |
| Token hand-off | Also automatic, via the same channel, in the same click — see safety reasoning below |
| Extension identity | A `"key"` added to `manifest.json` (generated once) gives the extension a stable, predictable ID regardless of install path, so Settings can target it by ID |
| Origin scoping | `externally_connectable.matches` is templated into the zipped manifest per-request from the actual request's origin (`request.host_url`) — tightly scoped to the user's real instance, not a broad wildcard |
| Sender validation | `background.js`'s external-message handler checks `sender.origin` before accepting anything (defense in depth beyond the manifest-level scoping) |
| Existing manual token flow | Kept as-is, for non-extension API use (curl, scripts) |
| Out of scope | Chrome Web Store publishing, other browsers, multi-instance support, auto-detecting install state ahead of time |

## Design

### 1. Why pushing the token automatically is safe

This was a specific point raised and worth documenting: sending the bearer
token via `chrome.runtime.sendMessage` doesn't hand it to a new party — the
Settings page already holds the plaintext token in its JS/DOM the moment
it's generated (that's how the existing reveal box shows it to the user).
Relaying it to the extension moves it from one thing the user controls
(their own logged-in Settings page) to another (their own installed
extension), gated by the tightly-scoped `externally_connectable.matches`
so no other origin can reach the extension this way. It also avoids a real
risk the manual copy-paste flow has: the token never touches the OS
clipboard, which other processes on the machine can read.

### 2. Extension changes (`scrapbook-chrome-extension` repo)

- **`manifest.json`**: add a `"key"` field (base64-encoded public half of a
  generated RSA key pair — the standard mechanism for giving an unpacked
  extension a stable ID; Chrome derives the ID as a SHA-256 hash of the
  decoded key). This makes the extension's ID identical every time it's
  loaded, regardless of which folder it's unpacked into. Also add
  `"externally_connectable"` with a `matches` array — populated with a
  placeholder here since the real value is injected per-download (see
  section 3); confirm during implementation planning exactly how Chrome
  expects this field's match-pattern syntax and whether `onMessageExternal`
  needs any permission beyond `externally_connectable` itself (verify
  against current Chrome docs before finalizing, the same way `<all_urls>`
  vs. `activeTab` was verified for `captureVisibleTab` earlier — extension
  API details in this project have been wrong on first assumption before).
- **`background.js`**: add a `chrome.runtime.onMessageExternal.addListener`
  handler. Validates `sender.origin` matches what's expected (or at minimum
  logs/rejects anything unexpected — exact validation strategy is an
  implementation-planning detail), then handles a message shape like
  `{type: 'CONNECT', baseUrl, token}` by writing both to
  `chrome.storage.local` (the same keys `getConfig()` already reads),
  responding `{ok: true}`.

### 3. Backend changes (`scrapbook` repo)

- **New route** (e.g. `GET /extension/download`): reads the extension
  repo's source from a bind-mounted path (new volume in
  `docker-compose.override.yml`, mirroring the existing pattern already
  used there for cross-repo/cross-directory local dev needs — see
  `[[scrapbook-local-dev-quirks]]`), builds a zip in memory or a temp file,
  and serves it as a download. Before zipping, the route rewrites the
  `manifest.json` inside the zip's copy to set
  `externally_connectable.matches` to the current request's origin
  (`request.host_url`), so the downloaded extension is pre-scoped correctly
  with no manual editing. Excludes `.git/`, `docs/`, and other non-runtime
  files from the zip.
- **Settings page** (`templates/settings.html`):
  - A "Get the extension" section: short numbered install steps (download →
    unzip → `chrome://extensions` → enable Developer mode → Load unpacked →
    select the folder) plus a **Download** button hitting the new route.
  - A **Connect Extension** button: on click, calls the existing
    `POST /api/tokens` to create a token (reusing the existing reveal-box UI
    so the user still has a visible record of it), then calls
    `chrome.runtime.sendMessage(EXTENSION_ID, {type: 'CONNECT', baseUrl:
    window.location.origin, token}, callback)`. `EXTENSION_ID` is a
    hardcoded JS constant, computed once from the generated key (see
    section 2) and baked into the page — no backend involvement needed for
    this call itself, since `chrome.runtime.sendMessage` targeting an
    external extension ID is a plain browser API available to any web page,
    gated entirely by the target extension's own `externally_connectable`
    allowlist.
  - Success: "Extension connected!" Failure (extension not installed, not
    loaded, ID mismatch, or the origin doesn't match what the extension was
    scoped to): a clear message telling the user to check the extension is
    installed, not inventing more specific diagnosis than
    `chrome.runtime.lastError` actually provides.
  - Existing "Generate token" flow and token table are unchanged — this is
    additive.

## Out of scope

- Publishing to the Chrome Web Store.
- Firefox or other non-Chromium browsers.
- Supporting more than one Scrapbook instance/token from a single Settings
  page or extension install.
- Detecting whether the extension is installed before the user clicks
  Connect (the button just attempts the message and reports failure if
  unreachable, rather than pre-flighting).
- Automatically re-connecting if the user's Scrapbook URL changes later
  (e.g. moving from localhost to a real domain) — re-downloading and
  re-connecting is the expected path, consistent with the rest of this
  project's "personal tool, reconfigure manually when your setup changes"
  posture.

## Success criteria

1. Downloading the extension from Settings and loading it unpacked works
   with no manual file-finding.
2. Clicking "Connect Extension" (with the extension loaded) configures both
   the URL and a working token with zero manual typing or clipboard use.
3. The resulting extension state is indistinguishable from one configured
   manually via its options page — same storage keys, same behavior.
4. A Settings page loaded from a different origin than the one the
   extension was downloaded/scoped for cannot successfully message it.
5. If the extension isn't installed or reachable, clicking Connect fails
   clearly rather than silently.
