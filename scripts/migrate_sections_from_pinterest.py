#!/usr/bin/env python3
"""
Production migration script to restore Pinterest section assignments
This script reads pins.zip and assigns pins to their correct sections

Usage:
    1. Make sure pins.zip is in the /app directory
    2. Run: python3 scripts/migrate_sections_from_pinterest.py
    
Or trigger from web interface via database version system
"""
import os
import sys
import json
import zipfile
import mysql.connector
from collections import defaultdict
import time

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', 'db'),
        user=os.getenv('DB_USER', 'db'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'db'),
        charset='utf8mb4',
        collation='utf8mb4_unicode_ci'
    )

def get_user_id(cursor, email=None):
    """Get the user ID for the main Pinterest import user
    
    If email not specified, finds the user with the most pins
    """
    if email:
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        result = cursor.fetchone()
        if result:
            return result[0]
    
    # Find user with most pins (the Pinterest import user)
    cursor.execute("""
        SELECT user_id, COUNT(*) as pin_count 
        FROM pins 
        GROUP BY user_id 
        ORDER BY pin_count DESC 
        LIMIT 1
    """)
    result = cursor.fetchone()
    if result:
        user_id = result[0]
        cursor.execute("SELECT email FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        print(f"Using user with most pins: {user[0] if user else user_id}")
        return user_id
    
    return None

def process_pinterest_zip(zip_path='pins.zip'):
    """Process the Pinterest export ZIP and extract section assignments"""
    if not os.path.exists(zip_path):
        print(f"❌ {zip_path} not found!")
        return None
    
    print(f"📦 Processing {zip_path}...")
    
    # Map of pin_id -> (board_slug, section_name)
    pin_section_map = {}
    board_pins = defaultdict(lambda: defaultdict(list))
    
    with zipfile.ZipFile(zip_path, 'r') as z:
        for file_path in z.namelist():
            if not file_path.endswith('.json'):
                continue
            
            if file_path.startswith('__MACOSX'):
                continue
            
            parts = file_path.split('/')
            
            # Structure: pins/board-name/section-name/pin.json (4 parts = has section)
            # OR:        pins/board-name/pin.json (3 parts = no section)
            if len(parts) == 4:
                board_slug = parts[1]
                section_name = parts[2]
                pin_filename = parts[3]
                pin_id = os.path.splitext(pin_filename)[0]
                
                # Skip hidden files
                if board_slug.startswith('.') or section_name.startswith('.'):
                    continue
                
                pin_section_map[pin_id] = (board_slug, section_name)
                board_pins[board_slug][section_name].append(pin_id)
    
    print(f"✓ Found {len(pin_section_map):,} pins with section assignments")
    print(f"✓ Across {len(board_pins)} boards")
    print()
    
    return pin_section_map, board_pins

def get_or_create_section(cursor, db, board_id, section_name, user_id):
    """Get existing section or create new one"""
    cursor.execute("""
        SELECT id FROM sections 
        WHERE board_id = %s AND name = %s AND user_id = %s
    """, (board_id, section_name, user_id))
    
    result = cursor.fetchone()
    if result:
        return result[0]
    
    # Create new section
    cursor.execute("""
        INSERT INTO sections (board_id, name, user_id, created_at, updated_at)
        VALUES (%s, %s, %s, NOW(), NOW())
    """, (board_id, section_name, user_id))
    db.commit()
    
    return cursor.lastrowid

def apply_section_assignments(pin_section_map, user_id):
    """Apply section assignments to database"""
    db = get_db_connection()
    cursor = db.cursor()
    
    print("=" * 80)
    print("APPLYING SECTION ASSIGNMENTS")
    print("=" * 80)
    print()
    
    # Get board name mapping (slug -> DB board_id)
    cursor.execute("SELECT id, name FROM boards WHERE user_id = %s", (user_id,))
    boards = cursor.fetchall()
    
    board_map = {}
    for board_id, board_name in boards:
        # Create slug from board name
        slug = board_name.lower().replace(' ', '-')
        board_map[slug] = board_id
    
    print(f"Found {len(board_map)} boards in database")
    print()
    
    # Process pin assignments
    updates_to_apply = []
    sections_to_create = defaultdict(set)
    matched_pins = 0
    unmatched_pins = 0
    
    for pin_id, (board_slug, section_name) in pin_section_map.items():
        if board_slug not in board_map:
            unmatched_pins += 1
            continue
        
        board_id = board_map[board_slug]
        
        # Check if pin exists in database
        cursor.execute("""
            SELECT id, section_id FROM pins 
            WHERE pin_id = %s AND board_id = %s AND user_id = %s
        """, (pin_id, board_id, user_id))
        
        result = cursor.fetchone()
        if not result:
            unmatched_pins += 1
            continue
        
        db_pin_id, current_section_id = result
        matched_pins += 1
        
        # Track sections we need to create
        sections_to_create[board_id].add(section_name)
        
        # We'll update sections later after creating them
        updates_to_apply.append((db_pin_id, board_id, section_name))
    
    print(f"Matched {matched_pins:,} pins")
    print(f"Unmatched {unmatched_pins:,} pins")
    print()
    
    # Create sections that don't exist
    print("Creating/verifying sections...")
    section_id_map = {}  # (board_id, section_name) -> section_id
    
    for board_id, section_names in sections_to_create.items():
        for section_name in section_names:
            section_id = get_or_create_section(cursor, db, board_id, section_name, user_id)
            section_id_map[(board_id, section_name)] = section_id
    
    print(f"✓ Verified {len(section_id_map)} sections")
    print()
    
    # Apply updates in batches
    print(f"Updating {len(updates_to_apply):,} pin assignments...")
    
    batch_size = 500
    updated_count = 0
    
    for i in range(0, len(updates_to_apply), batch_size):
        batch = updates_to_apply[i:i + batch_size]
        
        for db_pin_id, board_id, section_name in batch:
            section_id = section_id_map.get((board_id, section_name))
            if section_id:
                cursor.execute("""
                    UPDATE pins 
                    SET section_id = %s 
                    WHERE id = %s
                """, (section_id, db_pin_id))
                updated_count += 1
        
        db.commit()
        print(f"  Updated {updated_count}/{len(updates_to_apply)} pins...")
    
    print()
    print(f"✅ Successfully updated {updated_count:,} pins!")
    
    cursor.close()
    db.close()
    
    return updated_count

def main():
    print()
    print("=" * 80)
    print("PINTEREST SECTION MIGRATION")
    print("=" * 80)
    print()
    
    # Get user
    db = get_db_connection()
    cursor = db.cursor()
    user_id = get_user_id(cursor)
    
    if not user_id:
        print("❌ No users found in database!")
        return
    
    print(f"Using user_id: {user_id}")
    print()
    
    cursor.close()
    db.close()
    
    # Process ZIP
    result = process_pinterest_zip()
    if not result:
        return
    
    pin_section_map, board_pins = result
    
    # Apply assignments
    updated = apply_section_assignments(pin_section_map, user_id)
    
    # Show final statistics
    db = get_db_connection()
    cursor = db.cursor()
    
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN section_id IS NOT NULL THEN 1 ELSE 0 END) as with_sections
        FROM pins
        WHERE user_id = %s
    """, (user_id,))
    
    stats = cursor.fetchone()
    total = stats[0] if stats else 0
    with_sections = stats[1] if stats and len(stats) > 1 else 0
    
    print()
    print("=" * 80)
    print("FINAL STATISTICS")
    print("=" * 80)
    print(f"Total pins: {total:,}")
    print(f"Pins with sections: {with_sections:,}")
    if total > 0:
        print(f"Percentage: {with_sections / total * 100:.1f}%")
    print()
    
    cursor.close()
    db.close()

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

