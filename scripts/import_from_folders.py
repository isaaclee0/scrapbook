import os
import json
import mysql.connector
from mysql.connector import pooling
from pathlib import Path
import time

# Database connection pool configuration
dbconfig = {
    "host": "db",
    "user": "db",
    "password": os.getenv('DB_PASSWORD'),
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

def reset_database():
    """Drop and recreate all tables"""
    db = cnxpool.get_connection()
    cursor = db.cursor()
    
    try:
        # Drop tables in correct order (respecting foreign key constraints)
        cursor.execute("DROP TABLE IF EXISTS pins")
        cursor.execute("DROP TABLE IF EXISTS sections")
        cursor.execute("DROP TABLE IF EXISTS boards")
        
        # Recreate tables
        cursor.execute("""
            CREATE TABLE boards (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        
        cursor.execute("""
            CREATE TABLE sections (
                id INT AUTO_INCREMENT PRIMARY KEY,
                board_id INT NOT NULL,
                name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        
        cursor.execute("""
            CREATE TABLE pins (
                id INT AUTO_INCREMENT PRIMARY KEY,
                board_id INT NOT NULL,
                section_id INT,
                pin_id VARCHAR(300),
                link TEXT,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                notes TEXT,
                image_url TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE,
                FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE SET NULL
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        
        db.commit()
        print("✅ Database tables recreated successfully!")
        
    except mysql.connector.Error as err:
        print(f"❌ Error resetting database: {err}")
        db.rollback()
    finally:
        cursor.close()
        db.close()

def extract_pin_data(pin_data):
    """Extract pin data from the nested JSON structure"""
    try:
        json_data = pin_data.get('otherPropertiesMap', {}).get('_json', {})
        
        # Get title - prefer gridTitle if available
        title = json_data.get('gridTitle', '') or json_data.get('title', '')
        
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

def create_board(name, cursor, db):
    """Create a new board"""
    try:
        cursor.execute("""
            INSERT INTO boards (name)
            VALUES (%s)
        """, (name,))
        
        board_id = cursor.lastrowid
        db.commit()
        print(f"✅ Created board: '{name}' (ID: {board_id})")
        return board_id
        
    except mysql.connector.Error as err:
        print(f"❌ Error creating board '{name}': {err}")
        db.rollback()
        return None

def create_section(board_id, name, cursor, db):
    """Create a new section for a board"""
    try:
        cursor.execute("""
            INSERT INTO sections (board_id, name)
            VALUES (%s, %s)
        """, (board_id, name))
        
        section_id = cursor.lastrowid
        db.commit()
        print(f"✅ Created section: '{name}' for board ID {board_id}")
        return section_id
        
    except mysql.connector.Error as err:
        print(f"❌ Error creating section '{name}': {err}")
        db.rollback()
        return None

def insert_pin(board_id, section_id, pin_id, pin_data, cursor, db):
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

def process_pins_directory():
    """Process all pins in the pins directory"""
    db = cnxpool.get_connection()
    cursor = db.cursor()
    
    try:
        pins_dir = Path('pins')
        if not pins_dir.exists():
            print(f"❌ Directory not found: {pins_dir}")
            return
        
        total_pins = 0
        total_boards = 0
        total_sections = 0
        
        # Process each board folder
        for board_folder in pins_dir.iterdir():
            if not board_folder.is_dir():
                continue
                
            board_name = board_folder.name
            print(f"\nProcessing board: {board_name}")
            
            # Create board
            board_id = create_board(board_name, cursor, db)
            if not board_id:
                continue
            total_boards += 1
            
            # Process each section folder
            for section_folder in board_folder.iterdir():
                if not section_folder.is_dir():
                    continue
                    
                section_name = section_folder.name
                print(f"  Processing section: {section_name}")
                
                # Create section
                section_id = create_section(board_id, section_name, cursor, db)
                if not section_id:
                    continue
                total_sections += 1
                
                # Process each pin file
                for pin_file in section_folder.glob('*.json'):
                    try:
                        with open(pin_file, 'r') as f:
                            pin_data = json.load(f)
                            
                        pin_id = pin_file.stem
                        if insert_pin(board_id, section_id, pin_id, pin_data, cursor, db):
                            total_pins += 1
                            
                    except Exception as e:
                        print(f"❌ Error processing pin file {pin_file}: {e}")
                        continue
        
        print(f"\n📊 Import Summary:")
        print(f"✅ Created {total_boards} boards")
        print(f"✅ Created {total_sections} sections")
        print(f"✅ Imported {total_pins} pins")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        cursor.close()
        db.close()

if __name__ == "__main__":
    # Reset database
    reset_database()
    
    # Import pins
    process_pins_directory()
    
    print("✅ Import complete!") 