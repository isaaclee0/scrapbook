import io
import base64
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse, unquote

from PIL import Image

import app as app_module
from audit_helpers import snapshot_pin, snapshot_board
from csrf import issue_csrf_token
from pin_gallery import list_images, mutate_gallery
from tests.gallery_db import SqliteCursor


class GalleryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            PRAGMA foreign_keys = ON;
            CREATE TABLE boards (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT,
                default_image_url TEXT, created_at TEXT);
            CREATE TABLE sections (id INTEGER PRIMARY KEY, user_id INTEGER, board_id INTEGER,
                name TEXT, default_image_url TEXT, created_at TEXT);
            CREATE TABLE pins (id INTEGER PRIMARY KEY, user_id INTEGER, board_id INTEGER,
                section_id INTEGER, title TEXT, description TEXT, notes TEXT, link TEXT,
                created_at TEXT, image_url TEXT NOT NULL, cached_image_id INTEGER,
                uses_cached_image INTEGER DEFAULT 0, images_initialized INTEGER DEFAULT 0,
                dominant_color TEXT, palette_color_1 TEXT, palette_color_2 TEXT,
                palette_color_3 TEXT, palette_color_4 TEXT, palette_color_5 TEXT);
            CREATE TABLE cached_images (id INTEGER PRIMARY KEY, cached_filename TEXT,
                width INTEGER, height INTEGER, cache_status TEXT, original_url TEXT,
                quality_level TEXT, file_size INTEGER, updated_at TEXT);
            CREATE TABLE pin_images (id INTEGER PRIMARY KEY AUTOINCREMENT,
                pin_id INTEGER NOT NULL REFERENCES pins(id) ON DELETE CASCADE,
                image_url TEXT NOT NULL, preview_url TEXT, width INTEGER, height INTEGER,
                cached_image_id INTEGER, uses_cached_image INTEGER DEFAULT 0,
                position INTEGER NOT NULL, UNIQUE(pin_id, position));
            CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                action TEXT, entity_type TEXT, entity_id INTEGER, actor_email TEXT,
                before_data TEXT, after_data TEXT, metadata TEXT, request_id TEXT,
                ip_address TEXT, outcome TEXT);
            CREATE TABLE url_health (pin_id INTEGER, status TEXT, archive_url TEXT);
            INSERT INTO boards VALUES (9, 7, 'Recipes', NULL, '2026-10-13');
            INSERT INTO sections VALUES (3, 7, 9, 'Cakes', NULL, '2026-10-13');
            INSERT INTO pins (id,user_id,board_id,section_id,title,image_url)
                VALUES (42,7,9,3,'Cake','https://example.test/cake.png');
            INSERT INTO pins (id,user_id,board_id,title,image_url)
                VALUES (43,8,9,'Private','https://example.test/private.png');
        ''')
        self.client = app_module.app.test_client()
        self.client.set_cookie('session_token', 'gallery-test')
        self.headers = {'X-CSRF-Token': issue_csrf_token('gallery-test')}
        self.temp = tempfile.TemporaryDirectory()
        self.events = []
        self.addCleanup(self.temp.cleanup)

        @contextmanager
        def transaction(dictionary=False, isolation_level=None):
            cursor = SqliteCursor(self.db, dictionary)
            try:
                yield self.db, cursor
                self.db.commit()
                self.events.append('commit')
            except Exception:
                self.db.rollback()
                raise

        outer = self
        class Connection:
            def cursor(self, dictionary=False, **kwargs):
                return SqliteCursor(outer.db, dictionary)
            def close(self):
                pass
            def commit(self):
                outer.db.commit()

        for mock in (
            patch.object(app_module, 'get_current_user', return_value={'id': 7, 'email': 'owner@example.test'}),
            patch.object(app_module, 'tx', transaction),
            patch.object(app_module, 'get_db_connection', return_value=Connection()),
            patch.object(app_module.app, 'root_path', self.temp.name),
            patch.object(app_module, 'redis_client', None),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def upload(self, pin_id=42, replace_id=None):
        data = io.BytesIO()
        Image.new('RGB', (600, 2400), 'white').save(data, 'PNG')
        data.seek(0)
        fields = {'file': (data, 'recipe.png')}
        if replace_id is not None:
            fields['replace_id'] = str(replace_id)
        return self.client.post(f'/api/pin/{pin_id}/images', data=fields, headers=self.headers)

    def test_upload_cover_card_and_delete_undo_keep_entire_gallery(self):
        uploaded = self.upload()
        self.assertEqual(uploaded.status_code, 200, uploaded.json)
        ids = [image['id'] for image in uploaded.json['images']]
        self.assertEqual(len(ids), 2)
        made_cover = self.client.post('/api/pin/42/images/manage', headers=self.headers,
                                     json={'action': 'cover', 'image_id': ids[1]})
        self.assertEqual(made_cover.status_code, 200, made_cover.json)
        card = self.client.get('/api/pin/42/card')
        self.assertEqual(card.status_code, 200, card.json)
        self.assertEqual(card.json['pin']['image_count'], 2)
        self.assertEqual((card.json['pin']['cached_width'], card.json['pin']['cached_height']), (600, 2400))
        cursor = SqliteCursor(self.db)
        before = snapshot_pin(cursor, 42)
        self.db.execute('DELETE FROM pins WHERE id=42')
        app_module._undo_pin_delete(cursor, 7, before)
        restored = list_images(cursor, {'id': 42})
        self.assertEqual([image['id'] for image in restored], [ids[1], ids[0]])
        self.assertEqual(restored[0]['image_url'], made_cover.json['images'][0]['image_url'])

    def test_board_delete_undo_restores_gallery_ids_and_order(self):
        uploaded = self.upload().json['images']
        cursor = SqliteCursor(self.db)
        before = snapshot_board(cursor, 9)
        # In the real route board scope is user-owned; remove unrelated fixture pin.
        before['pins'] = [pin for pin in before['pins'] if pin['user_id'] == 7]
        self.db.execute('DELETE FROM pins WHERE id=42')
        self.db.execute('DELETE FROM sections WHERE id=3')
        self.db.execute('DELETE FROM boards WHERE id=9')
        app_module._undo_board_delete(cursor, 7, before)
        self.assertEqual(list_images(cursor, {'id': 42}), uploaded)

    def test_legacy_cover_replacement_preserves_secondary_image(self):
        uploaded = self.upload().json['images']
        response = self.client.post('/update-pin/42', headers=self.headers,
                                    json={'image_url': 'https://example.test/new-cake.png'})
        self.assertEqual(response.status_code, 200, response.json)
        images = self.client.get('/api/pin/42/images').json['images']
        self.assertEqual([image['id'] for image in images], [image['id'] for image in uploaded])
        self.assertEqual(images[0]['image_url'], 'https://example.test/new-cake.png')
        self.assertEqual(images[1]['image_url'], uploaded[1]['image_url'])

    def test_foreign_pin_upload_and_foreign_image_management_fail(self):
        uploaded = self.upload().json['images']
        self.assertEqual(self.upload(pin_id=43).status_code, 404)
        response = self.client.post('/api/pin/43/images/manage', headers=self.headers,
                                    json={'action': 'cover', 'image_id': uploaded[0]['id']})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get('/api/pin/43/images').status_code, 404)

    def test_legacy_data_url_replaces_cover_and_clears_stale_cache(self):
        images = self.upload().json['images']
        self.db.execute("UPDATE pins SET cached_image_id=84, uses_cached_image=1 WHERE id=42")
        self.db.execute("UPDATE pin_images SET cached_image_id=84, uses_cached_image=1 WHERE id=?", (images[0]['id'],))
        self.db.commit()
        data = io.BytesIO()
        Image.new('RGB', (700, 1000), 'red').save(data, 'PNG')
        response = self.client.post('/update-pin/42', headers=self.headers,
            json={'image_url': 'data:image/png;base64,' + base64.b64encode(data.getvalue()).decode()})
        self.assertEqual(response.status_code, 200, response.json)
        updated = self.client.get('/api/pin/42/images').json['images']
        self.assertEqual([image['id'] for image in updated], [image['id'] for image in images])
        self.assertEqual((updated[0]['width'], updated[0]['height']), (700, 1000))
        self.assertTrue(updated[0]['image_url'].startswith('/cached/gallery/'))
        self.assertEqual(self.db.execute('SELECT cached_image_id, uses_cached_image FROM pins WHERE id=42').fetchone(), (None, 0))

    def test_legacy_default_removes_cover_then_preserves_empty_placeholder(self):
        images = self.upload().json['images']
        for count in (1, 0):
            response = self.client.post('/update-pin/42', headers=self.headers,
                json={'image_url': '/static/images/default_pin.png'})
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(self.client.get('/api/pin/42/images').json['image_count'], count)
        self.assertEqual(self.db.execute('SELECT image_url FROM pins WHERE id=42').fetchone()[0], '/static/images/default_pin.png')

    def test_invalid_upload_does_not_replace_saved_image(self):
        images = self.upload().json['images']
        response = self.client.post('/api/pin/42/images', headers=self.headers,
            data={'file': (io.BytesIO(b'<script>invalid</script>'), 'recipe.png'), 'replace_id': str(images[0]['id'])})
        self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual(self.client.get('/api/pin/42/images').json['images'], images)

    def test_stale_browser_metadata_cannot_overwrite_new_cover(self):
        images = self.upload().json['images']
        self.client.post('/api/pin/42/images/manage', headers=self.headers,
                         json={'action': 'cover', 'image_id': images[1]['id']})
        stale = {'image_url': images[0]['image_url'], 'width': 100, 'height': 100,
                 'dominant_color_1': '#111111', 'dominant_color_2': '#222222'}
        for endpoint in ('save-pin-dimensions', 'save-pin-colors'):
            response = self.client.post(f'/{endpoint}/42', json=stale)
            self.assertEqual(response.status_code, 409, response.json)
        current = self.client.post('/save-pin-dimensions/42', json={
            'image_url': images[1]['image_url'], 'width': 100, 'height': 100})
        self.assertEqual(current.status_code, 200, current.json)
        self.assertEqual(self.db.execute('SELECT cached_image_id FROM pins WHERE id=42').fetchone(), (None,))
        self.assertEqual(self.db.execute('SELECT width,height FROM pin_images WHERE id=?', (images[1]['id'],)).fetchone(), (600,2400))

    def test_image_view_cache_is_invalidated_after_commit(self):
        outer = self
        class Cache:
            def scan_iter(self, **kwargs):
                outer.events.append('invalidate')
                return ['view:7:/']
            def delete(self, key):
                pass
        with patch.object(app_module, 'redis_client', Cache()):
            response = self.upload()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.events, ['commit', 'invalidate'])

    def test_immediate_dimensions_keep_gallery_cache_and_cover_colours(self):
        for existing_cache in (False, True):
            with self.subTest(existing_cache=existing_cache):
                self.db.execute('DELETE FROM pin_images WHERE pin_id=42')
                self.db.execute('DELETE FROM cached_images')
                self.db.execute('''UPDATE pins SET images_initialized=0,
                    cached_image_id=NULL, uses_cached_image=0,
                    dominant_color='#123456', palette_color_1='#654321' WHERE id=42''')
                images = list_images(SqliteCursor(self.db), {'id': 42})
                if existing_cache:
                    self.db.execute('''INSERT INTO cached_images
                        (id, original_url, width, height, quality_level, cache_status)
                        VALUES (9, 'https://example.test/cake.png', 800, 1200, 'low', 'pending')''')
                self.db.commit()
                with patch.object(app_module, 'calculate_image_dimensions', return_value=(400, 600)):
                    self.assertTrue(app_module.update_pin_dimensions(42, 'https://example.test/cake.png'))
                cached_id = self.db.execute('SELECT cached_image_id FROM pins WHERE id=42').fetchone()[0]
                expected_dimensions = (800, 1200) if existing_cache else (400, 600)
                self.assertEqual(self.db.execute('''SELECT cached_image_id, width, height
                    FROM pin_images WHERE id=?''', (images[0]['id'],)).fetchone(),
                    (cached_id, 0, 0))
                current = list_images(SqliteCursor(self.db), {'id': 42})[0]
                self.assertEqual((current['width'], current['height']), expected_dimensions)
                # Background decoding replaces immediate estimates; gallery
                # dimensions must still reflect the now-authoritative cache.
                self.db.execute('UPDATE cached_images SET width=1000,height=1600 WHERE id=?', (cached_id,))
                current = list_images(SqliteCursor(self.db), {'id': 42})[0]
                self.assertEqual((current['width'], current['height']), (1000,1600))
                response = self.upload()
                self.assertEqual(response.status_code, 200, response.json)
                self.assertEqual(self.db.execute('''SELECT cached_image_id, dominant_color,
                    palette_color_1 FROM pins WHERE id=42''').fetchone(),
                    (cached_id, '#123456', '#654321'))

    def test_immediate_dimensions_ignore_old_cover_and_preserve_known_dimensions(self):
        images = list_images(SqliteCursor(self.db), {'id': 42})
        self.db.execute('UPDATE pin_images SET width=900, height=1600 WHERE id=?', (images[0]['id'],))
        self.db.commit()
        with patch.object(app_module, 'calculate_image_dimensions', return_value=(400, 600)):
            self.assertFalse(app_module.update_pin_dimensions(42, 'https://example.test/old.png'))
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM cached_images').fetchone()[0], 0)
            self.assertTrue(app_module.update_pin_dimensions(42, 'https://example.test/cake.png'))
        self.assertEqual(self.db.execute('SELECT width,height FROM pin_images WHERE id=?',
            (images[0]['id'],)).fetchone(), (900,1600))

    def test_google_image_search_signs_selected_image_and_rejects_other_ids(self):
        images = self.upload().json['images']
        image_id = images[1]['id']
        response = self.client.get(f'/api/pin/42/google-lens-url?image={image_id}')
        self.assertEqual(response.status_code, 200, response.json)
        public = parse_qs(urlparse(response.json['google_search_url']).query)['url'][0]
        token = urlparse(public).path.rsplit('/', 1)[1]
        payload = app_module._temp_image_link_serializer().loads(token)
        self.assertEqual(payload['image_id'], image_id)
        with patch.object(app_module, '_serve_image_url', return_value='selected') as serve:
            self.assertEqual(self.client.get(urlparse(public).path).data, b'selected')
            serve.assert_called_once_with(images[1]['image_url'])
        self.assertEqual(self.client.get('/api/pin/42/google-lens-url?image=999').status_code, 404)


if __name__ == '__main__':
    unittest.main()
