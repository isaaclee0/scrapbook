"""Session recovery through real Flask hooks, cookies, and JWT verification."""
import io
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from unittest.mock import MagicMock, patch

import jwt
import mysql.connector
import redis

# app.py connects and initializes indexes at import. Keep this suite independent
# of local/production services, including when run on its own.
with patch('mysql.connector.pooling.MySQLConnectionPool', side_effect=mysql.connector.Error('test isolation')), \
     patch('mysql.connector.connect', side_effect=mysql.connector.Error('test isolation')), \
     patch('redis.Redis.ping', side_effect=redis.ConnectionError('test isolation')), \
     redirect_stdout(io.StringIO()):
    import app as app_module

import auth_utils


SIGNING_KEY = 'synthetic-session-regression-signing-key'
OTHER_KEY = 'synthetic-session-regression-foreign-key'
SIGNATURE_ERROR = 'Invalid token: Signature verification failed'


class AuthSessionTests(unittest.TestCase):
    def setUp(self):
        for replacement in (
            patch.object(auth_utils, 'JWT_SECRET_KEY', SIGNING_KEY),
            patch.object(auth_utils, 'JWT_ALGORITHM', 'HS256'),
            patch.object(auth_utils, 'SESSION_EXPIRY', 2592000),
            patch.dict(os.environ, {'FLASK_ENV': 'production', 'SESSION_EXPIRY': '2592000'}),
            patch.dict(app_module.app.config, TESTING=True),
            patch.object(app_module, 'redis_client', None),
            patch.object(app_module, 'get_db_connection', side_effect=AssertionError('unexpected database access')),
            patch.object(app_module, 'send_otp_email', side_effect=AssertionError('email prohibited')),
            patch.object(app_module, 'send_welcome_email', side_effect=AssertionError('email prohibited')),
            patch('socket.socket.connect', side_effect=AssertionError('network prohibited')),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)
        self.client = app_module.app.test_client()

    def token(self, *, key=SIGNING_KEY, days=20, algorithm='HS256', token_type='session', user_id=7):
        now = datetime.now(timezone.utc)
        return jwt.encode({
            'user_id': user_id, 'email': 'owner@example.test', 'type': token_type,
            'iat': now - timedelta(minutes=1), 'exp': now + timedelta(days=days),
        }, key, algorithm=algorithm)

    def request(self, path, *, method='GET', **kwargs):
        log = io.StringIO()
        with redirect_stdout(log):
            response = self.client.open(path, method=method, base_url='https://localhost', **kwargs)
            response.get_data()
            response.close()
        return response, log.getvalue()

    def session_headers(self, response):
        result = []
        for header in response.headers.getlist('Set-Cookie'):
            cookie = SimpleCookie(header)
            if 'session_token' in cookie:
                result.append(cookie['session_token'])
        return result

    def assert_session_cleared(self, response):
        cookies = self.session_headers(response)
        self.assertEqual(len(cookies), 1)
        self.assertEqual(cookies[0].value, '')
        self.assertEqual(cookies[0]['max-age'], '0')
        self.assertEqual(cookies[0]['path'], '/')
        self.assertEqual(cookies[0]['domain'], '')
        self.assertIsNone(self.client.get_cookie('session_token'))

    def test_bad_signature_is_rejected_once_and_cookie_is_cleared(self):
        for path, status in [('/', 302), ('/api/boards', 401)]:
            with self.subTest(path=path):
                self.client.set_cookie('session_token', self.token(key=OTHER_KEY))
                response, log = self.request(path)
                self.assertEqual(response.status_code, status)
                self.assertEqual(log.count(SIGNATURE_ERROR), 1)
                self.assert_session_cleared(response)
                if status == 302:
                    self.assertEqual(response.location, '/auth/login')
                else:
                    self.assertEqual(response.json['error'], 'Authentication required')
                again, log = self.request(path)
                self.assertEqual(again.status_code, status)
                self.assertEqual(log, '')

    def test_all_invalid_cookie_kinds_remain_rejected(self):
        signed = self.token()
        parts = signed.split('.')
        parts[2] = ('A' if parts[2][0] != 'A' else 'B') + parts[2][1:]
        cases = [
            ('tampered', '.'.join(parts), SIGNATURE_ERROR),
            ('expired', self.token(days=-1), 'Token has expired'),
            ('expired foreign key', self.token(key=OTHER_KEY, days=-1), SIGNATURE_ERROR),
            ('algorithm', self.token(algorithm='HS512'), 'Invalid token: The specified alg value is not allowed'),
            ('wrong type', self.token(token_type='magic_link'), ''),
            ('malformed', 'sp_pat_synthetic', 'Invalid token: Not enough segments'),
        ]
        for label, token, expected_log in cases:
            with self.subTest(kind=label):
                self.client.set_cookie('session_token', token)
                response, log = self.request('/api/boards')
                self.assertEqual(response.status_code, 401)
                self.assertEqual(log.strip(), expected_log)
                self.assert_session_cleared(response)

    def test_login_handoff_script_is_public_without_exposing_other_assets(self):
        for cookie in [None, self.token(key=OTHER_KEY)]:
            with self.subTest(has_cookie=cookie is not None):
                if cookie:
                    self.client.set_cookie('session_token', cookie)
                login, _ = self.request('/auth/login')
                self.assertEqual(login.status_code, 200)
                self.assertIn('/static/js/extension_handoff.js', login.get_data(as_text=True))
                script, log = self.request('/static/js/extension_handoff.js')
                self.assertEqual(script.status_code, 200)
                self.assertIn('javascript', script.mimetype)
                self.assertEqual(log, '')
                for path in ['/cached/private.png', '/static/images/default_pin.png', '/static/js/masonry.js']:
                    protected, _ = self.request(path)
                    self.assertEqual(protected.status_code, 302)
                    self.assertEqual(protected.location, '/auth/login')

    def test_cache_hit_and_refresh_share_one_signature_verification(self):
        self.client.set_cookie('session_token', self.token(days=1))
        cache = MagicMock()
        cache.get.return_value = '<p>cached for user 7</p>'
        with patch.object(app_module, 'redis_client', cache), \
             patch.object(auth_utils.jwt, 'decode', wraps=jwt.decode) as decode:
            response, log = self.request('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), '<p>cached for user 7</p>')
        self.assertEqual(decode.call_count, 1)
        self.assertEqual(log, '')
        cookies = self.session_headers(response)
        self.assertEqual(len(cookies), 1)
        payload = jwt.decode(cookies[0].value, SIGNING_KEY, algorithms=['HS256'])
        self.assertEqual(payload['user_id'], 7)
        self.assertEqual(payload['exp'] - payload['iat'], 2592000)
        self.assertEqual(cookies[0]['max-age'], '2592000')
        self.assertTrue(cookies[0]['secure'])
        self.assertTrue(cookies[0]['httponly'])
        self.assertEqual(cookies[0]['samesite'], 'Lax')
        self.assertEqual(cookies[0]['path'], '/')
        self.assertEqual(cookies[0]['domain'], '')

    def test_session_outside_refresh_window_is_not_reissued(self):
        self.client.set_cookie('session_token', self.token())
        response, log = self.request('/static/js/masonry.js')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.session_headers(response), [])
        self.assertEqual(log, '')

    def test_logout_clears_missing_invalid_and_near_expiry_sessions(self):
        for cookie in [None, self.token(key=OTHER_KEY), self.token(days=1)]:
            with self.subTest(has_cookie=cookie is not None):
                if cookie:
                    self.client.set_cookie('session_token', cookie)
                response, _ = self.request('/auth/logout')
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.location, '/auth/login')
                self.assert_session_cleared(response)
                protected, _ = self.request('/static/js/masonry.js')
                self.assertEqual(protected.status_code, 302)

    def test_otp_success_replaces_stale_cookie_and_preserves_new_session(self):
        self.client.set_cookie('session_token', self.token(key=OTHER_KEY))
        db = MagicMock()
        db.cursor.return_value.fetchone.return_value = {'id': 7, 'email': 'owner@example.test'}
        otp_store = MagicMock()
        otp_store.get.return_value = '654321'
        with patch.object(app_module, 'get_db_connection', return_value=db), \
             patch.object(app_module, 'redis_client', otp_store):
            response, _ = self.request('/auth/login', method='POST', json={
                'email': 'owner@example.test', 'action': 'verify', 'otp': '654321',
            })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])
        cookies = self.session_headers(response)
        self.assertEqual(len(cookies), 1)
        payload = jwt.decode(cookies[0].value, SIGNING_KEY, algorithms=['HS256'])
        self.assertEqual(payload['user_id'], 7)
        protected, log = self.request('/static/js/masonry.js')
        self.assertEqual(protected.status_code, 200)
        self.assertEqual(log, '')

    def bearer_database(self, accepted):
        """Exercise the real PAT digest lookup; fake only the database boundary."""
        db = MagicMock()
        expected_hash = auth_utils.hash_api_token('sp_pat_synthetic')
        def execute(query, params=()):
            if 'FROM api_tokens' in query:
                self.assertEqual(params, (expected_hash,))
                db.cursor.return_value.fetchone.return_value = (
                    {'id': 8, 'email': 'api@example.test', 'token_id': 3} if accepted else None
                )
        db.cursor.return_value.execute.side_effect = execute
        return db

    def test_valid_bearer_survives_bad_cookie_and_clears_it(self):
        self.client.set_cookie('session_token', self.token(key=OTHER_KEY))
        with patch.object(app_module, 'get_db_connection', return_value=self.bearer_database(True)):
            response, log = self.request('/static/js/masonry.js', headers={'Authorization': 'Bearer sp_pat_synthetic'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(log.count(SIGNATURE_ERROR), 1)
        self.assert_session_cleared(response)

    def test_rejected_bearer_does_not_fall_back_to_valid_cookie(self):
        self.client.set_cookie('session_token', self.token())
        with patch.object(app_module, 'get_db_connection', return_value=self.bearer_database(False)):
            response, _ = self.request('/static/js/masonry.js', headers={'Authorization': 'Bearer sp_pat_synthetic'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json['error'], 'Authentication required')

    def test_bearer_cache_uses_authenticated_user_not_another_sessions_cookie(self):
        cache_values = {'view:7:/': '<p>private session data</p>', 'view:8:/': '<p>API user data</p>'}
        cache = MagicMock()
        cache.get.side_effect = cache_values.get
        for cookie in [None, self.token(user_id=7)]:
            with self.subTest(has_cookie=cookie is not None):
                if cookie:
                    self.client.set_cookie('session_token', cookie)
                with patch.object(app_module, 'get_db_connection', return_value=self.bearer_database(True)), \
                     patch.object(app_module, 'redis_client', cache):
                    response, _ = self.request('/', headers={'Authorization': 'Bearer sp_pat_synthetic'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_data(as_text=True), '<p>API user data</p>')

    def test_standalone_refresh_still_rejects_invalid_tokens(self):
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(auth_utils.refresh_session_token(self.token(key=OTHER_KEY)))
            self.assertIsNone(auth_utils.refresh_session_token(self.token(days=-1)))
        current = self.token()
        self.assertEqual(auth_utils.refresh_session_token(current), current)
        refreshed = auth_utils.refresh_session_token(self.token(days=1))
        payload = jwt.decode(refreshed, SIGNING_KEY, algorithms=['HS256'])
        self.assertEqual(payload['exp'] - payload['iat'], 2592000)


if __name__ == '__main__':
    unittest.main()
