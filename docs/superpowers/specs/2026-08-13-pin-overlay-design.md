# Board Pin Overlay — Design

**Date:** 2026-08-13  
**Status:** Approved

## Problem

Pins currently look like a lightbox, but opening one follows a normal link to
`/pin/<id>` and replaces the board document. Closing the pin calls
`history.back()`. If the browser restores the board from its back/forward
cache, the original grid survives. If it reloads the board instead, only the
first 40 pins are server-rendered, the active section resets to "all", and a
100 ms timer tries to restore a saved pixel offset. This intermittently loses
the user's place, especially after enough time in another browser tab for the
cached board document to be evicted.

The intended product behavior is simpler: a pin is an overlay on the board.
Opening or closing it must not unload, rebuild, filter, resize, or scroll the
board underneath it.

## Decisions

| Topic | Choice |
|---|---|
| User experience | Keep the board document alive and display the pin in a centered overlay panel |
| Reuse strategy | Load the existing pin editor in a same-origin iframe instead of merging its roughly 2,300 lines of markup, styles, and inline behavior into the board template |
| Panel size | Match the current pin lightbox: 90vw, maximum 1200px wide, 90vh high, 16px radius; the board remains visible through a dimmed backdrop |
| Mobile behavior | Preserve the current responsive behavior: the panel becomes full-screen at 768px and below |
| URL/history | Represent an open pin as `/board/<board-id>?pin=<pin-id>` using the History API; Back closes and Forward reopens the overlay |
| Direct navigation | `/pin/<id>` remains a complete standalone page; directly loading a board `?pin=` URL opens its overlay after the board renders |
| Board synchronization | The embedded pin reports mutations to the board; on close the board refreshes or removes only the affected card |
| Scroll behavior | Never reconstruct board scroll; the board DOM, loaded cards, section state, and scroll offset remain in memory |
| Testing | Add a narrow Playwright smoke suite for overlay, history, mutation, and scroll behavior, plus server-side route tests |

## Architecture

### 1. Parent overlay on the board

`board.html` gains an overlay shell outside a dedicated wrapper around the
ordinary board content. The shell contains:

- a fixed, viewport-sized backdrop using the current
  `rgba(0, 0, 0, 0.75)` treatment;
- a centered panel measuring `90vw × 90vh`, capped at 1200px wide, with a
  16px radius and the existing lightbox shadow;
- a titled iframe that fills the panel; and
- a loading state and a recoverable error state with Retry, Open as Page, and
  Close actions.

The iframe, not the shell, contains the existing pin header, image, metadata,
editing controls, and secondary dialogs. The parent shell supplies the outer
backdrop and panel dimensions so there is no nested or double backdrop.

While open, the ordinary board wrapper is `inert` and hidden from assistive
technology. Focus moves into the panel and returns to the originating pin card
on close. The overlay prevents wheel and touch events on the exposed backdrop
from reaching the board. It does not hide the document scrollbar or otherwise
change viewport width, because doing so could trigger a masonry relayout. The
iframe remains independently scrollable.

On screens 768px wide or narrower, the shell removes its outer padding and the
panel fills the viewport with no corner radius, matching the current mobile
pin layout.

### 2. Overlay controller

A new `static/js/pin-overlay.js` module owns overlay behavior instead of adding
another large inline script to `board.html`. It exposes one board-scoped
controller initialized with the board ID, shell elements, grid element, and
card-refresh callback.

The controller is responsible for:

- delegated interception of ordinary primary-button clicks on `.pin-card a`;
- preserving normal browser behavior for Command/Ctrl/Shift/Alt clicks,
  middle clicks, `target` links, downloads, and prevented events;
- opening and closing the shell and iframe;
- reconciling the `?pin=` URL with History API state;
- responding to Back and Forward through `popstate`;
- focus placement and restoration;
- Escape, backdrop, X, and Cancel close paths;
- same-origin iframe message validation;
- loading, failure, Retry, and Open as Page states; and
- refreshing the affected board card after a pin mutation.

The existing per-link `saveScrollOnPinClick()` listener and delayed
`restoreScrollPosition()` pixel restoration are removed. With overlay clicks,
the board never navigates. Modified clicks open another tab while the board
stays in place. If JavaScript fails entirely, the existing link still provides
normal full-page navigation and the browser's native history behavior.

### 3. URL and history behavior

Opening pin 456 from board 123 pushes one same-document entry:

```text
/board/123?pin=456
history.state = { scrapbookPinOverlay: true, pinId: 456 }
```

