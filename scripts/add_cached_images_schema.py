#!/usr/bin/env python3

import mysql.connector
import os
import sys

# Add the parent directory to Python path to import from app.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app import get_db_connection
except ImportError:
    print("Could not import from app.py, using direct connection")
    
    # Fallback database connection
    def get_db_connection():
        return mysql.connector.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            user=os.getenv('DB_USER', 'db'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME', 'db'),
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci'
        )

def add_cached_images_table():
    """Add cached images table to store low-quality cached versions of images"""
    try:
        db = get_db_connection()
        cursor = db.cursor()
        
        print("Creating cached images table...")
        
        # Create table for cached images
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cached_images (
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
                UNIQUE KEY unique_url_quality (original_url(500), quality_level),
                INDEX idx_cached_images_original_url (original_url(500)),
                INDEX idx_cached_images_status (cache_status),
                INDEX idx_cached_images_created_at (created_at)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        
        # Add cached image reference to pins table
        cursor.execute("""
            ALTER TABLE pins 
            ADD COLUMN IF NOT EXISTS cached_image_id INT DEFAULT NULL,
            ADD COLUMN IF NOT EXISTS uses_cached_image BOOLEAN DEFAULT FALSE
        """)
        
        # Add foreign key constraint
        cursor.execute("""
            ALTER TABLE pins 
            ADD CONSTRAINT fk_pins_cached_image 
            FOREIGN KEY (cached_image_id) REFERENCES cached_images(id) 
            ON DELETE SET NULL
        """)
        
        db.commit()
        print("✅ Successfully added cached images table and pin references")
        
        # Check current pins that could benefit from caching
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM pins 
            WHERE image_url LIKE 'http%' 
            AND (cached_image_id IS NULL OR uses_cached_image = FALSE)
        """)
        result = cursor.fetchone()
        uncached_count = result[0] if result else 0
        
        print(f"📊 Found {uncached_count} pins with external images that could benefit from caching")
        
    except mysql.connector.Error as e:
        print(f"❌ Database error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'db' in locals():
            db.close()
    
    return True

if __name__ == "__main__":
    print("📁 Adding cached images schema...")
    success = add_cached_images_table()
    if success:
        print("✅ Schema update completed successfully!")
    else:
        print("❌ Schema update failed!")
        sys.exit(1) 