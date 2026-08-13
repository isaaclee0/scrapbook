# Send to Scrappl

Chrome extension: right-click any image on any page → "Send to Scrappl" →
save it to a board in your self-hosted [Scrappl](https://github.com/) instance
without leaving the page.

## Setup

1. Generate a personal access token in your Scrappl instance under
   **Settings → API Tokens**.
2. Load this extension unpacked: `chrome://extensions` → enable
   **Developer mode** → **Load unpacked** → select this directory.
3. Click the extension's **Details → Extension options**, enter your
   Scrappl instance's base URL and the token, and save.
4. Right-click any image on any page → **Send to Scrappl**.

In the save dialog, click a board or section field to see its alphabetized
list, then type to filter it. The first entry in each list lets you create a
board or section without leaving the dialog. A section can be created after a
board is selected (including a board created in that same dialog).

Not published to the Chrome Web Store — personal use only.