The path remains a board path so existing board functions that derive the
board ID from `window.location.pathname` continue to work while the overlay is
open.

The controller follows these rules:

1. A pin click calls `history.pushState()` and opens the corresponding iframe.
2. Browser Back removes the overlay entry; the resulting `popstate` closes the
   panel without touching the board.
3. Browser Forward restores the `?pin=` entry and reopens the panel.
4. Loading `/board/123?pin=456` directly opens that pin after controller
   initialization. Because this entry was not pushed by the current board,
   pressing the panel X removes `pin` with `history.replaceState()` rather than
   sending the user away from the board.
5. An invalid, inaccessible, deleted, or cross-board pin produces the overlay
   error state without altering the board.
6. The standalone `/pin/456` URL remains available for copied direct links,
   modified clicks, JavaScript-disabled navigation, and Open as Page.

Only the `pin` query parameter is added or removed. Other board query
parameters are preserved.

### 4. Embedded pin mode

`view_pin()` recognizes the exact query value `embedded=1` and passes an
`embedded` boolean to `pin.html`. The iframe URL also supplies
`board_id=<current-board-id>`; embedded rendering returns 404 unless the pin's
user-scoped `board_id` matches that expected board. This prevents a hand-edited
board URL from embedding one of the user's pins under the wrong board.
Authentication and user-scoped pin lookup otherwise remain identical to the
standalone page.

In embedded mode:

- global navigation, the floating add controls, development footer, and other
  page chrome are not rendered or are explicitly hidden;
- the iframe document background is transparent;
- `.pin-lightbox` supplies no outer backdrop or padding and fills the iframe;
- `.pin-content` fills the iframe panel while retaining its internal header,
  image/details layout, dialogs, and responsive behavior; and
- fullscreen permission is enabled on the iframe so the existing image
  fullscreen control remains functional.

Standalone mode is unchanged.

Pin actions call one `closePinView()` abstraction rather than invoking
`history.back()` or assigning a board URL directly. In standalone mode it uses
the current navigation behavior. In embedded mode it posts a close request to
the parent.

### 5. Parent/iframe message protocol

Messages use a versioned, namespaced object:

```json
{
  "source": "scrappl-pin-overlay",
  "version": 1,
  "type": "changed",
  "pinId": 456,
  "change": "updated"
}
```

Supported `type` values are:

- `ready` — the embedded editor has initialized;
- `close` — X or Cancel requests that the parent close the overlay; and
- `changed` — the pin was updated, moved, or deleted.

Supported `change` values are `updated`, `moved`, and `deleted`. Multiple
changes collapse into one dirty state; the parent does not repeatedly refresh
the card while the user is still editing.

The board accepts a message only when all of the following are true:

- `event.origin === window.location.origin`;
- `event.source === overlayIframe.contentWindow`;
- the namespace and version match; and
- the message pin ID matches the currently open pin.

Unknown fields, types, versions, sources, and origins are ignored.

### 6. Pin-card synchronization

A new authenticated endpoint, `GET /api/pin/<int:pin_id>/card`, returns the
current user-scoped representation needed by `createBoardPinCard()`, including
the pin and board IDs, section ID/name, title, image and source URLs, cached
filename and dimensions, dominant colors, and current link status. A pin that
does not belong to the current user returns 404, without revealing whether it
exists for another user.

When a dirty overlay closes:

1. For a known deletion, remove the existing card immediately.
2. Otherwise request the latest card representation.
3. If the pin still belongs to the current board, replace or update its card
   and reapply the active section filter.
4. If it moved to another board, remove it from this grid.
5. Run masonry only after a visible card was changed, added, hidden, or
   removed.
6. Restore focus to the refreshed card when it still exists; otherwise focus
   the grid or the nearest remaining card.

Closing an unchanged pin performs no network request and no masonry layout.
Board-title, board-cover, or section-cover changes made from the pin editor do
not force a board reload and are not synchronized in this change; they become
current on the next normal board visit. The pin grid and its position always
take priority.

### 7. Lifecycle cleanup

Because overlay use no longer navigates away from the board, background board
processing may continue normally behind the inert UI. On an actual board
navigation, `stopAllProcessing()` also closes and clears
`processingState.eventSource` in addition to its existing fetch and timeout
cleanup. This prevents a tracked server-sent-events connection from surviving
longer than its board page.

## Error handling

