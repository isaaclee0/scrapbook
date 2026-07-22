"""Per-session CSRF token issued via the session cookie itself.

The token is an HMAC of the session_token. It is exposed to templates via a
Flask context processor and must be sent back on destructive requests in the
`X-CSRF-Token` header (or `csrf_token` JSON field).
"""

import hmac
import hashlib
import os
from functools import wraps
from flask import request, jsonify

CSRF_SECRET = (os.getenv('JWT_SECRET_KEY', 'change-this-in-production')).encode()


def issue_csrf_token(session_token: str) -> str:
    if not session_token:
        return ''
    return hmac.new(CSRF_SECRET, session_token.encode(), hashlib.sha256).hexdigest()


def verify_csrf(session_token: str, presented: str) -> bool:
    if not session_token or not presented:
        return False
    expected = issue_csrf_token(session_token)
    return hmac.compare_digest(expected, presented)


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
