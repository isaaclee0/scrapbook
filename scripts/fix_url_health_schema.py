#!/usr/bin/env python3
"""
Fix URL health table schema mismatch.
This script updates the url_health table to have the correct ENUM values.
"""

import mysql.connector
import os

# Database configuration
dbconfig = {
    "host": os.getenv('DB_HOST', 'db'),
    "user": os.getenv('DB_USER', 'db'),
    "password": os.getenv('DB_PASSWORD'),
    "database": os.getenv('DB_NAME', 'db'),
    "charset": 'utf8mb4',
    "collation": 'utf8mb4_unicode_ci'
}

def fix_url_health_schema():
    """Fix the URL health table schema to match the application expectations."""
    try:
        # Connect to the database
        db = mysql.connector.connect(**dbconfig)
        cursor = db.cursor()
        
        print("🔍 Checking current URL health table schema...")
        
        # Check if the table exists
        cursor.execute("SHOW TABLES LIKE 'url_health'")
        if not cursor.fetchone():
            print("❌ URL health table does not exist. Creating it...")
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
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """)
            db.commit()
            print("✅ URL health table created successfully!")
            return
        
        # Check the current ENUM values
        cursor.execute("""
            SELECT COLUMN_TYPE 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE() 
            AND TABLE_NAME = 'url_health' 
            AND COLUMN_NAME = 'status'
        """)
        
        result = cursor.fetchone()
        if result:
            current_enum = result[0]
            print(f"📋 Current status ENUM: {current_enum}")
            
            # Check if we need to update the ENUM
            if "'healthy'" in current_enum and "'live'" not in current_enum:
                print("🔧 Updating status ENUM from 'healthy' to 'live'...")
                
                # First, update any existing 'healthy' values to 'live'
                cursor.execute("UPDATE url_health SET status = 'live' WHERE status = 'healthy'")
                updated_rows = cursor.rowcount
                print(f"📝 Updated {updated_rows} rows from 'healthy' to 'live'")
                
                # Now modify the ENUM column
                cursor.execute("""
                    ALTER TABLE url_health 
                    MODIFY COLUMN status ENUM('unknown', 'live', 'broken', 'archived') DEFAULT 'unknown'
                """)
                
                db.commit()
                print("✅ URL health table schema updated successfully!")
                
            elif "'live'" in current_enum:
                print("✅ Schema is already correct (has 'live' value)")
            else:
                print("⚠️  Unexpected ENUM values found. Current schema:")
                print(f"   {current_enum}")
                print("   Expected: ENUM('unknown', 'live', 'broken', 'archived')")
        
        # Verify the final schema
        cursor.execute("""
            SELECT COLUMN_TYPE 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE() 
            AND TABLE_NAME = 'url_health' 
            AND COLUMN_NAME = 'status'
        """)
        
        final_result = cursor.fetchone()
        if final_result:
            print(f"✅ Final status ENUM: {final_result[0]}")
        
    except mysql.connector.Error as err:
        print(f"❌ Database error: {err}")
        if 'db' in locals():
            db.rollback()
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        if 'db' in locals():
            db.rollback()
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'db' in locals():
            try:
                db.close()
            except:
                pass

if __name__ == "__main__":
    print("🔧 Fixing URL health table schema...")
    fix_url_health_schema()
    print("✨ Schema fix completed!") 