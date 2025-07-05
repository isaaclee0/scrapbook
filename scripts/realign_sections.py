import os
import json
import mysql.connector
import zipfile
from collections import defaultdict
import time
from mysql.connector import pooling

# Track processed boards
PROCESSED_BOARDS_FILE = 'processed_boards.txt'

def load_processed_boards():
    if os.path.exists(PROCESSED_BOARDS_FILE):
        with open(PROCESSED_BOARDS_FILE, 'r') as f:
            return set(line.strip() for line in f)
    return set()

def save_processed_board(board_name):
    with open(PROCESSED_BOARDS_FILE, 'a') as f:
        f.write(f"{board_name}\n")

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

def get_or_create_section(board_id, section_name, cursor, db):
    if not section_name:
        return None
        
    # Check if section exists
    cursor.execute("SELECT id FROM sections WHERE board_id = %s AND name = %s", (board_id, section_name))
    result = cursor.fetchone()
    
    if result:
        print(f"✔ Section '{section_name}' already exists for board ID {board_id}.")
        return result[0]
    
    # Create new section
    cursor.execute("""
        INSERT INTO sections (board_id, name, created_at, updated_at)
        VALUES (%s, %s, NOW(), NOW())
    """, (board_id, section_name))
    db.commit()
    section_id = cursor.lastrowid
    print(f"✅ Created new section '{section_name}' for board ID {board_id}.")
    return section_id

def get_board_id(board_name, cursor):
    cursor.execute("SELECT id FROM boards WHERE name = %s", (board_name,))
    result = cursor.fetchone()
    if not result:
        print(f"❌ Board '{board_name}' not found in database.")
        return None
    return result[0]

def is_valid_name(name):
    # Skip hidden files, system files, and invalid names
    return not (name.startswith('._') or name.startswith('__') or name.strip() == '')

def verify_pin_exists(pin_id, board_id, cursor):
    cursor.execute("SELECT id FROM pins WHERE id = %s AND board_id = %s", (pin_id, board_id))
    return cursor.fetchone() is not None

def extract_section_from_json(json_data):
    """Extract section name from JSON data"""
    try:
        # Check for section in CustomFolderName
        custom_folder = json_data.get('otherPropertiesMap', {}).get('CustomFolderName', '')
        if custom_folder:
            # Format: "username/board-name/section-name"
            parts = custom_folder.split('/')
            if len(parts) >= 3:
                return parts[2]
    except Exception as e:
        print(f"❌ Error extracting section from JSON: {e}")
    return None

