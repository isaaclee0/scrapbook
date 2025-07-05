import os
import json
import mysql.connector

# Database connection
try:
    db = mysql.connector.connect(
        host="db",
        user="db",
        password=os.getenv('DB_PASSWORD'),
        database="db",
        charset='utf8mb4',
        collation='utf8mb4_unicode_ci'  # Change this line
    )
    cursor = db.cursor()
    print("✅ Connected to the database successfully!")
except mysql.connector.Error as err:
    print(f"❌ Database connection failed: {err}")
    exit(1)

# Function to insert board into DB (if not exists)
def get_or_create_board(board_name):
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

# Function for batch inserting pins
def batch_insert_pins(board_id, pins):
    query = "INSERT INTO pins (board_id, pin_id, link, title, description, image_url) VALUES (%s, %s, %s, %s, %s, %s)"
    values = []
    for pin in pins:
        pin_id = pin.get("id", "")
        link = pin.get("link", "")
        title = pin.get("title", "")
        description = pin.get("description", "")
        image_url = pin["media"][0]["url"] if pin.get("media") else ""
        values.append((board_id, pin_id, link, title, description, image_url))
    cursor.executemany(query, values)
    db.commit()
    print(f"✅ Batch inserted {len(values)} pins for board ID: {board_id}")

# Loop through files in "pins" directory
for board_name in os.listdir("pins"):
    board_path = os.path.join("pins", board_name)
    if os.path.isdir(board_path):
        board_id = get_or_create_board(board_name)
        pins_to_insert = []

        for pin_file in os.listdir(board_path):
            if pin_file.endswith(".json"):
                with open(os.path.join(board_path, pin_file), 'r') as f:
                    try:
                        pin_data = json.load(f)["otherPropertiesMap"]["_json"]
                        
                        # Check if pin already exists to avoid duplicates
                        cursor.execute("SELECT id FROM pins WHERE pin_id = %s", (pin_data.get("id", ""),))
                        if not cursor.fetchone():
                            pins_to_insert.append(pin_data)
                        
                        # Batch insert if we have collected enough pins
                        if len(pins_to_insert) >= 1000:  # Adjust batch size as needed
                            batch_insert_pins(board_id, pins_to_insert)
                            pins_to_insert = []
                    except Exception as e:
                        print(f"❌ Error loading {pin_file}: {e}")

        # Insert any remaining pins
        if pins_to_insert:
            batch_insert_pins(board_id, pins_to_insert)

# Close DB connection
cursor.close()
db.close()
print("✅ Database connection closed successfully!")