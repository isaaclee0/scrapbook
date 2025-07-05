import mysql.connector
from mysql.connector import Error
import os

# Database configuration
dbconfig = {
    "host": os.getenv('DB_HOST', 'db'),
    "user": os.getenv('DB_USER', 'db'),
    "password": os.getenv('DB_PASSWORD'),
    "database": os.getenv('DB_NAME', 'db'),
    "charset": 'utf8mb4',
    "collation": 'utf8mb4_unicode_ci'
}

def table_exists(table_name):
    cursor.execute("SHOW TABLES LIKE %s", (table_name,))
    return cursor.fetchone() is not None

def column_exists(table_name, column_name):
    cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE %s", (column_name,))
    return cursor.fetchone() is not None

def foreign_key_exists(table_name, fk_name):
    cursor.execute(f"""
        SELECT CONSTRAINT_NAME 
        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE 
        WHERE TABLE_NAME = %s AND CONSTRAINT_NAME = %s
    """, (table_name, fk_name))
    return cursor.fetchone() is not None

def update_schema():
    conn = None
    cursor = None
    try:
        # Connect to the database
        conn = mysql.connector.connect(**dbconfig)
        cursor = conn.cursor()

        # Add slug column to boards table if it doesn't exist
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.columns 
            WHERE table_schema = DATABASE()
                AND table_name = 'boards'
                AND column_name = 'slug';
        """)
        
        if cursor.fetchone()[0] == 0:
            print("Adding slug column to boards table...")
            cursor.execute("""
                ALTER TABLE boards 
                ADD COLUMN slug VARCHAR(255) NOT NULL DEFAULT '';
            """)
            
            # Update existing boards to have slugs based on their names
            cursor.execute("""
                UPDATE boards 
                SET slug = LOWER(REPLACE(TRIM(name), ' ', '-'))
                WHERE slug = '';
            """)
            
            conn.commit()
            print("Schema updated successfully!")
        else:
            print("Slug column already exists in boards table.")

    except mysql.connector.Error as err:
        print(f"Error: {err}")
        if conn:
            conn.rollback()

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    update_schema()