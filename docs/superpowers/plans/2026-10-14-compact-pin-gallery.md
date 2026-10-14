# Compact pin gallery implementation plan

**Goal:** Reclaim image space using the bottom-strip design approved in chat.

**Architecture:** Keep gallery data and mutations unchanged. The gallery module creates one footer containing horizontally scrolling thumbnails, navigation, an add button, and an image-actions disclosure. The image surface accepts file drops and the focused gallery accepts image paste.

**Scope:** Local Docker and workspace only. Preserve unrelated authentication edits. No database or ownership changes.

- [x] Add browser coverage for image space at desktop widths, a non-wrapping footer, overflow-menu dismissal/focus, and file-only drag feedback. Adapt existing gallery interactions to open the actions disclosure.
- [x] In `static/js/pin-gallery.js`, group controls into one footer, hide management actions behind an accessible disclosure, and move upload/drop handling onto the gallery. Close the disclosure on Escape, outside interaction, selection, and actions; restore focus appropriately.
- [x] In `static/css/pin-gallery.css`, reserve about 56px for controls and let the image fill the remaining area without cropping. Use 36px thumbnails, visible focus rings, horizontal thumbnail scrolling, and touch-friendly targets on mobile. Keep menus and errors within the gallery bounds.
- [x] In `templates/pin.html`, keep the image fullscreen shortcut and supply existing board/section/search actions to the footer menu without duplicate replace/remove controls.
- [x] Run gallery, stack, and overlay tests in Chromium and WebKit. Inspect desktop and mobile rendering, including 20 images, one image, empty gallery, fullscreen, paste/drop, and failure recovery. Show the finished local preview.

Verification command: `npm run test:pin-gallery`.

## Verification results

- `npm run test:pin-gallery`: 96 tests passed across Chromium and WebKit.
- `git diff --check`: passed.
- Rendered the actual pin template against two cached sample images in a temporary loopback preview; no database changes.
- At 805 × 827, the gallery is 665px tall, with a 612px image area and a 53px toolbar (92% image area).
- Visually checked the popup and the 390px mobile layout; restored the browser viewport afterward.
- Local Docker serves the updated assets. No production operations or deployment.

## Upload feedback refinement — 2026-10-15

- Upload progress and success use a small overlay above the bottom controls, without changing the image area.
- Success fades after three seconds; a later upload restarts that timer. Batches receive one summary, and failed files retain their retry controls.
- Toasts announce status without moving keyboard focus and respect reduced-motion preferences.
- Verified the visible toast and its disappearance on the local demo pin. `npm run test:pin-gallery`: 106 tests passed across Chromium and WebKit.
