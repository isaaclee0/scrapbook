# Searchable Board and Section Pickers — Design

**Date:** 2026-08-13
**Status:** Approved

## Problem

The Chrome extension currently renders boards and sections as native select
elements. The board list is now large enough that scanning it is slow, and the
popup does not let a user create a section. Board creation exists, but it is
hidden behind a special select option and uses a different interaction from
ordinary selection.

This change makes both fields searchable, consistently alphabetized, and able
to create the relevant item without leaving the extension dialog.

## Scope

- Replace the board and section selects in the injected extension dialog with
  accessible searchable comboboxes.
- Sort boards and sections alphabetically in the extension, independent of API
  response order.
- Let users create a board or a section from its corresponding picker.
- Preserve the existing image, title, notes, save, authentication, and error
  behavior.
- Defer region-selection and screenshot hardening until a failing site can be
  reproduced. No capture behavior changes are part of this design.

## Interaction Design

### Opening and filtering

Focusing or clicking an empty picker opens its full list. A create action is
pinned above the existing items:

- `+ Create new board` for the board picker.
- `+ Create new section` for the section picker.

Existing items appear below that action in case-insensitive alphabetical order.
Typing filters existing items by a case-insensitive substring match while the
create action remains visible. The section picker is disabled until a board is
selected.

Each picker follows standard combobox keyboard behavior:

- Arrow Down and Arrow Up move through visible options.
- Enter selects the active option.
- Escape closes the list without changing the selection.
- Tab leaves the field normally.
- Clicking outside closes the list.

The selected item's name remains visible in the input. Editing that text starts
a new search; it does not change the selected ID until the user chooses another
item. The pin Save button continues to depend on a selected board ID, not merely
text in the board input.

### Board changes

Selecting a board stores its ID, clears any selected section, and requests that
board's sections. While the request is pending, the section picker is disabled
and indicates that sections are loading. Once loaded, it is enabled and opens
the alphabetized results on interaction.

If the user selects another board before an earlier sections request completes,
the earlier response is ignored. Clearing the board clears and disables the
section picker.

### Creating items

Choosing a create action reveals a compact inline row below that picker with a
name input, Create button, and Cancel button.

- Creating a board sends the trimmed name to the existing `POST /create-board`
  endpoint. The returned board is inserted into the local list, the list is
  re-sorted, and the board becomes selected immediately. The section picker is
  then enabled with an empty list so the user may create a section for the new
  board without another round trip.
- Creating a section sends the selected board ID and trimmed name to the
  existing `POST /create-section` endpoint. The returned section is inserted,
  the section list is re-sorted, and the section becomes selected immediately.

Create is disabled for an empty trimmed name and while its request is pending.
Enter submits the inline name field; Escape or Cancel exits creation and returns
focus to the picker. API errors use the dialog's existing inline error area and
leave the entered name available for correction or retry.

## Architecture

### Content script

`chrome-extension/content.js` owns a small reusable combobox component used for
both fields. The component accepts item records shaped as `{ id, name }` and
callbacks for selection and creation. It owns only presentation state—query,
open/closed state, and active option—while the dialog continues to own selected
board and section IDs.

The component exposes operations to:

- replace and alphabetize its items;
- enable or disable interaction;
- select or clear an item by ID;
- render loading and empty states; and
- destroy document-level listeners when the dialog closes.

Keeping selection IDs in the dialog state prevents typed but unselected text
from being submitted as a real board or section.

### Background service worker

`chrome-extension/background.js` adds a `CREATE_SECTION` message case that
posts `{ board_id, name }` to `/create-section`. The route already accepts
bearer-token authentication through the existing API-token path, so no Flask
route or database change is required.

### Styling and isolation

The combobox, listbox, options, empty/loading states, and inline creation rows
are styled inside the existing Shadow DOM. Host-page CSS therefore cannot
change their layout. The list has a bounded height and scrolls independently so
large board collections do not make the dialog exceed the viewport.

## Data Flow

1. The dialog requests boards with `LIST_BOARDS`.
2. Returned boards are normalized to `{ id, name }`, alphabetized, and passed
   to the board combobox.
3. Selecting a board clears the section selection and sends `LIST_SECTIONS`.
4. Returned sections are normalized, alphabetized, and passed to the section
   combobox if the selected board still matches the request.
5. A create action sends `CREATE_BOARD` or `CREATE_SECTION` through the
   background worker.
6. A successful result is normalized, inserted, re-sorted, and selected.
7. Saving a pin uses the selected IDs exactly as it does today.

## Error Handling

- Board-list failure leaves the board picker enabled with an error message and
  no selectable items.
- Section-list failure leaves the selected board intact, re-enables the section
  picker, and shows an inline error so the user may still save without a
  section.
- Creation failures retain the typed name and keep the creation row open.
- Duplicate-name and validation errors are displayed from the backend response.
- Late section responses cannot overwrite sections belonging to a newer board
  selection.
- Closing the dialog removes any combobox listeners attached outside its Shadow
  DOM.

## Testing

Automated tests will exercise behavior rather than internal implementation:

- Case-insensitive alphabetical sorting for boards and sections.
- Full-list display on focus/click and substring filtering while typing.
- The create action remains first while filtering.
- Mouse and keyboard selection, dismissal, and focus behavior.
- A board change clears the section and rejects stale section responses.
- The section picker is disabled without a board and while loading.
- Board creation selects and sorts the returned board.
- Section creation sends the selected board ID, then selects and sorts the
  returned section.
- Empty names do not submit; failures retain input for retry.
- Pin submission still sends selected board and section IDs.
- The background worker maps `CREATE_SECTION` to the correct endpoint and JSON
  body.

The extension manifest and scripts will also receive syntax checks, and the
Flask test suite will confirm the reused endpoints have not regressed.

## Files

| File | Change |
|---|---|
| `chrome-extension/content.js` | Replace native selects with reusable comboboxes and add both inline creation flows. |
| `chrome-extension/background.js` | Relay `CREATE_SECTION` to `/create-section`. |
| `chrome-extension/manifest.json` | Bump the extension patch version after behavior changes. |
| `tests/extension/*` | Add focused automated coverage for picker and message behavior. |
| `package.json` | Add an extension test command if required by the selected test harness. |

## Success Criteria

1. Clicking an empty board or enabled section field shows every existing item
   in case-insensitive alphabetical order, with the create action first.
2. Typing filters the visible existing items without hiding the create action.
3. Both fields can be operated entirely by mouse or keyboard.
4. A new board can be created, selected, and followed immediately by creation
   of a section within it.
5. A new section can be created only for the selected board and is selected
   after creation.
6. Changing boards cannot leave or submit a section from the previous board.
7. Existing pin-saving behavior remains unchanged.
8. Region-selection and screenshot behavior is unchanged in this delivery.
