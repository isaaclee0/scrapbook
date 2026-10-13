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
    CACHE_WORKER_MAX_IDLE_ROUNDS  Back off after N unsuccessful batches (0/1 = immediately)
    CACHE_WORKER_IDLE_BACKOFF     Sleep when no work can progress (default: 300)
    CACHE_WORKER_HEARTBEAT_FILE   Local activity file (default: /tmp/scrappl-cache-worker.json)
    CACHE_WORKER_HEALTH_MAX_AGE   Maximum inactivity in seconds (default: 300)
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
import threading
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger('cache_worker')


class WorkerHeartbeat:
    """Written by processing activity, never by an independent liveness thread."""
    def __init__(self, path=None):
        self.path = Path(path or os.getenv('CACHE_WORKER_HEARTBEAT_FILE', '/tmp/scrappl-cache-worker.json'))
        self.lock = threading.Lock()
        self.last_write = None

    def touch(self, force=False):
        with self.lock:
            now = time.monotonic()
            if not force and self.last_write is not None and now - self.last_write < 5:
                return
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'pid': os.getpid(), 'at': time.time()}))
            temporary.replace(self.path)
            self.last_write = now

    def healthy(self):
        try:
            record = json.loads(self.path.read_text())
            pid = int(record['pid'])
            if pid <= 0:
                return False
            os.kill(pid, 0)
            age = time.time() - float(record['at'])
            return 0 <= age <= float(os.getenv('CACHE_WORKER_HEALTH_MAX_AGE', '300'))
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def remove(self):
        self.path.unlink(missing_ok=True)


def uncached_count():
    """Count work eligible now (not every external image still uncached)."""
    from scripts.image_cache_service import count_eligible_images
    return count_eligible_images()


class CacheWorker:
    def __init__(self, batch_size, sleep_sec, max_idle_rounds, idle_backoff):
        self.batch_size = batch_size
        self.sleep_sec = sleep_sec
        self.max_idle_rounds = max_idle_rounds
        self.idle_backoff = idle_backoff
        self.running = True
        self._service = None
        self.heartbeat = WorkerHeartbeat()

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
        return service.cache_all_external_images(
            limit=self.batch_size,
            process_dimensions=False,
            progress_callback=self.heartbeat.touch,
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
        self.heartbeat.touch(force=True)
        try:
            while self.running:
                try:
                    before = uncached_count()
                    self.heartbeat.touch()
                    if before == 0:
                        logger.info('No eligible images; sleeping %ss (failed items may be cooling down or exhausted)', self.idle_backoff)
                        self._interruptible_sleep(self.idle_backoff)
                        idle_rounds = 0
                        continue

                    batch_num += 1
                    logger.info('Batch %s: up to %s pins (%s eligible)', batch_num, self.batch_size, before)
                    result = self.run_batch()
                    after = uncached_count()
                    self.heartbeat.touch()
                    logger.info('Batch %s done: cached %s, failed/skipped %s, %s eligible remaining',
                                batch_num, result['cached'], result['failed_or_skipped'], after)
                    idle_rounds = idle_rounds + 1 if result['cached'] == 0 else 0
                    backoff = after == 0 or idle_rounds >= max(1, self.max_idle_rounds)
                    self._interruptible_sleep(self.idle_backoff if backoff else self.sleep_sec)
                except Exception:
                    logger.exception('Cache loop failed; backing off %ss', self.idle_backoff)
                    self._interruptible_sleep(self.idle_backoff)
        finally:
            self.heartbeat.remove()
            logger.info('Cache worker stopped')

    def _interruptible_sleep(self, seconds):
        """Sleep in small slices so SIGTERM is picked up promptly."""
        end = time.monotonic() + seconds
        while self.running:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            self.heartbeat.touch()
            time.sleep(min(1.0, remaining))


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
        help='Back off after N unsuccessful batches (0/1 = immediately)',
    )
    parser.add_argument(
        '--idle-backoff', type=float,
        default=float(os.getenv('CACHE_WORKER_IDLE_BACKOFF', '300')),
    )
    parser.add_argument('--healthcheck', action='store_true', help='Check recent processing activity and exit')
    parser.add_argument('--once', action='store_true', help='Run a single batch then exit')
    args = parser.parse_args()

    if args.healthcheck:
        return 0 if WorkerHeartbeat().healthy() else 1
    if args.batch_size <= 0 or args.sleep < 0 or args.idle_backoff <= 0:
        parser.error('batch-size and idle-backoff must be positive; sleep must be nonnegative')

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
        result = worker.run_batch()
        after = uncached_count()
        logging.info('Done — %s cached, %s failed/skipped, %s eligible remaining',
                     result['cached'], result['failed_or_skipped'], after)
        return

    worker = CacheWorker(
        batch_size=args.batch_size,
        sleep_sec=args.sleep,
        max_idle_rounds=args.max_idle_rounds,
        idle_backoff=args.idle_backoff,
    )
    worker.run()


if __name__ == '__main__':
    sys.exit(main())
