#!/usr/bin/env python3
"""
Export section assignments to a lightweight SQL file
This can be run in production without needing the large pins.zip file
"""
import os
import mysql.connector

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', 'db'),
        user=os.getenv('DB_USER', 'db'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'db'),
        charset='utf8mb4',
        collation='utf8mb4_unicode_ci'
    )

def main():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    print("Exporting section assignments...")
    
    # Get all pins with sections (use database ID if pin_id is NULL)
    cursor.execute("""
        SELECT p.id, p.pin_id, b.name as board_name, s.name as section_name
        FROM pins p
        JOIN boards b ON p.board_id = b.id
        JOIN sections s ON p.section_id = s.id
        WHERE p.section_id IS NOT NULL
        ORDER BY b.name, s.name
    """)
    
    assignments = cursor.fetchall()
    
    # Write to SQL file
    output_file = 'section_assignments.sql'
    with open(output_file, 'w') as f:
        f.write("-- Section assignment migration\n")
        f.write("-- Generated from existing section data\n")
        f.write("-- Run this in production to restore Pinterest section assignments\n\n")
        
        for assignment in assignments:
            # Escape single quotes
            board_name = assignment['board_name'].replace("'", "''")
            section_name = assignment['section_name'].replace("'", "''")
            
            # Use pin_id if available, otherwise use database ID
            if assignment['pin_id']:
                identifier = f"p.pin_id = '{assignment['pin_id'].replace(chr(39), chr(39)+chr(39))}'"
            else:
                identifier = f"p.id = {assignment['id']}"
            
            f.write(f"""UPDATE pins p
JOIN boards b ON p.board_id = b.id
JOIN sections s ON s.board_id = b.id
SET p.section_id = s.id
WHERE {identifier}
  AND b.name = '{board_name}'
  AND s.name = '{section_name}'
  AND p.section_id IS NULL;

""")
    
    print(f"✅ Exported {len(assignments)} section assignments to {output_file}")
    print(f"   File size: {os.path.getsize(output_file) / 1024:.1f} KB")
    print()
    print("To apply in production:")
    print(f"  1. Copy {output_file} to production server")
    print("  2. docker cp section_assignments.sql <container>:/app/")
    print("  3. docker-compose exec web mysql -udb -p\$DB_PASSWORD db < section_assignments.sql")
    
    cursor.close()
    db.close()

if __name__ == '__main__':
    main()

