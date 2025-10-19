#!/usr/bin/env python3
"""
Migration script to add image support to sections table
This script:
1. Adds a default_image_url column to sections table
2. Populates it with a random pin image from each section
"""
import os
import sys
import mysql.connector
from datetime import datetime

# Add parent directory to path to import from app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'db')
    )

def main():
    print("=" * 80)
    print("SECTIONS IMAGE MIGRATION")
    print("=" * 80)
    print()
    
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    # Step 1: Check if column already exists
    cursor.execute("""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'sections' 
        AND COLUMN_NAME = 'default_image_url'
    """)
    
    if cursor.fetchone():
        print("✓ Column 'default_image_url' already exists in sections table")
    else:
        print("Adding 'default_image_url' column to sections table...")
        cursor.execute("""
            ALTER TABLE sections 
            ADD COLUMN default_image_url TEXT NULL
            AFTER name
        """)
        db.commit()
        print("✓ Column added successfully")
    
    print()
    print("=" * 80)
    print("POPULATING SECTION IMAGES")
    print("=" * 80)
    print()
    
    # Step 2: For each section, get a random pin image
    cursor.execute("""
        SELECT s.id, s.name, s.board_id,
               (SELECT p.image_url 
                FROM pins p 
                WHERE p.section_id = s.id 
                  AND p.image_url IS NOT NULL 
                  AND p.image_url != ''
                ORDER BY RAND() 
                LIMIT 1) as random_image
        FROM sections s
    """)
    sections = cursor.fetchall()
    
    updated_count = 0
    no_image_count = 0
    
    for section in sections:
        if section['random_image']:
            cursor.execute("""
                UPDATE sections 
                SET default_image_url = %s 
                WHERE id = %s
            """, (section['random_image'], section['id']))
            updated_count += 1
            print(f"✓ Section '{section['name']}' (ID: {section['id']}) - image set")
        else:
            no_image_count += 1
            print(f"⚠ Section '{section['name']}' (ID: {section['id']}) - no pins with images")
    
    db.commit()
    
    print()
    print("=" * 80)
    print("MIGRATION COMPLETE")
    print("=" * 80)
    print(f"Sections with images set: {updated_count}")
    print(f"Sections without images: {no_image_count}")
    print()
    
    # Show some sample data
    print("Sample sections with images:")
    cursor.execute("""
        SELECT id, name, default_image_url 
        FROM sections 
        WHERE default_image_url IS NOT NULL 
        LIMIT 5
    """)
    samples = cursor.fetchall()
    for sample in samples:
        image_preview = sample['default_image_url'][:60] + '...' if len(sample['default_image_url']) > 60 else sample['default_image_url']
        print(f"  - {sample['name']}: {image_preview}")
    
    cursor.close()
    db.close()
    
    print()
    print("Done!")

if __name__ == '__main__':
    main()

