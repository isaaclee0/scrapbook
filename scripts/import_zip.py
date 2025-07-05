import os
import json
import mysql.connector
import zipfile

# Database connection
try:
    db = mysql.connector.connect(
        host="db",
        user="db",
        password=os.getenv('DB_PASSWORD'),
        database="db",
        charset='utf8mb4',
        collation='utf8mb4_unicode_ci'
    )
    cursor = db.cursor()
    print("✅ Connected to the database successfully!")
except mysql.connector.Error as err:
    print(f"❌ Database connection failed: {err}")
    exit(1)

# Function to insert or get board
def get_or_create_board(board_name, cursor, db):
    cursor.execute("SELECT id FROM boards WHERE name = %s", (board_name,))
    board = cursor.fetchone()
    if board:
        print(f"✔ Board '{board_name}' already exists.")
        return board[0]
    else:
        cursor.execute("INSERT INTO boards (name) VALUES (%s)", (board_name,))
        db.commit()
        print(f"✅ Created new board: {board_name}")
        return cursor.lastrowid

# Function to insert or get section
def get_or_create_section(board_id, section_name, cursor, db):
    if not section_name:  # No section
        return None
    cursor.execute("SELECT id FROM sections WHERE board_id = %s AND name = %s", (board_id, section_name))
    section = cursor.fetchone()
    if section:
        print(f"✔ Section '{section_name}' already exists for board ID {board_id}.")
        return section[0]
    else:
        cursor.execute("INSERT INTO sections (board_id, name) VALUES (%s, %s)", (board_id, section_name))
        db.commit()
        print(f"✅ Created new section: {section_name} for board ID {board_id}")
        return cursor.lastrowid

# Function for batch inserting new pins
def batch_insert_pins(pins, cursor, db):
    query = """
        INSERT INTO pins (board_id, section_id, pin_id, link, title, description, image_url)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    cursor.executemany(query, pins)
    db.commit()
    print(f"✅ Batch inserted {len(pins)} new pins")

# Function for batch updating existing pins
def batch_update_pins(pins, cursor, db):
    query = """
        UPDATE pins 
        SET board_id = %s, section_id = %s, link = %s, title = %s, description = %s, image_url = %s
        WHERE pin_id = %s
    """
    cursor.executemany(query, pins)
    db.commit()
    print(f"✅ Batch updated {len(pins)} existing pins")

# Find ZIP file in current directory
zip_file = None
for filename in os.listdir("."):
    if filename.endswith(".zip"):
        zip_file = filename
        break

if not zip_file:
    print("❌ No ZIP file found in the current directory")
    cursor.close()
    db.close()
    exit(1)

print(f"📦 Found ZIP file: {zip_file}")

# Process the ZIP file
try:
    with zipfile.ZipFile(zip_file, 'r') as zip_ref:
        new_pins_to_insert = []
        existing_pins_to_update = []
        
        for file_path in zip_ref.namelist():
            if file_path.endswith(".json"):
                parts = file_path.split('/')
                if len(parts) < 2:
                    print(f"⚠ Skipping {file_path}: Invalid folder structure")
                    continue
                
                # Determine board and section
                board_name = parts[1]  # e.g., "baby-stuff"
                section_name = None
                if len(parts) == 4:  # e.g., "basketfuls/baby-stuff/craft/88101736435883110.json"
                    section_name = parts[2]
                # If len(parts) == 3, it’s "basketfuls/baby-stuff/88101736435883110.json" (no section)
                
                board_id = get_or_create_board(board_name, cursor, db)
                section_id = get_or_create_section(board_id, section_name, cursor, db)
                
                try:
                    pin_data = json.loads(zip_ref.read(file_path))["otherPropertiesMap"]["_json"]
                    pin_id = pin_data.get("id", "")
                    if not pin_id or len(pin_id) > 300:  # Updated to match VARCHAR(300)
                        print(f"⚠ Skipping {file_path}: Invalid or too long pin_id '{pin_id}'")
                        continue
                    
                    # Check if pin exists
                    cursor.execute("SELECT id FROM pins WHERE pin_id = %s", (pin_id,))
                    existing_pin = cursor.fetchone()
                    
                    # Extract pin details
                    link = pin_data.get("link", "")
                    title = pin_data.get("title", "")
                    description = pin_data.get("description", "")
                    image_url = pin_data["media"][0]["url"] if pin_data.get("media") else ""
                    
                    if existing_pin:
                        existing_pins_to_update.append((board_id, section_id, link, title, description, image_url, pin_id))
                        print(f"🔄 Queued update for pin '{pin_id}'")
                    else:
                        new_pins_to_insert.append((board_id, section_id, pin_id, link, title, description, image_url))
                        print(f"➕ Queued new pin '{pin_id}'")
                    
                    if len(new_pins_to_insert) >= 1000:
                        batch_insert_pins(new_pins_to_insert, cursor, db)
                        new_pins_to_insert = []
                    if len(existing_pins_to_update) >= 1000:
                        batch_update_pins(existing_pins_to_update, cursor, db)
                        existing_pins_to_update = []
                except Exception as e:
                    print(f"❌ Error processing {file_path}: {e}")
        
        if new_pins_to_insert:
            batch_insert_pins(new_pins_to_insert, cursor, db)
        if existing_pins_to_update:
            batch_update_pins(existing_pins_to_update, cursor, db)

except zipfile.BadZipFile:
    print(f"❌ {zip_file} is not a valid ZIP file")
except Exception as e:
    print(f"❌ Unexpected error: {e}")
finally:
    cursor.close()
    db.close()
    print("✅ Database connection closed successfully!")