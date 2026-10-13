import json
import sqlite3
import unittest
import hashlib
import io
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from tests.gallery_db import SqliteCursor
from scripts import cache_cleanup, image_cache_service
import pin_gallery

from image_retention import retained_cache_filenames


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('''
            CREATE TABLE pins (image_url TEXT, cached_image_id INTEGER);
            CREATE TABLE pin_images (image_url TEXT, preview_url TEXT, cached_image_id INTEGER);
            CREATE TABLE cached_images (id INTEGER, cached_filename TEXT);
            CREATE TABLE boards (default_image_url TEXT);
            CREATE TABLE sections (default_image_url TEXT);
            CREATE TABLE audit_log (before_data TEXT, after_data TEXT);
        ''')
        self.addCleanup(self.db.close)

    def test_originals_and_gallery_cache_references_survive_cleanup(self):
        self.db.execute("INSERT INTO pins VALUES ('/cached/old_pasted.png', NULL)")
        self.db.execute("INSERT INTO cached_images VALUES (3, 'remote_low.webp')")
        self.db.execute("INSERT INTO pin_images VALUES ('https://example.test/cake.jpg', NULL, 3)")
        self.db.execute("INSERT INTO pin_images VALUES ('/cached/gallery/recipe.png', '/cached/gallery/preview.webp', NULL)")
        self.assertEqual(retained_cache_filenames(self.db.cursor()), {
            'old_pasted.png', 'remote_low.webp', 'gallery/recipe.png', 'gallery/preview.webp',
        })

    def test_board_section_and_deleted_pin_undo_files_are_retained(self):
        self.db.execute("INSERT INTO boards VALUES ('/cached/board.webp')")
        self.db.execute("INSERT INTO sections VALUES ('/cached/section.webp')")
        self.db.execute("INSERT INTO cached_images VALUES (9, 'deleted_cache.webp')")
        snapshot = {'pins': [{'image_url': '/cached/deleted.png', 'images': [
            {'image_url': 'https://example.test/recipe.jpg', 'cached_image_id': 9},
            {'image_url': '/cached/gallery/removed.png', 'preview_url': '/cached/gallery/removed_preview.webp'},
        ]}]}
        self.db.execute('INSERT INTO audit_log VALUES (?, ?)', (json.dumps(snapshot), '{invalid'))
        self.assertEqual(retained_cache_filenames(self.db.cursor()), {
            'board.webp', 'section.webp', 'deleted.png', 'deleted_cache.webp',
            'gallery/removed.png', 'gallery/removed_preview.webp',
        })

    def test_unreferenced_remote_cache_is_not_retained(self):
        self.db.execute("INSERT INTO cached_images VALUES (1, 'unused_low.webp')")
        self.assertEqual(retained_cache_filenames(self.db.cursor()), set())


class CacheCursor(SqliteCursor):
    def execute(self, query, params=()):
        query = re.sub(r'DATE_SUB\(NOW\(\), INTERVAL %s DAY\)', "datetime('now', '-' || %s || ' days')", query)
        query = query.replace('NOW()', 'CURRENT_TIMESTAMP')
        query = query.replace('ON DUPLICATE KEY UPDATE', 'ON CONFLICT(original_url, quality_level) DO UPDATE SET')
        query = re.sub(r'VALUES\((\w+)\)', r'excluded.\1', query)
        super().execute(query, params)


class CacheConnection:
    def __init__(self, db):
        self.db = db

    def cursor(self, dictionary=False):
        return CacheCursor(self.db, dictionary)

    def start_transaction(self):
        self.db.commit()
        self.db.execute('BEGIN')

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def close(self):
        pass


class CacheMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE pins (id INTEGER PRIMARY KEY, image_url TEXT, cached_image_id INTEGER,
                uses_cached_image INTEGER DEFAULT 0, dominant_color TEXT, palette_color_1 TEXT,
                palette_color_2 TEXT, palette_color_3 TEXT, palette_color_4 TEXT, palette_color_5 TEXT,
                images_initialized INTEGER DEFAULT 0, board_id INTEGER DEFAULT 9);
            CREATE TABLE pin_images (id INTEGER PRIMARY KEY, pin_id INTEGER, image_url TEXT,
                preview_url TEXT, width INTEGER, height INTEGER, cached_image_id INTEGER,
                uses_cached_image INTEGER DEFAULT 0, position INTEGER DEFAULT 0,
                UNIQUE(pin_id, position));
            CREATE TABLE cached_images (id INTEGER PRIMARY KEY, original_url TEXT,
                cached_filename TEXT, file_size INTEGER, width INTEGER, height INTEGER,
                quality_level TEXT DEFAULT 'low', cache_status TEXT DEFAULT 'cached',
                updated_at TEXT, last_accessed TEXT DEFAULT '2000-01-01',
                retry_count INTEGER DEFAULT 0, last_retry_at TEXT,
                UNIQUE(original_url, quality_level));
            CREATE TABLE boards (default_image_url TEXT);
            CREATE TABLE sections (default_image_url TEXT);
            CREATE TABLE audit_log (before_data TEXT, after_data TEXT);
        ''')
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.connection = CacheConnection(self.db)
        with patch.object(image_cache_service.ImageCacheService, '_check_ffmpeg_available', return_value=False):
            self.service = image_cache_service.ImageCacheService(cache_dir=str(self.root))
        self.addCleanup(self.service.session.close)
        self.stats = {key: 0 for key in ('recover_count', 'recover_old_bytes', 'recover_new_bytes',
            'purge_legacy_count', 'purge_legacy_bytes', 'reprocess_count', 'reprocess_old_bytes',
            'reprocess_new_bytes', 'purge_orphan_count', 'purge_orphan_bytes', 'errors')}

    def image(self, name, size=(1200, 1800)):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', size, 'red').save(target, 'PNG')
        return target

    def cache(self, cache_id, name, url=None):
        self.db.execute('INSERT INTO cached_images (id, original_url, cached_filename, width, height) VALUES (?, ?, ?, 1200, 1800)',
            (cache_id, url or 'https://example.test/' + name, name))

    def test_expiry_preserves_gallery_upload_cover_and_undo_references(self):
        references = ['gallery/original.png', 'pasted.png', 'remote_low.webp', 'board.webp', 'section.webp', 'undo.webp']
        for index, name in enumerate(references + ['unused.webp'], 1):
            self.image(name)
            self.cache(index, name)
        self.db.execute("INSERT INTO pins (id, image_url) VALUES (1, '/cached/pasted.png')")
        self.db.execute("INSERT INTO pin_images (id, pin_id, image_url, cached_image_id) VALUES (1, 1, 'https://example.test/recipe', 3)")
        self.db.execute("INSERT INTO boards VALUES ('/cached/board.webp')")
        self.db.execute("INSERT INTO sections VALUES ('/cached/section.webp')")
        self.db.execute('INSERT INTO audit_log VALUES (?, NULL)', (json.dumps({'image_url': '/cached/undo.webp'}),))
        with patch.object(image_cache_service, 'get_db_connection', return_value=self.connection):
            self.service.cleanup_old_cache()
        self.assertTrue(all((self.root / name).exists() for name in references))
        self.assertFalse((self.root / 'unused.webp').exists())
        self.assertEqual(self.db.execute('SELECT cache_status FROM cached_images WHERE id=7').fetchone()[0], 'expired')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM cached_images WHERE cache_status="cached"').fetchone()[0], 6)

    def test_legacy_purge_keeps_referenced_files_but_removes_unused_files(self):
        kept = 'a' * 32 + '.png'
        unused = 'b' * 32 + '.png'
        self.image(kept)
        self.image(unused)
        self.db.execute('INSERT INTO pins (id, image_url) VALUES (1, ?)', ('/cached/' + kept,))
        with patch.object(cache_cleanup, 'CACHE_DIR', str(self.root)):
            cache_cleanup.purge_legacy(True, set(), self.stats, retained_cache_filenames(self.db.cursor()))
        self.assertTrue((self.root / kept).exists())
        self.assertFalse((self.root / unused).exists())

    def test_legacy_recovery_never_resizes_or_removes_referenced_source(self):
        url = 'https://example.test/cake.png'
        stem = hashlib.md5(url.encode()).hexdigest()
        source = self.image(stem + '.png')
        original = source.read_bytes()
        self.db.execute('INSERT INTO pins (id, image_url) VALUES (1, ?)', (url,))
        self.db.execute('INSERT INTO pin_images (id, pin_id, image_url) VALUES (1, 1, ?)', ('/cached/' + source.name,))
        with patch.object(cache_cleanup, 'CACHE_DIR', str(self.root)):
            cache_cleanup.recover_legacy(CacheCursor(self.db), self.service, True, self.stats)
        self.assertTrue(source.exists())
        self.assertEqual(source.read_bytes(), original)

    def test_legacy_recovery_does_not_overwrite_a_referenced_destination(self):
        url = 'https://example.test/cake.png'
        stem = hashlib.md5(url.encode()).hexdigest()
        source = self.image(stem + '.png')
        destination = self.image(stem[:16] + '_low.webp', (1800, 2400))
        original = destination.read_bytes()
        self.db.execute('INSERT INTO pins (id, image_url) VALUES (1, ?)', (url,))
        self.db.execute('INSERT INTO boards VALUES (?)', ('/cached/' + destination.name,))
        with patch.object(cache_cleanup, 'CACHE_DIR', str(self.root)):
            cache_cleanup.recover_legacy(CacheCursor(self.db), self.service, True, self.stats)
        self.assertTrue(source.exists())
        self.assertEqual(destination.read_bytes(), original)

    def test_unreferenced_legacy_recovery_still_creates_a_working_cache(self):
        url = 'https://example.test/cake.png'
        stem = hashlib.md5(url.encode()).hexdigest()
        source = self.image(stem + '.png')
        self.db.execute('INSERT INTO pins (id, image_url) VALUES (1, ?)', (url,))
        with patch.object(cache_cleanup, 'CACHE_DIR', str(self.root)):
            cache_cleanup.recover_legacy(CacheCursor(self.db), self.service, True, self.stats)
        self.assertFalse(source.exists())
        with Image.open(self.root / (stem[:16] + '_low.webp')) as image:
            self.assertLessEqual(max(image.size), 400)
        self.assertIsNotNone(self.db.execute('SELECT cached_image_id FROM pins WHERE id=1').fetchone()[0])

    def test_reprocessing_retains_full_resolution_and_orphaned_undo_images(self):
        kept = 'a' * 16 + '_low.png'
        undo = 'b' * 16 + '_low.png'
        unused = 'c' * 16 + '_low.png'
        orphan = 'd' * 16 + '_low.png'
        for name in [kept, undo, unused, orphan]:
            self.image(name)
        self.cache(1, kept)
        self.cache(2, unused)
        self.db.execute('INSERT INTO pin_images (id, pin_id, image_url, cached_image_id) VALUES (1, 1, ?, 1)', ('https://example.test/recipe',))
        self.db.execute('INSERT INTO audit_log VALUES (?, NULL)', (json.dumps({'image_url': '/cached/' + undo}),))
        with patch.object(cache_cleanup, 'CACHE_DIR', str(self.root)):
            cache_cleanup.reprocess_oversized(CacheCursor(self.db), self.service, True, self.stats)
        with Image.open(self.root / kept) as image:
            self.assertEqual(image.size, (1200, 1800))
        self.assertTrue((self.root / undo).exists())
        self.assertFalse((self.root / orphan).exists())
        with Image.open(self.root / ('c' * 16 + '_low.webp')) as image:
            self.assertLessEqual(max(image.size), 400)

    def test_existing_old_cover_cache_cannot_replace_current_cover_or_publish(self):
        url = 'https://example.test/old-cover.png'
        name = self.service._generate_cache_filename(url, 'low')
        self.image(name)
        self.cache(7, name, url)
        self.db.execute("INSERT INTO pins (id, image_url) VALUES (1, 'https://example.test/new-cover.png')")
        self.db.execute('INSERT INTO pin_images (id, pin_id, image_url) VALUES (1, 1, ?)', (url,))
        with patch.object(image_cache_service, 'get_db_connection', return_value=self.connection), \
             patch.object(self.service, '_should_retry', return_value=True), \
             patch.object(self.service, '_publish') as publish:
            self.service._cache_image(1, url, board_id=9)
        self.assertIsNone(self.db.execute('SELECT cached_image_id FROM pins WHERE id=1').fetchone()[0])
        self.assertEqual(self.db.execute('SELECT cached_image_id FROM pin_images WHERE id=1').fetchone()[0], 7)
        publish.assert_not_called()

    def test_current_cover_cache_still_attaches_and_publishes_to_current_board(self):
        url = 'https://example.test/current.png'
        name = self.service._generate_cache_filename(url, 'low')
        self.image(name)
        self.cache(7, name, url)
        self.db.execute('INSERT INTO pins (id, image_url, board_id) VALUES (1, ?, 10)', (url,))
        self.db.execute('INSERT INTO pin_images (id, pin_id, image_url) VALUES (1, 1, ?)', (url,))
        with patch.object(image_cache_service, 'get_db_connection', return_value=self.connection), \
             patch.object(self.service, '_should_retry', return_value=True), \
             patch.object(self.service, '_publish') as publish:
            cache_id = self.service._cache_image(1, url, board_id=9)
        self.assertEqual(cache_id, 7)
        self.assertEqual(self.db.execute('SELECT cached_image_id, uses_cached_image FROM pins WHERE id=1').fetchone(), (7, 1))
        self.assertEqual(self.db.execute('SELECT cached_image_id, uses_cached_image FROM pin_images WHERE id=1').fetchone(), (7, 1))
        publish.assert_called_once_with(10, 'pin_cached', {'pin_id': 1, 'cached_filename': name, 'image_url': url})

    def test_expiry_aborts_before_deleting_when_reference_scan_fails(self):
        original = self.image('unused.webp')
        self.cache(1, original.name)
        self.db.execute('DROP TABLE pin_images')
        with patch.object(image_cache_service, 'get_db_connection', return_value=self.connection):
            self.service.cleanup_old_cache()
        self.assertTrue(original.exists())
        self.assertEqual(self.db.execute('SELECT cache_status FROM cached_images WHERE id=1').fetchone()[0], 'cached')

    def test_downloaded_old_cover_cannot_write_colors_after_cover_changes(self):
        url = 'https://example.test/old-cover.png'
        self.db.execute('INSERT INTO pins (id, image_url) VALUES (1, ?)', (url,))
        self.db.execute('INSERT INTO pin_images (id, pin_id, image_url) VALUES (1, 1, ?)', (url,))
        buffer = io.BytesIO()
        Image.new('RGB', (600, 900), 'red').save(buffer, 'PNG')

        def download(*args, **kwargs):
            self.db.execute("UPDATE pins SET image_url='https://example.test/new-cover.png' WHERE id=1")
            class Response:
                content = buffer.getvalue()
                headers = {'content-type': 'image/png'}
                def raise_for_status(self): pass
            return Response()

        with patch.object(image_cache_service, 'get_db_connection', return_value=self.connection), \
             patch.object(self.service, '_should_retry', return_value=True), \
             patch.object(self.service.session, 'get', side_effect=download), \
             patch.object(self.service, '_publish') as publish:
            cache_id = self.service._cache_image(1, url, board_id=9)
        self.assertIsNotNone(cache_id)
        self.assertEqual(self.db.execute('SELECT cached_image_id, dominant_color FROM pins WHERE id=1').fetchone(), (None, None))
        self.assertEqual(self.db.execute('SELECT cached_image_id FROM pin_images WHERE id=1').fetchone()[0], cache_id)
        publish.assert_not_called()

    def test_current_cover_download_writes_the_schema_color_columns(self):
        url = 'https://example.test/current.png'
        self.db.execute('INSERT INTO pins (id, image_url) VALUES (1, ?)', (url,))
        self.db.execute('INSERT INTO pin_images (id, pin_id, image_url) VALUES (1, 1, ?)', (url,))
        buffer = io.BytesIO()
        Image.new('RGB', (600, 900), 'red').save(buffer, 'PNG')
        class Response:
            content = buffer.getvalue()
            headers = {'content-type': 'image/png'}
            def raise_for_status(self): pass
        with patch.object(image_cache_service, 'get_db_connection', return_value=self.connection), \
             patch.object(self.service, '_should_retry', return_value=True), \
             patch.object(self.service.session, 'get', return_value=Response()), \
             patch.object(self.service, '_mark_cache_failed'), \
             patch.object(self.service, '_publish') as publish:
            cache_id = self.service._cache_image(1, url, board_id=9)
        self.assertIsNotNone(cache_id)
        self.assertEqual(self.db.execute('SELECT dominant_color, palette_color_1 FROM pins WHERE id=1').fetchone(), ('#e00000', '#e00000'))
        self.assertEqual(publish.call_count, 2)

    def test_dimensions_for_previous_cover_do_not_attach_to_new_cover(self):
        url = 'https://example.test/old.png'
        self.db.execute('INSERT INTO pins (id, image_url) VALUES (1, ?)', (url,))
        self.db.execute('INSERT INTO pin_images (id, pin_id, image_url) VALUES (1, 1, ?)', (url,))
        buffer = io.BytesIO()
        Image.new('RGB', (1200, 1800), 'red').save(buffer, 'PNG')

        def download(*args, **kwargs):
            self.db.execute("UPDATE pins SET image_url='https://example.test/new.png' WHERE id=1")
            class Response:
                raw = io.BytesIO(buffer.getvalue())
                def raise_for_status(self): pass
            return Response()

        with patch.object(image_cache_service, 'get_db_connection', return_value=self.connection), \
             patch.object(self.service.session, 'get', side_effect=download):
            self.service.process_missing_dimensions()
        self.assertIsNone(self.db.execute('SELECT cached_image_id FROM pins WHERE id=1').fetchone()[0])
        self.assertEqual(self.db.execute('SELECT width, height FROM pin_images WHERE id=1').fetchone(), (1200, 1800))

    def test_dimension_only_cache_survives_appending_to_initialized_gallery(self):
        url = 'https://example.test/cake.png'
        self.db.execute("INSERT INTO pins (id, image_url, dominant_color, palette_color_1) VALUES (1, ?, '#123456', '#654321')", (url,))
        pin = {'id': 1, 'image_url': url}
        cursor = CacheCursor(self.db)
        pin_gallery.ensure_pin_images(cursor, pin)
        buffer = io.BytesIO()
        Image.new('RGB', (1200, 1800), 'red').save(buffer, 'PNG')
        class Response:
            raw = io.BytesIO(buffer.getvalue())
            def raise_for_status(self): pass
        with patch.object(image_cache_service, 'get_db_connection', return_value=self.connection), \
             patch.object(self.service.session, 'get', return_value=Response()):
            self.service.process_missing_dimensions()
        cache_id = self.db.execute('SELECT cached_image_id FROM pins WHERE id=1').fetchone()[0]
        self.assertIsNotNone(cache_id)
        pin_gallery.mutate_gallery(cursor, pin, 'add', upload={
            'image_url': '/cached/gallery/recipe.png', 'width': 800, 'height': 2400,
        })
        self.assertEqual(self.db.execute('SELECT cached_image_id, uses_cached_image, dominant_color, palette_color_1 FROM pins WHERE id=1').fetchone(),
            (cache_id, 0, '#123456', '#654321'))
        self.assertEqual(self.db.execute('SELECT cached_image_id, uses_cached_image, width, height FROM pin_images WHERE pin_id=1 AND position=0').fetchone(),
            (cache_id, 0, 1200, 1800))


if __name__ == '__main__':
    unittest.main()
