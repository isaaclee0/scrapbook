# Audit Log + Board-Deletion Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 30-day audit log of every change to boards/sections/pins with one-click undo for destructive actions, and close the underlying transactional and CSRF gaps that allow boards to disappear silently.

**Architecture:**
- New `audit_log` table written by an `audit_helpers.py` module (used from `app.py`).
- Mutating routes wrapped to capture before/after snapshots, request metadata, and outcome.
- `delete_board` and `move_board` rewritten as explicit transactions that include the audit-log INSERT, so audit and effect are atomic.
- New `csrf.py` helper providing a per-session token validated by a `@require_csrf` decorator on destructive POSTs.
- New `/audit-log` page (filterable, paginated) and `/audit/undo/<id>` route.
- New `migrate.py` step creates the table; new `scripts/audit_cleanup.py` purges rows older than 30 days.

**Tech Stack:** Flask, MariaDB via mysql.connector, Jinja2 templates, vanilla JS (matching the existing app style).

---

## Files Modified / Created

- **New:** `audit_helpers.py` — record/undo helpers.
- **New:** `csrf.py` — token issue + verify + decorator.
- **New:** `templates/audit_log.html` — list view.
- **New:** `scripts/audit_cleanup.py` — 30-day retention purge.
- **Modify:** `migrate.py` — Task 1 (create `audit_log` table; add `deleted_at` columns for soft-delete-style undo helpers if needed).
- **Modify:** `init.sql` — Task 1 (mirror schema for fresh installs).
- **Modify:** `app.py` — Tasks 2–9 (transactions, audit calls, CSRF, undo route, audit-log page, instrument migration scripts).
- **Modify:** `templates/board.html`, `templates/boards.html` — Task 8 (include CSRF token in destructive forms/JS).
- **Modify:** `migrate_to_isaac.py`, `migrate_to_shelley.py`, `scripts/remove_sweb_user.py` — Task 9 (write a `system.bulk_reassign` / `user.delete` row before touching data).

---

## Execution order

Tasks are listed in dependency order. Each commits separately. Tasks 2–4 must land before Task 5 (audit calls assume transactional safety).

---

### Task 1: Create `audit_log` table and migration

**Problem:** No table exists for recording changes. Without it, nothing else in this plan works.

**Files:**
- Modify: `migrate.py` (add Step 13)
- Modify: `init.sql` (add `audit_log` definition near the bottom)

- [ ] **Step 1: Add to `migrate.py` after Step 12**

Add a new step:

```python
        # Migration Step 13: Audit log
        info("\nStep 13: Audit log")
        if not table_exists(cursor, 'audit_log'):
            cursor.execute("""
                CREATE TABLE audit_log (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    created_at TIMESTAMP(3) DEFAULT CURRENT_TIMESTAMP(3),
                    user_id INT NULL,
                    actor_email VARCHAR(255),
                    action VARCHAR(64) NOT NULL,
                    entity_type VARCHAR(32) NOT NULL,
                    entity_id INT NULL,
                    before_data JSON NULL,
                    after_data JSON NULL,
                    metadata JSON NULL,
                    request_id VARCHAR(40),
                    ip_address VARCHAR(45),
                    outcome ENUM('success','failure') DEFAULT 'success',
                    INDEX idx_audit_created (created_at),
                    INDEX idx_audit_user (user_id, created_at),
                    INDEX idx_audit_entity (entity_type, entity_id, created_at),
                    INDEX idx_audit_action (action, created_at),
                    INDEX idx_audit_outcome (outcome, created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            success("Created audit_log table")
        else:
            warning("audit_log table already exists")
```

- [ ] **Step 2: Mirror in `init.sql`**

Append the same `CREATE TABLE` (with `CREATE TABLE IF NOT EXISTS audit_log`) before the trailing seed-data block.

- [ ] **Step 3: Verify**

Run `docker compose exec web python migrate.py`. Output should include `✅ Created audit_log table` (first run) or `⚠️ audit_log table already exists` (subsequent runs).

- [ ] **Step 4: Commit**

```bash
git add migrate.py init.sql
git commit -m "Add audit_log table for tracking all entity changes"
```

---

### Task 2: Add transactional safety helper

**Problem:** Pool is configured `autocommit=True` (`app.py:304`). Multi-statement deletes/moves are not atomic. There are zero `db.rollback()` calls anywhere.