- An iframe load that does not reach the `ready` handshake within a bounded
  timeout displays Retry, Open as Page, and Close. A late valid `ready` message
  may still replace the error state with the editor.
- Retry reloads only the iframe. Open as Page navigates normally to
  `/pin/<id>`.
- If card refresh fails, the board stays open and unchanged, the overlay still
  closes, and a toast explains that the card may be stale. The board is never
  reloaded as recovery.
- A 404 after an `updated` or `moved` notification removes the card only when
  the embedded editor also reported deletion; otherwise it leaves the card in
  place and reports the refresh failure. This avoids treating transient or
  authorization errors as deletion.
- Repeated open/close actions cancel obsolete loading timers and ignore
  messages for previously open pins.

## Accessibility

- The shell uses dialog semantics with `aria-modal="true"` and an accessible
  label identifying the pin editor.
- The iframe has a descriptive `title`.
- Focus enters the pin editor after `ready`, remains out of the inert board,
  and returns to the originating card or a deterministic fallback on close.
- Escape closes the top-level pin overlay only when an inner confirmation or
  editing dialog is not active.
- X, Cancel, Retry, Open as Page, and backdrop behavior are keyboard operable.
- Existing mobile layout and reduced-motion preferences remain honored.

## Files

| File | Change |
|---|---|
| `templates/board.html` | Add the parent shell and board wrapper, initialize the controller, remove legacy pixel scroll save/restore, and provide the card refresh integration |
| `static/js/pin-overlay.js` | New isolated overlay, history, focus, message, loading, and recovery controller |
| `templates/pin.html` | Add embedded presentation and route navigation-sensitive actions through the parent message bridge |
| `templates/base.html` | Suppress shared page chrome when rendering an embedded pin, without affecting standalone pages |
| `app.py` | Pass embedded mode to the pin template and add the user-scoped pin-card JSON endpoint |
| `package.json` / lockfile | Add the narrow Playwright test command and development dependency |
| `tests/` | Add server route coverage and focused overlay browser scenarios |

## Verification

### Server and template tests

- Standalone pin rendering retains global page chrome and normal navigation.
- Embedded pin rendering omits global chrome and enables the message bridge.
- Pin lookup and pin-card JSON are user-scoped.
- The card endpoint returns all fields required by board-card rendering.
- Missing, deleted, and other-user pins return 404 without information
  leakage.

### Playwright browser tests

- An ordinary pin click opens the bounded overlay and does not navigate or
  replace the board document.
- The board remains visible around the panel.
- Modified clicks retain native new-tab/new-window behavior.
- X, Cancel, backdrop, Escape, and Back close the overlay; Forward reopens it.
- A directly loaded board `?pin=` URL opens the overlay and X reveals the same
  board instead of leaving it.
- Invalid iframe messages are ignored.
- Editing a pin refreshes its card without moving board scroll.
- Moving or deleting a pin removes it and relays out visible cards.
- Closing an unchanged pin does not invoke card refresh or masonry layout.
- After infinite scrolling and selecting a section, open a pin, background and
  restore the browser tab, then close the pin. Scroll position, loaded cards,
  and the active section remain exactly unchanged.
- The desktop panel is bounded and centered; the mobile panel fills the
  viewport.
- Iframe failure exposes working Retry, Open as Page, and Close controls.

Manual verification covers current Chrome and Safari, responsive sizing,
screen-reader focus flow, image fullscreen, external links, and secondary pin
dialogs.

## Out of scope

- Rewriting the pin editor as native board DOM or a client-side component
- Applying the overlay to search results, the home Pins feed, random-pin
  navigation, or other pages in this change
- Prefetching pin iframe documents
- Keeping multiple pin overlays open
- Redesigning the pin editor's internal layout or editing controls
- Live synchronization of unrelated board metadata beyond the affected pin
  card
- General conversion of the application into a single-page app

## Success criteria

1. Opening a pin from a board never unloads or reconstructs that board.
2. The centered pin panel matches the current desktop lightbox dimensions and
   leaves the dimmed board visible around it; current mobile full-screen
   behavior remains intact.
3. Closing after infinite scrolling, section filtering, or time spent in
   another browser tab reveals the exact unchanged board position and state.
4. X, Cancel, backdrop, Escape, Back, Forward, direct URLs, modified clicks,
   and standalone pin pages behave predictably.
5. Pin edits, moves, and deletion update only the affected board card without
   reloading the board.
6. Cross-origin or stale iframe messages cannot control the overlay.
7. Failures remain local to the overlay and never use a board reload as
   recovery.
