"""
Per-board pub/sub for live processing updates (image caching, color extraction,
URL health checks). Backs the /api/board-events/<id> SSE stream so clients get
push updates instead of polling /api/board-status.

Uses Redis pub/sub when available, falls back to an in-memory dispatcher
otherwise. Both expose the same publish() / subscribe() API. The in-memory
path only delivers across threads in a single process — fine for dev and
single-worker setups; multi-worker production should run Redis.
"""

import json
import queue
import threading
from collections import defaultdict

_redis = None
_mem_subscribers = defaultdict(set)
_mem_lock = threading.Lock()

# Yield interval used by subscribe() to interleave heartbeats and disconnect
# detection. The value is a poll timeout, not a delivery delay — events still
# arrive immediately when published.
_TICK_SECONDS = 1.0


def init(redis_client):
    """Wire a Redis client into the bus. Pass None (or skip the call) to use
    the in-memory dispatcher. Safe to call once at app startup."""
    global _redis
    _redis = redis_client


def _channel(board_id):
    return f"board:{board_id}"


def publish(board_id, event_type, payload=None):
    """Fan out an event to every subscriber of this board.

    payload kwargs are merged with {"type": event_type} into the JSON body the
    client sees. publish() never raises — Redis errors fall through to the
    in-memory path so a flaky cache doesn't break write requests."""
    body = {"type": event_type}
    if payload:
        body.update(payload)
    msg = json.dumps(body)

    if _redis is not None:
        try:
            _redis.publish(_channel(board_id), msg)
            return
        except Exception:
            pass  # fall through to in-memory below

    with _mem_lock:
        subs = list(_mem_subscribers.get(board_id, ()))
    for q in subs:
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass


def subscribe(board_id):
    """Generator yielding JSON event strings, or None on each tick.

    Callers use the None ticks to send SSE heartbeats and notice client
    disconnects (the next yield raises GeneratorExit, which our finally
    blocks turn into clean unsubscribes)."""
    if _redis is not None:
        ps = _redis.pubsub(ignore_subscribe_messages=True)
        ps.subscribe(_channel(board_id))
        try:
            while True:
                msg = ps.get_message(timeout=_TICK_SECONDS)
                if msg and msg.get('type') == 'message':
                    yield msg.get('data')
                else:
                    yield None
        finally:
            try:
                ps.unsubscribe()
                ps.close()
            except Exception:
                pass
    else:
        q = queue.Queue(maxsize=1000)
        with _mem_lock:
            _mem_subscribers[board_id].add(q)
        try:
            while True:
                try:
                    yield q.get(timeout=_TICK_SECONDS)
                except queue.Empty:
                    yield None
        finally:
            with _mem_lock:
                _mem_subscribers[board_id].discard(q)
