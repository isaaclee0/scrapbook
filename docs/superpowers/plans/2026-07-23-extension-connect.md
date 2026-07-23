# Extension Download & One-Click Connect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user download the Chrome extension and configure it (Scrapbook URL + a fresh API token) with a single "Connect Extension" click from Settings — no manual file-finding, no copy-paste, no clipboard use.

**Architecture:** The extension gets a permanent, stable identity (a `"key"` in `manifest.json`, giving it a fixed ID regardless of install path) and a new `chrome.runtime.onMessageExternal` handler that accepts `{baseUrl, token}` from pages on an allowed origin. The Scrapbook backend gets a route that zips the extension repo's live source on request — reading it directly (no vendored copy, no drift) via a new Docker bind mount — templating the correct origin into the zipped manifest's `externally_connectable`. The Settings page gets a Download link and a Connect button that creates a token and pushes it straight into the extension via the browser's native website-to-extension messaging API.

**Tech Stack:** Flask/Python (backend), vanilla JS/Manifest V3 (extension) — consistent with both existing codebases, no new frameworks or build steps.

**Spec:** `docs/superpowers/specs/2026-07-23-extension-connect-design.md`

**Pre-generated values used throughout this plan** (an RSA key pair generated once, ahead of time, specifically so the manifest's `"key"` field and the Settings page's hardcoded extension-ID constant are guaranteed to match — regenerating either independently would produce a different, mismatched value and silently break the whole feature). **Use these exact values verbatim in every task below — do not regenerate them:**

```
PUBLIC_KEY_B64=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAvnuOIWtxdkm1quPsqycg+jXa+W03MBUII2JkGm2Q7ZYd/fyWDR5/KSZfDhlHKwTuzFJN32cmJxYwwreG8KrF00ywK/NmiYh849FqpGjG4PzJWyiyj1/VXWVK4WOjWFRTdKZ4pmxI+JcsW5179l6M1ZxfIn48Z8GA9Im73yjuMhIV2T5F0aLKWi5oclsEbVKR4lgW9aUhVkLzmqW+uI3NbSscahXIju9Bdj9ZdfK63kwfev7rBwH6f7SlcNkRtJNkIsZwgeSikizDBQFEmSW0HKkRu0LlOvlpF3uEMsu9uMcAPDxOABsL80//41pB54MGs1qAWKUE14HIvRoYjwoZSQIDAQAB
EXTENSION_ID=lbombjkndojncljbogbkhkbdaenhhjfl
```

