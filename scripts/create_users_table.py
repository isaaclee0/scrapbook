#!/usr/bin/env python3
"""
Create users table for authentication system
"""

import mysql.connector
import os

def create_users_table():
    """Create the users table in the database"""
    try:
        # Connect to database
        connection = mysql.connector.connect(
            host=os.getenv('DB_HOST', 'db'),
            user=os.getenv('DB_USER', 'db'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME', 'db')
        )
        
        cursor = connection.cursor()
        
        # Create users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(255) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP NULL,
                is_active BOOLEAN DEFAULT TRUE,
                INDEX idx_email (email)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        
        print("✅ Users table created successfully")
        
        connection.commit()
        cursor.close()
        connection.close()
        
        return True
        
    except mysql.connector.Error as err:
        print(f"❌ Error creating users table: {err}")
        return False

if __name__ == "__main__":
    create_users_table()
