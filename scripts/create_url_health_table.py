import mysql.connector
import os

# Database configuration
dbconfig = {
    "host": os.getenv('DB_HOST', 'db'),
    "user": os.getenv('DB_USER', 'db'),
    "password": os.getenv('DB_PASSWORD', '3Uy@7SGMAHVyC^Oo'),
    "database": os.getenv('DB_NAME', 'db'),
    "charset": 'utf8mb4',
    "collation": 'utf8mb4_unicode_ci'
}

def main():
    try:
        # Connect to the database
        db = mysql.connector.connect(**dbconfig)
        cursor = db.cursor()
        
        # Create URL health tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS url_health (
                id INT AUTO_INCREMENT PRIMARY KEY,
                pin_id INT NOT NULL,
                url VARCHAR(2048) NOT NULL,
                last_checked DATETIME,
                status ENUM('unknown', 'healthy', 'broken', 'archived') DEFAULT 'unknown',
                archive_url VARCHAR(2048),
                FOREIGN KEY (pin_id) REFERENCES pins(id) ON DELETE CASCADE
            )
        """)
        
        # Create indexes for frequently queried columns
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_boards_name ON boards(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pins_board_id ON pins(board_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pins_section_id ON pins(section_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sections_board_id ON sections(board_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pins_created_at ON pins(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_url_health_pin_id ON url_health(pin_id)")
        
        db.commit()
        print("✅ Database indexes and URL health table created successfully")
        
    except mysql.connector.Error as err:
        print(f"❌ Error creating indexes: {err}")
        if db:
            db.rollback()
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'db' in locals():
            try:
                db.close()
            except:
                pass  # Ignore errors during cleanup

if __name__ == "__main__":
    main() 