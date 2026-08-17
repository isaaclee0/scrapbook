#!/usr/bin/env python3
"""
Database Migration Script for Scrappl v1.5.0

This script automatically migrates the database to the latest schema.
It's safe to run multiple times - it checks for existing tables/columns before creating them.

Usage:
    python migrate.py
    
Or via Docker:
    docker-compose exec web python migrate.py
"""

import mysql.connector
import os
import sys
import json
from datetime import datetime


LEGACY_HTML_MIGRATION = '2026-08-18-normalize-legacy-html-entities'
LEGACY_TEXT_COLUMNS = {
    'boards': ('name',),
    'sections': ('name',),
    'pins': ('title', 'description', 'notes'),
    'api_tokens': ('name',),
}

# ANSI color codes for pretty output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def log(message, color=''):
    """Print colored log message"""
    print(f"{color}{message}{Colors.END}")

def success(message):
    log(f"✅ {message}", Colors.GREEN)

def warning(message):
    log(f"⚠️  {message}", Colors.YELLOW)

def error(message):
    log(f"❌ {message}", Colors.RED)

def info(message):
    log(f"ℹ️  {message}", Colors.BLUE)

def get_db_connection():
    """Get database connection"""
    try:
        return mysql.connector.connect(
            host=os.getenv('DB_HOST', 'db'),
            user=os.getenv('DB_USER', 'db'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME', 'db'),
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci'
        )
    except mysql.connector.Error as err:
        error(f"Database connection failed: {err}")
        sys.exit(1)

def table_exists(cursor, table_name):
    """Check if a table exists"""
    cursor.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = %s
    """, (table_name,))
    return cursor.fetchone()[0] > 0

def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table"""
    cursor.execute("""
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema = DATABASE()
        AND table_name = %s
        AND column_name = %s
    """, (table_name, column_name))
    return cursor.fetchone()[0] > 0

def index_exists(cursor, table_name, index_name):
    """Check if an index exists"""
    cursor.execute("""
        SELECT COUNT(*) FROM information_schema.statistics
        WHERE table_schema = DATABASE()
        AND table_name = %s
        AND index_name = %s
    """, (table_name, index_name))
    return cursor.fetchone()[0] > 0

def execute_sql(cursor, sql, success_msg, skip_msg=None):
    """Execute SQL and handle errors gracefully"""
    try:
        cursor.execute(sql)
        success(success_msg)
        return True
    except mysql.connector.Error as e:
        if "Duplicate" in str(e) or "already exists" in str(e):
            if skip_msg:
                warning(skip_msg)
            return False
        else:
            error(f"Error: {e}")
            return False


def decode_legacy_html_entities(value):
    """Reverse every layer added by the old storage-time html.escape call."""
    if not isinstance(value, str):
        return value

    decoded = value
    while True:
        next_value = (decoded
                      .replace('&quot;', '"')
                      .replace('&#x27;', "'")
                      .replace('&lt;', '<')
                      .replace('&gt;', '>')
                      .replace('&amp;', '&'))
        if next_value == decoded:
            return decoded
        decoded = next_value


def decode_legacy_json_value(value):
    if isinstance(value, dict):
        return {key: decode_legacy_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_legacy_json_value(item) for item in value]
    if isinstance(value, str):
        return decode_legacy_html_entities(value)
    return value


def _decode_json_document(value):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        value = value.decode('utf-8')
    document = json.loads(value) if isinstance(value, str) else value
    return json.dumps(decode_legacy_json_value(document), ensure_ascii=False)


def migrate_legacy_html_entities(cursor):
    """Normalize text escaped by pre-2.5.9 releases, exactly once."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name VARCHAR(191) PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    cursor.execute("SELECT 1 FROM schema_migrations WHERE name = %s", (LEGACY_HTML_MIGRATION,))
    if cursor.fetchone():
        return 0

    changed_rows = 0
    for table, columns in LEGACY_TEXT_COLUMNS.items():
        if not table_exists(cursor, table):
            continue

        cursor.execute(f"SELECT id, {', '.join(columns)} FROM {table}")
        for row in cursor.fetchall() or []:
            row_id, *values = row
            decoded = [decode_legacy_html_entities(value) for value in values]
            if decoded == values:
                continue
            assignments = ', '.join(f"{column} = %s" for column in columns)
            cursor.execute(
                f"UPDATE {table} SET {assignments} WHERE id = %s",
                tuple(decoded) + (row_id,),
            )
            changed_rows += 1

    if table_exists(cursor, 'audit_log'):
        cursor.execute(
            "SELECT id, actor_email, before_data, after_data, metadata FROM audit_log"
        )
        for row_id, actor_email, before_data, after_data, metadata in cursor.fetchall() or []:
            decoded_values = (
                decode_legacy_html_entities(actor_email),
                _decode_json_document(before_data),
                _decode_json_document(after_data),
                _decode_json_document(metadata),
            )
            original_values = (
                actor_email,
                before_data.decode('utf-8') if isinstance(before_data, (bytes, bytearray)) else before_data,
                after_data.decode('utf-8') if isinstance(after_data, (bytes, bytearray)) else after_data,
                metadata.decode('utf-8') if isinstance(metadata, (bytes, bytearray)) else metadata,
            )
            comparable_original = tuple(
                json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                for value in original_values
            )
            if decoded_values == comparable_original:
                continue
            cursor.execute("""
                UPDATE audit_log
                SET actor_email = %s, before_data = %s, after_data = %s, metadata = %s
                WHERE id = %s
            """, decoded_values + (row_id,))
            changed_rows += 1

    cursor.execute(
        "INSERT INTO schema_migrations (name) VALUES (%s)",
        (LEGACY_HTML_MIGRATION,),
    )
    return changed_rows

def migrate_database():
    """Main migration function"""
    log("\n" + "="*60, Colors.BOLD)
    log("🚀 Scrappl Database Migration to v1.5.0", Colors.BOLD)
    log("="*60 + "\n", Colors.BOLD)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Migration Step 1: Create users table
        info("Step 1: Users table")
        if not table_exists(cursor, 'users'):
            cursor.execute("""
                CREATE TABLE users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    INDEX idx_email (email)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            success("Created users table")
        else:
            warning("Users table already exists")
        
        # Migration Step 2: Add user_id to boards
        info("\nStep 2: Add user ownership to boards")
        if not column_exists(cursor, 'boards', 'user_id'):
            # First, ensure at least one user exists (for default value)
            cursor.execute("SELECT COUNT(*) FROM users")
            user_count = cursor.fetchone()[0]
            
            if user_count == 0:
                warning("No users found, creating default user")
                default_email = os.getenv('DEFAULT_USER_EMAIL', 'admin@localhost')
                cursor.execute("INSERT INTO users (email, created_at) VALUES (%s, NOW())", (default_email,))
                conn.commit()
                info(f"Created default user: {default_email}")
            
            cursor.execute("SELECT id FROM users ORDER BY id LIMIT 1")
            default_user_id = cursor.fetchone()[0]
            
            cursor.execute("""
                ALTER TABLE boards
                ADD COLUMN user_id INT NOT NULL DEFAULT %s
            """, (default_user_id,))
            cursor.execute("""
                ALTER TABLE boards 
                ADD INDEX idx_boards_user_id (user_id),
                ADD FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            """)
            success("Added user_id to boards")
        else:
            warning("Boards.user_id already exists")
        
        # Migration Step 3: Add user_id to pins
        info("\nStep 3: Add user ownership to pins")
        if not column_exists(cursor, 'pins', 'user_id'):
            cursor.execute("SELECT id FROM users ORDER BY id LIMIT 1")
            default_user_id = cursor.fetchone()[0]
            
            cursor.execute("""
                ALTER TABLE pins
                ADD COLUMN user_id INT NOT NULL DEFAULT %s
            """, (default_user_id,))
            cursor.execute("""
                ALTER TABLE pins 
                ADD INDEX idx_pins_user_id (user_id),
                ADD FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            """)
            success("Added user_id to pins")
        else:
            warning("Pins.user_id already exists")
        
        # Migration Step 4: Add user_id to sections
        info("\nStep 4: Add user ownership to sections")
        if not column_exists(cursor, 'sections', 'user_id'):
            cursor.execute("SELECT id FROM users ORDER BY id LIMIT 1")
            default_user_id = cursor.fetchone()[0]
            
            cursor.execute("""
                ALTER TABLE sections
                ADD COLUMN user_id INT NOT NULL DEFAULT %s
            """, (default_user_id,))
            cursor.execute("""
                ALTER TABLE sections 
                ADD INDEX idx_sections_user_id (user_id),
                ADD FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            """)
            success("Added user_id to sections")
        else:
            warning("Sections.user_id already exists")
        
        # Migration Step 5: Create cached_images table
        info("\nStep 5: Image caching system")
        if not table_exists(cursor, 'cached_images'):
            cursor.execute("""
                CREATE TABLE cached_images (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    original_url VARCHAR(2048) NOT NULL,
                    cached_filename VARCHAR(255) NOT NULL,
                    file_size INT DEFAULT 0,
                    width INT DEFAULT 0,
                    height INT DEFAULT 0,
                    quality_level ENUM('thumbnail', 'low', 'medium') DEFAULT 'low',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    cache_status ENUM('pending', 'cached', 'failed', 'expired') DEFAULT 'pending',
                    retry_count INT DEFAULT 0,
                    last_retry_at TIMESTAMP NULL,
                    UNIQUE KEY unique_url_quality (original_url(500), quality_level),
                    INDEX idx_cached_images_original_url (original_url(500)),
                    INDEX idx_cached_images_status (cache_status),
                    INDEX idx_cached_images_created_at (created_at),
                    INDEX idx_cached_images_retry (retry_count, last_retry_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            success("Created cached_images table")
        else:
            warning("cached_images table already exists")
        
        # Migration Step 6: Add cached image reference to pins
        info("\nStep 6: Link pins to cached images")
        if not column_exists(cursor, 'pins', 'cached_image_id'):
            cursor.execute("""
                ALTER TABLE pins 
                ADD COLUMN cached_image_id INT DEFAULT NULL,
                ADD COLUMN uses_cached_image BOOLEAN DEFAULT FALSE
            """)
            success("Added cached image columns to pins")
        else:
            warning("Pins already have cached image columns")
        
        # Migration Step 7: Add color extraction columns to pins
        info("\nStep 7: Color extraction system")
        color_columns = ['dominant_color', 'palette_color_1', 'palette_color_2', 
                        'palette_color_3', 'palette_color_4', 'palette_color_5']
        
        colors_added = False
        for color_col in color_columns:
            if not column_exists(cursor, 'pins', color_col):
                cursor.execute(f"ALTER TABLE pins ADD COLUMN {color_col} VARCHAR(7) DEFAULT NULL")
                colors_added = True
        
        if colors_added:
            success("Added color extraction columns to pins")
        else:
            warning("Pins already have color columns")
        
        # Migration Step 8: Ensure url_health table has correct schema
        info("\nStep 8: URL health tracking")
        if table_exists(cursor, 'url_health'):
            # Check if it has the old schema and update if needed
            if not column_exists(cursor, 'url_health', 'archive_url'):
                warning("Updating url_health schema to latest version")
                cursor.execute("DROP TABLE url_health")
                cursor.execute("""
                    CREATE TABLE url_health (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        pin_id INT NOT NULL,
                        url VARCHAR(2048) NOT NULL,
                        last_checked DATETIME,
                        status ENUM('unknown', 'live', 'broken', 'archived') DEFAULT 'unknown',
                        archive_url VARCHAR(2048),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        FOREIGN KEY (pin_id) REFERENCES pins(id) ON DELETE CASCADE,
                        UNIQUE KEY unique_url_health_pin_id (pin_id),
                        INDEX idx_url_health_status (status),
                        INDEX idx_url_health_last_checked (last_checked)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                success("Updated url_health table to latest schema")
            else:
                warning("url_health already at latest version")
        else:
            cursor.execute("""
                CREATE TABLE url_health (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    pin_id INT NOT NULL,
                    url VARCHAR(2048) NOT NULL,
                    last_checked DATETIME,
                    status ENUM('unknown', 'live', 'broken', 'archived') DEFAULT 'unknown',
                    archive_url VARCHAR(2048),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (pin_id) REFERENCES pins(id) ON DELETE CASCADE,
                    UNIQUE KEY unique_url_health_pin_id (pin_id),
                    INDEX idx_url_health_status (status),
                    INDEX idx_url_health_last_checked (last_checked)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            success("Created url_health table")
        
        # Migration Step 8b: Deduplicate url_health rows and enforce one row per pin
        info("\nStep 8b: url_health deduplication and unique constraint")
        if table_exists(cursor, 'url_health'):
            cursor.execute("""
                DELETE t1 FROM url_health t1
                INNER JOIN url_health t2
                ON t1.pin_id = t2.pin_id
                AND (
                    t1.last_checked < t2.last_checked
                    OR (t1.last_checked IS NULL AND t2.last_checked IS NOT NULL)
                    OR (t1.last_checked <=> t2.last_checked AND t1.id < t2.id)
                )
            """)
            deleted = cursor.rowcount
            if deleted:
                success(f"Removed {deleted} duplicate url_health rows")

            if not index_exists(cursor, 'url_health', 'unique_url_health_pin_id'):
                try:
                    cursor.execute(
                        "ALTER TABLE url_health ADD UNIQUE KEY unique_url_health_pin_id (pin_id)"
                    )
                    success("Added unique constraint on url_health.pin_id")
                except mysql.connector.Error as e:
                    if "Duplicate" not in str(e):
                        warning(f"Could not add unique constraint on url_health.pin_id: {e}")
            else:
                warning("url_health.pin_id unique constraint already exists")

            cursor.execute(
                "UPDATE pins SET link = REPLACE(link, '&amp;', '&') WHERE link LIKE '%&amp;%'"
            )
            fixed_links = cursor.rowcount
            if fixed_links:
                success(f"Fixed {fixed_links} links with HTML-escaped ampersands")
        
        # Migration Step 9: Add slug and updated_at to boards if missing
        info("\nStep 9: Board enhancements")
        if not column_exists(cursor, 'boards', 'slug'):
            cursor.execute("""
                ALTER TABLE boards 
                ADD COLUMN slug VARCHAR(255) UNIQUE,
                ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            """)
            success("Added slug and updated_at to boards")
        else:
            warning("Boards already have slug column")
        
        # Migration Step 10: Create OTP codes table
        info("\nStep 10: OTP authentication system")
        if not table_exists(cursor, 'otp_codes'):
            cursor.execute("""
                CREATE TABLE otp_codes (
                    email VARCHAR(255) NOT NULL,
                    otp VARCHAR(6) NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (email),
                    INDEX idx_otp_expires_at (expires_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            success("Created otp_codes table")
        else:
            warning("otp_codes table already exists")
        
        # Migration Step 10b: Add retry tracking columns to cached_images
        info("\nStep 10b: Add retry tracking columns to cached_images")
        if not column_exists(cursor, 'cached_images', 'retry_count'):
            cursor.execute("""
                ALTER TABLE cached_images
                ADD COLUMN retry_count INT DEFAULT 0,
                ADD COLUMN last_retry_at TIMESTAMP NULL
            """)
            success("Added retry_count and last_retry_at to cached_images")
        else:
            warning("cached_images already has retry columns")

        # Migration Step 11: Ensure all indexes exist
        info("\nStep 11: Performance indexes")
        indexes = [
            ('boards', 'idx_boards_created_at', 'created_at'),
            ('boards', 'idx_boards_slug', 'slug'),
            ('sections', 'idx_sections_created_at', 'created_at'),
            ('pins', 'idx_pins_updated_at', 'updated_at'),
            ('pins', 'idx_pins_title', 'title(100)'),
        ]
        
        for table, idx_name, column in indexes:
            if not index_exists(cursor, table, idx_name):
                try:
                    cursor.execute(f"CREATE INDEX {idx_name} ON {table}({column})")
                    success(f"Created index {idx_name} on {table}")
                except mysql.connector.Error as e:
                    if "Duplicate" not in str(e):
                        warning(f"Could not create index {idx_name}: {e}")
        
        # Commit all changes
        conn.commit()
        
        # Migration Step 13: Audit log
        info("\nStep 13: Audit log")
        if not table_exists(cursor, 'audit_log'):
            cursor.execute("""
                CREATE TABLE audit_log (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    created_at TIMESTAMP(3) DEFAULT CURRENT_TIMESTAMP(3),
                    user_id INT NULL,
                    actor_email VARCHAR(255),
                    action VARCHAR(64) NOT NULL,
                    entity_type VARCHAR(32) NOT NULL,
                    entity_id INT NULL,
                    before_data JSON NULL,
                    after_data JSON NULL,
                    metadata JSON NULL,
                    request_id VARCHAR(40),
                    ip_address VARCHAR(45),
                    outcome ENUM('success','failure') DEFAULT 'success',
                    INDEX idx_audit_created (created_at),
                    INDEX idx_audit_user (user_id, created_at),
                    INDEX idx_audit_entity (entity_type, entity_id, created_at),
                    INDEX idx_audit_action (action, created_at),
                    INDEX idx_audit_outcome (outcome, created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            success("Created audit_log table")
        else:
            warning("audit_log table already exists")

        # Migration Step 14: API tokens table
        info("\nStep 14: API tokens (personal access tokens)")
        if not table_exists(cursor, 'api_tokens'):
            cursor.execute("""
                CREATE TABLE api_tokens (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    token_hash CHAR(64) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TIMESTAMP NULL,
                    revoked_at TIMESTAMP NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    INDEX idx_api_tokens_hash (token_hash),
                    INDEX idx_api_tokens_user (user_id, revoked_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            success("Created api_tokens table")
        else:
            warning("api_tokens table already exists")

        # Migration Step 15: Normalize text escaped before storage by older releases.
        info("\nStep 15: Normalize legacy HTML entities")
        normalized_rows = migrate_legacy_html_entities(cursor)
        if normalized_rows:
            success(f"Normalized {normalized_rows} rows containing legacy HTML entities")
        else:
            warning("Legacy HTML entity migration already applied or no rows needed changes")
        conn.commit()

        # Migration Step 12: Summary
        info("\nStep 12: Migration summary")
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM boards")
        board_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM pins")
        pin_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM sections")
        section_count = cursor.fetchone()[0]
        
        log("\n" + "="*60, Colors.BOLD)
        success("Migration completed successfully!")
        log("="*60, Colors.BOLD)
        log("\n📊 Database Statistics:", Colors.BOLD)
        info(f"   Users:    {user_count}")
        info(f"   Boards:   {board_count}")
        info(f"   Sections: {section_count}")
        info(f"   Pins:     {pin_count}")
        log("")
        
    except Exception as e:
        error(f"Migration failed: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()
    
    return True

if __name__ == "__main__":
    success_flag = migrate_database()
    sys.exit(0 if success_flag else 1)
