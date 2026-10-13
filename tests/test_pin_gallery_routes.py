import unittest
from contextlib import contextmanager
from unittest.mock import patch

import app as app_module
from csrf import issue_csrf_token


class RouteCursor:
    def __init__(self, pin):
        self.pin = pin
        self.queries = []

    def execute(self, query, params=()):
        self.queries.append((query, params))

    def fetchone(self):
        return self.pin


class GalleryRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.client.set_cookie('session_token', 'gallery-test')
        self.headers = {'X-CSRF-Token': issue_csrf_token('gallery-test')}
        self.cursor = RouteCursor({'id': 42, 'user_id': 7, 'image_url': '/cached/cake.png'})
        user_patch = patch.object(app_module, 'get_current_user', return_value={'id': 7, 'email': 'owner@example.test'})
        user_patch.start()
        self.addCleanup(user_patch.stop)

        @contextmanager
        def transaction(**kwargs):
            yield None, self.cursor

        tx_patch = patch.object(app_module, 'tx', transaction)
        tx_patch.start()
        self.addCleanup(tx_patch.stop)

    def test_gallery_returns_ordered_images_for_owned_pin(self):
        # The route serializes the real service contract; persistence is covered separately.
        images = [{'id': 10, 'image_url': '/cached/cake.png', 'position': 0},
                  {'id': 11, 'image_url': '/cached/recipe.png', 'position': 1}]
        with patch.object(app_module, 'gallery_list_images', return_value=images, create=True), \
             patch.object(app_module, 'gallery_ensure_pin_images', create=True):
            response = self.client.get('/api/pin/42/images')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'success': True, 'images': images, 'image_count': 2})
        self.assertIn('user_id = %s', self.cursor.queries[0][0])
        self.assertEqual(self.cursor.queries[0][1], (42, 7))

    def test_missing_or_other_users_pin_is_not_disclosed(self):
        self.cursor.pin = None
        response = self.client.get('/api/pin/42/images')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json['error'], 'Pin not found')

    def test_mutation_requires_csrf(self):
        response = self.client.post('/api/pin/42/images/manage', json={'action': 'remove', 'image_id': 10})
        self.assertEqual(response.status_code, 403)

    def test_management_rejects_unknown_action(self):
        response = self.client.post('/api/pin/42/images/manage', headers=self.headers,
                                    json={'action': 'delete-everything'})
        self.assertEqual(response.status_code, 400)

    def test_upload_requires_a_file(self):
        response = self.client.post('/api/pin/42/images', headers=self.headers)
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
