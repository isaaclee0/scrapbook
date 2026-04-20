"""Audit log helpers.

Designed to be called from inside a tx() block in app.py so that the audit row
is committed atomically with the underlying mutation.
"""

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


def _columns(cursor):
    return [c[0] for c in cursor.description] if cursor.description else []


def _row_to_dict(cursor, row):
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return dict(zip(_columns(cursor), row))


def _rows_to_dicts(cursor, rows):
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return list(rows)
    cols = _columns(cursor)
    return [dict(zip(cols, r)) for r in rows]


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
    """Insert one row into audit_log using the caller's cursor.

    Returns the inserted audit_log.id.
    """
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
    board = _row_to_dict(cursor, cursor.fetchone())
    if not board:
        return None

    cursor.execute("SELECT * FROM sections WHERE board_id = %s", (board_id,))
    sections = _rows_to_dicts(cursor, cursor.fetchall())

    cursor.execute("SELECT * FROM pins WHERE board_id = %s", (board_id,))
    pins = _rows_to_dicts(cursor, cursor.fetchall())

    return {"board": board, "sections": sections, "pins": pins}


def snapshot_pin(cursor, pin_id: int) -> Optional[dict]:
    cursor.execute("SELECT * FROM pins WHERE id = %s", (pin_id,))
    return _row_to_dict(cursor, cursor.fetchone())


def snapshot_section(cursor, section_id: int) -> Optional[dict]:
    cursor.execute("SELECT * FROM sections WHERE id = %s", (section_id,))
    section = _row_to_dict(cursor, cursor.fetchone())
    if not section:
        return None
    cursor.execute("SELECT * FROM pins WHERE section_id = %s", (section_id,))
    section['pins'] = _rows_to_dicts(cursor, cursor.fetchall())
    return section
