#!/usr/bin/env python3
"""
Migration script for v1.0.1
Creates the url_health table and other schema updates needed for existing deployments.
"""

import mysql.connector
import os
import sys

def get_db_connection():
    """Get database connection using environment variables"""
    dbconfig = {
        "host": os.getenv('DB_HOST', 'db'),
        "user": os.getenv('DB_USER', 'db'),
        "password": os.getenv('DB_PASSWORD'),
        "database": os.getenv('DB_NAME', 'db'),
        "charset": 'utf8mb4',
        "collation": 'utf8mb4_unicode_ci'
    }
    
    try:
        return mysql.connector.connect(**dbconfig)
    except mysql.connector.Error as err:
        print(f"❌ Error connecting to database: {err}")
        sys.exit(1)

def migrate_to_v1_0_1():
    """Run v1.0.1 migration"""
    print("🔄 Starting v1.0.1 migration...")
    
    try:
        db = get_db_connection()
        cursor = db.cursor()
        
        # Check if url_health table already exists
        cursor.execute("SHOW TABLES LIKE 'url_health'")
        table_exists = cursor.fetchone()
        
        if table_exists:
            print("✅ url_health table already exists, skipping creation")
        else:
            print("📋 Creating url_health table...")
            cursor.execute("""
                CREATE TABLE url_health (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    pin_id INT NOT NULL,
                    url VARCHAR(2048) NOT NULL,
                    last_checked DATETIME,
                    status ENUM('unknown', 'live', 'broken', 'archived') DEFAULT 'unknown',
                    archive_url VARCHAR(2048),
                    FOREIGN KEY (pin_id) REFERENCES pins(id) ON DELETE CASCADE
                )
            """)
            print("✅ url_health table created successfully")
        
        # Create indexes if they don't exist
        print("📋 Creating database indexes...")
        indexes_to_create = [
            ("idx_boards_name", "CREATE INDEX IF NOT EXISTS idx_boards_name ON boards(name)"),
            ("idx_pins_board_id", "CREATE INDEX IF NOT EXISTS idx_pins_board_id ON pins(board_id)"),
            ("idx_pins_section_id", "CREATE INDEX IF NOT EXISTS idx_pins_section_id ON pins(section_id)"),
            ("idx_sections_board_id", "CREATE INDEX IF NOT EXISTS idx_sections_board_id ON sections(board_id)"),
            ("idx_pins_created_at", "CREATE INDEX IF NOT EXISTS idx_pins_created_at ON pins(created_at)")
        ]
        
        for index_name, create_sql in indexes_to_create:
            try:
                cursor.execute(create_sql)
                print(f"✅ Index {index_name} created/verified")
            except mysql.connector.Error as err:
                print(f"⚠️  Index {index_name} already exists or error: {err}")
        
        # Check if we need to update any existing ENUM values in url_health table
        if table_exists:
            print("🔍 Checking url_health table schema...")
            cursor.execute("SHOW COLUMNS FROM url_health LIKE 'status'")
            column_info = cursor.fetchone()
            if column_info:
                # Check if the ENUM includes all required values
                enum_values = column_info[1].replace("enum(", "").replace(")", "").replace("'", "").split(",")
                required_values = ['unknown', 'live', 'broken', 'archived']
                
                if not all(value in enum_values for value in required_values):
                    print("⚠️  url_health.status ENUM needs updating...")
                    print("   This requires manual intervention. Please run the fix_url_health_schema_robust.py script.")
        
        db.commit()
        print("✅ Migration completed successfully!")
        
    except mysql.connector.Error as err:
        print(f"❌ Database error during migration: {err}")
        if 'db' in locals():
            db.rollback()
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error during migration: {e}")
        if 'db' in locals():
            db.rollback()
        sys.exit(1)
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'db' in locals():
            db.close()

if __name__ == '__main__':
    migrate_to_v1_0_1() 