**Decision:** Don't flip the pool default (would change behavior of every other route). Instead add a context manager that explicitly toggles autocommit off for the critical sections.

**Files:**
- Modify: `app.py` (add helper near `get_db_connection`)

- [ ] **Step 1: Add `tx()` context manager to `app.py`**

After `def get_db_connection()` (~line 454), add:

```python
from contextlib import contextmanager

@contextmanager
def tx():
    """
    Transactional context manager. Uses an explicit BEGIN/COMMIT/ROLLBACK on a pool
    connection where the pool default is autocommit=True. Yields (db, cursor).
    The cursor is a buffered cursor returning tuples; pass dictionary=True via
    db.cursor(...) inside the block if you need dicts for queries inside the txn.
    """
    db = get_db_connection()
    db.autocommit = False
    cursor = db.cursor(buffered=True)
    try:
        yield db, cursor
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            # Restore pool default before returning the connection.
            db.autocommit = True
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass
```

- [ ] **Step 2: Commit**

```bash
git add app.py
git commit -m "Add tx() transactional context manager for atomic multi-statement writes"
```

---

### Task 3: Convert `delete_board` and `move_board` to use `tx()`

**Problem:** `delete_board` (`app.py:2178–2211`) and `move_board` (`app.py:2112–2176`) execute multiple DELETE/UPDATE statements that are auto-committed individually. A failure mid-flow leaves the board in a partial state. `move_board`'s `UPDATE sections` is also missing a `user_id` filter.

**Files:**
- Modify: `app.py:2112–2211`

- [ ] **Step 1: Rewrite `delete_board`**

Replace the body of `delete_board` (after `user = get_current_user()`) with:

```python
    try:
        with tx() as (db, cursor):
            cursor.execute("SELECT * FROM boards WHERE id = %s AND user_id = %s",
                           (board_id, user['id']))
            board_row = cursor.fetchone()
            if not board_row:
                return jsonify({"error": "Board not found"}), 404

            cursor.execute("DELETE FROM pins WHERE board_id = %s AND user_id = %s",
                           (board_id, user['id']))
            cursor.execute("DELETE FROM sections WHERE board_id = %s AND user_id = %s",
                           (board_id, user['id']))
            cursor.execute("DELETE FROM boards WHERE id = %s AND user_id = %s",
                           (board_id, user['id']))

        if redis_client:
            redis_client.delete(f"view:{user['id']}:/")
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error deleting board: {str(e)}")
        return jsonify({"error": "Failed to delete board"}), 500
```

(The audit recording call lands inside this block in Task 5.)

- [ ] **Step 2: Rewrite `move_board`**

Replace the body of `move_board` similarly, scoping every UPDATE/DELETE by `user_id` and wrapping with `tx()`. Add the missing `user_id` filter on `UPDATE sections`:

```python
    try:
        data = request.get_json() or {}
        target_board_id = data.get('target_board_id')
        if not target_board_id:
            return jsonify({"error": "Target board ID is required"}), 400

        with tx() as (db, cursor):
            cursor.execute("SELECT * FROM boards WHERE id = %s AND user_id = %s",
                           (board_id, user['id']))
            source_board = cursor.fetchone()
            if not source_board:
                return jsonify({"error": "Source board not found"}), 404
            source_board_name = source_board[1] if not isinstance(source_board, dict) else source_board['name']

            cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s",
                           (target_board_id, user['id']))
            if not cursor.fetchone():
                return jsonify({"error": "Target board not found"}), 404

            cursor.execute("""
                INSERT INTO sections (board_id, name, user_id)
                VALUES (%s, %s, %s)
            """, (target_board_id, source_board_name, user['id']))
            new_section_id = cursor.lastrowid

            cursor.execute("""
                UPDATE pins SET board_id = %s, section_id = %s
                WHERE board_id = %s AND user_id = %s
            """, (target_board_id, new_section_id, board_id, user['id']))

            cursor.execute("""
                UPDATE sections SET board_id = %s
                WHERE board_id = %s AND user_id = %s AND id != %s
            """, (target_board_id, board_id, user['id'], new_section_id))

            cursor.execute("DELETE FROM boards WHERE id = %s AND user_id = %s",
                           (board_id, user['id']))

        if redis_client:
            redis_client.delete(f"view:{user['id']}:/")
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error moving board: {str(e)}")
        return jsonify({"error": "Failed to move board"}), 500
```

