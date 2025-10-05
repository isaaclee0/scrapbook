#!/usr/bin/env python3
"""
Database Migration Script for Scrapbook v1.5.0

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
from datetime import datetime

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
    cursor.execute(f"""
        SELECT COUNT(*) FROM information_schema.tables 
        WHERE table_schema = DATABASE() AND table_name = '{table_name}'
    """)
    return cursor.fetchone()[0] > 0

def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table"""
    cursor.execute(f"""
        SELECT COUNT(*) FROM information_schema.columns 
        WHERE table_schema = DATABASE() 
        AND table_name = '{table_name}' 
        AND column_name = '{column_name}'
    """)
    return cursor.fetchone()[0] > 0

def index_exists(cursor, table_name, index_name):
    """Check if an index exists"""
    cursor.execute(f"""
        SELECT COUNT(*) FROM information_schema.statistics 
        WHERE table_schema = DATABASE() 
        AND table_name = '{table_name}' 
        AND index_name = '{index_name}'
    """)
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

def migrate_database():
    """Main migration function"""
    log("\n" + "="*60, Colors.BOLD)
    log("🚀 Scrapbook Database Migration to v1.5.0", Colors.BOLD)
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
            
            cursor.execute(f"""
                ALTER TABLE boards 
                ADD COLUMN user_id INT NOT NULL DEFAULT {default_user_id}
            """)
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
            
            cursor.execute(f"""
                ALTER TABLE pins 
                ADD COLUMN user_id INT NOT NULL DEFAULT {default_user_id}
            """)
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
            
            cursor.execute(f"""
                ALTER TABLE sections 
                ADD COLUMN user_id INT NOT NULL DEFAULT {default_user_id}
            """)
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
                        INDEX idx_url_health_pin_id (pin_id),
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
                    INDEX idx_url_health_pin_id (pin_id),
                    INDEX idx_url_health_status (status),
                    INDEX idx_url_health_last_checked (last_checked)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            success("Created url_health table")
        
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
        
        # Migration Step 10: Ensure all indexes exist
        info("\nStep 10: Performance indexes")
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
        
        # Migration Step 11: Summary
        info("\nStep 11: Migration summary")
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

