"""Image URL additions use the same ownership, transaction and audit as uploads."""
import json
import unittest

from tests import test_gallery_integration as fixtures


class GalleryImageUrlTests(unittest.TestCase):
    setUp = fixtures.GalleryIntegrationTests.setUp

    def add_url(self, url, pin_id=42, headers=None):
        return self.client.post(f'/api/pin/{pin_id}/images',
                                data={'image_url': url},
                                headers=self.headers if headers is None else headers)

    def test_url_appends_persists_and_audits_without_replacing_cover(self):
        response = self.add_url('  https://images.example.test/recipe.png?size=large  ')
        self.assertEqual(response.status_code, 200, response.json)
        images = response.json['images']
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0]['image_url'], 'https://example.test/cake.png')
        self.assertEqual(images[1]['image_url'], 'https://images.example.test/recipe.png?size=large')
        self.assertEqual(self.client.get('/api/pin/42/images').json['images'], images)
        action, after = self.db.execute('SELECT action,after_data FROM audit_log').fetchone()
        self.assertEqual(action, 'pin.images.add')
        self.assertEqual(len(json.loads(after)['images']), 2)

    def test_url_requires_ownership_and_csrf(self):
        url = 'https://images.example.test/recipe.png'
        self.assertEqual(self.add_url(url, pin_id=43).status_code, 404)
        self.assertEqual(self.add_url(url, headers={}).status_code, 403)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM pin_images').fetchone()[0], 0)

    def test_rejects_invalid_urls_without_mutation(self):
        for url in ('', 'javascript:alert(1)', 'data:image/png;base64,AA==',
                    'file:///tmp/image.png', '//example.test/image.png',
                    'https://', 'https://user:password@example.test/image.png',
                    'https://example.test/a\nb.png', 'https://example.test/a b.png',
                    'https://example.test/a\\b.png', 'https://[invalid/image.png',
                    'https://example.test:bad/image.png', 'https://example.test/' + 'x' * 2048):
            with self.subTest(url=url[:60]):
                response = self.add_url(url)
                self.assertEqual(response.status_code, 400)
                self.assertIn('URL', response.json['error'])
                self.assertEqual(self.db.execute('SELECT COUNT(*) FROM pin_images').fetchone()[0], 0)

    def test_url_respects_gallery_capacity(self):
        for index in range(19):
            self.assertEqual(self.add_url(f'https://images.example.test/{index}.png').status_code, 200)
        response = self.add_url('https://images.example.test/overflow.png')
        self.assertIn(response.status_code, (400, 409))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM pin_images').fetchone()[0], 20)
