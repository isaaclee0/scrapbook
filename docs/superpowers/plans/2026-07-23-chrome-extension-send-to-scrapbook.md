# Send to Scrapbook — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user right-click any image in Chrome, choose "Send to Scrapbook," and save it to their self-hosted Scrapbook instance from an in-page dialog, without leaving the page.

**Architecture:** Part A adds Personal Access Token (bearer) auth to the existing `scrapbook` Flask app, additive to its current cookie-based auth — no existing behavior changes. Part B is a new Manifest V3 Chrome extension (separate repo) with a background service worker that owns the token and makes all network calls, and a content script that renders the pin-save dialog in a Shadow DOM and captures the image as a data URL.

**Tech Stack:** Flask / MariaDB (existing `scrapbook` repo, Python), vanilla JS + Manifest V3 (new `scrapbook-chrome-extension` repo, no build step, no frameworks).

**Spec:** `docs/superpowers/specs/2026-07-22-chrome-extension-send-to-scrapbook-design.md`

---

## Part A: Backend — Personal Access Tokens (`scrapbook` repo)

### Task 1: `api_tokens` table migration

**Files:**
- Modify: `migrate.py`

- [ ] **Step 1: Verify the table doesn't exist yet**

Run:
```bash
docker compose exec -T db sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "SHOW TABLES LIKE '"'"'api_tokens'"'"';"'
```
Expected: empty output (no rows).

- [ ] **Step 2: Add the migration step**

In `migrate.py`, insert this block right after the `audit_log` table block (after the `warning("audit_log table already exists")` line, before the `# Migration Step 12: Summary` comment):

```python
        # Migration Step 14: API tokens table
        info("\nStep 14: API tokens (personal access tokens)")
        if not table_exists(cursor, 'api_tokens'):
            cursor.execute("""
                CREATE TABLE api_tokens (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    token_hash CHAR(64) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TIMESTAMP NULL,
                    revoked_at TIMESTAMP NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    INDEX idx_api_tokens_hash (token_hash),
                    INDEX idx_api_tokens_user (user_id, revoked_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            success("Created api_tokens table")
        else:
            warning("api_tokens table already exists")
```

- [ ] **Step 3: Run the migration**

Run:
```bash
docker compose exec -T web python migrate.py
```
Expected: output includes `Step 14: API tokens (personal access tokens)` followed by `✅ Created api_tokens table`.

- [ ] **Step 4: Verify the table now exists with the right columns**

Run:
```bash
docker compose exec -T db sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "DESCRIBE api_tokens;"'
```
Expected: 7 rows — `id, user_id, name, token_hash, created_at, last_used_at, revoked_at`.

- [ ] **Step 5: Run the migration again to confirm idempotency**

Run:
```bash
docker compose exec -T web python migrate.py
```
Expected: output includes `⚠️  api_tokens table already exists` and exits 0.

- [ ] **Step 6: Commit**

```bash
git add migrate.py
git commit -m "Add api_tokens table migration for extension personal access tokens"
```

---

### Task 2: Token generation & hashing helpers

**Files:**
- Modify: `auth_utils.py`

- [ ] **Step 1: Add the helpers**

At the top of `auth_utils.py`, add two imports next to the existing ones:

```python
import jwt
import os
import random
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict
```

Then append this to the end of `auth_utils.py`:

```python
API_TOKEN_PREFIX = 'sb_pat_'


def generate_api_token() -> str:
    """Generate a new personal access token (plaintext, shown to the user once)."""
    return API_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_api_token(token: str) -> str:
    """SHA-256 hex digest of a token, for storage/lookup. Never store the plaintext."""
    return hashlib.sha256(token.encode()).hexdigest()
```

- [ ] **Step 2: Verify by hand**

Run:
```bash
docker compose exec -T web python -c "
from auth_utils import generate_api_token, hash_api_token
t = generate_api_token()
print('token:', t)
print('starts with prefix:', t.startswith('sb_pat_'))
print('hash:', hash_api_token(t))
print('hash is deterministic:', hash_api_token(t) == hash_api_token(t))
"
```
Expected: prints a token starting with `sb_pat_`, `starts with prefix: True`, a 64-char hex hash, and `hash is deterministic: True`.

- [ ] **Step 3: Commit**

```bash
git add auth_utils.py
git commit -m "Add personal access token generation/hashing helpers"
```

---

### Task 3: Bearer-token support in `get_current_user()`

**Files:**
- Modify: `app.py:26` (import line)
- Modify: `app.py:514-530` (`get_current_user`)

- [ ] **Step 1: Seed one manual token row for testing**

Run:
```bash
docker compose exec -T db sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "
INSERT INTO api_tokens (user_id, name, token_hash)
VALUES (2, \"manual-test\", SHA2(\"test-token-value\", 256));
"'
```

- [ ] **Step 2: Verify it fails (bearer auth not wired up yet)**