(This is the public half of a key pair; the private half was never committed anywhere and isn't needed by any part of this implementation — unpacked, non-Web-Store extensions don't sign updates. `EXTENSION_ID` is deterministically derived from `PUBLIC_KEY_B64` — SHA-256 of the decoded key, first 16 bytes, each hex nibble mapped through `0123456789abcdef` → `abcdefghijklmnop` — you don't need to re-derive it, just use the value above.)

**Verified extension-API facts used in this plan** (checked against current Chrome documentation before writing this plan, following this project's established practice of verifying extension-API assumptions rather than guessing — a wrong assumption about content-script CORS earlier in this project cost a rework cycle):
- Setting `"key"` in `manifest.json` to a base64-encoded DER public key makes Chrome derive a fixed, deterministic extension ID, stable across reloads and regardless of which folder the extension is unpacked into.
- `externally_connectable.matches` requires match patterns with at least a real second-level domain for regular domains (`*.com` alone is invalid) — **except `localhost`, which is explicitly supported** (`http://localhost/*` is Chrome's documented pattern for "match any localhost port during development").
- **Match patterns do not support port numbers at all.** Any port is implicitly matched; including one in the pattern is either ignored or breaks the match (behavior is inconsistent in documentation, so this plan never emits one — always strip the port and use `scheme://hostname/*`). This matters concretely here: the dev environment runs on `localhost:8000`, and naively templating `request.host_url` (which includes the port) directly into the pattern would have silently broken the exact case this feature is built and tested against.
- No extra `"permissions"` entry is needed for `externally_connectable` — the manifest key itself is sufficient to enable `chrome.runtime.onMessageExternal`.
- `chrome.runtime.sendMessage(extensionId, message, callback)` targeting an external extension by ID is a plain browser API available to any web page — it requires no manifest/permission declaration on the calling page's side, only that the target extension's `externally_connectable.matches` allows the calling page's origin.

---

## Part A: Extension repo (`~/scrapbook/scrapbook-chrome-extension`)

### Task 1: Manifest — stable identity + default local dev origin

**Files:**
- Modify: `manifest.json`

- [ ] **Step 1: Add `"key"` and a default `"externally_connectable"`**

Replace the entire contents of `manifest.json` with:

```json
{
  "manifest_version": 3,
  "name": "Send to Scrapbook",
  "version": "1.2.0",
  "description": "Right-click any image and save it to your Scrapbook instance.",
  "permissions": ["contextMenus", "storage", "scripting"],
  "host_permissions": ["<all_urls>"],
  "background": {
    "service_worker": "background.js"
  },
  "options_page": "options.html",
  "action": {},
  "commands": {
    "capture-region": {
      "suggested_key": {
        "default": "Alt+Shift+S"
      },
      "description": "Select a region of the page to send to Scrapbook"
    }
  },
  "key": "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAvnuOIWtxdkm1quPsqycg+jXa+W03MBUII2JkGm2Q7ZYd/fyWDR5/KSZfDhlHKwTuzFJN32cmJxYwwreG8KrF00ywK/NmiYh849FqpGjG4PzJWyiyj1/VXWVK4WOjWFRTdKZ4pmxI+JcsW5179l6M1ZxfIn48Z8GA9Im73yjuMhIV2T5F0aLKWi5oclsEbVKR4lgW9aUhVkLzmqW+uI3NbSscahXIju9Bdj9ZdfK63kwfev7rBwH6f7SlcNkRtJNkIsZwgeSikizDBQFEmSW0HKkRu0LlOvlpF3uEMsu9uMcAPDxOABsL80//41pB54MGs1qAWKUE14HIvRoYjwoZSQIDAQAB",
  "externally_connectable": {
    "matches": ["http://localhost/*"]
  }
}
```

(Changes from the current file: `version` bumped `1.1.0` → `1.2.0`; two new top-level keys, `"key"` and `"externally_connectable"`. The `key` value must be copied EXACTLY as shown — it's the pre-generated `PUBLIC_KEY_B64` value from this plan's header. The `externally_connectable.matches` default of `http://localhost/*` is deliberate: it's what makes this exact repo — loaded unpacked directly, the way it's been tested throughout this whole project — already work for local Connect-flow testing against `http://localhost:8000` without needing to go through the zip-download route first. A later task's backend zip route REPLACES this value with the actual requesting server's real origin when building a downloadable copy — this default only matters for direct/local development use of this repo.)

- [ ] **Step 2: Verify valid JSON and confirm the resulting extension ID**

```bash
cd ~/scrapbook/scrapbook-chrome-extension
python3 -c "
import json, hashlib, base64
d = json.load(open('manifest.json'))
print('valid JSON, keys:', sorted(d.keys()))
der = base64.b64decode(d['key'])
digest = hashlib.sha256(der).hexdigest()[:32]
ext_id = digest.translate(str.maketrans('0123456789abcdef', 'abcdefghijklmnop'))
print('computed extension id:', ext_id)
assert ext_id == 'lbombjkndojncljbogbkhkbdaenhhjfl', 'MISMATCH — key value was altered, stop and report'
print('matches expected EXTENSION_ID — OK')
"
```
Expected: prints the key list including `key` and `externally_connectable`, computes `lbombjkndojncljbogbkhkbdaenhhjfl`, and the assert passes. **If the assert fails, STOP — it means the key value wasn't copied exactly; do not proceed to later tasks with a mismatched ID, since the backend/Settings-page tasks hardcode the expected ID and nothing will connect.**

- [ ] **Step 3: Load the updated extension and note the real ID from Chrome itself (manual, for your own confidence — not required to pass this task)**

If you have a moment, reload the extension at `chrome://extensions` and check the ID shown on its card matches `lbombjkndojncljbogbkhkbdaenhhjfl`. If you don't have browser access in this environment, the Step 2 computation is authoritative — Chrome's ID derivation is exactly the algorithm just run, this is well-documented, deterministic behavior, not something that needs a live Chrome instance to confirm.

- [ ] **Step 4: Commit**

```bash
git add manifest.json
git commit -m "Add stable extension identity (key) and default externally_connectable origin"
```

---

### Task 2: Background — external message handler for Connect

**Files:**
- Modify: `background.js`

- [ ] **Step 1: Add the external message handler**

In `background.js`, add this block after the existing `chrome.runtime.onMessage.addListener(...)` block at the end of the file (i.e. as the last thing in the file):

```javascript
chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  if (!sender.origin || !sender.url) {
    sendResponse({ ok: false, error: 'Missing sender origin' });
    return false;
  }
  if (message.type !== 'CONNECT') {
    sendResponse({ ok: false, error: `Unknown message type: ${message.type}` });
    return false;
  }
  if (!message.baseUrl || !message.token) {
    sendResponse({ ok: false, error: 'baseUrl and token are required' });
    return false;
  }
  // Defense in depth beyond manifest-level externally_connectable scoping:
  // only accept a baseUrl that matches the origin the message actually came
  // from. This stops a page from asking us to store a DIFFERENT baseUrl
  // than the one it's actually serving from.
  let requestedOrigin;
  try {
    requestedOrigin = new URL(message.baseUrl).origin;
  } catch (err) {
    sendResponse({ ok: false, error: 'Invalid baseUrl' });
    return false;
  }
  if (requestedOrigin !== sender.origin) {
    console.warn('[scrapbook] rejected CONNECT: baseUrl origin does not match sender origin', requestedOrigin, sender.origin);
    sendResponse({ ok: false, error: 'baseUrl does not match sender origin' });
    return false;
  }
  chrome.storage.local.set({ baseUrl: message.baseUrl.replace(/\/+$/, ''), token: message.token }, () => {
    sendResponse({ ok: true });
  });
  return true; // keep the message channel open for the async storage.set callback
});
```

Notes for context (don't act on these, just understand why the code looks like this):
- `sender.origin` is populated by Chrome itself for external messages — it can't be spoofed by the sending page's JS, unlike anything in the message body. Validating `message.baseUrl`'s origin against `sender.origin` means even if a page's own JS bug (or a future compromised dependency on that page) tried to point the extension at a different domain than the page is actually served from, the extension refuses.
- Manifest-level `externally_connectable.matches` (Task 1) already restricts WHICH pages can send this message at all — this handler's origin check is a second, independent layer, not a replacement for that.
- `getConfig()` (already defined earlier in this file) already strips trailing slashes when READING `baseUrl` — this handler also strips them when WRITING, so stored values are consistent regardless of which path (Connect vs. the options page) wrote them.

- [ ] **Step 2: Verify syntax**

```bash
cd ~/scrapbook/scrapbook-chrome-extension
node --check background.js && echo "background.js syntax OK"
```

- [ ] **Step 3: Verify the logic as thoroughly as you can without a real browser**

`chrome.runtime.onMessageExternal` and `sender.origin` are extension-only APIs unavailable in Node — but the handler's actual logic (origin string comparison, URL parsing, object shape checks) is plain JS you CAN exercise directly. Write a small scratch test (not committed) that imports/re-implements just the core validation logic and confirms:
- A message with `type !== 'CONNECT'` is rejected.
- A message missing `baseUrl` or `token` is rejected.
- A message where `new URL(message.baseUrl).origin` doesn't match a given `sender.origin` value is rejected (test both a matching and a non-matching case).
- A malformed `message.baseUrl` (e.g. not a valid URL) is caught by the try/catch rather than throwing.

You can do this either by extracting the validation logic into a standalone test script that mirrors the real function, or by using the same `vm`-sandbox technique an earlier task in this project used to exercise real `background.js` code with mocked `chrome.*` globals (mock `chrome.storage.local.set` to just call its callback immediately, mock `chrome.runtime.onMessageExternal.addListener` to just capture the handler function so you can invoke it directly with constructed `message`/`sender` objects). Either approach is fine — pick whichever gives you real confidence, and report which you used.

- [ ] **Step 4: Commit**

```bash
git add background.js
git commit -m "Add onMessageExternal handler for one-click Connect from Settings"
```

---

## Part B: Backend repo (`/Users/isaaclee/scrapbook/scrapbook`)

### Task 3: Docker mount + `/extension/download` route

**Files:**
- Modify: `docker-compose.override.yml` (untracked, local-only — do not expect this to be committed to git)
- Modify: `app.py`

- [ ] **Step 1: Add the extension repo as a bind mount**

Read the current `docker-compose.override.yml` first (`cat docker-compose.override.yml`) to confirm it still has the `PYTHONUSERBASE` environment blocks for `web` and `cache-worker` shown below — if it looks substantially different, STOP and report NEEDS_CONTEXT rather than guessing how to merge your change in.

Add a `volumes:` entry to the `web:` service (only `web` needs this — `cache-worker` never serves HTTP routes). The file should end up looking like:

```yaml
# LOCAL-ONLY (do not commit): docker-compose.yml runs containers as root
# (user "0:0") but the image installs Python packages under
# /home/appuser/.local, so root's Python can't find them. Point the user
# site-packages at the right place.
services:
  web:
    environment:
      - PYTHONUSERBASE=/home/appuser/.local
    volumes:
      - /Users/isaaclee/scrapbook/scrapbook-chrome-extension:/extension-src:ro
  cache-worker:
    environment:
      - PYTHONUSERBASE=/home/appuser/.local
```

(Only the new `volumes:` block under `web:` is an addition — everything else in the file is unchanged. Docker Compose merges `volumes:` lists across `-f docker-compose.yml -f docker-compose.override.yml` by appending, not replacing, so this adds to — doesn't remove — the base file's existing `.:/app` and `/app/node_modules` mounts. This mirrors the exact pattern already documented for this repo's local dev setup: mounting a sibling host directory read-only into the container for a cross-repo need.)

- [ ] **Step 2: Restart the web container to pick up the new mount**

```bash
docker compose up -d --no-deps web
```

- [ ] **Step 3: Verify the mount worked**

```bash
docker compose exec -T web ls /extension-src
```
Expected: lists the extension repo's files (`manifest.json`, `background.js`, `content.js`, `options.html`, `options.js`, `README.md`, `.git`, `docs`, `.gitignore`).

- [ ] **Step 4: Add the download route**

In `app.py`, update the Flask import line (around line 1) to add `send_file`:

Find:
```python
from flask import Flask, render_template, jsonify, request, send_from_directory, redirect, url_for, make_response, g, Response, stream_with_context
```

Replace with:
```python
from flask import Flask, render_template, jsonify, request, send_from_directory, send_file, redirect, url_for, make_response, g, Response, stream_with_context
```

Add these two imports near the top of the file, alongside the other standard-library imports (e.g. right after `import mimetypes`):

```python
import io
import zipfile
from urllib.parse import urlparse
```

Add this route. Place it near the other `/settings`/`/api/tokens` routes added in an earlier feature (search for `def settings_page():` and add this immediately before it):

```python
EXTENSION_SOURCE_DIR = os.getenv('EXTENSION_SOURCE_DIR', '/extension-src')


@app.route('/extension/download')
@login_required
def download_extension():
    """Zip the Chrome extension's current source and serve it as a download.

    Reads directly from a bind-mounted copy of the separate extension repo
    (see EXTENSION_SOURCE_DIR) rather than a vendored copy, so this always
    reflects the extension's actual latest code with no sync step. The
    zipped manifest.json's externally_connectable.matches is rewritten to
    this request's actual origin (scheme + hostname, no port — match
    patterns don't support ports) so the downloaded extension is correctly
    scoped to talk back to whichever Scrapbook instance served it.
    """
    if not os.path.isdir(EXTENSION_SOURCE_DIR):
        return jsonify({"error": "Extension source not available on this server"}), 404

    parsed = urlparse(request.host_url)
    origin_pattern = f"{parsed.scheme}://{parsed.hostname}/*"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(EXTENSION_SOURCE_DIR):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'docs']
            for filename in files:
                if filename.startswith('.'):
                    continue
                filepath = os.path.join(root, filename)
                arcname = os.path.join(
                    'scrapbook-chrome-extension',
                    os.path.relpath(filepath, EXTENSION_SOURCE_DIR),
                )
                if filename == 'manifest.json':
                    with open(filepath, 'r') as f:
                        manifest = json.load(f)
                    manifest['externally_connectable'] = {"matches": [origin_pattern]}
                    zf.writestr(arcname, json.dumps(manifest, indent=2))
                else:
                    zf.write(filepath, arcname)

    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='scrapbook-chrome-extension.zip',
    )
```

- [ ] **Step 5: Restart and verify the route works**

```bash
docker compose restart web
SESSION_TOKEN=$(docker compose exec -T web python -c "from auth_utils import generate_session_token; print(generate_session_token(2, 'shelley@leemail.com.au'))" | tr -d '\r')
curl -s -o /tmp/scrapbook-extension-test.zip -w "%{http_code}\n" --cookie "session_token=$SESSION_TOKEN" http://localhost:8000/extension/download
```
Expected: `200`.

- [ ] **Step 6: Verify the zip contents and the manifest rewrite**

```bash
cd /tmp && unzip -o scrapbook-extension-test.zip -d extension-test-unzip && ls extension-test-unzip/scrapbook-chrome-extension/
python3 -c "
import json
d = json.load(open('extension-test-unzip/scrapbook-chrome-extension/manifest.json'))
print('externally_connectable:', d.get('externally_connectable'))
print('key present:', 'key' in d)
assert d['externally_connectable']['matches'] == ['http://localhost/*'], d['externally_connectable']
print('OK — matches expected origin pattern for a request to http://localhost:8000')
"
```
Expected: lists `manifest.json`, `background.js`, `content.js`, `options.html`, `options.js`, `README.md` (no `.git`, no `docs`, no dotfiles); the manifest check confirms `externally_connectable.matches` is `["http://localhost/*"]` (note: NOT `http://localhost:8000/*` — the port must be stripped, per this plan's header notes on match-pattern syntax) and that `key` (from the extension repo's own committed manifest.json, Task 1) survived the rewrite unchanged.

- [ ] **Step 7: Clean up test artifacts**

```bash
rm -rf /tmp/scrapbook-extension-test.zip /tmp/extension-test-unzip
```

- [ ] **Step 8: Commit**

```bash
git add app.py
git commit -m "Add /extension/download route that zips and origin-scopes the Chrome extension"
```

(`docker-compose.override.yml` is untracked/local-only per this repo's convention — do not `git add` it.)

---

### Task 4: Settings page — Get the extension + Connect Extension

**Files:**
- Modify: `templates/settings.html`

- [ ] **Step 1: Add the new sections above the existing "API Tokens" heading**

Find:
```html
<div class="max-w-3xl mx-auto px-4 py-8">
    <div class="mb-6">
        <h1 class="text-3xl font-semibold text-gray-900">API Tokens</h1>
```

Replace with:
```html
<div class="max-w-3xl mx-auto px-4 py-8">
    <div class="mb-6">
        <h1 class="text-3xl font-semibold text-gray-900">Chrome Extension</h1>
        <p class="text-gray-600 mt-1">
            Send images to Scrapbook from any webpage without leaving the page.
        </p>
    </div>

    <div class="bg-white border border-gray-200 rounded-lg p-4 mb-4">
        <h2 class="text-lg font-semibold text-gray-900 mb-2">1. Get the extension</h2>
        <ol class="list-decimal list-inside text-sm text-gray-700 space-y-1 mb-3">
            <li>Download and unzip the extension below.</li>
            <li>Open <code class="bg-gray-100 px-1 rounded">chrome://extensions</code> and enable <strong>Developer mode</strong> (top right).</li>
            <li>Click <strong>Load unpacked</strong> and select the unzipped <code class="bg-gray-100 px-1 rounded">scrapbook-chrome-extension</code> folder.</li>
        </ol>
        <a href="{{ url_for('download_extension') }}" class="button primary-button" style="display:inline-block; text-decoration:none;">Download extension</a>
    </div>

    <div class="bg-white border border-gray-200 rounded-lg p-4 mb-4">
        <h2 class="text-lg font-semibold text-gray-900 mb-2">2. Connect it</h2>
        <p class="text-sm text-gray-600 mb-3">
            With the extension loaded, click below to configure it automatically —
            this creates a token and sends it straight to the extension, no copying
            or pasting required.
        </p>
        <button id="connectExtensionBtn" class="button primary-button">Connect Extension</button>
        <p id="connectStatus" class="text-sm mt-2"></p>
    </div>

    <div class="mb-6">
        <h1 class="text-3xl font-semibold text-gray-900">API Tokens</h1>
```

(This wraps the existing `<h1>API Tokens</h1>` in a second `<div class="mb-6">` block rather than replacing it, and the existing description paragraph right after it is untouched — only text ABOVE the original `<h1>` is new. Double-check after editing that the original `<p class="text-gray-600 mt-1">Personal access tokens let other tools...` paragraph and everything below it in the file is still present and unchanged.)

- [ ] **Step 2: Add the Connect button's JS**

Find the top of the existing `<script>` block:
```javascript
(function () {
    const rowsEl = document.getElementById('tokenRows');
    const newTokenName = document.getElementById('newTokenName');
    const createBtn = document.getElementById('createTokenBtn');
    const reveal = document.getElementById('newTokenReveal');
    const revealValue = document.getElementById('newTokenValue');
```

Replace with:
```javascript
(function () {
    const EXTENSION_ID = 'lbombjkndojncljbogbkhkbdaenhhjfl';
    const rowsEl = document.getElementById('tokenRows');
    const newTokenName = document.getElementById('newTokenName');
    const createBtn = document.getElementById('createTokenBtn');
    const reveal = document.getElementById('newTokenReveal');
    const revealValue = document.getElementById('newTokenValue');
    const connectBtn = document.getElementById('connectExtensionBtn');
    const connectStatus = document.getElementById('connectStatus');
```

Then, immediately after the existing `loadTokens()` function definition ends (find the line `loadTokens();` at the very bottom of the IIFE, right before the closing `})();` — add the new code BEFORE that final `loadTokens();` call), add:

```javascript
    async function createToken(name) {
        const res = await fetch('/api/tokens', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.error || 'Failed to create token');
        }
        return data.token;
    }

    connectBtn.addEventListener('click', async () => {
        connectBtn.disabled = true;
        connectStatus.textContent = 'Connecting…';
        connectStatus.className = 'text-sm mt-2 text-gray-600';
        try {
            const token = await createToken('Chrome extension');
            revealValue.textContent = token;
            reveal.style.display = 'block';
            loadTokens();

            if (!window.chrome || !chrome.runtime || !chrome.runtime.sendMessage) {
                connectStatus.textContent = 'Token created — but this browser has no chrome.runtime API to reach the extension. Paste the token above into the extension\'s options page manually.';
                connectStatus.className = 'text-sm mt-2 text-red-600';
                return;
            }

            chrome.runtime.sendMessage(
                EXTENSION_ID,
                { type: 'CONNECT', baseUrl: window.location.origin, token },
                (response) => {
                    if (chrome.runtime.lastError || !response || !response.ok) {
                        connectStatus.textContent = "Token created, but couldn't reach the extension — make sure it's installed and loaded, then try again. (You can also paste the token above into the extension's options page manually.)";
                        connectStatus.className = 'text-sm mt-2 text-red-600';
                        return;
                    }
                    connectStatus.textContent = 'Extension connected!';
                    connectStatus.className = 'text-sm mt-2 text-green-600';
                }
            );
        } catch (err) {
            connectStatus.textContent = err.message || 'Something went wrong.';
            connectStatus.className = 'text-sm mt-2 text-red-600';
        } finally {
            connectBtn.disabled = false;
        }
    });

```

- [ ] **Step 3: Verify the template renders**

```bash
cd /Users/isaaclee/scrapbook/scrapbook
docker compose restart web
SESSION_TOKEN=$(docker compose exec -T web python -c "from auth_utils import generate_session_token; print(generate_session_token(2, 'shelley@leemail.com.au'))" | tr -d '\r')
curl -s -o /dev/null -w "%{http_code}\n" --cookie "session_token=$SESSION_TOKEN" http://localhost:8000/settings
curl -s --cookie "session_token=$SESSION_TOKEN" http://localhost:8000/settings | grep -o 'id="connectExtensionBtn"\|id="connectStatus"\|Download extension\|lbombjkndojncljbogbkhkbdaenhhjfl'
```
Expected: `200`, and all four markers found (confirming the new sections rendered and the extension ID constant made it into the page).

- [ ] **Step 4: Confirm the existing token management UI is untouched**

```bash
curl -s --cookie "session_token=$SESSION_TOKEN" http://localhost:8000/settings | grep -o 'id="tokenRows"\|id="createTokenBtn"\|id="revokeModal"'
```
Expected: all three still present — confirms this task's additions didn't disturb the pre-existing token list/create/revoke UI from earlier work.

- [ ] **Step 5: Commit**

```bash
git add templates/settings.html
git commit -m "Add Get Extension and Connect Extension sections to Settings"
```

---

## Task 5: Final end-to-end verification checklist

**Files:** none (verification only)

This requires a real Chrome browser — same as prior real-browser verification passes in this project.

- [ ] **Step 1: Download and load**

From `http://localhost:8000/settings`, click "Download extension." Unzip the downloaded file, load it unpacked via `chrome://extensions` → Developer mode → Load unpacked. Confirm the loaded extension's ID (shown on its card) is `lbombjkndojncljbogbkhkbdaenhhjfl` — proving the `key` field produces a stable ID even for a freshly-unzipped copy in a brand-new folder location.

- [ ] **Step 2: Connect**

Back on the Settings page (same browser tab or a fresh one at `http://localhost:8000/settings`), click "Connect Extension." Confirm:
- The token reveal box shows a new `sb_pat_...` token.
- The status message reads "Extension connected!" within a couple seconds.
- The new token appears in the API Tokens table below.

- [ ] **Step 3: Confirm the extension is actually configured**

Open the extension's options page (`chrome://extensions` → Details → Extension options). Confirm the Scrapbook URL and token fields are already filled in — matching what Settings just pushed, with no manual entry.

- [ ] **Step 4: Confirm it actually works end-to-end**

Right-click an image on any page → "Send to Scrapbook" → confirm the board list loads (proving the pushed token is valid) and a save succeeds.

- [ ] **Step 5: Confirm the origin scoping actually blocks other origins**

Open the browser's JavaScript console on a page NOT served from your Scrapbook origin (e.g. any other website, or `about:blank`) and attempt:
```javascript
chrome.runtime.sendMessage('lbombjkndojncljbogbkhkbdaenhhjfl', {type:'CONNECT', baseUrl:'http://evil.example.com', token:'fake'}, console.log)
```
Expected: `chrome.runtime.sendMessage` is either undefined in that page's context, or the call fails/times out silently — because that page's origin isn't in the extension's `externally_connectable.matches`, Chrome doesn't expose the messaging API to it at all for this extension. Confirm the extension's stored `baseUrl`/`token` (check via the options page) are unchanged after this attempt.

- [ ] **Step 6: Re-read the spec's success criteria**

Re-read `docs/superpowers/specs/2026-07-23-extension-connect-design.md`'s "Success criteria" section and confirm all five are met based on what you just verified.
