#!/usr/bin/env python3
"""
Add indexes to improve search performance.
"""

import sys
import os

# Add parent directory to path to import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import get_db_connection
import mysql.connector

def main():
    db = None
    cursor = None
    try:
        print("🔍 Adding search performance indexes...")
        db = get_db_connection()
        cursor = db.cursor()
        
        # Add fulltext indexes for faster LIKE searches
        # Note: For better performance with LIKE '%term%', consider upgrading to MySQL 5.7+ 
        # and using fulltext indexes, or use a search engine like Elasticsearch
        
        indexes = [
            ("idx_pins_title", "CREATE INDEX IF NOT EXISTS idx_pins_title ON pins(title)"),
            ("idx_pins_user_id", "CREATE INDEX IF NOT EXISTS idx_pins_user_id ON pins(user_id)"),
            ("idx_boards_name", "CREATE INDEX IF NOT EXISTS idx_boards_name ON boards(name)"),
            ("idx_boards_user_id", "CREATE INDEX IF NOT EXISTS idx_boards_user_id ON boards(user_id)"),
        ]
        
        for index_name, create_sql in indexes:
            try:
                print(f"Creating index: {index_name}...")
                cursor.execute(create_sql)
                print(f"✅ {index_name} created successfully")
            except mysql.connector.Error as err:
                if err.errno == 1061:  # Duplicate key name
                    print(f"ℹ️  {index_name} already exists")
                else:
                    print(f"⚠️  Error creating {index_name}: {err}")
        
        db.commit()
        print("\n✅ Search indexes added successfully!")
        print("\nNote: For very large datasets, consider using MySQL FULLTEXT indexes")
        print("or a dedicated search engine like Elasticsearch for better performance.")
        
    except mysql.connector.Error as err:
        print(f"❌ Database error: {err}")
        if db:
            db.rollback()
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()

if __name__ == "__main__":
    main()

