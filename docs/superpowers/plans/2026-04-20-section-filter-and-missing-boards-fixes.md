# Section Filter & Missing Boards Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 9 bugs causing section filters to leak cross-section pins and boards to disappear for users.

**Architecture:** All changes are in `app.py` (Flask routes/logic) and `templates/board.html` (client-side filter). No new files needed. Each fix is a surgical edit; no refactoring beyond the bug site.

**Tech Stack:** Flask, MariaDB via mysql.connector, Redis (optional), Jinja2 templates, vanilla JS.

---

## Files Modified

- `app.py` — Tasks 1–6, 9
- `templates/board.html` — Tasks 7, 8

---

### Task 1: Validate board ownership and section/board consistency in add-pin

**Problem:** `/add-pin` at `app.py:1575` inserts a pin without verifying (a) the board belongs to the user and (b) the section_id (if supplied) belongs to that board. This creates orphan pins that distort section pin counts.

**Files:**
- Modify: `app.py:1608–1632`

- [ ] **Step 1: Locate the add-pin DB work (after input parsing, before INSERT)**

Open `app.py` and find the block at lines ~1608–1632. It starts with `db = get_db_connection()`.

- [ ] **Step 2: Add board ownership check after `db = get_db_connection()`**

Replace this block (lines ~1608–1616, the `SHOW COLUMNS` block comes after):

```python
        db = get_db_connection()
        cursor = db.cursor()
        
        # Verify board belongs to the current user
        cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s", (board_id, user['id']))
        if not cursor.fetchone():
            return jsonify({"error": "Board not found"}), 404
        
        # Verify section belongs to this board (if provided)
        if section_id:
            cursor.execute(
                "SELECT id FROM sections WHERE id = %s AND board_id = %s",
                (section_id, board_id)
            )
            if not cursor.fetchone():
                return jsonify({"error": "Section not found or belongs to a different board"}), 400
        
        # Check if pins table has cached image columns
        cursor.execute("SHOW COLUMNS FROM pins LIKE 'cached_image_id'")
```

The full replacement for the section starting at `db = get_db_connection()` through `cursor.execute("SHOW COLUMNS FROM pins LIKE 'cached_image_id'")`:

```python
        db = get_db_connection()
        cursor = db.cursor()
        
        # Verify board belongs to the current user
        cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s", (board_id, user['id']))
        if not cursor.fetchone():
            return jsonify({"error": "Board not found"}), 404
        
        # Verify section belongs to this board (if provided)
        if section_id:
            cursor.execute(
                "SELECT id FROM sections WHERE id = %s AND board_id = %s",
                (section_id, board_id)
            )
            if not cursor.fetchone():
                return jsonify({"error": "Section not found or belongs to a different board"}), 400
        
        # Check if pins table has cached image columns
        cursor.execute("SHOW COLUMNS FROM pins LIKE 'cached_image_id'")
```

- [ ] **Step 3: Manual verification**

Run the app locally. Try adding a pin via the UI on a valid board with a valid section. Should succeed. Try POSTing to `/add-pin` with a mismatched section_id — should return 400.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Fix add-pin to validate board ownership and section/board consistency"
```

---

### Task 2: Fix move-board INSERT missing user_id

**Problem:** `app.py:2210` creates a new section without setting `user_id`, which is `NOT NULL`. In strict SQL mode this aborts the board move. With a migration-set default, the section gets the wrong owner.

**Files:**
- Modify: `app.py:2210–2213`

- [ ] **Step 1: Find the INSERT in move_board**

In `app.py`, locate `def move_board` (~line 2184). Find this exact block:

```python
        # Create a new section in the target board with the source board's name
        cursor.execute("""
            INSERT INTO sections (board_id, name)
            VALUES (%s, %s)
        """, (target_board_id, source_board_name))
```

- [ ] **Step 2: Add user_id to the INSERT**

Replace with:

```python
        # Create a new section in the target board with the source board's name
        cursor.execute("""
            INSERT INTO sections (board_id, name, user_id)
            VALUES (%s, %s, %s)
        """, (target_board_id, source_board_name, user['id']))
