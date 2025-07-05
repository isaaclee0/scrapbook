import mysql.connector
from mysql.connector import pooling
import time
import zipfile
import json
import os
from collections import defaultdict

# Database connection pool configuration
dbconfig = {
    "host": "db",
    "user": "db",
    "password": "3Uy@7SGMAHVyC^Oo",
    "database": "db",
    "pool_name": "mypool",
    "pool_size": 5,
    "charset": 'utf8mb4',
    "collation": 'utf8mb4_unicode_ci'
}

# Create connection pool
try:
    cnxpool = mysql.connector.pooling.MySQLConnectionPool(**dbconfig)
    print("✅ Database connection pool created successfully!")
except mysql.connector.Error as err:
    print(f"❌ Error creating connection pool: {err}")
    exit(1)

def format_board_name(name):
    # Replace dashes with spaces and capitalize each word
    return ' '.join(word.capitalize() for word in name.replace('-', ' ').split())

def get_board_id(name, cursor):
    # Try exact match first
    cursor.execute("SELECT id FROM boards WHERE name = %s", (name,))
    result = cursor.fetchone()
    if result:
        return result[0]
        
    # Try with dashes replaced by spaces
    formatted_name = format_board_name(name)
    cursor.execute("SELECT id FROM boards WHERE name = %s", (formatted_name,))
    result = cursor.fetchone()
    if result:
        return result[0]
        
    return None

def create_board(name, cursor, db):
    formatted_name = format_board_name(name)
    
    try:
        # Create the new board
        cursor.execute("""
            INSERT INTO boards (name)
            VALUES (%s)
        """, (formatted_name,))
        
        board_id = cursor.lastrowid
        db.commit()
        print(f"✅ Created board: '{formatted_name}' (ID: {board_id})")
        return board_id
        
    except mysql.connector.Error as err:
        print(f"❌ Error creating board '{formatted_name}': {err}")
        db.rollback()
        return None

def get_or_create_section(board_id, section_name, cursor, db):
    if not section_name:
        return None
        
    try:
        # Check if section exists
        cursor.execute("SELECT id FROM sections WHERE board_id = %s AND name = %s", 
                      (board_id, section_name))
        result = cursor.fetchone()
        
        if result:
            return result[0]
            
        # Create new section
        cursor.execute("""
            INSERT INTO sections (board_id, name)
            VALUES (%s, %s)
        """, (board_id, section_name))
        
        section_id = cursor.lastrowid
        db.commit()
        print(f"✅ Created section: '{section_name}' for board ID {board_id}")
        return section_id
        
    except mysql.connector.Error as err:
        print(f"❌ Error creating section '{section_name}': {err}")
        db.rollback()
        return None

def pin_exists(board_id, pin_id, cursor):
    cursor.execute("SELECT id FROM pins WHERE board_id = %s AND pin_id = %s", (board_id, pin_id))
    return cursor.fetchone() is not None

def extract_pin_data(pin_data):
    """Extract pin data from the nested JSON structure"""
    try:
        json_data = pin_data.get('otherPropertiesMap', {}).get('_json', {})
        
        # Get title - prefer gridTitle if available
        title = json_data.get('gridTitle', '') or json_data.get('title', '')
        
        # Truncate title if it's too long (max 255 characters)
        if len(title) > 255:
            print(f"⚠️ Truncating long title: {title[:50]}...")
            title = title[:255]
        
        # Get description
        description = json_data.get('description', '')
        
        # Get image URL from media array
        image_url = ''
        media = json_data.get('media', [])
        if media and isinstance(media, list) and len(media) > 0:
            image_url = media[0].get('url', '')
        
        # Get link
        link = json_data.get('link', '')
        
        return {
            'title': title,
            'description': description,
            'image_url': image_url,
            'link': link
        }
    except Exception as e:
        print(f"❌ Error extracting pin data: {e}")
        return {
            'title': '',
            'description': '',
            'image_url': '',
            'link': ''
        }

def update_pin(cursor, db, board_id, section_id, pin_id, pin_data):
    """Update an existing pin with new data"""
    try:
        data = extract_pin_data(pin_data)
        cursor.execute("""
            UPDATE pins 
            SET title = %s, 
                description = %s, 
                image_url = %s, 
                link = %s,
                section_id = %s
            WHERE board_id = %s AND pin_id = %s
        """, (
            data['title'],
            data['description'],
            data['image_url'],
            data['link'],
            section_id,
            board_id,
            pin_id
        ))
        db.commit()
        return True
    except Exception as e:
        print(f"❌ Error updating pin {pin_id}: {e}")
        db.rollback()
        return False

