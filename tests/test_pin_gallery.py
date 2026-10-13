"""Gallery contract exercised through real SQL and image decoding."""
import io
import sqlite3
import tempfile
import unittest
import re
from pathlib import Path

from PIL import Image

import pin_gallery as gallery
from tests.gallery_db import SqliteCursor


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            PRAGMA foreign_keys = ON;
            CREATE TABLE pins (id INTEGER PRIMARY KEY, image_url TEXT NOT NULL,
                cached_image_id INTEGER, uses_cached_image INTEGER DEFAULT 0,
                images_initialized INTEGER DEFAULT 0, dominant_color TEXT,
                palette_color_1 TEXT, palette_color_2 TEXT, palette_color_3 TEXT,
                palette_color_4 TEXT, palette_color_5 TEXT);
            CREATE TABLE cached_images (id INTEGER PRIMARY KEY, cached_filename TEXT,
                width INTEGER, height INTEGER, cache_status TEXT);
            CREATE TABLE pin_images (id INTEGER PRIMARY KEY AUTOINCREMENT,
                pin_id INTEGER NOT NULL REFERENCES pins(id) ON DELETE CASCADE,
                image_url TEXT NOT NULL, preview_url TEXT, width INTEGER, height INTEGER,
                cached_image_id INTEGER, uses_cached_image INTEGER DEFAULT 0,
                position INTEGER NOT NULL, UNIQUE (pin_id, position));
            INSERT INTO pins (id, image_url, dominant_color) VALUES (1, 'https://example.com/cake.jpg', '#abcdef');
            INSERT INTO pins (id, image_url) VALUES (2, '/static/images/default_pin.png');
        ''')
        self.cursor = SqliteCursor(self.db)
        self.pin = {'id': 1, 'image_url': 'https://example.com/cake.jpg'}

    def add(self, name='recipe', pin=None):
        return gallery.mutate_gallery(self.cursor, pin or self.pin, 'add', upload={
            'image_url': '/cached/gallery/' + name + '.png',
            'preview_url': '/cached/gallery/' + name + '-preview.webp',
            'width': 800, 'height': 2400,
        })

    def test_legacy_initialization_is_idempotent_even_with_tuple_cursor(self):
        first = gallery.list_images(self.cursor, self.pin)
        again = gallery.list_images(SqliteCursor(self.db, False), self.pin)
        self.assertEqual(first, again)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]['display_url'], 'https://example.com/cake.jpg')

    def test_legacy_cached_cover_keeps_original_and_cache_dimensions(self):
        self.db.execute("INSERT INTO cached_images VALUES (9, 'cake.webp', 200, 300, 'cached')")
        self.db.execute('UPDATE pins SET cached_image_id=9, uses_cached_image=1 WHERE id=1')
        image = gallery.list_images(self.cursor, self.pin)[0]
        self.assertEqual(image['image_url'], 'https://example.com/cake.jpg')
        self.assertEqual(image['display_url'], '/cached/cake.webp')
        self.assertEqual((image['width'], image['height']), (200, 300))

    def test_provisional_legacy_cache_dimensions_do_not_override_later_decoding(self):
        for status in ('pending', 'failed'):
            with self.subTest(status=status):
                self.db.execute('DELETE FROM pin_images WHERE pin_id=1')
                self.db.execute('DELETE FROM cached_images WHERE id=9')
                self.db.execute('UPDATE pins SET images_initialized=0, cached_image_id=9, uses_cached_image=1 WHERE id=1')
                self.db.execute('INSERT INTO cached_images VALUES (9, ?, 800, 600, ?)', ('cake.webp', status))
                gallery.ensure_pin_images(self.cursor, self.pin)
                stored = gallery.snapshot_images(self.cursor, 1)[0]
                self.assertEqual((stored['width'], stored['height']), (0, 0))
                self.db.execute("UPDATE cached_images SET width=900, height=2400, cache_status='cached' WHERE id=9")
                image = gallery.list_images(self.cursor, self.pin)[0]
                self.assertEqual((image['width'], image['height']), (900, 2400))

    def test_uploaded_decoded_dimensions_remain_authoritative(self):
        images = self.add()
        image_id = images[-1]['id']
        self.db.execute("INSERT INTO cached_images VALUES (9, 'recipe.webp', 400, 1200, 'cached')")
        self.db.execute('UPDATE pin_images SET cached_image_id=9 WHERE id=?', (image_id,))
        uploaded = gallery.list_images(self.cursor, self.pin)[-1]
        self.assertEqual((uploaded['width'], uploaded['height']), (800, 2400))

    def test_placeholder_is_empty_and_first_add_becomes_cover(self):
        pin = {'id': 2, 'image_url': '/static/images/default_pin.png'}
        self.assertEqual(gallery.list_images(self.cursor, pin), [])
        images = self.add(pin=pin)
        self.assertEqual(len(images), 1)
        self.assertEqual(self.db.execute('SELECT image_url FROM pins WHERE id=2').fetchone()[0], images[0]['image_url'])

    def test_add_appends_and_does_not_change_cover_or_colours(self):
        images = self.add()
        self.assertEqual([image['position'] for image in images], [0, 1])
        self.assertEqual(images[1]['height'], 2400)
        self.assertEqual(self.db.execute('SELECT image_url, dominant_color FROM pins WHERE id=1').fetchone(),
                         ('https://example.com/cake.jpg', '#abcdef'))

    def test_replace_preserves_identity_and_cover_projection(self):
        images = self.add()
        cover_id = images[0]['id']
        result = gallery.mutate_gallery(self.cursor, self.pin, 'replace', image_id=cover_id,
            upload={'image_url': '/cached/gallery/new.png', 'width': 600, 'height': 900})
        self.assertEqual([image['id'] for image in result], [image['id'] for image in images])
        self.assertEqual(result[0]['image_url'], '/cached/gallery/new.png')
        self.assertEqual(self.db.execute('SELECT cached_image_id, uses_cached_image, dominant_color FROM pins WHERE id=1').fetchone(), (None, 0, None))

    def test_cover_promotes_image_and_preserves_other_relative_order(self):
        self.add('a')
        images = self.add('b')
        result = gallery.mutate_gallery(self.cursor, self.pin, 'cover', image_id=images[2]['id'])
        self.assertEqual([image['id'] for image in result], [images[2]['id'], images[0]['id'], images[1]['id']])
        self.assertEqual(self.db.execute('SELECT image_url FROM pins WHERE id=1').fetchone()[0], '/cached/gallery/b.png')

    def test_reorder_keeps_cover_and_rejects_stale_or_incomplete_sets(self):
        self.add('a')
        images = self.add('b')
        ids = [image['id'] for image in images]
        reordered = gallery.mutate_gallery(self.cursor, self.pin, 'reorder', image_ids=[ids[0], ids[2], ids[1]])
        self.assertEqual([image['id'] for image in reordered], [ids[0], ids[2], ids[1]])
        for invalid in ([ids[0]], [ids[0], ids[1], 999], [ids[0], ids[1], ids[1]], [ids[1], ids[0], ids[2]]):
            with self.subTest(ids=invalid), self.assertRaises(gallery.GalleryError) as raised:
                gallery.mutate_gallery(self.cursor, self.pin, 'reorder', image_ids=invalid)
            self.assertEqual(raised.exception.status, 409)

    def test_missing_or_foreign_image_cannot_be_mutated(self):
        foreign_id = self.add(pin={'id': 2})[0]['id']
        for action in ('cover', 'remove', 'replace'):
            for image_id in (999, foreign_id):
                with self.subTest(action=action), self.assertRaises(gallery.GalleryError):
                    gallery.mutate_gallery(self.cursor, self.pin, action, image_id=image_id, upload={'image_url': 'new'})
        self.assertEqual(len(gallery.list_images(self.cursor, self.pin)), 1)

    def test_removing_cover_promotes_next_and_empty_gallery_stays_empty(self):
        images = self.add()
        result = gallery.mutate_gallery(self.cursor, self.pin, 'remove', image_id=images[0]['id'])
        self.assertEqual(result[0]['id'], images[1]['id'])
        gallery.mutate_gallery(self.cursor, self.pin, 'remove', image_id=result[0]['id'])
        stale_pin = {'id': 1, 'image_url': 'https://example.com/cake.jpg'}
        self.assertEqual(gallery.list_images(self.cursor, stale_pin), [])
        self.assertEqual(self.db.execute('SELECT image_url FROM pins WHERE id=1').fetchone()[0], '/static/images/default_pin.png')

    def test_maximum_image_count_rejects_add_but_allows_replace(self):
        for i in range(19):
            images = self.add(str(i))
        with self.assertRaises(gallery.GalleryError) as raised:
            self.add('overflow')
        self.assertEqual(raised.exception.status, 409)
        result = gallery.mutate_gallery(self.cursor, self.pin, 'replace', image_id=images[-1]['id'], upload={'image_url': 'new'})
        self.assertEqual(len(result), 20)

    def test_snapshot_restore_preserves_ids_order_dimensions_and_empty_state(self):
        self.add()
        before = gallery.snapshot_images(SqliteCursor(self.db, False), 1)
        gallery.mutate_gallery(self.cursor, self.pin, 'remove', image_id=before[0]['id'])
        gallery.restore_images(self.cursor, 1, before)
        self.assertEqual(gallery.snapshot_images(self.cursor, 1), before)
        self.assertEqual(self.db.execute('SELECT image_url FROM pins WHERE id=1').fetchone()[0], 'https://example.com/cake.jpg')
        gallery.restore_images(self.cursor, 1, [])
        self.assertEqual(gallery.list_images(self.cursor, self.pin), [])

    def test_snapshot_initializes_legacy_pin_without_prior_gallery_read(self):
        rows = gallery.snapshot_images(self.cursor, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['pin_id'], 1)

    def test_restore_cannot_take_another_pins_image_id(self):
        images = self.add()
        foreign = gallery.snapshot_images(self.cursor, 2)
        if not foreign:
            self.add(pin={'id': 2})
            foreign = gallery.snapshot_images(self.cursor, 2)
        with self.assertRaises(gallery.GalleryError) as raised:
            gallery.restore_images(self.cursor, 1, foreign)
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(gallery.list_images(self.cursor, self.pin), images)

    def test_migration_backfills_once_and_does_not_resurrect_removed_image(self):
        from migrate import migrate_pin_images

        class MigrationCursor(SqliteCursor):
            def execute(self, query, params=()):
                if 'information_schema.columns' in query:
                    self.cursor.execute('SELECT COUNT(*) FROM pragma_table_info(?) WHERE name = ?', params)
                    return
                if 'CREATE TABLE IF NOT EXISTS pin_images' in query:
                    query = re.sub(r'\) ENGINE=.*', ')', query, flags=re.S)
                    query = re.sub(r'UNIQUE KEY \w+', 'UNIQUE', query)
                    query = re.sub(r'^\s*INDEX[^\n]+', '', query, flags=re.M)
                    query = re.sub(r',\s*\)', ')', query)
                    query = query.replace('INT AUTO_INCREMENT PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')
                super().execute(query, params)

        self.db.execute('DROP TABLE pin_images')
        self.db.execute('ALTER TABLE pins DROP COLUMN images_initialized')
        cursor = MigrationCursor(self.db, False)
        migrate_pin_images(cursor)
        before = gallery.list_images(self.cursor, self.pin)
        self.assertEqual(len(before), 1)
        migrate_pin_images(cursor)
        self.assertEqual(gallery.list_images(self.cursor, self.pin), before)
        gallery.mutate_gallery(self.cursor, self.pin, 'remove', image_id=before[0]['id'])
        migrate_pin_images(cursor)
        self.assertEqual(gallery.list_images(self.cursor, self.pin), [])
        self.assertEqual(gallery.list_images(self.cursor, {'id': 2}), [])


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage_root = Path(self.directory.name) / 'gallery'

    def image_file(self, size=(800, 2400), exif=None):
        file = io.BytesIO()
        image = Image.new('RGB', size, 'white')
        image.save(file, 'PNG', **({'exif': exif} if exif else {}))
        file.seek(0)
        return file

    def test_uploaded_recipe_keeps_readable_original_and_small_preview(self):
        image = gallery.save_upload(self.image_file(), self.storage_root, 20 * 1024 * 1024, 40_000_000)
        self.assertEqual(image['height'], 2400)
        self.assertNotEqual(image['preview_url'], image['image_url'])
        original = self.storage_root / image['image_url'].rsplit('/', 1)[1]
        preview = self.storage_root / image['preview_url'].rsplit('/', 1)[1]
        with Image.open(original) as decoded:
            self.assertEqual(decoded.size, (800, 2400))
        with Image.open(preview) as decoded:
            self.assertLessEqual(max(decoded.size), 1600)

    def test_upload_normalizes_exif_orientation(self):
        exif = Image.Exif()
        exif[274] = 6
        image = gallery.save_upload(self.image_file((30, 60), exif), self.storage_root, 10000, 10000)
        self.assertEqual((image['width'], image['height']), (60, 30))

    def test_corrupt_png_checksum_is_rejected_before_writing(self):
        data = bytearray(self.image_file((30, 30)).getvalue())
        chunk = data.index(b'IDAT')
        chunk_length = int.from_bytes(data[chunk - 4:chunk], 'big')
        data[chunk + 4 + chunk_length] ^= 1
        with self.assertRaises(gallery.GalleryError):
            gallery.save_upload(io.BytesIO(data), self.storage_root, 10000, 10000)
        self.assertFalse(self.storage_root.exists())

    def test_invalid_svg_and_oversized_uploads_leave_no_files(self):
        cases = [(io.BytesIO(b'not an image'), 10000, 10000, 400),
                 (io.BytesIO(b'<svg/>'), 10000, 10000, 400),
                 (self.image_file(), 10, 40_000_000, 413),
                 (self.image_file(), 1_000_000, 100, 413)]
        for file, max_bytes, max_pixels, status in cases:
            with self.subTest(status=status), self.assertRaises(gallery.GalleryError) as raised:
                gallery.save_upload(file, self.storage_root, max_bytes, max_pixels)
            self.assertEqual(raised.exception.status, status)
            self.assertFalse(self.storage_root.exists() and any(self.storage_root.iterdir()))

    def test_remove_keeps_uploaded_bytes_for_undo(self):
        image = gallery.save_upload(self.image_file(), self.storage_root, 20 * 1024 * 1024, 40_000_000)
        case = GalleryTests()
        case.setUp()
        try:
            result = gallery.mutate_gallery(case.cursor, {'id': 2}, 'add', upload=image)
            gallery.mutate_gallery(case.cursor, {'id': 2}, 'remove', image_id=result[0]['id'])
        finally:
            case.doCleanups()
        self.assertTrue((self.storage_root / image['image_url'].rsplit('/', 1)[1]).is_file())


if __name__ == '__main__':
    unittest.main()
