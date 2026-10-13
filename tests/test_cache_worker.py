"""Cache queue regressions: real SQL/state and image bytes, no external network."""
import io
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import requests
from PIL import Image
from scripts import cache_worker, image_cache_service
from tests import test_gallery_retention as fixtures
from tests.test_gallery_retention import CacheConnection, CacheCursor


class QueueCursor(CacheCursor):
    def execute(self, query, params=()):
        query = query.replace('TIMESTAMPDIFF(SECOND,', 'TIMESTAMPDIFF_SECONDS(')
        # Also run the old query to reproduce exhausted entries starving the LIMIT.
        query = query.replace('DATE_SUB(NOW(), INTERVAL POWER(2, ci.retry_count) HOUR)',
                              "datetime('now', '-' || POWER(2, ci.retry_count) || ' hours')")
        super().execute(query, params)


class QueueConnection(CacheConnection):
    def cursor(self, dictionary=False):
        return QueueCursor(self.db, dictionary)


class Response:
    def __init__(self, content, content_type='image/png', status=200):
        self.content = content
        self.headers = {'content-type': content_type}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)

    def iter_content(self, chunk_size):
        yield self.content

    def close(self):
        pass


class CacheQueueTests(unittest.TestCase):
    def setUp(self):
        fixtures.CacheMaintenanceTests.setUp(self)
        self.db.execute('ALTER TABLE pins ADD COLUMN created_at TEXT')
        self.db.create_function('TIMESTAMPDIFF_SECONDS', 2,
            lambda start, end: (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
        self.db.create_function('IF', 3, lambda condition, yes, no: yes if condition else no)
        self.connection = QueueConnection(self.db)
        self.addCleanup(patch.stopall)
        patch.object(image_cache_service, 'get_db_connection', return_value=self.connection).start()
        import app
        patch.object(app, 'get_db_connection', return_value=self.connection).start()
        patch.object(self.service, '_publish').start()

    def pin(self, pin_id, retries=None, hours_ago=48, attached=False, kind=None, status='failed'):
        url = f'https://example.test/{pin_id}.png'
        cache_id = None
        if retries is not None:
            when = (datetime.utcnow() - timedelta(hours=hours_ago)).isoformat(' ', timespec='seconds')
            self.db.execute('''INSERT INTO cached_images
                (id,original_url,cached_filename,cache_status,retry_count,last_retry_at,updated_at,failure_kind)
                VALUES (?,?,'pending',?,?,?,?,?)''', (pin_id, url, status, retries, when, when, kind))
            if attached:
                cache_id = pin_id
        self.db.execute('INSERT INTO pins (id,image_url,cached_image_id,created_at) VALUES (?,?,?,?)',
                        (pin_id,url,cache_id,f'2026-01-{pin_id:02}'))
        self.db.execute('INSERT INTO pin_images (pin_id,image_url) VALUES (?,?)', (pin_id,url))
        self.db.commit()
        return url

    def selected(self, limit=20):
        selected = []
        def enqueue(pin_id, *args, **kwargs):
            selected.append(pin_id)
            if kwargs.get('on_complete'):
                kwargs['on_complete'](None)
        with patch.object(self.service, 'queue_image_for_caching', side_effect=enqueue):
            self.service.cache_all_external_images(limit=limit)
        return selected

    def test_exhausted_unlinked_record_cannot_starve_eligible_pin(self):
        self.pin(1)
        self.pin(2, retries=3)
        self.assertEqual(self.selected(limit=1), [1])
        self.assertEqual(cache_worker.uncached_count(), 1)

    def test_count_selection_and_downloader_share_cooldown_and_limit(self):
        fixtures = [(1, 1, 1, None, False), (2, 1, 3, None, True),
                    (3, 2, 3, None, False), (4, 2, 5, None, True),
                    (5, 3, 200, None, False), (6, 1, 200, 'unsupported', False)]
        for pin_id, retries, hours, kind, eligible in fixtures:
            url = self.pin(pin_id, retries, hours, attached=True, kind=kind)
            self.assertEqual(self.service._should_retry(url, 'low'), eligible, pin_id)
        self.assertEqual(set(self.selected()), {2, 4})
        self.assertEqual(cache_worker.uncached_count(), 2)

    def test_stale_pending_never_bypasses_retry_limit(self):
        url = self.pin(1, retries=3, status='pending')
        self.assertFalse(self.service._should_retry(url, 'low'))

    def test_success_writes_webp_and_attaches_to_pin_and_gallery(self):
        url = self.pin(1, retries=1)
        data = io.BytesIO()
        Image.new('RGB', (800,600), 'red').save(data, 'PNG')
        with patch.object(self.service.session, 'get', return_value=Response(data.getvalue())):
            result = self.service._cache_image(1, url)
        self.assertIsNotNone(result)
        self.assertEqual(self.db.execute('SELECT cache_status,retry_count,last_retry_at,failure_kind FROM cached_images').fetchone(), ('cached',0,None,None))
        self.assertEqual(self.db.execute('SELECT cached_image_id,uses_cached_image FROM pins').fetchone(), (result,1))
        self.assertEqual(self.db.execute('SELECT cached_image_id FROM pin_images').fetchone()[0], result)
        with Image.open(self.root / self.service._generate_cache_filename(url,'low')) as img:
            self.assertEqual(img.format, 'WEBP')
            self.assertEqual(img.size, (400,300))

    def test_unsupported_html_pdf_and_social_video_page_are_terminal(self):
        for pin_id, content_type in enumerate(['text/html','application/pdf','text/html'], 1):
            with self.subTest(content_type=content_type, pin_id=pin_id):
                url = self.pin(pin_id)
                if pin_id == 3:
                    url = 'https://social.example/videos/123'
                    self.db.execute('UPDATE pins SET image_url=? WHERE id=?', (url,pin_id))
                    self.db.commit()
                    self.service.ffmpeg_available = True
                with patch.object(self.service.session, 'get', return_value=Response(b'not an image',content_type)):
                    self.assertIsNone(self.service._cache_image(pin_id,url))
                self.assertEqual(self.db.execute('SELECT failure_kind,retry_count FROM cached_images WHERE original_url=?',(url,)).fetchone(), ('unsupported',1))
                self.assertFalse(self.service._should_retry(url,'low'))
        self.assertEqual(self.selected(), [])

    def test_transient_http_failure_cools_down_but_404_is_terminal(self):
        for pin_id, status, kind in [(1,429,'retryable'),(2,503,'retryable'),(3,404,'http_permanent')]:
            url = self.pin(pin_id)
            with patch.object(self.service.session, 'get', return_value=Response(b'',status=status)):
                self.service._cache_image(pin_id,url)
            self.assertEqual(self.db.execute('SELECT failure_kind,retry_count FROM cached_images WHERE original_url=?',(url,)).fetchone(), (kind,1))
            self.assertFalse(self.service._should_retry(url,'low'))
        self.assertEqual(cache_worker.uncached_count(), 0)

    def test_cached_file_reuse_is_allowed_even_with_legacy_retry_count(self):
        url = self.pin(1,retries=3,status='cached')
        Image.new('RGB',(20,20),'red').save(self.root / 'pending','PNG')
        self.assertEqual(self.service._cache_image(1,url), 1)

    def test_missing_cached_file_records_failure_and_stops_requeueing(self):
        url = self.pin(1, retries=0, status='cached')
        with patch.object(self.service.session,'get',return_value=Response(b'',status=404)):
            self.assertIsNone(self.service._cache_image(1,url))
        self.assertEqual(self.db.execute('SELECT cache_status,retry_count,failure_kind FROM cached_images').fetchone(),
                         ('failed',1,'http_permanent'))
        self.assertEqual(cache_worker.uncached_count(),0)

    def test_missing_cached_file_with_exhausted_budget_is_retired_without_request(self):
        url = self.pin(1, retries=3, status='cached')
        with patch.object(self.service.session,'get',side_effect=AssertionError('must not download')):
            self.assertIsNone(self.service._cache_image(1,url))
        self.assertEqual(self.db.execute('SELECT cache_status,retry_count FROM cached_images').fetchone(), ('failed',3))
        self.assertEqual(cache_worker.uncached_count(),0)

    def test_success_survives_failure_row_created_during_download(self):
        url = self.pin(1)
        data = io.BytesIO()
        Image.new('RGB',(20,20),'blue').save(data,'PNG')
        def download(*args,**kwargs):
            self.service._mark_cache_failed(url,'low','older process failed')
            return Response(data.getvalue())
        with patch.object(self.service.session,'get',side_effect=download):
            result = self.service._cache_image(1,url)
        self.assertIsNotNone(result)
        self.assertEqual(self.db.execute('SELECT cache_status,retry_count FROM cached_images').fetchone(), ('cached',0))
        self.assertEqual(self.db.execute('SELECT cached_image_id FROM pins').fetchone()[0],result)

    def test_failure_metadata_never_downgrades_a_concurrent_success(self):
        url = self.pin(1, retries=0, status='cached')
        self.service._mark_cache_failed(url, 'low', 'late timeout')
        self.assertEqual(self.db.execute('SELECT cache_status,retry_count,failure_kind FROM cached_images').fetchone(),
                         ('cached',0,None))

    def test_failed_attempt_increments_existing_budget_without_reset(self):
        url = self.pin(1, retries=2)
        self.service._mark_cache_failed(url, 'low', 'timeout')
        self.assertEqual(self.db.execute('SELECT retry_count,failure_kind FROM cached_images').fetchone(), (3,'retryable'))
        self.assertFalse(self.service._should_retry(url,'low'))


class WorkerHealthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'heartbeat.json'

    def test_health_rejects_missing_stale_corrupt_and_dead_process(self):
        self.assertTrue(hasattr(cache_worker,'WorkerHeartbeat'), 'worker needs a processing heartbeat')
        heartbeat = cache_worker.WorkerHeartbeat(self.path)
        self.assertFalse(heartbeat.healthy())
        heartbeat.touch()
        self.assertTrue(heartbeat.healthy())
        self.path.write_text(json.dumps({'pid':os.getpid(),'at':0}))
        self.assertFalse(heartbeat.healthy())
        self.path.write_text('broken')
        self.assertFalse(heartbeat.healthy())
        heartbeat.touch(force=True)
        with patch('os.kill',side_effect=ProcessLookupError):
            self.assertFalse(heartbeat.healthy())

    def test_long_sleep_refreshes_heartbeat(self):
        worker = cache_worker.CacheWorker(1,10,0,300)
        self.assertTrue(hasattr(worker,'heartbeat'))
        worker.heartbeat = cache_worker.WorkerHeartbeat(self.path)
        with patch.object(cache_worker.time,'sleep',side_effect=lambda seconds: worker.stop()):
            worker._interruptible_sleep(3600)
        self.assertTrue(worker.heartbeat.healthy())

    def test_long_download_refreshes_health_only_when_bytes_arrive(self):
        heartbeat = cache_worker.WorkerHeartbeat(self.path)
        now = [1000.0]
        class SlowResponse:
            def iter_content(self, chunk_size):
                for _ in range(5):
                    now[0] += 200
                    yield b'chunk'
        service = image_cache_service.ImageCacheService.__new__(image_cache_service.ImageCacheService)
        with patch.object(cache_worker.time,'time',side_effect=lambda: now[0]), \
             patch.object(cache_worker.time,'monotonic',side_effect=lambda: now[0]):
            heartbeat.touch()
            for chunk in service._download_chunks(SlowResponse(),heartbeat.touch):
                self.assertEqual(chunk,b'chunk')
                self.assertTrue(heartbeat.healthy())
            now[0] += 301
            self.assertFalse(heartbeat.healthy())

    def test_no_success_backs_off_by_default_even_if_eligible_count_falls(self):
        worker = cache_worker.CacheWorker(1,10,0,300)
        sleeps=[]
        def sleep(seconds):
            sleeps.append(seconds)
            worker.stop()
        with patch.object(cache_worker,'uncached_count',side_effect=[2,1]), \
             patch.object(worker,'run_batch',return_value={'selected':1,'cached':0,'failed_or_skipped':1}), \
             patch.object(worker,'_interruptible_sleep',side_effect=sleep):
            worker.run()
        self.assertEqual(sleeps,[300])