def insert_pin(cursor, db, board_id, section_id, pin_id, pin_data):
    """Insert a new pin"""
    try:
        data = extract_pin_data(pin_data)
        cursor.execute("""
            INSERT INTO pins (board_id, section_id, pin_id, title, description, image_url, link)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            board_id,
            section_id,
            pin_id,
            data['title'],
            data['description'],
            data['image_url'],
            data['link']
        ))
        db.commit()
        return True
    except Exception as e:
        print(f"❌ Error inserting pin {pin_id}: {e}")
        db.rollback()
        return False

def process_zip_file(zip_path):
    # Get a connection from the pool
    db = cnxpool.get_connection()
    cursor = db.cursor()
    
    try:
        boards_created = 0
        sections_created = 0
        pins_added = 0
        pins_updated = 0
        pins_skipped = 0
        processed_boards = set()
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # First, collect all board names from the ZIP
            board_paths = set()
            for file_path in zip_ref.namelist():
                if file_path.startswith('pins/') and not file_path.endswith('/'):
                    parts = file_path.split('/')
                    if len(parts) >= 2:
                        board_paths.add(parts[1])
            
            print(f"\n📊 Found {len(board_paths)} boards in ZIP file")
            
            # Process each board
            for board_name in sorted(board_paths):
                print(f"\nProcessing board: {board_name}")
                
                # Check if board exists (with name variations)
                board_id = get_board_id(board_name, cursor)
                
                if not board_id:
                    # Board doesn't exist, create it
                    board_id = create_board(board_name, cursor, db)
                    if board_id:
                        boards_created += 1
                    else:
                        print(f"❌ Skipping board {board_name} due to creation error")
                        continue
                
                # Track processed boards to avoid duplicates
                if board_id in processed_boards:
                    print(f"⏩ Already processed board {board_name}, skipping")
                    continue
                processed_boards.add(board_id)
                
                # Process sections and pins for this board
                board_pins = 0
                board_pins_updated = 0
                board_pins_skipped = 0
                board_sections = set()
                
                # Find all files for this board
                for file_path in zip_ref.namelist():
                    if not file_path.startswith(f'pins/{board_name}/'):
                        continue
                        
                    # Skip directories
                    if file_path.endswith('/'):
                        continue
                        
                    # Get section name if it exists
                    parts = file_path.split('/')
                    section_name = parts[2] if len(parts) == 4 else None
                    
                    # Process section if needed
                    section_id = None
                    if section_name and section_name not in board_sections:
                        section_id = get_or_create_section(board_id, section_name, cursor, db)
                        if section_id:
                            board_sections.add(section_name)
                            sections_created += 1
                    
                    # Process pin
                    try:
                        with zip_ref.open(file_path) as f:
                            pin_data = json.load(f)
                            
                        # Extract pin information
                        pin_id = os.path.splitext(os.path.basename(file_path))[0]
                        
                        # Check if pin exists
                        if pin_exists(board_id, pin_id, cursor):
                            # Update existing pin
                            if update_pin(cursor, db, board_id, section_id, pin_id, pin_data):
                                board_pins_updated += 1
                                pins_updated += 1
                        else:
                            # Insert new pin
                            if insert_pin(cursor, db, board_id, section_id, pin_id, pin_data):
                                board_pins += 1
                                pins_added += 1
                        
                    except Exception as e:
                        print(f"❌ Error processing pin {file_path}: {e}")
                        continue
                
                print(f"✅ Added {board_pins} new pins to board {board_name}")
                print(f"✅ Updated {board_pins_updated} existing pins")
                if board_pins_skipped > 0:
                    print(f"⏩ Skipped {board_pins_skipped} pins")
                
                # Add a small delay to reduce database load
                time.sleep(0.1)
            
        print(f"\n📊 Summary:")
        print(f"✅ Created {boards_created} new boards")
        print(f"✅ Created {sections_created} new sections")
        print(f"✅ Added {pins_added} new pins")
        print(f"✅ Updated {pins_updated} existing pins")
        print(f"⏩ Skipped {pins_skipped} pins")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        cursor.close()
        db.close()
        print("✅ Database connection closed")

if __name__ == "__main__":
    process_zip_file('pins.zip') 