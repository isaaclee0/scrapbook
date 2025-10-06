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
    
    def get_db_connection():
        return mysql.connector.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            user=os.getenv('DB_USER', 'db'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME', 'db'),
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci'
        )

def add_board_default_image_column():
    """Add default_image_url column to boards table"""
    db = None
    cursor = None
    
    try:
        db = get_db_connection()
        cursor = db.cursor()
        
        print("🔄 Checking if default_image_url column exists in boards table...")
        
        # Check if column already exists
        cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = DATABASE() 
            AND TABLE_NAME = 'boards' 
            AND COLUMN_NAME = 'default_image_url'
        """)
        
        column_exists = cursor.fetchone()[0] > 0
        
        if column_exists:
            print("✅ default_image_url column already exists in boards table")
            return True
        
        print("📝 Adding default_image_url column to boards table...")
        
        # Add the column
        cursor.execute("""
            ALTER TABLE boards 
            ADD COLUMN default_image_url TEXT NULL 
            AFTER name
        """)
        
        db.commit()
        
        print("✅ Successfully added default_image_url column to boards table")
        return True
        
    except mysql.connector.Error as e:
        print(f"❌ Error adding default_image_url column: {e}")
        if db:
            db.rollback()
        return False
        
    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()

if __name__ == "__main__":
    print("=" * 60)
    print("Board Default Image Migration - v1.5.4")
    print("=" * 60)
    success = add_board_default_image_column()
    print("=" * 60)
    
    if success:
        print("✅ Migration completed successfully!")
        sys.exit(0)
    else:
        print("❌ Migration failed!")
        sys.exit(1)

