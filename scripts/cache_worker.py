#!/usr/bin/env python3
"""
Long-running image cache worker for production servers.

Downloads external pin images to static/cached_images/ in batches. Safe to
restart — skips already-cached images and respects retry limits.

Run as a Docker service (recommended):
    docker compose up -d cache-worker

One-off backfill:
    python scripts/cache_worker.py --once --batch-size 500

Environment variables:
    CACHE_WORKER_BATCH_SIZE       Pins per batch (default: 200)
    CACHE_WORKER_SLEEP            Seconds between batches (default: 10)
    CACHE_WORKER_MAX_IDLE_ROUNDS  Stop-after N batches with no progress (default: 0 = never stop)
    CACHE_WORKER_IDLE_BACKOFF     Extra sleep when idle (default: 300)
"""

import argparse
import logging
import os
import signal
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger('cache_worker')


def uncached_count():
    from app import get_db_connection

    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("""
        SELECT COUNT(*)
        FROM pins p
        LEFT JOIN cached_images ci ON p.cached_image_id = ci.id
        WHERE p.image_url LIKE 'http%%'
          AND (p.cached_image_id IS NULL OR ci.cache_status IS NULL
               OR ci.cache_status IN ('pending', 'failed'))
          AND (ci.retry_count IS NULL OR ci.retry_count < 3
               OR ci.last_retry_at < DATE_SUB(NOW(), INTERVAL POWER(2, ci.retry_count) HOUR))
    """)
    count = cursor.fetchone()[0]
    cursor.close()
    db.close()
    return count


class CacheWorker:
    def __init__(self, batch_size, sleep_sec, max_idle_rounds, idle_backoff):
        self.batch_size = batch_size
        self.sleep_sec = sleep_sec
        self.max_idle_rounds = max_idle_rounds
        self.idle_backoff = idle_backoff
        self.running = True
        self._service = None

    def stop(self, *_args):
        if self.running:
            logger.info('Shutdown requested — finishing current batch')
        self.running = False

    def _service_instance(self):
        if self._service is None:
            from scripts.image_cache_service import ImageCacheService
            workers = int(os.getenv('CACHE_WORKER_THREADS', '6'))
            self._service = ImageCacheService(max_workers=workers)
        return self._service

    def run_batch(self):
        service = self._service_instance()
        service.cache_all_external_images(
            limit=self.batch_size,
            process_dimensions=False,
        )

    def run(self):
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)

        logger.info(
            'Cache worker started (batch=%s, sleep=%ss, idle_limit=%s)',
            self.batch_size, self.sleep_sec, self.max_idle_rounds or 'none',
        )

        idle_rounds = 0
        batch_num = 0

        while self.running:
            before = uncached_count()
            if before == 0:
                logger.info('All external images cached — sleeping %ss', self.sleep_sec)
                self._interruptible_sleep(self.sleep_sec)
                idle_rounds = 0
                continue

            batch_num += 1
            logger.info('Batch %s: caching up to %s pins (%s uncached)', batch_num, self.batch_size, before)

            try:
                self.run_batch()
            except Exception:
                logger.exception('Batch %s failed', batch_num)
                self._interruptible_sleep(self.sleep_sec)
                continue

            after = uncached_count()
            cached = before - after
            logger.info('Batch %s done: cached ~%s, %s remaining', batch_num, cached, after)

            if cached <= 0:
                idle_rounds += 1
                logger.warning('No progress this batch (idle round %s)', idle_rounds)
                if self.max_idle_rounds and idle_rounds >= self.max_idle_rounds:
                    logger.info(
                        'No progress for %s batches — backing off %ss',
                        idle_rounds, self.idle_backoff,
                    )
                    self._interruptible_sleep(self.idle_backoff)
                    idle_rounds = 0
            else:
                idle_rounds = 0

            if self.running and after > 0:
                self._interruptible_sleep(self.sleep_sec)

        logger.info('Cache worker stopped')

    def _interruptible_sleep(self, seconds):
        """Sleep in small slices so SIGTERM is picked up promptly."""
        end = time.time() + seconds
        while self.running and time.time() < end:
            time.sleep(min(1.0, end - time.time()))


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s [cache_worker] %(message)s',
    )

    parser = argparse.ArgumentParser(description='Scrappl image cache worker')
    parser.add_argument('--batch-size', type=int, default=int(os.getenv('CACHE_WORKER_BATCH_SIZE', '200')))
    parser.add_argument('--sleep', type=float, default=float(os.getenv('CACHE_WORKER_SLEEP', '10')))
    parser.add_argument(
        '--max-idle-rounds', type=int,
        default=int(os.getenv('CACHE_WORKER_MAX_IDLE_ROUNDS', '0')),
        help='Exit after N consecutive batches with no progress (0 = run forever)',
    )
    parser.add_argument(
        '--idle-backoff', type=float,
        default=float(os.getenv('CACHE_WORKER_IDLE_BACKOFF', '300')),
    )
    parser.add_argument('--once', action='store_true', help='Run a single batch then exit')
    args = parser.parse_args()

    if args.once:
        logging.info('Running single batch (size=%s)', args.batch_size)
        worker = CacheWorker(
            batch_size=args.batch_size,
            sleep_sec=args.sleep,
            max_idle_rounds=0,
            idle_backoff=args.idle_backoff,
        )
        before = uncached_count()
        logging.info('%s uncached images', before)
        worker.run_batch()
        after = uncached_count()
        logging.info('Done — %s cached, %s remaining', before - after, after)
        return

    worker = CacheWorker(
        batch_size=args.batch_size,
        sleep_sec=args.sleep,
        max_idle_rounds=args.max_idle_rounds,
        idle_backoff=args.idle_backoff,
    )
    worker.run()


if __name__ == '__main__':
    main()