Run:
```bash
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer test-token-value" http://localhost:8000/api/boards
```
Expected: `302` (redirected to login — `get_current_user()` doesn't look at the `Authorization` header yet).

- [ ] **Step 3: Update the import line**

In `app.py`, change line 26 from:

```python
from auth_utils import generate_magic_link_token, generate_session_token, verify_token, refresh_session_token, generate_otp, store_otp, verify_otp
```

to:

```python
from auth_utils import generate_magic_link_token, generate_session_token, verify_token, refresh_session_token, generate_otp, store_otp, verify_otp, hash_api_token
```

- [ ] **Step 4: Replace `get_current_user()`**

In `app.py`, replace:

```python
def get_current_user():
    """
    Get the currently authenticated user from session cookie
    Returns user dict or None
    """
    token = request.cookies.get('session_token')
    if not token:
        return None
    
    payload = verify_token(token, token_type='session')
    if not payload:
        return None
    
    return {
        'id': payload.get('user_id'),
        'email': payload.get('email')
    }
```

with:

```python
def get_current_user():
    """
    Get the currently authenticated user from a Bearer API token or session
    cookie. Returns user dict or None.
    """
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return _get_user_from_api_token(auth_header[len('Bearer '):].strip())

    token = request.cookies.get('session_token')
    if not token:
        return None

    payload = verify_token(token, token_type='session')
    if not payload:
        return None

    return {
        'id': payload.get('user_id'),
        'email': payload.get('email')
    }


def _get_user_from_api_token(token):
    """Look up the user for a Bearer personal access token. Returns user dict or None."""
    if not token:
        return None
    token_hash = hash_api_token(token)
    with tx(dictionary=True) as (db, cursor):
        cursor.execute("""
            SELECT u.id, u.email, t.id AS token_id
            FROM api_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.token_hash = %s AND t.revoked_at IS NULL
        """, (token_hash,))
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute("UPDATE api_tokens SET last_used_at = NOW() WHERE id = %s", (row['token_id'],))
        return {'id': row['id'], 'email': row['email']}
```

- [ ] **Step 5: Restart the web container to pick up the change**

Run:
```bash
docker compose restart web
```

- [ ] **Step 6: Verify a valid token now works**

Run:
```bash
curl -s -H "Authorization: Bearer test-token-value" http://localhost:8000/api/boards | head -c 200
```
Expected: a JSON array starting with `[{`, e.g. `[{"id":..., "name":..., ...`. Not a login page, not an error.

- [ ] **Step 7: Verify `last_used_at` was updated**

Run:
```bash
docker compose exec -T db sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "SELECT name, last_used_at FROM api_tokens WHERE name=\"manual-test\";"'
```
Expected: `last_used_at` is a recent timestamp, not `NULL`.

- [ ] **Step 8: Verify an invalid token is rejected**

Run:
```bash
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer wrong-token" http://localhost:8000/api/boards
```
Expected: `302` (falls through to "no user" — still a redirect at this point because `login_required`'s JSON-vs-redirect logic hasn't been fixed yet; that's Task 4).

- [ ] **Step 9: Verify cookie auth still works (regression check)**

Run:
```bash
SESSION_TOKEN=$(docker compose exec -T web python -c "from auth_utils import generate_session_token; print(generate_session_token(2, 'shelley@leemail.com.au'))" | tr -d '\r')
curl -s -o /dev/null -w "%{http_code}\n" --cookie "session_token=$SESSION_TOKEN" http://localhost:8000/api/boards
```
Expected: `200`.

- [ ] **Step 10: Commit**

```bash
git add app.py
git commit -m "Support Bearer personal access tokens in get_current_user()"
```

---

### Task 4: Fix `login_required` to return JSON for bearer requests

**Files:**
- Modify: `app.py:608-626` (`login_required`)

- [ ] **Step 1: Confirm the failure mode**

Run (from Task 3, Step 8 — same result, restated as the thing this task fixes):
```bash
curl -s -i -H "Authorization: Bearer wrong-token" http://localhost:8000/get-sections/1 | head -5
```
Expected: `HTTP/1.1 302 FOUND` with a `Location: /auth/login` header — an extension can't act on an HTML redirect.

- [ ] **Step 2: Update `login_required`**

In `app.py`, replace:

```python
def login_required(f):
    """
    Decorator to require authentication for a route
    For API endpoints, returns JSON error instead of redirecting
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            # Check if this is an API endpoint (starts with /api/)
            # or a POST/PUT/DELETE request with JSON content
            is_api_endpoint = request.path.startswith('/api/')
            is_json_request = request.method in ['POST', 'PUT', 'DELETE'] and request.is_json
            if is_api_endpoint or is_json_request:
                return jsonify({"error": "Authentication required", "success": False}), 401
            # For non-API routes, redirect to login
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function
```

with:

```python
def login_required(f):
    """
    Decorator to require authentication for a route
    For API endpoints, returns JSON error instead of redirecting
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            # Check if this is an API endpoint (starts with /api/),
            # a POST/PUT/DELETE request with JSON content, or a request
            # that attempted Bearer token auth (never redirect a non-browser
            # client to an HTML login page).
            is_api_endpoint = request.path.startswith('/api/')
            is_json_request = request.method in ['POST', 'PUT', 'DELETE'] and request.is_json
            is_bearer_request = request.headers.get('Authorization', '').startswith('Bearer ')
            if is_api_endpoint or is_json_request or is_bearer_request:
                return jsonify({"error": "Authentication required", "success": False}), 401
            # For non-API routes, redirect to login
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function
```

- [ ] **Step 3: Restart and verify**

Run:
```bash
docker compose restart web
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer wrong-token" http://localhost:8000/get-sections/1
```
Expected: `401`.

- [ ] **Step 4: Verify the response body is JSON**

Run:
```bash
curl -s -H "Authorization: Bearer wrong-token" http://localhost:8000/get-sections/1
```
Expected: `{"error": "Authentication required", "success": false}`.

- [ ] **Step 5: Verify unauthenticated browser navigation still redirects (regression check)**

Run:
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/board/1
```
Expected: `302` (no Authorization header at all → falls through to the redirect branch, unchanged).

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "Return JSON 401 instead of redirecting for Bearer-authenticated requests"
```

---

### Task 5: Skip CSRF check for bearer-authenticated requests

**Files:**
- Modify: `csrf.py`

- [ ] **Step 1: Confirm the failure mode**

Run:
```bash
curl -s -H "Authorization: Bearer test-token-value" -H "Content-Type: application/json" \
  -d '{"name": "curl-csrf-check"}' \
  http://localhost:8000/create-board
```
Expected: `{"error": "CSRF token missing or invalid"}` — a valid bearer token still gets blocked by the cookie-CSRF check.

- [ ] **Step 2: Update `require_csrf`**

In `csrf.py`, replace:

```python
def require_csrf(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        session_token = request.cookies.get('session_token', '')
        presented = request.headers.get('X-CSRF-Token')
        if not presented:
            body = request.get_json(silent=True) or {}
            presented = body.get('csrf_token', '') if isinstance(body, dict) else ''
        if not verify_csrf(session_token, presented or ''):
            return jsonify({"error": "CSRF token missing or invalid"}), 403
        return view(*args, **kwargs)
    return wrapper
```

with:

```python
def require_csrf(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        # CSRF defends cookie-based sessions specifically (a malicious page
        # can't read another origin's response, but browsers still attach
        # cookies to requests it triggers). That attack doesn't apply to
        # Bearer-token requests, which carry no cookie for a browser to
        # attach automatically. Every @require_csrf route is preceded by
        # @login_required, which already rejected an invalid/missing token
        # before this decorator runs — so a present Authorization: Bearer
        # header here means the request already authenticated successfully.
        if request.headers.get('Authorization', '').startswith('Bearer '):
            return view(*args, **kwargs)
        session_token = request.cookies.get('session_token', '')
        presented = request.headers.get('X-CSRF-Token')
        if not presented:
            body = request.get_json(silent=True) or {}
            presented = body.get('csrf_token', '') if isinstance(body, dict) else ''
        if not verify_csrf(session_token, presented or ''):
            return jsonify({"error": "CSRF token missing or invalid"}), 403
        return view(*args, **kwargs)
    return wrapper
```

- [ ] **Step 3: Restart and verify the valid-token case now succeeds**

Run:
```bash
docker compose restart web
curl -s -H "Authorization: Bearer test-token-value" -H "Content-Type: application/json" \
  -d '{"name": "curl-csrf-check"}' \
  http://localhost:8000/create-board
```
Expected: `{"success": true, "board_id": ..., "name": "curl-csrf-check", "slug": "curl-csrf-check"}`.

- [ ] **Step 4: Clean up the test board**

Run:
```bash
docker compose exec -T db sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "DELETE FROM boards WHERE name=\"curl-csrf-check\";"'
```

- [ ] **Step 5: Verify cookie-based CSRF protection still works (regression check)**

Run:
```bash
SESSION_TOKEN=$(docker compose exec -T web python -c "from auth_utils import generate_session_token; print(generate_session_token(2, 'shelley@leemail.com.au'))" | tr -d '\r')
curl -s --cookie "session_token=$SESSION_TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "should-be-blocked"}' \
  http://localhost:8000/create-board
```
Expected: `{"error": "CSRF token missing or invalid"}` — no `X-CSRF-Token` header was sent, so a cookie-authenticated request without it is still blocked exactly as before.

- [ ] **Step 6: Commit**

```bash
git add csrf.py
git commit -m "Skip CSRF check for Bearer-authenticated requests"
```

---

### Task 6: `/api/tokens` routes (list, create, revoke)

**Files:**
- Modify: `app.py` (add routes near `audit_log_page`/`api_audit_log`, around line 3614)

- [ ] **Step 1: Add the routes**

In `app.py`, add this block right after the `api_audit_log` function (search for `@app.route('/api/audit-log')` to find the area; add after that whole function ends):

```python
@app.route('/settings')
@login_required
def settings_page():
    """Render the settings page (API personal access token management)."""
    return render_template('settings.html')


@app.route('/api/tokens', methods=['GET'])
@login_required
def list_api_tokens():
    user = get_current_user()
    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, name, created_at, last_used_at
            FROM api_tokens
            WHERE user_id = %s AND revoked_at IS NULL
            ORDER BY created_at DESC
        """, (user['id'],))
        tokens = cursor.fetchall()
        return jsonify(tokens)
    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


@app.route('/api/tokens', methods=['POST'])
@login_required
@require_csrf
def create_api_token():
    user = get_current_user()
    data = request.get_json() or {}
    name = sanitize_string(data.get('name', ''), max_length=100)
    if not name:
        return jsonify({"error": "Token name is required"}), 400

    plaintext = generate_api_token()
    token_hash = hash_api_token(plaintext)

    with tx() as (db, cursor):
        cursor.execute("""
            INSERT INTO api_tokens (user_id, name, token_hash)
            VALUES (%s, %s, %s)
        """, (user['id'], name, token_hash))
        token_id = cursor.lastrowid

        record_audit(cursor, action='api_token.create', entity_type='api_token',
                     entity_id=token_id, user_id=user['id'],
                     actor_email=user.get('email'), before=None,
                     after={'id': token_id, 'name': name},
                     metadata={'route': request.path},
                     ip_address=request.remote_addr)

    return jsonify({'success': True, 'id': token_id, 'name': name, 'token': plaintext})


@app.route('/api/tokens/<int:token_id>/revoke', methods=['POST'])
@login_required
@require_csrf
def revoke_api_token(token_id):
    user = get_current_user()
    with tx() as (db, cursor):
        cursor.execute("""
            SELECT id FROM api_tokens WHERE id = %s AND user_id = %s AND revoked_at IS NULL
        """, (token_id, user['id']))
        if not cursor.fetchone():
            return jsonify({"error": "Token not found"}), 404

        cursor.execute("UPDATE api_tokens SET revoked_at = NOW() WHERE id = %s", (token_id,))

        record_audit(cursor, action='api_token.revoke', entity_type='api_token',
                     entity_id=token_id, user_id=user['id'],
                     actor_email=user.get('email'), before=None, after=None,
                     metadata={'route': request.path},
                     ip_address=request.remote_addr)

    return jsonify({'success': True})
```

Also add `generate_api_token` to the `auth_utils` import on line 26 (it currently only imports `hash_api_token` from Task 3):

```python
from auth_utils import generate_magic_link_token, generate_session_token, verify_token, refresh_session_token, generate_otp, store_otp, verify_otp, hash_api_token, generate_api_token
```

- [ ] **Step 2: Add a placeholder template so the route doesn't 500**

This is a throwaway placeholder — Task 7 replaces it with the real UI. Create `templates/settings.html`:

```html
{% extends "base.html" %}
{% block content %}
<p>Settings page placeholder — replaced in Task 7.</p>
{% endblock %}
```

- [ ] **Step 3: Restart and verify list (empty except the manual-test row from Task 3)**

Run:
```bash
docker compose restart web
SESSION_TOKEN=$(docker compose exec -T web python -c "from auth_utils import generate_session_token; print(generate_session_token(2, 'shelley@leemail.com.au'))" | tr -d '\r')
curl -s --cookie "session_token=$SESSION_TOKEN" http://localhost:8000/api/tokens
```
Expected: a JSON array containing one object with `"name":"manual-test"`.

- [ ] **Step 4: Verify token creation**

Run:
```bash
CSRF_TOKEN=$(curl -s --cookie "session_token=$SESSION_TOKEN" http://localhost:8000/settings \
  | grep -o 'name="csrf-token" content="[^"]*"' | sed 's/.*content="//; s/"$//')

curl -s --cookie "session_token=$SESSION_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" \
  -H "Content-Type: application/json" -d '{"name":"curl-created-token"}' \
  http://localhost:8000/api/tokens
```
Expected: `{"success": true, "id": ..., "name": "curl-created-token", "token": "sb_pat_..."}`. **Copy the `token` value** — it's used in Task 8.

- [ ] **Step 5: Verify the new token works for a real request**

Run (substituting the token from Step 4):
```bash
curl -s -H "Authorization: Bearer <paste token here>" http://localhost:8000/api/boards | head -c 100
```
Expected: a JSON array (200), same as the manual-test token in Task 3.

- [ ] **Step 6: Verify revoke**

Run (substituting the `id` from Step 4's response):
```bash
curl -s --cookie "session_token=$SESSION_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" \
  -X POST http://localhost:8000/api/tokens/<id from step 4>/revoke
```
Expected: `{"success": true}`.

- [ ] **Step 7: Verify a revoked token is rejected**

Run:
```bash
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer <paste token here>" http://localhost:8000/api/boards
```
Expected: `401`.

- [ ] **Step 8: Verify the revoked token no longer appears in the list**

Run:
```bash
curl -s --cookie "session_token=$SESSION_TOKEN" http://localhost:8000/api/tokens
```
Expected: only `manual-test` remains (the `curl-created-token` row is gone from the list, though it still exists in the DB with `revoked_at` set).

- [ ] **Step 9: Commit**

```bash
git add app.py templates/settings.html
git commit -m "Add /api/tokens list/create/revoke routes"
```

---

### Task 7: Settings page UI + nav link

**Files:**
- Modify: `templates/settings.html` (replace placeholder from Task 6)
- Modify: `templates/base.html` (nav link, around line 986-999)

- [ ] **Step 1: Write the real settings template**

Replace the entire contents of `templates/settings.html` with:

```html
{% extends "base.html" %}

{% block content %}
<div class="max-w-3xl mx-auto px-4 py-8">
    <div class="mb-6">
        <h1 class="text-3xl font-semibold text-gray-900">API Tokens</h1>
        <p class="text-gray-600 mt-1">
            Personal access tokens let other tools (like the Send to Scrapbook browser
            extension) act on your behalf without a login cookie. Treat a token like a
            password — anyone with it can create pins and boards as you.
        </p>
    </div>

    <div class="bg-white border border-gray-200 rounded-lg p-4 mb-4">
        <div style="display:flex; gap:12px; align-items:flex-end;">
            <div style="flex:1;">
                <label style="display:block; font-size:11px; font-weight:600; color:#6b7280; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:6px;">Token name</label>
                <input id="newTokenName" type="text" placeholder="e.g. Chrome extension"
                    style="width:100%; padding:8px 12px; border:1px solid #ddd; border-radius:4px; font-size:14px;">
            </div>
            <button id="createTokenBtn" class="button primary-button">Generate token</button>
        </div>
        <div id="newTokenReveal" style="display:none; margin-top:12px; padding:12px; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:6px;">
            <p style="font-size:13px; color:#166534; margin-bottom:6px;">
                Copy this token now — you won't be able to see it again.
            </p>
            <code id="newTokenValue" style="display:block; padding:8px; background:white; border-radius:4px; font-size:13px; word-break:break-all;"></code>
        </div>
    </div>

    <div class="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <table class="w-full text-sm">
            <thead class="bg-gray-50 text-gray-700">
                <tr>
                    <th class="text-left px-3 py-2 font-medium">Name</th>
                    <th class="text-left px-3 py-2 font-medium">Created</th>
                    <th class="text-left px-3 py-2 font-medium">Last used</th>
                    <th class="text-right px-3 py-2 font-medium">Revoke</th>
                </tr>
            </thead>
            <tbody id="tokenRows" class="divide-y divide-gray-100">
                <tr><td colspan="4" class="px-3 py-6 text-center text-gray-400">Loading…</td></tr>
            </tbody>
        </table>
    </div>
</div>

<!-- Revoke confirmation modal -->
<div id="revokeModal" class="modal" style="display: none;">
    <div class="modal-content">
        <div class="modal-header">
            <h3 class="text-xl font-bold">Revoke this token?</h3>
        </div>
        <div class="modal-body">
            <p class="text-gray-600 text-sm" id="revokeModalDesc"></p>
            <p class="text-gray-400 text-xs mt-2">Anything using it (e.g. the browser extension) will stop working immediately.</p>
        </div>
        <div class="modal-actions">
            <button id="revokeModalCancel" class="button secondary-button">Cancel</button>
            <button id="revokeModalConfirm" class="button delete-button">Revoke</button>
        </div>
    </div>
</div>

<script>
(function () {
    const rowsEl = document.getElementById('tokenRows');
    const newTokenName = document.getElementById('newTokenName');
    const createBtn = document.getElementById('createTokenBtn');
    const reveal = document.getElementById('newTokenReveal');
    const revealValue = document.getElementById('newTokenValue');
    const revokeModal = document.getElementById('revokeModal');
    const revokeModalDesc = document.getElementById('revokeModalDesc');
    const revokeModalCancel = document.getElementById('revokeModalCancel');
    const revokeModalConfirm = document.getElementById('revokeModalConfirm');
    let pendingRevokeId = null;

    function fmtTime(iso) {
        if (!iso) return '—';
        try { return new Date(iso).toLocaleString(); } catch (_) { return iso; }
    }

    function escapeHtml(s) {
        const div = document.createElement('div');
        div.textContent = s;
        return div.innerHTML;
    }

    async function loadTokens() {
        const res = await fetch('/api/tokens');
        const tokens = await res.json();
        if (!tokens.length) {
            rowsEl.innerHTML = '<tr><td colspan="4" class="px-3 py-6 text-center text-gray-400">No tokens yet.</td></tr>';
            return;
        }
        rowsEl.innerHTML = tokens.map((t) => `
            <tr>
                <td class="px-3 py-2">${escapeHtml(t.name)}</td>
                <td class="px-3 py-2 text-gray-500 whitespace-nowrap">${fmtTime(t.created_at)}</td>
                <td class="px-3 py-2 text-gray-500 whitespace-nowrap">${fmtTime(t.last_used_at)}</td>
                <td class="px-3 py-2 text-right">
                    <button class="button delete-button revoke-btn" data-id="${t.id}" data-name="${escapeHtml(t.name)}">Revoke</button>
                </td>
            </tr>
        `).join('');
    }

    createBtn.addEventListener('click', async () => {
        const name = newTokenName.value.trim();
        if (!name) return;
        createBtn.disabled = true;
        try {
            const res = await fetch('/api/tokens', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name }),
            });
            const data = await res.json();
            if (!res.ok) {
                showToast(data.error || 'Failed to create token');
                return;
            }
            revealValue.textContent = data.token;
            reveal.style.display = 'block';
            newTokenName.value = '';
            loadTokens();
        } finally {
            createBtn.disabled = false;
        }
    });

    rowsEl.addEventListener('click', (e) => {
        const btn = e.target.closest('.revoke-btn');
        if (!btn) return;
        pendingRevokeId = btn.dataset.id;
        revokeModalDesc.textContent = `Revoke "${btn.dataset.name}"?`;
        revokeModal.style.display = 'flex';
    });

    revokeModalCancel.addEventListener('click', () => {
        revokeModal.style.display = 'none';
        pendingRevokeId = null;
    });

    revokeModalConfirm.addEventListener('click', async () => {
        if (!pendingRevokeId) return;
        revokeModalConfirm.disabled = true;
        const res = await fetch(`/api/tokens/${pendingRevokeId}/revoke`, { method: 'POST' });
        revokeModalConfirm.disabled = false;
        revokeModal.style.display = 'none';
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            showToast(data.error || 'Failed to revoke token');
            pendingRevokeId = null;
            return;
        }
        pendingRevokeId = null;
        loadTokens();
    });

    loadTokens();
})();
</script>
{% endblock %}
```

- [ ] **Step 2: Add a nav link**

In `templates/base.html`, find the "Logout button" comment (around line 993) and add a Settings link right before it:

```html
            <!-- Settings link -->
            <a href="{{ url_for('settings_page') }}"
                class="flex items-center space-x-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 p-2 rounded-lg transition-colors"
                title="Settings">
                <i class="fas fa-gear text-lg"></i>
                <span class="text-sm font-medium hidden sm:inline">Settings</span>
            </a>
            <!-- Logout button -->
            <a href="{{ url_for('logout') }}"
                class="text-lg text-gray-600 hover:text-gray-900 hover:bg-gray-100 p-2 rounded-lg transition-colors"
                title="Logout">
                <i class="fas fa-sign-out-alt"></i>
            </a>
```

- [ ] **Step 3: Manual verification in the browser**

Run:
```bash
docker compose restart web
```

Then, per the local-dev-quirks recipe, mint a session JWT for user 2, set it as the `session_token` cookie in your browser, and open `http://localhost:8000/settings`. Confirm:
- The "API Tokens" page renders with the nav bar's gear icon linking to it.
- The table lists the `manual-test` token from Task 3 (`Last used` populated from the curl requests).
- Typing a name and clicking "Generate token" shows the green reveal box with a `sb_pat_...` value, and the table refreshes to include it.
- Clicking "Revoke" opens the confirmation modal (not a native browser dialog); confirming removes the row from the table.

- [ ] **Step 4: Commit**

```bash
git add templates/settings.html templates/base.html
git commit -m "Add Settings page UI for API token management"
```

---

### Task 8: Version bump + full reused-endpoint verification

**Files:**
- Modify: `VERSION`

- [ ] **Step 1: Bump the version**

Change the contents of `VERSION` from `2.3.1` to `2.4.0` (new feature — personal access tokens).

- [ ] **Step 2: Restart and mint a fresh token for full verification**

Run:
```bash
docker compose restart web
SESSION_TOKEN=$(docker compose exec -T web python -c "from auth_utils import generate_session_token; print(generate_session_token(2, 'shelley@leemail.com.au'))" | tr -d '\r')
CSRF_TOKEN=$(curl -s --cookie "session_token=$SESSION_TOKEN" http://localhost:8000/settings \
  | grep -o 'name="csrf-token" content="[^"]*"' | sed 's/.*content="//; s/"$//')
curl -s --cookie "session_token=$SESSION_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" \
  -H "Content-Type: application/json" -d '{"name":"e2e-verification"}' \
  http://localhost:8000/api/tokens
```
Expected: `{"success": true, "id": ..., "name": "e2e-verification", "token": "sb_pat_..."}`. Export it:
```bash
export API_TOKEN="<paste the token value>"
```

- [ ] **Step 3: Verify `/api/boards`**

Run:
```bash
curl -s -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/api/boards | python3 -c "import json,sys; b=json.load(sys.stdin); print(len(b), 'boards; first id =', b[0]['id'])"
```
Expected: prints a board count > 0 and a board id.

- [ ] **Step 4: Verify `/get-sections/<board_id>`**

Run (substitute the board id from Step 3):
```bash
curl -s -H "Authorization: Bearer $API_TOKEN" http://localhost:8000/get-sections/<board_id> | head -c 200
```
Expected: a JSON array (possibly empty `[]` if that board has no sections — either is a valid 200 response).

- [ ] **Step 5: Verify `/create-board`**

Run:
```bash
curl -s -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"e2e-verification-board"}' \
  http://localhost:8000/create-board
```
Expected: `{"success": true, "board_id": ..., "name": "e2e-verification-board", "slug": "e2e-verification-board"}`.

- [ ] **Step 6: Verify `/add-pin` with a `data:image/` payload (the extension's actual image-upload path)**

Run (substitute the `board_id` from Step 5):
```bash
curl -s -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" \
  -d '{"board_id": <board_id>, "title": "e2e verification pin", "image_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="}' \
  http://localhost:8000/add-pin
```
Expected: `{"success": true, "pin_id": ...}`.

- [ ] **Step 7: Confirm the pin looks identical to a normal pin (same code path)**

Run (substitute the `pin_id` from Step 6):
```bash
docker compose exec -T db sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "SELECT id, title, board_id, uses_cached_image, cached_image_id IS NOT NULL AS has_cache_row FROM pins WHERE id=<pin_id>;"'
```
Expected: one row, `uses_cached_image = 1`, `has_cache_row = 1` — proving it went through `save_pasted_image`, the same path used by copy-paste in the web UI.

- [ ] **Step 8: Clean up all test data**

Run:
```bash
docker compose exec -T db sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e "
DELETE FROM pins WHERE title=\"e2e verification pin\";
DELETE FROM boards WHERE name IN (\"e2e-verification-board\");
DELETE FROM api_tokens WHERE name IN (\"manual-test\", \"e2e-verification\");
"'
```

- [ ] **Step 9: Commit**

```bash
git add VERSION
git commit -m "Bump version to 2.4.0 for personal access token support"
```

**Part A is now complete and independently useful** — you can generate a token in Settings and script against the Scrapbook API with `curl` even before the extension exists.

---

## Part B: Chrome Extension (new repo `~/scrapbook/scrapbook-chrome-extension`)

### Task 9: Repo scaffold + manifest.json

**Files:**
- Create: `~/scrapbook/scrapbook-chrome-extension/manifest.json`
- Create: `~/scrapbook/scrapbook-chrome-extension/.gitignore`
- Create: `~/scrapbook/scrapbook-chrome-extension/README.md`

- [ ] **Step 1: Create the repo**

```bash
mkdir -p ~/scrapbook/scrapbook-chrome-extension
cd ~/scrapbook/scrapbook-chrome-extension
git init
```

- [ ] **Step 2: Write `manifest.json`**

```json
{
  "manifest_version": 3,
  "name": "Send to Scrapbook",
  "version": "1.0.0",
  "description": "Right-click any image and save it to your Scrapbook instance.",
  "permissions": ["contextMenus", "storage", "scripting"],
  "host_permissions": ["<all_urls>"],
  "background": {
    "service_worker": "background.js"
  },
  "options_page": "options.html"
}
```

No custom icons for v1 — Chrome falls back to a generic default, which is fine for a personal, unpacked-only extension. Add icons later if wanted.

- [ ] **Step 3: Write `.gitignore`**

```
.DS_Store
```

- [ ] **Step 4: Write a short `README.md`**

```markdown
# Send to Scrapbook

Chrome extension: right-click any image on any page → "Send to Scrapbook" →
save it to a board in your self-hosted [Scrapbook](https://github.com/) instance
without leaving the page.

## Setup

1. Generate a personal access token in your Scrapbook instance under
   **Settings → API Tokens**.
2. Load this extension unpacked: `chrome://extensions` → enable
   **Developer mode** → **Load unpacked** → select this directory.
3. Click the extension's **Details → Extension options**, enter your
   Scrapbook instance's base URL and the token, and save.
4. Right-click any image on any page → **Send to Scrapbook**.

Not published to the Chrome Web Store — personal use only.
```

- [ ] **Step 5: Verify the manifest loads**

Open `chrome://extensions`, enable Developer mode, click "Load unpacked", select `~/scrapbook/scrapbook-chrome-extension`. Expected: the extension appears in the list as "Send to Scrapbook" with no errors shown (there's no `background.js`/`options.html` yet, so Chrome will show errors about missing files — that's expected at this step; confirm the *manifest itself* parses by checking the error is about missing files, not malformed JSON).

- [ ] **Step 6: Commit**

```bash
git add manifest.json .gitignore README.md
git commit -m "Scaffold Send to Scrapbook extension repo"
```

---

### Task 10: Options page (base URL + token)

**Files:**
- Create: `~/scrapbook/scrapbook-chrome-extension/options.html`
- Create: `~/scrapbook/scrapbook-chrome-extension/options.js`

- [ ] **Step 1: Write `options.html`**

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Send to Scrapbook — Settings</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 420px; margin: 40px auto; color: #222; }
    h1 { font-size: 18px; }
    label { display: block; margin: 16px 0 4px; font-size: 13px; font-weight: 600; }
    input { width: 100%; padding: 8px; border: 2px solid #e1e5e9; border-radius: 8px; font-size: 13px; box-sizing: border-box; }
    button { margin-top: 20px; padding: 8px 16px; border: none; border-radius: 4px; background: #2980b9; color: white; cursor: pointer; font-size: 13px; }
    #status { margin-top: 12px; font-size: 13px; color: #16a34a; min-height: 16px; }
    p.hint { font-size: 12px; color: #666; }
  </style>
</head>
<body>
  <h1>Send to Scrapbook</h1>
  <p class="hint">Generate a token in Scrapbook under Settings → API Tokens, then paste it here.</p>
  <label for="baseUrl">Scrapbook URL</label>
  <input id="baseUrl" type="text" placeholder="https://scrapbook.example.com">
  <label for="token">API Token</label>
  <input id="token" type="password" placeholder="sb_pat_...">
  <button id="save">Save</button>
  <div id="status"></div>
  <script src="options.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `options.js`**

```javascript
const baseUrlInput = document.getElementById('baseUrl');
const tokenInput = document.getElementById('token');
const statusEl = document.getElementById('status');

async function loadSaved() {
  const { baseUrl, token } = await chrome.storage.local.get(['baseUrl', 'token']);
  if (baseUrl) baseUrlInput.value = baseUrl;
  if (token) tokenInput.value = token;
}

document.getElementById('save').addEventListener('click', async () => {
  const baseUrl = baseUrlInput.value.trim().replace(/\/+$/, '');
  const token = tokenInput.value.trim();
  await chrome.storage.local.set({ baseUrl, token });
  statusEl.textContent = 'Saved.';
  setTimeout(() => { statusEl.textContent = ''; }, 2000);
});

loadSaved();
```

- [ ] **Step 3: Manual verification**

At `chrome://extensions`, click the reload icon on "Send to Scrapbook" (background.js still missing, so the extension card will still show an error — that's fine for now). Right-click the extension's icon area isn't available yet without a toolbar button; instead open the options page directly: click **Details** on the extension card → **Extension options**. Enter a base URL (e.g. `http://localhost:8000`) and the `sb_pat_...` token from Part A, Task 8. Click Save, confirm "Saved." appears. Reload the options page and confirm both fields are still populated.

- [ ] **Step 4: Commit**

```bash
git add options.html options.js
git commit -m "Add extension options page for Scrapbook URL and token"
```

---

### Task 11: Background service worker (context menu + API relay)

**Files:**
- Create: `~/scrapbook/scrapbook-chrome-extension/background.js`

- [ ] **Step 1: Write `background.js`**

```javascript
const MENU_ID = 'send-to-scrapbook';

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: 'Send to Scrapbook',
    contexts: ['image'],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID || !tab || !tab.id) return;
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ['content.js'],
  });
  chrome.tabs.sendMessage(tab.id, {
    type: 'OPEN_DIALOG',
    srcUrl: info.srcUrl,
    pageUrl: tab.url,
    pageTitle: tab.title,
  });
});

async function getConfig() {
  const { baseUrl, token } = await chrome.storage.local.get(['baseUrl', 'token']);
  return { baseUrl: (baseUrl || '').replace(/\/+$/, ''), token: token || '' };
}

async function apiFetch(path, options = {}) {
  const { baseUrl, token } = await getConfig();
  if (!baseUrl || !token) {
    return { ok: false, notConfigured: true };
  }
  let response;
  try {
    response = await fetch(baseUrl + path, {
      ...options,
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
    });
  } catch (err) {
    return { ok: false, networkError: true };
  }
  let data = null;
  try {
    data = await response.json();
  } catch (_) {
    // non-JSON body, leave data null
  }
  return { ok: response.ok, status: response.status, data };
}

async function handleMessage(message) {
  switch (message.type) {
    case 'GET_CONFIG': {
      const { baseUrl, token } = await getConfig();
      return { ok: true, configured: Boolean(baseUrl && token) };
    }
    case 'LIST_BOARDS':
      return apiFetch('/api/boards');
    case 'LIST_SECTIONS':
      return apiFetch(`/get-sections/${message.boardId}`);
    case 'CREATE_BOARD':
      return apiFetch('/create-board', {
        method: 'POST',
        body: JSON.stringify({ name: message.name }),
      });
    case 'ADD_PIN': {
      const { baseUrl } = await getConfig();
      const result = await apiFetch('/add-pin', {
        method: 'POST',
        body: JSON.stringify(message.payload),
      });
      return { ...result, baseUrl };
    }
    default:
      return { ok: false, error: `Unknown message type: ${message.type}` };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message).then(sendResponse);
  return true; // keep the message channel open for the async response
});
```

- [ ] **Step 2: Manual verification — context menu registers**

Reload the extension at `chrome://extensions`. Visit any webpage with images, right-click an image. Expected: a "Send to Scrapbook" entry appears in the context menu (clicking it will currently fail silently or error in the service worker console, since `content.js` doesn't exist yet — that's expected, covered by Task 12).

- [ ] **Step 3: Manual verification — background API relay**

Open the service worker console: `chrome://extensions` → "Send to Scrapbook" card → **service worker** link (opens DevTools). In that console, run:

```javascript
chrome.runtime.sendMessage({ type: 'GET_CONFIG' }, console.log)
```
Expected: logs `{ok: true, configured: true}` (assuming options were saved in Task 10).

Then:
```javascript
chrome.runtime.sendMessage({ type: 'LIST_BOARDS' }, console.log)
```
Expected: logs `{ok: true, status: 200, data: [...]}` with an array of board objects from your running Scrapbook instance.

- [ ] **Step 4: Commit**

```bash
git add background.js
git commit -m "Add background service worker: context menu + API relay"
```

---

### Task 12: Content script — dialog shell, styling, image capture

**Files:**
- Create: `~/scrapbook/scrapbook-chrome-extension/content.js`

- [ ] **Step 1: Write `content.js` (shell + image capture only — board/section/save wiring comes in Task 13)**

```javascript
(function () {
  if (window.__scrapbookDialogInjected) return;
  window.__scrapbookDialogInjected = true;

  let root = null;

  function closeDialog() {
    if (root) {
      root.remove();
      root = null;
    }
  }

  function fetchImageAsDataUrl(url) {
    return fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error('Image fetch failed');
        return r.blob();
      })
      .then(
        (blob) =>
          new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
          })
      );
  }

  function sendToBackground(message) {
    return chrome.runtime.sendMessage(message);
  }

  function describeError(res) {
    if (res.notConfigured) return 'Not connected — open the extension options to add your Scrapbook URL and token.';
    if (res.networkError) return 'Could not reach your Scrapbook instance.';
    if (res.status === 401) return "Your Scrapbook token isn't valid — check the extension options.";
    return (res.data && res.data.error) || 'Something went wrong.';
  }

  const DIALOG_HTML = `
    <div class="sb-backdrop">
      <div class="sb-dialog">
        <div class="sb-header">
          <h2>Send to Scrapbook</h2>
          <button type="button" class="sb-close" aria-label="Close">&times;</button>
        </div>
        <div class="sb-body">
          <div class="sb-preview-wrap">
            <img class="sb-preview" style="display:none;">
            <div class="sb-preview-status">Loading image...</div>
          </div>
          <div class="sb-field">
            <label>Title</label>
            <input type="text" class="sb-title" placeholder="Enter a title...">
          </div>
          <div class="sb-field">
            <label>Board</label>
            <select class="sb-board"><option value="">Loading boards...</option></select>
          </div>
          <div class="sb-field sb-new-board-row" style="display:none;">
            <input type="text" class="sb-new-board-name" placeholder="New board name">
            <button type="button" class="sb-new-board-create">Create</button>
          </div>
          <div class="sb-field">
            <label>Section (optional)</label>
            <select class="sb-section"><option value="">Select a section...</option></select>
          </div>
          <div class="sb-field">
            <label>Notes</label>
            <textarea class="sb-notes" placeholder="Add notes..."></textarea>
          </div>
          <div class="sb-status"></div>
        </div>
        <div class="sb-footer">
          <button type="button" class="sb-cancel">Cancel</button>
          <button type="button" class="sb-save" disabled>Save</button>
        </div>
      </div>
    </div>
  `;

  const DIALOG_CSS = `
    .sb-backdrop {
      position: fixed; inset: 0; background: rgba(0,0,0,0.5);
      display: flex; align-items: center; justify-content: center;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .sb-dialog {
      background: white; border-radius: 12px; width: 360px; max-height: 90vh;
      overflow-y: auto; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .sb-header {
      padding: 16px 20px; border-bottom: 1px solid #eee;
      display: flex; justify-content: space-between; align-items: center;
    }
    .sb-header h2 { font-size: 16px; margin: 0; color: #222; }
    .sb-close { background: none; border: none; font-size: 22px; cursor: pointer; color: #666; line-height: 1; }
    .sb-body { padding: 16px 20px; }
    .sb-preview-wrap { margin-bottom: 14px; text-align: center; }
    .sb-preview { max-width: 100%; max-height: 220px; border-radius: 4px; }
    .sb-preview-status { font-size: 12px; color: #666; padding: 20px 0; }
    .sb-field { margin-bottom: 12px; }
    .sb-field label { display: block; margin-bottom: 4px; color: #333; font-size: 12px; font-weight: 600; }
    .sb-field input, .sb-field select, .sb-field textarea {
      width: 100%; padding: 10px; border: 2px solid #e1e5e9; border-radius: 8px;
      font-size: 13px; box-sizing: border-box; font-family: inherit;
    }
    .sb-field input:focus, .sb-field select:focus, .sb-field textarea:focus {
      outline: none; border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59,130,246,0.1);
    }
    .sb-field textarea { min-height: 60px; resize: vertical; }
    .sb-new-board-row { display: flex; gap: 8px; }
    .sb-new-board-row input { flex: 1; }
    .sb-new-board-row button {
      padding: 8px 12px; border-radius: 6px; border: none; background: #3b82f6; color: white; cursor: pointer; font-size: 13px;
    }
    .sb-status { font-size: 12px; min-height: 16px; margin-top: 4px; }
    .sb-status-error { color: #e74c3c; }
    .sb-status-success { color: #16a34a; }
    .sb-footer {
      padding: 14px 20px; border-top: 1px solid #eee;
      display: flex; justify-content: flex-end; gap: 8px;
    }
    .sb-footer button { padding: 8px 16px; border-radius: 4px; cursor: pointer; font-size: 13px; border: none; }
    .sb-cancel { background: #f5f5f5; border: 1px solid #ddd; }
    .sb-save { background: #2980b9; color: white; }
    .sb-save:hover:not(:disabled) { background: #2472a4; }
    .sb-save:disabled { background: #ccc; cursor: not-allowed; }
  `;

  function openDialog(srcUrl, pageUrl, pageTitle) {
    closeDialog();

    root = document.createElement('div');
    root.id = 'scrapbook-send-dialog-host';
    root.style.position = 'fixed';
    root.style.inset = '0';
    root.style.zIndex = '2147483647';
    document.body.appendChild(root);

    const shadow = root.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = DIALOG_CSS;
    shadow.appendChild(style);
    const wrapper = document.createElement('div');
    wrapper.innerHTML = DIALOG_HTML;
    shadow.appendChild(wrapper.firstElementChild);

    const els = {
      backdrop: shadow.querySelector('.sb-backdrop'),
      close: shadow.querySelector('.sb-close'),
      cancel: shadow.querySelector('.sb-cancel'),
      save: shadow.querySelector('.sb-save'),
      preview: shadow.querySelector('.sb-preview'),
      previewStatus: shadow.querySelector('.sb-preview-status'),
      title: shadow.querySelector('.sb-title'),
      board: shadow.querySelector('.sb-board'),
      status: shadow.querySelector('.sb-status'),
    };

    els.close.addEventListener('click', closeDialog);
    els.cancel.addEventListener('click', closeDialog);
    els.backdrop.addEventListener('click', (e) => {
      if (e.target === els.backdrop) closeDialog();
    });

    const matchedImg = Array.from(document.images).find(
      (img) => img.src === srcUrl || img.currentSrc === srcUrl
    );
    els.title.value = (matchedImg && matchedImg.alt) || pageTitle || '';

    fetchImageAsDataUrl(srcUrl)
      .then((dataUrl) => {
        els.preview.src = dataUrl;
        els.preview.style.display = 'block';
        els.previewStatus.textContent = '';
      })
      .catch(() => {
        els.previewStatus.textContent = 'Could not load this image.';
      });
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === 'OPEN_DIALOG') {
      openDialog(message.srcUrl, message.pageUrl, message.pageTitle);
    }
  });
})();
```

- [ ] **Step 2: Manual verification**

Reload the extension at `chrome://extensions`. Go to any webpage with images (e.g. a news article or blog). Right-click an image → "Send to Scrapbook". Expected:
- A centered modal appears with a dimmed backdrop, styled like the Scrapbook web app's dialog (white rounded card, blue focus rings, `#2980b9`-colored... note: Save button is disabled at this point since board loading isn't wired up yet).
- The image preview loads and displays the actual right-clicked image within ~1s.
- The Title field is pre-filled with the image's alt text (or the page title if the image has no alt text).
- Clicking outside the dialog (on the dimmed backdrop) or the × button closes it.
- Right-clicking a *different* image and choosing "Send to Scrapbook" again closes any previously-open dialog and opens a fresh one for the new image (no duplicate dialogs stacking).

- [ ] **Step 3: Commit**

```bash
git add content.js
git commit -m "Add content script: Shadow DOM dialog shell and image capture"
```

---

### Task 13: Content script — boards/sections/new-board/save wiring

**Files:**
- Modify: `~/scrapbook/scrapbook-chrome-extension/content.js`

- [ ] **Step 1: Add board/section/save state and wiring**

In `content.js`, replace the `openDialog` function body (everything from `function openDialog(srcUrl, pageUrl, pageTitle) {` to its closing `}`) with:

```javascript
  function openDialog(srcUrl, pageUrl, pageTitle) {
    closeDialog();

    root = document.createElement('div');
    root.id = 'scrapbook-send-dialog-host';
    root.style.position = 'fixed';
    root.style.inset = '0';
    root.style.zIndex = '2147483647';
    document.body.appendChild(root);

    const shadow = root.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = DIALOG_CSS;
    shadow.appendChild(style);
    const wrapper = document.createElement('div');
    wrapper.innerHTML = DIALOG_HTML;
    shadow.appendChild(wrapper.firstElementChild);

    const els = {
      backdrop: shadow.querySelector('.sb-backdrop'),
      close: shadow.querySelector('.sb-close'),
      cancel: shadow.querySelector('.sb-cancel'),
      save: shadow.querySelector('.sb-save'),
      preview: shadow.querySelector('.sb-preview'),
      previewStatus: shadow.querySelector('.sb-preview-status'),
      title: shadow.querySelector('.sb-title'),
      board: shadow.querySelector('.sb-board'),
      newBoardRow: shadow.querySelector('.sb-new-board-row'),
      newBoardName: shadow.querySelector('.sb-new-board-name'),
      newBoardCreate: shadow.querySelector('.sb-new-board-create'),
      section: shadow.querySelector('.sb-section'),
      notes: shadow.querySelector('.sb-notes'),
      status: shadow.querySelector('.sb-status'),
    };

    els.close.addEventListener('click', closeDialog);
    els.cancel.addEventListener('click', closeDialog);
    els.backdrop.addEventListener('click', (e) => {
      if (e.target === els.backdrop) closeDialog();
    });

    const state = { imageDataUrl: null, boardId: null, sectionId: null };

    function updateSaveEnabled() {
      els.save.disabled = !(state.imageDataUrl && els.title.value.trim() && state.boardId);
    }
    els.title.addEventListener('input', updateSaveEnabled);

    const matchedImg = Array.from(document.images).find(
      (img) => img.src === srcUrl || img.currentSrc === srcUrl
    );
    els.title.value = (matchedImg && matchedImg.alt) || pageTitle || '';

    fetchImageAsDataUrl(srcUrl)
      .then((dataUrl) => {
        state.imageDataUrl = dataUrl;
        els.preview.src = dataUrl;
        els.preview.style.display = 'block';
        els.previewStatus.textContent = '';
        updateSaveEnabled();
      })
      .catch(() => {
        els.previewStatus.textContent = 'Could not load this image.';
      });

    function setError(res) {
      els.status.textContent = describeError(res);
      els.status.className = 'sb-status sb-status-error';
    }

    async function loadBoards() {
      els.board.innerHTML = '<option value="">Loading boards...</option>';
      const res = await sendToBackground({ type: 'LIST_BOARDS' });
      if (!res.ok) {
        setError(res);
        els.board.innerHTML = '<option value="">Select a board...</option>';
        return;
      }
      els.board.innerHTML = '';
      els.board.appendChild(new Option('Select a board...', ''));
      els.board.appendChild(new Option('+ New board...', '__new__'));
      (res.data || []).forEach((b) => els.board.appendChild(new Option(b.name, String(b.id))));
    }

    els.board.addEventListener('change', async () => {
      if (els.board.value === '__new__') {
        els.newBoardRow.style.display = 'flex';
        els.board.value = '';
        state.boardId = null;
        els.section.innerHTML = '<option value="">Select a section...</option>';
        updateSaveEnabled();
        return;
      }
      state.boardId = els.board.value || null;
      state.sectionId = null;
      updateSaveEnabled();
      if (!state.boardId) {
        els.section.innerHTML = '<option value="">Select a section...</option>';
        return;
      }
      els.section.innerHTML = '<option value="">Loading sections...</option>';
      const res = await sendToBackground({ type: 'LIST_SECTIONS', boardId: state.boardId });
      if (!res.ok) {
        setError(res);
        els.section.innerHTML = '<option value="">Select a section...</option>';
        return;
      }
      els.section.innerHTML = '';
      els.section.appendChild(new Option('Select a section...', ''));
      (res.data || []).forEach((s) => els.section.appendChild(new Option(s.name, String(s.id))));
    });

    els.section.addEventListener('change', () => {
      state.sectionId = els.section.value || null;
    });

    els.newBoardCreate.addEventListener('click', async () => {
      const name = els.newBoardName.value.trim();
      if (!name) return;
      els.newBoardCreate.disabled = true;
      const res = await sendToBackground({ type: 'CREATE_BOARD', name });
      els.newBoardCreate.disabled = false;
      if (!res.ok) {
        setError(res);
        return;
      }
      const board = res.data;
      const option = new Option(board.name, String(board.board_id), true, true);
      els.board.insertBefore(option, els.board.children[2] || null);
      els.board.value = String(board.board_id);
      state.boardId = String(board.board_id);
      els.newBoardRow.style.display = 'none';
      els.newBoardName.value = '';
      els.section.innerHTML = '<option value="">Select a section...</option>';
      updateSaveEnabled();
    });

    els.save.addEventListener('click', async () => {
      els.save.disabled = true;
      els.status.textContent = 'Saving...';
      els.status.className = 'sb-status';
      const res = await sendToBackground({
        type: 'ADD_PIN',
        payload: {
          title: els.title.value.trim(),
          board_id: state.boardId,
          section_id: state.sectionId,
          notes: els.notes.value.trim(),
          image_url: state.imageDataUrl,
          source_url: pageUrl,
        },
      });
      if (!res.ok) {
        setError(res);
        updateSaveEnabled();
        return;
      }
      els.status.innerHTML = '';
      els.status.className = 'sb-status sb-status-success';
      const successText = document.createElement('span');
      successText.textContent = 'Saved! ';
      const link = document.createElement('a');
      link.href = `${res.baseUrl}/pin/${res.data.pin_id}`;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'View pin';
      link.style.color = '#2980b9';
      els.status.appendChild(successText);
      els.status.appendChild(link);
      setTimeout(closeDialog, 2500);
    });

    loadBoards();
  }
```

- [ ] **Step 2: Manual verification — full happy path**

Reload the extension. Right-click an image on any page → "Send to Scrapbook". Expected:
- Board dropdown populates with your real Scrapbook boards, plus a "+ New board..." entry at the top.
- Selecting a board populates the section dropdown with that board's real sections (or leaves just "Select a section..." if it has none).
- Save button is disabled until image + title + board are all present, then enables.
- Clicking Save shows "Saving...", then "Saved! View pin" with a working link that opens the new pin in a new tab on your actual Scrapbook instance.
- The dialog auto-closes ~2.5s after success.
- Open the pin in Scrapbook and confirm the image, title, board, section, and notes match what you entered.

- [ ] **Step 3: Manual verification — new board flow**

Right-click a different image → "Send to Scrapbook" → select "+ New board..." → type a new board name → click "Create". Expected: the new board is selected automatically, the section dropdown resets to empty (a brand-new board has no sections), Save enables once title is present, and saving works.

- [ ] **Step 4: Manual verification — error states**

- Temporarily clear the token in the options page (Task 10), reload, try again. Expected: dialog opens, board dropdown shows the "Not connected..." message in the status area (via `setError` on the `LIST_BOARDS` failure), Save stays disabled. Restore the token afterward.
- Temporarily change the base URL in options to an unreachable address (e.g. `http://localhost:9`), try again. Expected: "Could not reach your Scrapbook instance." Restore the correct URL afterward.

- [ ] **Step 5: Commit**

```bash
git add content.js
git commit -m "Wire up board/section selection, new-board creation, and save flow"
```

---

### Task 14: Final end-to-end verification checklist

**Files:** none (verification only)

- [ ] **Step 1: Cross-site test**

Right-click images on at least two different real websites (different domains, different image hosting — e.g. a news site and a blog with a third-party CDN). Confirm the dialog opens and the image previews correctly on both, validating that `host_permissions: ["<all_urls>"]` is doing its job bypassing per-site CORS restrictions.

- [ ] **Step 2: Multiple saves in one session**

Save three separate pins to three different boards/sections in one browsing session without reloading the extension. Confirm each appears correctly in Scrapbook with no cross-contamination of state between dialog opens (an old title/board selection leaking into a new dialog would indicate a state-reset bug).

- [ ] **Step 3: Verify against the spec's success criteria**

Re-read `docs/superpowers/specs/2026-07-22-chrome-extension-send-to-scrapbook-design.md`'s "Success criteria" section and confirm all five are met.

- [ ] **Step 4: Commit the extension repo's remote (optional)**

If you want this backed up to a remote (e.g. a private GitHub repo), create it and push — this step is optional and not required for the extension to function locally.