The `id != %s` guard on the UPDATE ensures the freshly-inserted target section isn't accidentally re-pointed.

- [ ] **Step 3: Manual verification**

- Delete a board → board, its pins, and its sections all gone.
- Move a board → source disappears, pins appear in target under a new section named after source. Sections from source land in target.
- Simulate a mid-flow failure: temporarily insert `raise RuntimeError('boom')` between two statements in `delete_board`, hit the route, confirm the board still exists. Remove the test code and re-run; cleanup should be complete.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Make delete_board and move_board atomic via tx(); fix move_board section scoping"
```

---

### Task 4: Add `audit_helpers.py`

**Problem:** Need a single, reusable way to write audit rows that works inside `tx()` and from migration scripts.

**Files:**
- New: `audit_helpers.py`

- [ ] **Step 1: Create the module**

```python
"""Audit log helpers. Designed to be called from inside a tx() block in app.py."""

import json
import uuid
from typing import Any, Optional


def _to_json(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    def _default(o):
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, default=_default)


def record_audit(
    cursor,
    *,
    action: str,
    entity_type: str,
    entity_id: Optional[int],
    user_id: Optional[int] = None,
    actor_email: Optional[str] = None,
    before: Any = None,
    after: Any = None,
    metadata: Optional[dict] = None,
    request_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    outcome: str = 'success',
) -> int:
    """Insert an audit row using the provided cursor (so it is part of the caller's
    transaction). Returns the inserted audit_log.id."""
    cursor.execute(
        """
        INSERT INTO audit_log
          (user_id, actor_email, action, entity_type, entity_id,
           before_data, after_data, metadata, request_id, ip_address, outcome)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            user_id, actor_email, action, entity_type, entity_id,
            _to_json(before), _to_json(after), _to_json(metadata),
            request_id or uuid.uuid4().hex[:32], ip_address, outcome,
        ),
    )
    return cursor.lastrowid


def snapshot_board(cursor, board_id: int) -> Optional[dict]:
    """Capture a full board snapshot (board row + sections + pins) for undo."""
    cursor.execute("SELECT * FROM boards WHERE id = %s", (board_id,))
    cols = [c[0] for c in cursor.description] if cursor.description else []
    row = cursor.fetchone()
    if not row:
        return None
    board = dict(zip(cols, row))

    cursor.execute("SELECT * FROM sections WHERE board_id = %s", (board_id,))
    scols = [c[0] for c in cursor.description]
    sections = [dict(zip(scols, r)) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM pins WHERE board_id = %s", (board_id,))
    pcols = [c[0] for c in cursor.description]
    pins = [dict(zip(pcols, r)) for r in cursor.fetchall()]

    return {"board": board, "sections": sections, "pins": pins}


def snapshot_pin(cursor, pin_id: int) -> Optional[dict]:
    cursor.execute("SELECT * FROM pins WHERE id = %s", (pin_id,))
    cols = [c[0] for c in cursor.description] if cursor.description else []
    row = cursor.fetchone()
    if not row:
        return None
    return dict(zip(cols, row))


def snapshot_section(cursor, section_id: int) -> Optional[dict]:
    cursor.execute("SELECT * FROM sections WHERE id = %s", (section_id,))
    cols = [c[0] for c in cursor.description] if cursor.description else []
    row = cursor.fetchone()
    if not row:
        return None
    section = dict(zip(cols, row))
    cursor.execute("SELECT * FROM pins WHERE section_id = %s", (section_id,))
    pcols = [c[0] for c in cursor.description]
    section['pins'] = [dict(zip(pcols, r)) for r in cursor.fetchall()]
    return section
```

- [ ] **Step 2: Commit**

```bash
git add audit_helpers.py
git commit -m "Add audit_helpers module with record_audit and entity snapshot helpers"
```

---

### Task 5: Instrument every mutating route

**Problem:** No audit data is captured today. Add `record_audit(...)` calls at the appropriate place in each mutating route.

**Files:**
- Modify: `app.py` — routes listed below

For each route, the pattern is:
1. If destructive: take a `before` snapshot inside the `tx()` block before deleting.
2. Write the audit row inside the same `tx()` block (so it commits atomically with the change).
3. Pass `user_id`, `actor_email`, `request.headers.get('X-Request-Id') or generated`, and `request.remote_addr`.

- [ ] **Step 1: Imports**

At the top of `app.py`:

```python
from audit_helpers import record_audit, snapshot_board, snapshot_pin, snapshot_section
```

- [ ] **Step 2: Routes to instrument**

| Route (current line) | action | entity_type | snapshot |
|---|---|---|---|
| `create_board` (1785) | `board.create` | `board` | `before=None`, `after={id, name, slug}` |
| `rename_board` (2086) | `board.rename` | `board` | `before={name}`, `after={name}` |
| `delete_board` (2180) | `board.delete` | `board` | `before=snapshot_board(...)`, `after=None` |
| `move_board` (2114) | `board.move` | `board` | `before=snapshot_board(source)`, `after={target_board_id, new_section_id}` |
| `set_board_image` (2215) | `board.update_image` | `board` | `before={default_image_url}`, `after={default_image_url}` |
| `create_section` (1914) | `section.create` | `section` | `after={id, name, board_id}` |
| `update_section` (1957) | `section.rename` | `section` | `before={name}`, `after={name}` |
| `delete_section` (2002) | `section.delete` | `section` | `before=snapshot_section(...)` |
| `set_section_image` (2256) | `section.update_image` | `section` | `before/after={default_image_url}` |
| `add_pin` (1493) | `pin.create` | `pin` | `after={id, board_id, section_id, image_url}` |
| `move_pin` (1862) | `pin.move` | `pin` | `before={board_id, section_id}`, `after={board_id, section_id}` |
| `move_pin_to_section` (2037) | `pin.move_to_section` | `pin` | `before/after={section_id}` |
| `delete_pin` (3152) | `pin.delete` | `pin` | `before=snapshot_pin(...)` |

- [ ] **Step 3: For each route already in `tx()` (delete_board, move_board)**

Add inside the `with tx()` block, after the mutation but before the block exits:

```python
record_audit(
    cursor,
    action='board.delete',  # or appropriate action
    entity_type='board',
    entity_id=board_id,
    user_id=user['id'],
    actor_email=user.get('email'),
    before=before_snapshot,
    after=None,
    metadata={'route': request.path},
    ip_address=request.remote_addr,
)
```

- [ ] **Step 4: Convert remaining destructive routes (`delete_section`, `delete_pin`) to `tx()`**

Same pattern — wrap the SELECT-snapshot + DELETE + audit insert in `with tx()`.

- [ ] **Step 5: For non-destructive routes (renames, image sets, creates, moves)**

These currently call `db.commit()` after a single statement. Convert to `tx()` so the audit row is part of the same commit:

```python
with tx() as (db, cursor):
    # existing ownership check + UPDATE/INSERT
    record_audit(cursor, action=..., entity_type=..., entity_id=..., user_id=user['id'],
                 actor_email=user.get('email'), before=..., after=..., ip_address=request.remote_addr)
```

- [ ] **Step 6: Manual verification**

After completing each route group, exercise the UI:
- Create/rename/delete a board → 3 rows appear in `audit_log` (query via phpMyAdmin).
- Add/move/delete a pin → 3 rows.
- Each row's `before_data` for delete actions contains a full restorable snapshot.

- [ ] **Step 7: Commit (per route group)**

E.g.:
```bash
git add app.py
git commit -m "Instrument board mutation routes with audit_log writes"
```

Repeat for sections, then for pins.

---

### Task 6: 30-day retention purge

**Problem:** The audit table will grow indefinitely. Add a cleanup script.

**Files:**
- New: `scripts/audit_cleanup.py`
- Modify: `README.md` — document the cron suggestion

- [ ] **Step 1: Create the script**

```python
#!/usr/bin/env python3
"""Delete audit_log rows older than AUDIT_RETENTION_DAYS (default 30)."""
import os
import sys
import mysql.connector

RETENTION_DAYS = int(os.getenv('AUDIT_RETENTION_DAYS', 30))

def main():
    conn = mysql.connector.connect(
        host=os.getenv('DB_HOST', 'db'),
        user=os.getenv('DB_USER', 'db'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME', 'db'),
    )
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM audit_log WHERE created_at < DATE_SUB(NOW(), INTERVAL %s DAY)",
            (RETENTION_DAYS,),
        )
        deleted = cursor.rowcount
        conn.commit()
        print(f"Deleted {deleted} audit_log rows older than {RETENTION_DAYS} days")
    finally:
        conn.close()

if __name__ == '__main__':
    sys.exit(main() or 0)
```

- [ ] **Step 2: Document daily cron in `README.md`** (one-liner under Maintenance):

> `docker compose exec web python scripts/audit_cleanup.py`  — run daily via cron to enforce 30-day retention.

- [ ] **Step 3: Commit**

```bash
git add scripts/audit_cleanup.py README.md
git commit -m "Add audit_cleanup script enforcing 30-day retention"
```

---

### Task 7: Add CSRF protection to destructive POSTs

**Problem:** No CSRF tokens. `SameSite=Lax` blocks cross-site `<form>` POSTs but does not block top-level link-triggered POSTs in older browsers, and provides no defense against authenticated XSS-leveraged requests.

**Files:**
- New: `csrf.py`
- Modify: `app.py` (apply decorator to destructive routes; expose token in templates via context processor)
- Modify: `templates/board.html`, `templates/boards.html` (pass token in fetch headers)

- [ ] **Step 1: Create `csrf.py`**

```python
"""Per-session CSRF token issued via cookie, validated via X-CSRF-Token header."""
import hmac
import hashlib
import os
from functools import wraps
from flask import request, jsonify

CSRF_SECRET = os.getenv('JWT_SECRET_KEY', 'change-this').encode()


def issue_csrf_token(session_token: str) -> str:
    return hmac.new(CSRF_SECRET, session_token.encode(), hashlib.sha256).hexdigest()


def verify_csrf(session_token: str, presented_token: str) -> bool:
    if not session_token or not presented_token:
        return False
    expected = issue_csrf_token(session_token)
    return hmac.compare_digest(expected, presented_token)


def require_csrf(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        session_token = request.cookies.get('session_token', '')
        presented = request.headers.get('X-CSRF-Token') or (request.get_json(silent=True) or {}).get('csrf_token')
        if not verify_csrf(session_token, presented or ''):
            return jsonify({"error": "CSRF token missing or invalid"}), 403
        return view(*args, **kwargs)
    return wrapper
```

- [ ] **Step 2: Expose token to templates via context processor in `app.py`**

```python
from csrf import issue_csrf_token, require_csrf

@app.context_processor
def inject_csrf_token():
    token = request.cookies.get('session_token', '')
    return {'csrf_token': issue_csrf_token(token) if token else ''}
```

- [ ] **Step 3: Apply `@require_csrf` to all destructive POST routes**

Apply to: `create_board`, `rename_board`, `delete_board`, `move_board`, `set_board_image`, `create_section`, `update_section`, `delete_section`, `set_section_image`, `add_pin`, `move_pin`, `move_pin_to_section`, `delete_pin`. Order: `@app.route(...)` → `@login_required` → `@require_csrf`.

- [ ] **Step 4: Update template fetch calls**

In `templates/board.html`, `templates/boards.html`, and any other template that POSTs, change every `fetch('/...', { method: 'POST', ... })` to include the header:

```javascript
const csrfToken = '{{ csrf_token }}';
fetch('/delete-board/{{ board.id }}', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
});
```

- [ ] **Step 5: Manual verification**

- Delete a board via UI → succeeds.
- In DevTools, repeat the request stripping the `X-CSRF-Token` header → 403.
- Confirm all other UI mutations still work.

- [ ] **Step 6: Commit**

```bash
git add csrf.py app.py templates/board.html templates/boards.html
git commit -m "Add CSRF protection to all destructive mutation routes"
```

---

### Task 8: Audit-log viewer page

**Problem:** Audit data is only useful if you can see it.

**Files:**
- New: `templates/audit_log.html`
- Modify: `app.py` — add `/audit-log` route

- [ ] **Step 1: Add route in `app.py`**

```python
@app.route('/audit-log')
@login_required
def audit_log_view():
    user = get_current_user()
    action_filter = request.args.get('action', '')
    entity_filter = request.args.get('entity_type', '')
    page = max(1, int(request.args.get('page', 1) or 1))
    per_page = 50
    offset = (page - 1) * per_page

    where = ["user_id = %s"]
    params = [user['id']]
    if action_filter:
        where.append("action = %s"); params.append(action_filter)
    if entity_filter:
        where.append("entity_type = %s"); params.append(entity_filter)
    where_sql = " AND ".join(where)

    db = get_db_connection()
    try:
        cursor = db.cursor(dictionary=True)
        cursor.execute(f"""
            SELECT id, created_at, action, entity_type, entity_id,
                   before_data, after_data, metadata, outcome
            FROM audit_log
            WHERE {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT %s OFFSET %s
        """, (*params, per_page, offset))
        rows = cursor.fetchall()
        cursor.execute(f"SELECT COUNT(*) AS c FROM audit_log WHERE {where_sql}", tuple(params))
        total = cursor.fetchone()['c']
    finally:
        db.close()

    return render_template('audit_log.html',
                           rows=rows, total=total, page=page, per_page=per_page,
                           action_filter=action_filter, entity_filter=entity_filter)
```

- [ ] **Step 2: Create `templates/audit_log.html`**

Minimal table + filter dropdowns + pagination. Each row shows: timestamp, action, entity_type/id, a "details" expander showing before/after JSON, and (for `*.delete` rows whose `before_data` is non-null) an Undo button that POSTs to `/audit/undo/<id>`.

- [ ] **Step 3: Add nav link in `templates/boards.html`** (or wherever the user menu lives) to `/audit-log`.

- [ ] **Step 4: Manual verification**

Trigger a few actions; visit `/audit-log` and confirm they appear in reverse-chronological order. Filters work. Pagination works.

- [ ] **Step 5: Commit**

```bash
git add app.py templates/audit_log.html templates/boards.html
git commit -m "Add /audit-log viewer with filters and pagination"
```

---

### Task 9: Undo route

**Problem:** Undo button needs a backend.

**Files:**
- Modify: `app.py` — add `/audit/undo/<int:audit_id>`

- [ ] **Step 1: Implement undo for `board.delete` and `pin.delete`**

```python
@app.route('/audit/undo/<int:audit_id>', methods=['POST'])
@login_required
@require_csrf
def audit_undo(audit_id):
    user = get_current_user()
    try:
        with tx() as (db, cursor):
            cursor.execute("""
                SELECT action, entity_type, entity_id, before_data, user_id
                FROM audit_log WHERE id = %s
            """, (audit_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({"error": "Audit row not found"}), 404
            action, entity_type, entity_id, before_data, owner = row
            if owner != user['id']:
                return jsonify({"error": "Not your audit row"}), 403
            if not before_data:
                return jsonify({"error": "Nothing to undo"}), 400

            import json as _json
            snap = _json.loads(before_data)

            if action == 'board.delete':
                b = snap['board']
                cursor.execute("""
                    INSERT INTO boards (id, user_id, name, slug, default_image_url, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (b['id'], b['user_id'], b['name'], b.get('slug'),
                      b.get('default_image_url'), b.get('created_at'), b.get('updated_at')))
                for s in snap.get('sections', []):
                    cursor.execute("""
                        INSERT INTO sections (id, board_id, user_id, name, default_image_url, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (s['id'], s['board_id'], s['user_id'], s['name'],
                          s.get('default_image_url'), s.get('created_at'), s.get('updated_at')))
                for p in snap.get('pins', []):
                    cursor.execute("""
                        INSERT INTO pins (id, user_id, board_id, section_id, pin_id, link, title,
                                          description, notes, image_url, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (p['id'], p['user_id'], p['board_id'], p.get('section_id'),
                          p.get('pin_id'), p.get('link'), p['title'], p.get('description'),
                          p.get('notes'), p['image_url'], p.get('created_at'), p.get('updated_at')))
                record_audit(cursor, action='board.undo_delete', entity_type='board',
                             entity_id=b['id'], user_id=user['id'],
                             actor_email=user.get('email'),
                             metadata={'restored_from_audit_id': audit_id},
                             ip_address=request.remote_addr)
            elif action == 'pin.delete':
                p = snap
                cursor.execute("""
                    INSERT INTO pins (id, user_id, board_id, section_id, pin_id, link, title,
                                      description, notes, image_url, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (p['id'], p['user_id'], p['board_id'], p.get('section_id'),
                      p.get('pin_id'), p.get('link'), p['title'], p.get('description'),
                      p.get('notes'), p['image_url'], p.get('created_at'), p.get('updated_at')))
                record_audit(cursor, action='pin.undo_delete', entity_type='pin',
                             entity_id=p['id'], user_id=user['id'],
                             actor_email=user.get('email'),
                             metadata={'restored_from_audit_id': audit_id},
                             ip_address=request.remote_addr)
            elif action == 'section.delete':
                s = snap
                cursor.execute("""
                    INSERT INTO sections (id, board_id, user_id, name, default_image_url, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (s['id'], s['board_id'], s['user_id'], s['name'],
                      s.get('default_image_url'), s.get('created_at'), s.get('updated_at')))
                for p in s.get('pins', []):
                    cursor.execute("UPDATE pins SET section_id = %s WHERE id = %s AND user_id = %s",
                                   (s['id'], p['id'], user['id']))
                record_audit(cursor, action='section.undo_delete', entity_type='section',
                             entity_id=s['id'], user_id=user['id'],
                             actor_email=user.get('email'),
                             metadata={'restored_from_audit_id': audit_id},
                             ip_address=request.remote_addr)
            else:
                return jsonify({"error": f"Undo not supported for action {action}"}), 400

        if redis_client:
            redis_client.delete(f"view:{user['id']}:/")
        return jsonify({"success": True})
    except mysql.connector.IntegrityError as ie:
        # Most common cause: id collision because the original row still exists,
        # or a parent row (e.g. user) is gone.
        return jsonify({"error": f"Cannot restore: {str(ie)}"}), 409
    except Exception as e:
        print(f"Audit undo failed: {e}")
        return jsonify({"error": "Undo failed"}), 500
```

Re-using the original `id` keeps incoming links/foreign keys consistent. If the user has since created a board/pin with that id (extremely unlikely with autoincrement) the undo fails cleanly with 409.

- [ ] **Step 2: Manual verification**

Delete a board with sections and pins → click Undo on the audit row → board reappears with all pins/sections intact and the same id.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "Add /audit/undo route to restore deleted boards/sections/pins from snapshots"
```

---

### Task 10: Instrument bulk-mutation scripts

**Problem:** `migrate_to_isaac.py`, `migrate_to_shelley.py`, and `scripts/remove_sweb_user.py` modify ownership / delete users without leaving any trace. If accidentally run against the wrong DB, there's nothing to forensically recover from.

**Files:**
- Modify: `migrate_to_isaac.py`, `migrate_to_shelley.py`, `scripts/remove_sweb_user.py`

- [ ] **Step 1: Before mutating, INSERT an `audit_log` row**

In each script, after the `cursor` is created and before any UPDATE/DELETE:

```python
cursor.execute("""
    INSERT INTO audit_log (user_id, actor_email, action, entity_type, entity_id, metadata, outcome)
    VALUES (%s, %s, %s, %s, %s, %s, 'success')
""", (target_user_id, target_email, 'system.bulk_reassign', 'user', target_user_id,
      json.dumps({'script': sys.argv[0], 'pre_counts': {'boards': total_boards, 'pins': total_pins, 'sections': total_sections}})))
connection.commit()
```

For `remove_sweb_user.py` use `action='user.delete'` and capture the user record + counts before the cascade.

- [ ] **Step 2: Add a `--confirm` flag**

Reject execution unless `--confirm` is passed. This prevents an accidental `python migrate_to_shelley.py` against production.

- [ ] **Step 3: Commit**

```bash
git add migrate_to_isaac.py migrate_to_shelley.py scripts/remove_sweb_user.py
git commit -m "Audit-log bulk reassignment / user-delete scripts and require --confirm"
```

---

## Self-Review Checklist

- [x] Task 1 — `audit_log` table exists in both `migrate.py` and `init.sql`.
- [x] Task 2 — `tx()` provides explicit transactions and rollback.
- [x] Task 3 — `delete_board` and `move_board` are atomic; `move_board` `UPDATE sections` is user-scoped.
- [x] Task 4 — `audit_helpers.py` provides `record_audit` + entity snapshot helpers.
- [x] Task 5 — Every mutating route writes an audit row inside its transaction.
- [x] Task 6 — Daily script enforces 30-day retention.
- [x] Task 7 — All destructive POSTs require `X-CSRF-Token` matching the session.
- [x] Task 8 — `/audit-log` page lists user's last 30 days with filters and pagination.
- [x] Task 9 — `/audit/undo/<id>` restores deleted boards/pins/sections from snapshots.
- [x] Task 10 — Bulk DB scripts log to `audit_log` and require `--confirm`.

**Dependency notes:**
- Task 3 depends on Task 2 (uses `tx()`).
- Task 5 depends on Tasks 2, 3, 4.
- Task 7 (CSRF) is independent of audit logic; can land in parallel but must precede Task 9 (undo).
- Task 8 depends on Task 1.
- Task 9 depends on Tasks 1, 4, 5, 7.