```

- [ ] **Step 3: Manual verification**

Use the UI to "Convert Board to Section" — should succeed and the source board should disappear, its pins appearing as a section in the target board.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Fix move-board to include user_id in new section INSERT"
```

---

### Task 3: Fix delete-board to scope section deletion by user

**Problem:** `app.py:2260` deletes sections with only `board_id` — no user check. A crafted request can delete sections of another user's board, nullifying those pins' section_id.

**Files:**
- Modify: `app.py:2256–2263`

- [ ] **Step 1: Find the delete-board sequence**

In `def delete_board` (~line 2250), find:

```python
        # First, delete all pins in the board (user-scoped)
        cursor.execute("DELETE FROM pins WHERE board_id = %s AND user_id = %s", (board_id, user['id']))
        
        # Then, delete all sections in the board
        cursor.execute("DELETE FROM sections WHERE board_id = %s", (board_id,))
        
        # Finally, delete the board itself (user-scoped)
        cursor.execute("DELETE FROM boards WHERE id = %s AND user_id = %s", (board_id, user['id']))
```

- [ ] **Step 2: Add a board ownership check before any deletion**

Replace the entire block with:

```python
        # Verify board belongs to user before any deletions
        cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s", (board_id, user['id']))
        if not cursor.fetchone():
            return jsonify({"error": "Board not found"}), 404
        
        # Delete all pins in the board (user-scoped)
        cursor.execute("DELETE FROM pins WHERE board_id = %s AND user_id = %s", (board_id, user['id']))
        
        # Delete all sections in the board (safe: board ownership already verified above)
        cursor.execute("DELETE FROM sections WHERE board_id = %s", (board_id,))
        
        # Delete the board itself (user-scoped)
        cursor.execute("DELETE FROM boards WHERE id = %s AND user_id = %s", (board_id, user['id']))
```

- [ ] **Step 3: Manual verification**

Delete a board via UI — should work. The board, its pins, and its sections should all be gone.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Fix delete-board to verify board ownership before deleting sections"
```

---

### Task 4: Fix section pin-count to scope by board

**Problem:** `app.py:905–913` — the sections query counts pins by `section_id` match without scoping by `board_id` or `user_id`. Orphan pins (wrong board, same section_id) inflate counts.

**Files:**
- Modify: `app.py:905–913`

- [ ] **Step 1: Find the sections query in the board route**

In `def board` (~line 888), find:

```python
        # Get sections for this board with pin count
        cursor.execute("""
            SELECT s.*, 
                   COUNT(p.id) as pin_count
            FROM sections s
            LEFT JOIN pins p ON p.section_id = s.id
            WHERE s.board_id = %s
            GROUP BY s.id
            ORDER BY s.name
        """, (board_id,))
```

- [ ] **Step 2: Add board and user scoping to the JOIN**

Replace with:

```python
        # Get sections for this board with pin count
        cursor.execute("""
            SELECT s.*, 
                   COUNT(p.id) as pin_count
            FROM sections s
            LEFT JOIN pins p ON p.section_id = s.id
                             AND p.board_id = s.board_id
                             AND p.user_id = %s
            WHERE s.board_id = %s
            GROUP BY s.id
            ORDER BY s.name
        """, (user['id'], board_id))
```

- [ ] **Step 3: Manual verification**

Load a board — section pin counts should be accurate. No phantom counts from orphan pins.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Fix section pin-count query to scope joins by board_id and user_id"
```

---

### Task 5: Merge duplicate /api/board/<id>/pins routes

**Problem:** Two functions (`board_pins_api` at line 1276 and `get_board_pins` at line 2580) register the same URL. Flask only serves the first. The first handler throws `ValueError` on `section_id='undefined'`; the second (dead code) has correct handling. Solution: remove the first, enhance the second to add `has_more` and the cached_images safety check.

**Files:**
- Modify: `app.py:1276–1370` (delete), `app.py:2580–2660` (enhance)

- [ ] **Step 1: Delete board_pins_api (lines 1276–1370)**

