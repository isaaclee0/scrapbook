# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Scrappl is a self-hosted, Pinterest-like personal image collection manager built with Flask. Core features: board/section organization, image scraping from URLs, URL health monitoring (Wayback Machine integration), OTP-based passwordless auth (via Brevo email), and Redis view caching.

## Running the App

**Docker (recommended):**
```bash
cp .env.example .env   # fill in secrets
docker compose build --no-cache
docker compose up -d   # app on :8000, phpMyAdmin on :8888
```

**Local dev** (requires a running MariaDB and optional Redis):
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export DB_HOST=localhost  # and other vars from .env.example
python app.py
```

**Database migrations** (idempotent, safe to rerun):
```bash
docker compose exec web python migrate.py
```

**Image cache worker** (production backfill — runs as `cache-worker` service):
```bash
docker compose up -d cache-worker
docker compose logs -f cache-worker
```

**CSS** (Tailwind):
```bash
npm run build:css    # one-shot build
npm run watch:css    # watch mode during dev
```

**Health check:** `GET /health`

## Architecture

Single-file Flask app (`app.py`, ~3,200 lines) with MariaDB, optional Redis, and Brevo for email.

**Key source files:**
- `app.py` — all routes (40+) and business logic
- `auth_utils.py` — JWT generation/validation, OTP handling, session refresh
- `email_service.py` — OTP and welcome emails via Brevo API
- `migrate.py` — idempotent schema migrations
- `init.sql` — initial DB schema
- `scripts/image_cache_service.py` — background async image caching with Pillow

**Database tables:** `users`, `boards`, `sections`, `pins`, `cached_images`, `url_health`, `otp_codes`

**Multi-tenancy:** every table has a `user_id` FK; all queries filter by it. The default user is seeded in `init.sql`.

**Authentication flow:** login form → OTP emailed via Brevo → verify OTP → 30-day JWT session cookie (HttpOnly, SameSite=Lax). Token auto-refreshes within 7 days of expiry.

**Caching:** Redis caches read-only views via the `@cache_view(timeout)` decorator. App falls back gracefully if Redis is unavailable.

**DB connections:** pool of 20 via `get_db_connection()`. Always release in `finally` blocks.

**Route shape:**
- `login_required` decorator returns JSON for `/api/*` endpoints and redirects for HTML views
- Sanitize all inputs through `sanitize_string()`, `sanitize_url()`, `sanitize_integer()` before DB queries

## Key Environment Variables

See `.env.example` for full list. Critical ones:

| Variable | Purpose |
|---|---|
| `DB_HOST/USER/PASSWORD/NAME` | MariaDB connection |
| `REDIS_HOST/PORT` | Cache (optional) |
| `BREVO_API_KEY` | Email delivery |
| `JWT_SECRET_KEY` | Token signing — change in production |
| `OTP_EXPIRY` | Default 600s |
| `SESSION_EXPIRY` | Default 2592000s (30 days) |
