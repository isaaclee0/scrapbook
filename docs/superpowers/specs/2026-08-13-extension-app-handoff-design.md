# Extension-to-App Pin Handoff — Design

**Date:** 2026-08-13  
**Status:** Approved

## Problem

The extension currently recreates the Add Pin form inside an arbitrary source
page. That duplicates board and section UI, requires an API token, and makes
the experience vulnerable to host-page layout, scrolling, and content-security
restrictions. The Scrappl app already owns the authenticated Add Pin workflow.

## Goal

For either **Send to Scrappl** on an image or a completed region capture, open
Scrappl immediately in a new tab and show its native Add Pin modal with these
values ready to edit:

- the captured image;
- the page URL where it came from; and
- the page title.

No API token is required. Production defaults to `https://scrappl.com`, while
a manually configurable URL supports local and staging testing.

## Scope

- Remove the injected extension Add Pin form and its board/section operations.
- Retain the extension's image fetch and region-selection mechanisms.
- Introduce an in-memory extension-to-app handoff that prepopulates the
  existing app modal.
- Simplify extension settings to a Scrappl URL override only.
- Preserve a handoff across login when the newly opened Scrappl tab is not
  authenticated.

This does not otherwise change the application's pin-save API or rework region
capture behavior.

## Architecture

### Extension

The background service worker is responsible for the handoff.

1. For a right-clicked image, it fetches the image as a data URL.
2. For a region capture, it receives the cropped PNG data URL from the existing
   page overlay.
3. It creates a random handoff nonce and opens the configured Scrappl URL in a
   new tab with only the nonce in its fragment identifier.
4. Once the tab is ready, it injects a tiny bridge into that Scrappl tab. The
   bridge posts the image data, page URL, title, and nonce to the page's own
   JavaScript via `window.postMessage`.

The image payload is never encoded in a URL, persisted in extension storage,
or sent to a new API endpoint. The tab URL fragment is removed immediately by
the app after it validates the nonce.

The extension uses `https://scrappl.com` when no override is stored. Its options
page exposes just one optional Scrappl URL field for localhost and staging.
The API-token field, setup text, background API calls, and extension connection
mechanism are removed.

### Scrappl app

Both the authenticated application layout and the standalone login page register
a narrowly scoped handoff listener. When either page receives a valid
nonce-matching payload from the extension bridge, it clears the fragment. On an
authenticated application page it then opens `showAddContentDialog()`.

The listener uses the modal's existing image-input path to populate the preview
and internal image data, sets the source URL field to the original page URL,
and sets the editable title field to the source page title. Board, section,
creation, validation, and final saving are handled solely by the app's existing
modal implementation.

If the user is unauthenticated, the app retains the payload in browser session
storage after receiving it, sends the user through its normal login flow, then
consumes the payload and opens the modal on the first authenticated app page.
Session storage is cleared as soon as the modal receives the values and is
cleared on expiry. The data never becomes server-side or cross-user state.

## Data Flow

```text
Image context menu / region capture
             |
             v
Extension fetches or crops image
             |
             v
Open Scrappl tab with one-time nonce in URL fragment
             |
             v
Extension bridge posts in-memory payload to Scrappl page
             |
             v
Authenticated: native Add Pin modal opens prefilled
Unauthenticated: session storage -> login -> modal opens prefilled
             |
             v
Existing Add Pin save flow persists the pin
```

## Validation and Error Handling

- The app accepts only a handoff whose nonce matches the fragment of the current
  page, then removes that fragment before rendering the modal.
- The listener verifies the payload shape and accepts only image data URLs.
- An invalid, expired, or duplicate handoff is ignored without opening a modal.
- If image retrieval or screenshot cropping fails, the extension does not open
  an empty Scrappl tab; it reports the existing capture failure instead.
- If the Scrappl tab cannot receive the bridge message, the extension surfaces
  a concise failure and leaves the source page unchanged.
- The app bounds session-storage handoffs by a short expiry and removes stale
  records before use.

## Testing

- Extension tests cover default/override URL resolution, new-tab creation,
  nonce construction, successful bridge delivery, and failure paths.
- App tests cover handoff payload validation and the post-login session-storage
  path.
- Browser-level coverage verifies that image and region flows open a new tab
  and prefill the app's Add Pin modal without an API token.
- Existing Add Pin tests verify source URL, title, and image save unchanged.

## Files Expected to Change

| File | Change |
|---|---|
| `chrome-extension/background.js` | Replace token/API dialog workflow with capture and app-tab handoff. |
| `chrome-extension/content.js` | Retain only region selection and capture messaging; remove injected form. |
| `chrome-extension/options.html` | Replace token setup controls with optional URL override. |
| `chrome-extension/options.js` | Store and validate only the URL override. |
| `chrome-extension/manifest.json` | Remove no-longer-needed external connection surface and bump version. |
| `templates/base.html` | Receive, validate, and consume authenticated app handoffs using the existing modal. |
| `templates/login.html` | Receive unauthenticated handoffs and retain them in session storage through login. |
| `tests/extension/*`, app tests | Add focused coverage for handoff behavior. |

## Success Criteria

1. No API key is created, copied, stored, or sent by the extension.
2. Image context-menu and screenshot flows open Scrappl immediately in a new
   tab after capture succeeds.
3. The normal app Add Pin modal—not extension UI—contains the image, source URL,
   and editable page title.
4. The extension defaults to `https://scrappl.com` and supports a URL override
   for development.
5. The handoff survives login, is user-local, and expires promptly.
6. Image data is absent from browser URLs and server logs.