Remove the entire function `board_pins_api` from `@app.route('/api/board/<int:board_id>/pins', methods=['GET'])` through its closing `finally` block. This is lines 1276–1370 inclusive.

After deletion, `get_board_pins` at the new (shifted) line becomes the sole handler.

- [ ] **Step 2: Enhance get_board_pins to add `has_more` and cached_images safety**

Find the `get_board_pins` function (now the only handler for `/api/board/<int:board_id>/pins`). Replace its query/return section:

Current return (end of function):
```python
        cursor.execute(query, tuple(params))
        pins = cursor.fetchall()
        
        return jsonify({
            'success': True,
            'pins': pins
        })
```

Replace with:

```python
        try:
            cursor.execute(query, tuple(params))
        except Exception as query_err:
            # Fallback: cached_images table may not exist — retry without that join
            print(f"Board pins query error, retrying without cached_images join: {query_err}")
            fallback_query = """
                SELECT p.*, s.name as section_name, b.name as board_name,
                       NULL as cached_filename, NULL as cache_status,
                       NULL as cached_width, NULL as cached_height
                FROM pins p
                LEFT JOIN sections s ON p.section_id = s.id
                LEFT JOIN boards b ON p.board_id = b.id
                WHERE p.board_id = %s AND p.user_id = %s
            """
            fallback_params = [board_id, user['id']]
            if section_id:
                if section_id == 'all':
                    pass
                elif section_id == 'undefined':
                    fallback_query += " AND p.section_id IS NULL"
                else:
                    try:
                        s_id = int(section_id)
                        fallback_query += " AND p.section_id = %s"
                        fallback_params.append(s_id)
                    except ValueError:
                        pass
            fallback_query += " ORDER BY p.created_at DESC, p.id ASC LIMIT %s OFFSET %s"
            fallback_params.extend([limit, offset])
            cursor.execute(fallback_query, tuple(fallback_params))

        pins = cursor.fetchall()

        return jsonify({
            'success': True,
            'pins': pins,
            'has_more': len(pins) == limit
        })
```

- [ ] **Step 3: Manual verification**

Load a board, scroll to trigger infinite scroll (loads more pins). Switch between sections — each should show only its pins. Check browser network tab: `/api/board/X/pins` returns `has_more` field.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Remove duplicate board pins API route; enhance get_board_pins with has_more and fallback"
```

---

### Task 6: Scope gallery Redis cache key by user_id

**Problem:** `app.py:70` — `cache_view` stores the rendered HTML under `view//` with no user discriminator. Multiple users share the same cached page, so User B can see User A's board list. All cache invalidation calls also use the un-scoped key.

**Files:**
- Modify: `app.py:60–85` (cache_view decorator), and all `redis_client.delete('view//')` calls

- [ ] **Step 1: Update cache_view to include user_id in the key**

Find `def cache_view` at line 60. Replace the entire function:

```python
def cache_view(timeout=300):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if os.getenv('FLASK_ENV') == 'development':
                return f(*args, **kwargs)
            if not redis_client:
                return f(*args, **kwargs)
            # Include user_id in key so each user has their own cached view
            token = request.cookies.get('session_token')
            user_id = 'anon'
            if token:
                try:
                    payload = verify_token(token, token_type='session')
                    if payload:
                        user_id = str(payload.get('user_id', 'anon'))
                except Exception:
                    pass
            qs = request.query_string.decode('utf-8')
            cache_key = f"view:{user_id}:{request.path}{'?' + qs if qs else ''}"
            cached_data = redis_client.get(cache_key)
            if cached_data:
                return cached_data
            response = f(*args, **kwargs)
            if isinstance(response, tuple):
                return response
            if hasattr(response, 'data'):
                redis_client.setex(cache_key, timeout, response.data.decode('utf-8'))
            elif isinstance(response, str):
                redis_client.setex(cache_key, timeout, response)
            return response
        return wrapper
    return decorator
```

- [ ] **Step 2: Update all gallery cache invalidation calls to use user-scoped key**

