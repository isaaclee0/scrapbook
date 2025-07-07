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

def add_color_columns():
    """Add dominant color columns to pins table"""
    try:
        db = get_db_connection()
        cursor = db.cursor()
        
        print("Adding dominant color columns to pins table...")
        
        # Add columns for storing dominant colors
        cursor.execute("""
            ALTER TABLE pins 
            ADD COLUMN IF NOT EXISTS dominant_color_1 VARCHAR(50) DEFAULT NULL,
            ADD COLUMN IF NOT EXISTS dominant_color_2 VARCHAR(50) DEFAULT NULL,
            ADD COLUMN IF NOT EXISTS colors_extracted BOOLEAN DEFAULT FALSE
        """)
        
        db.commit()
        print("✅ Successfully added color columns to pins table")
        
        # Check current pins that need color processing
        cursor.execute("SELECT COUNT(*) as count FROM pins WHERE colors_extracted = FALSE OR colors_extracted IS NULL")
        result = cursor.fetchone()
        unprocessed_count = result[0] if result else 0
        
        print(f"📊 Found {unprocessed_count} pins that could benefit from color extraction")
        
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
    print("🎨 Adding pin color schema...")
    success = add_color_columns()
    if success:
        print("✅ Schema update completed successfully!")
    else:
        print("❌ Schema update failed!")
        sys.exit(1) 