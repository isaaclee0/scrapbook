# Cache worker reliability implementation plan

**Goal:** Restore useful cache queue processing and give the worker an activity-based Docker health check.

**Architecture:** Count and select using a shared SQL predicate joined by original URL and quality. The downloader applies the same predicate. Add nullable failure kind/error metadata; existing retry counts remain untouched. Heartbeats come from loop work, download chunks and completed tasks, plus deliberate sleeps, never an independent timer.

**Tech stack:** Python, unittest, Pillow, MariaDB, Docker Compose, Portainer.

## Constraints

Preserve all pins, cache files, database records and volumes. No global retry reset. Keep existing thumbnail scraping and direct-video frame extraction. Release through the repository's Docker Hub process, then update Portainer's persisted compose source.

## Steps

- [x] Recheck production health, public site, image version and aggregate retry state.
- [x] Reproduce queue/downloader disagreement, unlinked retry records, stale-pending bypass, and idle behavior in `tests/test_cache_worker.py`.
- [x] Add shared retry/queue SQL in `scripts/image_cache_service.py`; count only eligible work and filter before LIMIT. Preserve existing cached file reuse.
- [x] Persist retryable/unsupported/permanent HTTP failure kinds with idempotent additive migration in `migrate.py`, `init.sql`, and `scripts/add_cached_images_schema.py`.
- [x] Return actual batch results and refresh worker activity from real progress. Back off on empty queues, zero successful results, and database/batch errors.
- [x] Implement stdlib-only `python scripts/cache_worker.py --healthcheck`, checking heartbeat age and process existence. Test missing/corrupt/stale/dead process, legitimate sleeps and long batch progress.
- [x] Set worker-specific health checks in both maintained compose files.
- [x] Run `.venv/bin/python -m unittest discover -s tests -q`, plus disposable MariaDB integration and Docker health checks using production Python/dependencies.
- [x] Review diff, release a patch version through Git and multiarch Docker Hub, back up and update the existing Portainer stack file without printing secrets, recreate only web/worker.
- [x] Verify worker Docker health, actual queue results, unchanged record/volume counts, and public HTTP health. Record any terminal or exhausted failures honestly.