def process_zip_file(zip_path):
    processed_boards = load_processed_boards()
    pin_section_map = {}
    board_pins = defaultdict(list)
    duplicate_pins = set()
    missing_pins = set()
    pin_id_mismatches = defaultdict(list)
    skipped_pins = 0  # Track skipped pins
    missing_boards = set()  # Track boards in ZIP but not in DB
    missing_sections = defaultdict(set)  # Track sections in ZIP but not in DB
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # First pass: collect all pins and check for duplicates
        pin_locations = defaultdict(list)
        for file_path in zip_ref.namelist():
            if not file_path.endswith('.json'):
                continue
                
            parts = file_path.split('/')
            if len(parts) < 3 or not is_valid_name(parts[1]):
                continue
                
            board_name = parts[1]
            pin_id = os.path.splitext(os.path.basename(file_path))[0]
            
            # Try to get section from file path first
            section_name = parts[2] if len(parts) == 4 else None
            
            # If no section in path, try to get it from JSON content
            if not section_name:
                try:
                    with zip_ref.open(file_path) as f:
                        json_data = json.load(f)
                        section_name = extract_section_from_json(json_data)
                except Exception as e:
                    print(f"❌ Error reading JSON for pin {pin_id}: {e}")
                    continue
            
            if section_name and not is_valid_name(section_name):
                section_name = None
            
            pin_locations[pin_id].append({
                'board_name': board_name,
                'section_name': section_name,
                'file_path': file_path
            })
            
            if len(pin_locations[pin_id]) > 1:
                duplicate_pins.add(pin_id)
        
        # Second pass: organize by board and check for duplicates
        for pin_id, locations in pin_locations.items():
            if len(locations) > 1:
                print(f"⚠️ Pin {pin_id} appears in multiple locations:")
                for loc in locations:
                    print(f"  - {loc['file_path']}")
                continue
                
            loc = locations[0]
            board_pins[loc['board_name']].append({
                'pin_id': pin_id,
                'section_name': loc['section_name'],
                'file_path': loc['file_path']
            })
        
        # Process each board
        total_boards = len(board_pins)
        processed_count = 0
        
        for board_name, pins in board_pins.items():
            # Skip if already processed
            if board_name in processed_boards:
                print(f"⏩ Skipping already processed board: {board_name}")
                processed_count += 1
                continue
                
            print(f"\n📊 Progress: {processed_count}/{total_boards} boards processed")
            print(f"📦 Processing board: {board_name}")
            
            # Get a new connection from the pool
            db = cnxpool.get_connection()
            cursor = db.cursor()
            
            try:
                # Get board ID
                board_id = get_board_id(board_name, cursor)
                if not board_id:
                    missing_boards.add(board_name)
                    continue
                
                # Process each pin
                sections_created = set()
                for pin in pins:
                    # Debug: Print the pin ID we're looking for
                    print(f"🔍 Looking for pin {pin['pin_id']} in board {board_name}")
                    
                    # Try to find the pin with different ID formats
                    cursor.execute("""
                        SELECT id, pin_id, title, section_id 
                        FROM pins 
                        WHERE board_id = %s 
                        AND (id = %s OR pin_id = %s OR CAST(id AS CHAR) = %s)
                    """, (board_id, pin['pin_id'], pin['pin_id'], pin['pin_id']))
                    result = cursor.fetchone()
                    
                    if result:
                        db_id, db_pin_id, title, current_section_id = result
                        print(f"✅ Found pin! Database ID: {db_id}, Pin ID: {db_pin_id}, Title: {title}")
                        
                        # Check for ID mismatch
                        if str(db_id) != str(pin['pin_id']) and str(db_pin_id) != str(pin['pin_id']):
                            pin_id_mismatches[board_name].append({
                                'file_id': pin['pin_id'],
                                'db_id': db_id,
                                'db_pin_id': db_pin_id,
                                'title': title
                            })
                        
                        section_name = pin['section_name']
                        if section_name:
                            # Get section ID for this board
                            cursor.execute("SELECT id FROM sections WHERE board_id = %s AND name = %s", 
                                         (board_id, section_name))
                            section_result = cursor.fetchone()
                            if not section_result:
                                missing_sections[board_name].add(section_name)
                                continue
                            target_section_id = section_result[0]
                        else:
                            target_section_id = None
                            
                        # Skip if section is already correct
                        if current_section_id == target_section_id:
                            skipped_pins += 1
                            continue
                            
                        # Use the actual database ID for the update
                        pin_section_map[db_id] = target_section_id
                    else:
                        print(f"❌ Pin {pin['pin_id']} not found in board {board_name}")
                        missing_pins.add(pin['pin_id'])
                        continue
                    
                    section_name = pin['section_name']
                    
                    # Only create section once per board
                    if section_name and section_name not in sections_created:
                        section_id = get_or_create_section(board_id, section_name, cursor, db)
                        sections_created.add(section_name)
                    elif section_name:
                        # Get existing section ID
                        cursor.execute("SELECT id FROM sections WHERE board_id = %s AND name = %s", 
                                     (board_id, section_name))
                        result = cursor.fetchone()
                        section_id = result[0] if result else None
                    else:
                        section_id = None
                    
                    if section_id:
                        pin_section_map[db_id] = section_id
                
                # Mark board as processed
                save_processed_board(board_name)
                processed_count += 1
                        
            finally:
                cursor.close()
                db.close()
    
    # Print summary of issues found
    if duplicate_pins:
        print("\n⚠️ Found duplicate pins:")
        for pin_id in sorted(duplicate_pins):
            print(f"  - {pin_id}")
            
    if missing_pins:
        print("\n❌ Found pins not in database:")
        for pin_id in sorted(missing_pins):
            print(f"  - {pin_id}")
            
    if pin_id_mismatches:
        print("\n⚠️ Found pin ID mismatches:")
        for board_name, mismatches in pin_id_mismatches.items():
            print(f"\nBoard: {board_name}")
            for mismatch in mismatches:
                print(f"  File ID: {mismatch['file_id']}")
                print(f"  Database ID: {mismatch['db_id']}")
                print(f"  Database Pin ID: {mismatch['db_pin_id']}")
                print(f"  Title: {mismatch['title']}")
                print("  ---")
                
    if skipped_pins:
        print(f"\n⏩ Skipped {skipped_pins} pins that already had the correct section")
        
    if missing_boards:
        print("\n❌ Boards in ZIP but not in database:")
        for board_name in sorted(missing_boards):
            print(f"  - {board_name}")
            
    if missing_sections:
        print("\n❌ Sections in ZIP but not in database:")
        for board_name, sections in missing_sections.items():
            print(f"\nBoard: {board_name}")
            for section_name in sorted(sections):
                print(f"  - {section_name}")
    
    return pin_section_map

def update_pin_sections(pin_section_map):
    if not pin_section_map:
        print("No pins to update")
        return
        
    print(f"\nUpdating {len(pin_section_map)} pins...")
    
    # Get a new connection from the pool
    db = cnxpool.get_connection()
    cursor = db.cursor()
    
    try:
        # Process in batches to avoid lock timeouts
        batch_size = 100
        pins = list(pin_section_map.items())
        total_pins = len(pins)
        processed = 0
        
        for i in range(0, total_pins, batch_size):
            batch = pins[i:i + batch_size]
            retries = 3
            
            while retries > 0:
                try:
                    # Start transaction
                    db.start_transaction()
                    
                    for pin_id, section_id in batch:
                        cursor.execute("""
                            UPDATE pins 
                            SET section_id = %s 
                            WHERE id = %s
                        """, (section_id, pin_id))
                    
                    # Commit transaction
                    db.commit()
                    processed += len(batch)
                    print(f"✅ Updated batch: {processed}/{total_pins} pins processed")
                    break
                    
                except mysql.connector.Error as e:
                    if e.errno == 1205:  # Lock wait timeout
                        retries -= 1
                        if retries > 0:
                            print(f"⚠️ Lock timeout, retrying... ({retries} attempts left)")
                            time.sleep(1)  # Wait before retrying
                            continue
                        else:
                            print(f"❌ Error updating batch after 3 retries: {str(e)}")
                            db.rollback()
                    else:
                        print(f"❌ Error updating batch: {str(e)}")
                        db.rollback()
                    break
                    
    finally:
        cursor.close()
        db.close()

def main():
    try:
        # Process ZIP file
        pin_section_map = process_zip_file('pins.zip')
        
        # Update pin sections
        update_pin_sections(pin_section_map)
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        # Close all connections in the pool
        for _ in range(cnxpool.pool_size):
            try:
                cnxpool.get_connection().close()
            except:
                pass
        print("✅ Database connection pool closed successfully!")

if __name__ == "__main__":
    main() 