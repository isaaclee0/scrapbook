# Pin image gallery

**Date:** 2026-10-13
**Status:** Implemented and verified on 2026-10-13, with static board indicators reflecting the user's final interaction choice. Verification is tracked in `../plans/2026-10-13-pin-image-gallery.md`.

## Purpose

A pin can hold several related images: for example, a cake photograph as its
cover and a recipe screenshot as its second image. The pin retains one title,
source link, description, and notes field. Images belong to the pin's gallery;
notes remain plain text.

## Agreed interaction direction

- A pin has an ordered collection of images and an explicitly chosen cover.
- The cover represents the pin on boards. A stack indicator identifies pins
  with more than one image.
- The opened pin supports arrows, an image-position indicator, and mobile
  swiping. Images do not advance automatically in the opened pin.
- Board cards remain on the cover. Clicking or tapping opens the pin to browse
  its gallery. There is no hover cycling, press-and-hold preview, or swipe
  gesture on board cards.
- Adding images is separate from editing notes. Upload, drag-and-drop, and
  pasting into an image-add area all add gallery images.

## Proposed interaction details

### Board cards

Show a small stack icon and total image count for pins with multiple images.
Single-image pins do not show gallery controls or a stack indicator. The cover
and board layout stay fixed. Clicking or tapping the card opens the pin on its
cover; arrows and swipes inside the opened pin browse the other images.

### Opened pin

Use the existing image area for the gallery. Show previous/next buttons and
the current position when multiple images exist. Keep these controls
discoverable on touch screens; desktop buttons can become more prominent on
hover and keyboard focus. Navigation wraps at either end.

Horizontal swipes navigate images while vertical gestures continue to scroll.
Buttons provide the same actions without requiring gestures. Arrow keys
navigate when focus is in the gallery, never while editing notes or other
text fields. Announce the selected image and its position to assistive
technology.

Show the complete selected image without cropping. Fullscreen opens that
selected image and supports enlargement and scrolling/panning so a tall
recipe can be read at a useful size. Returning from fullscreen preserves the
selected image. Gallery navigation does not create browser-history entries;
Back retains the existing pin-overlay behaviour.

### Adding and managing images

Provide an explicit **Add images** action in the pin view. Its focused add
area accepts pasted images and dropped files, and its file picker supports
multiple files. Do not intercept normal paste into the notes field.

Provide thumbnails for selecting images, changing their order, removing an
image, replacing an image, and choosing **Make cover**. Reordering must also
have buttons usable with a keyboard or touch, rather than requiring dragging.
New images append to the gallery without changing an existing cover.

The cover is always the first item in the displayed order. Making another
image the cover moves it to the first position and preserves the relative
order of the others. Other reordering applies to the remaining images;
changing the first position uses the explicit Make cover action.

Removing the cover promotes the next image. Removing the last image leaves
the existing default-pin placeholder; the placeholder is not an attachment
and does not contribute to the image count. The next added image becomes
the cover. Replacing an image preserves its position and cover role.

Existing image-specific tools, including fullscreen, image search, and setting
a board or section cover, operate on the currently selected image. Choosing
a board or section cover does not implicitly change the pin's cover.

## Implementation direction

The current application stores one image on each `pins` row. The pin view
already provides image replacement, removal, fullscreen, and a text notes
field. Board cards are rendered both on the server and through
`createBoardPinCard()`. The board overlay loads the pin view in an iframe and
refreshes an affected card after changes.

Introduce a related image collection with stable image IDs, pin ownership,
display order, image location, dimensions, and storage/cache references.
Keep the existing pin image fields as a compatibility projection of the
cover while existing readers and writers are integrated. All image mutations
must use a common gallery service so the collection and cover projection
change atomically. Existing pins migrate idempotently to a one-image
collection, excluding the default placeholder.

Keep gallery presentation in a small JavaScript module instead of extending
the large inline scripts in the pin and board
templates. Pass an optional selected image ID through the overlay opening
flow and validate that it belongs to the requested pin. Preserve existing
same-origin messaging, access checks, and board scroll behaviour.

Board queries return image counts without loading every attachment. Fetch a
gallery when opening a pin. Load alternate image bytes on demand; use
preview-sized cover images for boards and retain a readable version for the
opened pin. Invalidate gallery data after edits.
The initial board render, subsequently loaded cards, and refreshed cards
must show consistent indicators.

Uploaded recipe images are retained user content. Reuse suitable existing
image storage components, but do not allow cache expiry or cleanup to remove
the only copy of an attachment. Gallery references must be included in
cleanup checks and in pin/board/section deletion snapshots and restoration.
Removing an image must not delete a file still used as another image, board
cover, section cover, or retained undo snapshot.

Gallery requests use the existing authenticated, user-scoped access model
and CSRF protection for mutations. Validate uploads as actual images and
enforce configured file-size, decoded-image-size, and image-count limits on
the server. Return actionable errors without replacing the current gallery
with a failed upload. This is an implementation direction, not a completed
endpoint or database schema specification.

## Error handling

- An image that cannot load shows a local error in the opened gallery while
  retaining working navigation to the other images.
- For multiple uploads, show success or failure per file and allow retrying
  failures. Preserve the input order among successful additions.
- Failed removal, reorder, replacement, or cover changes retain the last
  saved state and offer retry. Keep selection by stable image ID after edits.
- The server serializes gallery mutations for each pin. Stale requests that
  reference missing images or an outdated reorder set are rejected and the
  client reloads the current collection rather than dropping other images.

## Verification for implementation

- Migrate existing remote images, cached images, uploaded images, and default
  placeholders; rerunning the migration must not duplicate attachments.
- Verify add, replace, reorder, make-cover, remove-cover, remove-last, and
  cross-user access behaviour, including atomic cover projection updates.
- Verify uploaded originals survive cache cleanup and that deletion/undo of
  pins and their containers preserves the gallery, order, and cover.
- Exercise desktop arrows, keyboard navigation, mobile swipes, accessible
  buttons, readable fullscreen images, and unaffected text-field input.
- Verify stack counts and static cover behavior on desktop and touch input.
- Confirm opening and closing preserves board position and filters, and
  cover metadata is protected from stale asynchronous updates.
- Check indicators and cover changes on server-rendered, dynamically loaded,
  and refreshed cards. Existing one-image creation paths must remain valid.

## Scope

The initial feature adds and manages images in an existing pin, supports the
opened gallery, and provides board indicators.
Existing pin-creation and extension capture flows continue to create one
image; users can add more after opening the resulting pin. Other pin lists
continue to show the cover and open the gallery.

Rich text notes, per-image captions or source links, video/PDF attachments,
recipe text recognition, merging separate pins into a gallery, and capturing
multiple images through the extension are separate future features.