There are ~9 places that call `redis_client.delete('view//')`. Each one is inside a `@login_required` route where `user = get_current_user()` is available. Replace every `redis_client.delete('view//')` with:

```python
redis_client.delete(f"view:{user['id']}:/")
```

Locations (search with `grep -n "delete('view//')" app.py`):
- `gallery()` ~line 863
- `create_board()` ~line 1899
- `move_pin()` ~line 1972
- `move_board()` ~line 2242
- `delete_board()` ~line 2272
- `set_board_image()` lines ~2313–2314 (also has `'view:/'` — fix both to `f"view:{user['id']}:/"`)
- `set_section_image()` ~line 2372
- `delete_pin()` ~line 3216

Also fix `set_section_image`'s board-level invalidation at ~line 2373:
```python
# Before (broken key format):
redis_client.delete(f'view:/board/{section["board_id"]}')
# After (correct format, though board view isn't currently Redis-cached):
redis_client.delete(f"view:{user['id']}:/board/{section['board_id']}")
```

- [ ] **Step 3: Manual verification**

Log in as user A, load `/` — boards appear. Log in as user B in another browser, load `/` — should see user B's boards, not A's. Create a new board as user A, refresh — should appear immediately (cache invalidated for user A's key only).

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Scope gallery Redis cache key by user_id to fix cross-user cache leakage"
```

---

### Task 7: Pass active section filter through infinite scroll fetch

**Problem:** `templates/board.html:1237` — infinite scroll fetches the next page of pins without passing the active `section_id`. When a section is selected, the infinite scroll silently loads and immediately hides unrelated pins, and never loads more pins for the active section beyond what `fetchSectionPins` already loaded (capped at 200).

**Files:**
- Modify: `templates/board.html` ~line 1237

- [ ] **Step 1: Find the infinite scroll fetch**

In `board.html`, locate the `handleScroll` function and find:

```javascript
                    fetch(`/api/board/${boardId}/pins?offset=${currentOffset}&limit=40`)
```

- [ ] **Step 2: Thread section filter and reset offset when section changes**

Replace just that fetch URL:

```javascript
                    const sectionParam = (typeof activeSectionFilter !== 'undefined' && activeSectionFilter !== 'all')
                        ? `&section_id=${activeSectionFilter}`
                        : '';
                    fetch(`/api/board/${boardId}/pins?offset=${currentOffset}&limit=40${sectionParam}`)
```

- [ ] **Step 3: Reset currentOffset when section changes**

Find the section click handler in `initializeSectionFiltering` where `activeSectionFilter = selectedSection` is set (~line 2091). Add a reset of `currentOffset` right after:

```javascript
                activeSectionFilter = selectedSection;
                window.activeSectionFilter = selectedSection;
                currentOffset = 0; // Reset pagination when switching sections
```

- [ ] **Step 4: Manual verification**

Load a board with sections. Click a section. Scroll to the bottom — the infinite scroll should only load more pins from that section. Switch back to "All" and scroll — should load all pins.

- [ ] **Step 5: Commit**

```bash
git add templates/board.html
git commit -m "Pass active section filter through infinite scroll and reset offset on section change"
```

---

### Task 8: Fix null section_id rendered as 'all' on pin cards

**Problem:** `templates/board.html:138` and `board.html:1296` — pins with no section get `data-section-id="all"`, the same string used by the "All" button. This creates fragile coupling and prevents a future "Uncategorized" filter. Use an empty string for unassigned pins so they are only shown when filter is 'all' (first clause of shouldShow), never when a specific section is active.

**Files:**
- Modify: `templates/board.html` lines ~138, ~1296, ~2172–2174

- [ ] **Step 1: Fix server-rendered pin cards**

Find line ~138:
```jinja
            data-section-id="{{ pin.section_id or 'all' }}"
```

Replace with:
```jinja
            data-section-id="{{ pin.section_id or '' }}"
```

- [ ] **Step 2: Fix JS-created pin cards**

Find line ~1296:
```javascript
        div.setAttribute('data-section-id', pin.section_id || 'all');
```

Replace with:
```javascript
        div.setAttribute('data-section-id', pin.section_id != null ? String(pin.section_id) : '');
```

- [ ] **Step 3: Update applyCurrentSectionFilter to handle empty string**

Find the `shouldShow` logic at ~line 2172:

```javascript
            const shouldShow = activeSectionFilter === 'all' ||
                pinSectionId === activeSectionFilter ||
                String(pinSectionId) === String(activeSectionFilter);
```

Replace with:

```javascript
            const shouldShow = activeSectionFilter === 'all' ||
                (pinSectionId !== '' && String(pinSectionId) === String(activeSectionFilter));
```

This means:
- `activeSectionFilter === 'all'` → show everything (including unassigned pins with `pinSectionId === ''`)
- Otherwise, only show pins whose section_id exactly matches the selected section (unassigned pins are hidden)

- [ ] **Step 4: Manual verification**

Load a board with sections. Click "All" — see all pins including ones with no section. Click a specific section — unassigned pins should be hidden. The section badge counts (from the server query fixed in Task 4) should match what's displayed.

- [ ] **Step 5: Commit**

```bash
git add templates/board.html
git commit -m "Fix null section_id data attribute collision with 'all' filter sentinel"
```

---

### Task 9: Fix cache invalidation key format in set-board-image and set-section-image

**Problem:** `app.py:2314` uses `'view:/'` and `app.py:2373` uses `f'view:/board/{id}'`. These don't match any stored key. After Task 6, gallery keys are `view:{user_id}:/`. These two calls become correct for the user-scoped format if they're also updated to use `user['id']`.

Note: `/board/<id>` is NOT Redis-cached (no `@cache_view` decorator), so the board-level invalidation at line 2373 is a no-op. It can be left as-is or updated for future-proofing.

**Files:**
- Modify: `app.py` set-board-image (~line 2314), set-section-image (~line 2372–2373)

- [ ] **Step 1: Fix set-board-image stale key**

In `set_board_image`, find the block with multiple Redis deletes (~lines 2311–2319):

```python
        if redis_client:
            # Clear all possible cache keys for the gallery view
            redis_client.delete('view//')
            redis_client.delete('view:/')
            # Also clear any user-specific cache
            redis_client.delete(f'user:{user["id"]}:gallery')
            # Clear all keys matching view pattern
            for key in redis_client.scan_iter(match='view*'):
                redis_client.delete(key)
```

Replace with (after Task 6 has standardised the key format):

```python
        if redis_client:
            redis_client.delete(f"view:{user['id']}:/")
```

The `scan_iter` loop was a workaround for not knowing the key format — it's no longer needed now that the format is deterministic.

- [ ] **Step 2: Fix set-section-image stale key**

In `set_section_image`, find (~lines 2370–2374):

```python
            if redis_client:
                redis_client.delete(f'view:/board/{section["board_id"]}')
```

Replace with:

```python
            if redis_client:
                redis_client.delete(f"view:{user['id']}:/")
```

(The board view is not Redis-cached, so board-level key invalidation has no effect. Invalidate the gallery view instead since a section image change affects the gallery thumbnail.)

- [ ] **Step 3: Manual verification**

Set a board image via the UI. Hard refresh the home page — the new image should show. There should be no `scan_iter` loop hammering Redis keys on every board image update.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "Fix cache invalidation key format in set-board-image and set-section-image"
```

---

## Self-Review Checklist

- [x] Task 1 covers: add-pin board ownership + section/board check
- [x] Task 2 covers: move-board missing user_id
- [x] Task 3 covers: delete-board cross-user section deletion
- [x] Task 4 covers: section pin-count JOIN missing scope
- [x] Task 5 covers: duplicate route + dead code + has_more
- [x] Task 6 covers: user-scoped Redis cache key + all invalidation calls
- [x] Task 7 covers: infinite scroll ignoring active section
- [x] Task 8 covers: null section_id data attribute collision
- [x] Task 9 covers: broken cache invalidation key format (depends on Task 6)

**Execution order matters:** Task 9 depends on Task 6 (key format). All other tasks are independent of each other.
