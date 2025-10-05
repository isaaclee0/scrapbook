# Database Migrations

This document explains how to manage database schema changes for Scrapbook.

## Quick Start

### Running Migrations

**Via Docker (recommended for production):**
```bash
docker-compose exec web python migrate.py
```

**Locally (for development):**
```bash
python migrate.py
```

The migration script is **idempotent** - it's safe to run multiple times. It will only apply changes that haven't been applied yet.

## What Gets Migrated

The `migrate.py` script brings your database up to **v1.5.0** schema, which includes:

### Tables Created
- ✅ `users` - User accounts for authentication
- ✅ `boards` - Pin boards (with user ownership)
- ✅ `sections` - Board sections (with user ownership)
- ✅ `pins` - Individual pins (with user ownership)
- ✅ `cached_images` - Optimized image cache
- ✅ `url_health` - URL health monitoring

### Columns Added
- ✅ `user_id` to `boards`, `pins`, and `sections` tables
- ✅ `slug` and `updated_at` to `boards`
- ✅ `cached_image_id` and `uses_cached_image` to `pins`
- ✅ Color extraction columns to `pins` (`dominant_color`, `palette_color_1-5`)

### Indexes Created
Performance indexes on frequently queried columns

## Migration Workflow

### For Existing Databases

If you have an existing Scrapbook installation from before v1.5.0:

1. **Backup your database** (always!)
   ```bash
   docker-compose exec db mysqldump -u db -p db > backup_$(date +%Y%m%d).sql
   ```

2. **Run migrations**
   ```bash
   docker-compose exec web python migrate.py
   ```

3. **Verify the migration**
   The script will show a summary of all tables and row counts

### For New Installations

New installations automatically get the correct schema via `init.sql`. No migration needed!

## Environment Variables

The migration script uses these environment variables (automatically configured in Docker):

- `DB_HOST` - Database hostname (default: `db`)
- `DB_USER` - Database username (default: `db`)
- `DB_PASSWORD` - Database password (from `.env`)
- `DB_NAME` - Database name (default: `db`)
- `DEFAULT_USER_EMAIL` - Email for the default admin user (default: `admin@localhost`)

## Manual Migrations

If you need to run specific migration scripts from the `scripts/` directory:

```bash
# Create users table
docker-compose exec web python scripts/create_users_table.py

# Add user ownership to boards and pins
docker-compose exec web python scripts/add_user_ownership.py
```

## Troubleshooting

### "Table already exists" warnings
This is normal! The migration script checks for existing tables/columns and skips them.

### Foreign key errors
Make sure to run migrations in the correct order (use `migrate.py` which handles this automatically).

### Permission errors
Ensure your database user has `ALTER TABLE` and `CREATE TABLE` privileges.

### Connection refused
1. Check that the database container is running: `docker-compose ps`
2. Verify credentials in `.env` file
3. Check database logs: `docker-compose logs db`

## Schema Version History

- **v1.5.0** (Current)
  - Multi-user authentication system
  - User ownership for all content
  - Image caching and color extraction
  - Inline section creation

- **v1.1.2** 
  - Video frame extraction
  - Retry limits for URL health checks

- **v1.1.1**
  - Development-only console logging

- **v1.1.0**
  - Automatic image caching
  - Color processing system

## Creating New Migrations

When adding new features that require schema changes:

1. **Update `init.sql`** with the new schema (for fresh installs)
2. **Add migration logic to `migrate.py`** (for existing installs)
3. **Test on a copy of production data**
4. **Document the changes** in this file

### Example Migration Pattern

```python
# Check if column exists
if not column_exists(cursor, 'table_name', 'new_column'):
    cursor.execute("""
        ALTER TABLE table_name 
        ADD COLUMN new_column VARCHAR(255) DEFAULT NULL
    """)
    success("Added new_column to table_name")
else:
    warning("table_name.new_column already exists")
```

## Rollback Strategy

To rollback a migration:

1. **Restore from backup** (safest option)
   ```bash
   docker-compose exec -T db mysql -u db -p db < backup_20241005.sql
   ```

2. **Manual rollback** (advanced)
   - Drop added columns: `ALTER TABLE table_name DROP COLUMN column_name;`
   - Drop added tables: `DROP TABLE table_name;`
   - Remove added indexes: `DROP INDEX index_name ON table_name;`

## Best Practices

1. ✅ **Always backup before migrating**
2. ✅ **Test migrations on a staging environment first**
3. ✅ **Run migrations during low-traffic periods**
4. ✅ **Monitor application logs after migration**
5. ✅ **Keep migrations idempotent** (safe to run multiple times)
6. ✅ **Document all schema changes**

## Support

If you encounter issues with migrations:
1. Check the troubleshooting section above
2. Review Docker logs: `docker-compose logs web`
3. Verify your schema: `docker-compose exec db mysql -u db -p db -e "SHOW TABLES;"`

