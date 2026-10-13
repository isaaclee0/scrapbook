"""Opt-in integration against a disposable MariaDB database named cache_test.

CACHE_TEST_MYSQL_PORT=<published test container port> python -m unittest tests.test_cache_mysql
Never points at the app's DB_HOST/DB_NAME or reads production credentials.
"""
import io
import os
import re
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import mysql.connector
from PIL import Image
from scripts import cache_worker, image_cache_service


@unittest.skipUnless(os.getenv('CACHE_TEST_MYSQL_PORT'), 'requires disposable MariaDB')
class CacheMysqlTests(unittest.TestCase):
    def connect(self):
        return mysql.connector.connect(host='127.0.0.1', port=int(os.environ['CACHE_TEST_MYSQL_PORT']),
            user='root', password='cache_test_only', database='cache_test', autocommit=True)

    def sql(self, query, params=()):
        db = self.connect()
        try:
            cursor = db.cursor(dictionary=True)
            cursor.execute(query, params)
            result = cursor.fetchall() if cursor.with_rows else cursor.lastrowid
            cursor.close()
            return result
        finally:
            db.close()

    def setUp(self):
        for table in ('pin_images','pins','cached_images'):
            self.sql(f'DROP TABLE IF EXISTS {table}')
        schema = Path('init.sql').read_text()
        self.sql(re.search(r'CREATE TABLE IF NOT EXISTS cached_images \(.*?;',schema,re.S)[0])
        self.sql('''CREATE TABLE pins (id INT AUTO_INCREMENT PRIMARY KEY, image_url TEXT,
            cached_image_id INT, uses_cached_image BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            board_id INT DEFAULT 1, dominant_color VARCHAR(7), palette_color_1 VARCHAR(7), palette_color_2 VARCHAR(7),
            palette_color_3 VARCHAR(7), palette_color_4 VARCHAR(7), palette_color_5 VARCHAR(7)) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
        self.sql('''CREATE TABLE pin_images (id INT AUTO_INCREMENT PRIMARY KEY, pin_id INT, image_url TEXT,
            cached_image_id INT, uses_cached_image BOOLEAN DEFAULT FALSE) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''')
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = image_cache_service.ImageCacheService(self.directory.name, max_workers=4)
        self.addCleanup(self.service.session.close)
        self.addCleanup(self.service.stop_workers)
        self.addCleanup(patch.stopall)
        patch.object(image_cache_service,'get_db_connection',side_effect=self.connect).start()
        patch.object(self.service,'_publish').start()
        self.requests = []
        requests = self.requests
        png = io.BytesIO()
        Image.new('RGB',(800,600),'blue').save(png,'PNG')
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                # Ensure duplicate-URL jobs overlap to catch parallel retry budget consumption.
                time.sleep(0.05)
                status, content_type, body = (200,'image/png',png.getvalue())
                if self.path.startswith('/page'):
                    content_type,body = 'text/html',b'<html>web page</html>'
                elif self.path.startswith('/retry'):
                    status,body = 503,b'temporary'
                self.send_response(status)
                self.send_header('Content-Type',content_type)
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self,*args): pass
        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.base_url = f'http://127.0.0.1:{self.server.server_port}'

    def pin(self,path,retries=None,hours=48,kind=None,attached=False):
        url = self.base_url+path
        pin_id = self.sql('INSERT INTO pins (image_url) VALUES (%s)',(url,))
        self.sql('INSERT INTO pin_images (pin_id,image_url) VALUES (%s,%s)',(pin_id,url))
        if retries is not None:
            cache_id = self.sql('''INSERT INTO cached_images
                (original_url,cached_filename,cache_status,retry_count,last_retry_at,failure_kind)
                VALUES (%s,'failed','failed',%s,DATE_SUB(NOW(),INTERVAL %s HOUR),%s)''',(url,retries,hours,kind))
            if attached:
                self.sql('UPDATE pins SET cached_image_id=%s WHERE id=%s',(cache_id,pin_id))
        return pin_id,url

    def test_real_batch_bypasses_exhausted_and_cooling_items_and_writes_cache(self):
        self.pin('/image',retries=1,hours=3)
        self.pin('/exhausted',retries=3)
        self.pin('/cooldown',retries=2,hours=1)
        self.pin('/terminal',retries=1,kind='unsupported')
        self.assertEqual(cache_worker.uncached_count(),1)
        results = self.service.cache_all_external_images(limit=1)
        self.assertEqual(results,{'selected':1,'cached':1,'failed_or_skipped':0})
        self.assertEqual(self.requests,['/image'])
        self.assertEqual(cache_worker.uncached_count(),0)
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM pins WHERE uses_cached_image=1')[0]['n'],1)
        self.assertEqual(len(list(Path(self.directory.name).glob('*.webp'))),1)

    def test_real_terminal_and_transient_results_are_not_reported_as_cached(self):
        self.pin('/page')
        self.pin('/retry')
        result = self.service.cache_all_external_images()
        self.assertEqual(result,{'selected':2,'cached':0,'failed_or_skipped':2})
        self.assertEqual({r['failure_kind'] for r in self.sql('SELECT failure_kind FROM cached_images')}, {'unsupported','retryable'})
        self.assertEqual(cache_worker.uncached_count(),0)

    def test_duplicate_urls_share_one_failure_attempt_per_batch(self):
        for _ in range(6):
            self.pin('/retry-duplicate')
        result = self.service.cache_all_external_images()
        self.assertEqual(result['cached'],0)
        self.assertEqual(self.sql('SELECT retry_count FROM cached_images')[0]['retry_count'],1)
        self.assertEqual(len(self.requests),1)

    def test_success_upsert_returns_existing_id_after_concurrent_failure(self):
        pin_id,url = self.pin('/image-upsert')
        real_get = self.service.session.get
        def download(*args,**kwargs):
            self.service._mark_cache_failed(url,'low','older process failed')
            return real_get(*args,**kwargs)
        with patch.object(self.service.session,'get',side_effect=download):
            cache_id = self.service._cache_image(pin_id,url)
        row = self.sql('SELECT id,cache_status,retry_count FROM cached_images')[0]
        self.assertEqual(row,{'id':cache_id,'cache_status':'cached','retry_count':0})
        self.assertEqual(self.sql('SELECT cached_image_id FROM pins')[0]['cached_image_id'],cache_id)

    def test_lock_covers_independent_service_instances(self):
        from concurrent.futures import ThreadPoolExecutor
        first,url = self.pin('/retry-two-services',retries=2)
        second,_ = self.pin('/retry-two-services')
        other = image_cache_service.ImageCacheService(self.directory.name,max_workers=1)
        self.addCleanup(other.session.close)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda item: item[0]._cache_image(item[1],url),
                                    [(self.service,first),(other,second)]))
        self.assertEqual(results,[None,None])
        self.assertEqual(self.sql('SELECT retry_count FROM cached_images')[0]['retry_count'],3)
        self.assertEqual(len(self.requests),1)
