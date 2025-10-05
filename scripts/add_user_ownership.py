#!/usr/bin/env python3
"""
Add user_id columns to boards and pins tables
Migrate existing data to isaac@leemail.com.au
"""

import mysql.connector
import os

ISAAC_EMAIL = "isaac@leemail.com.au"

def migrate_to_multi_user():
    """Add user ownership to boards and pins"""
    try:
        # Connect to database
        connection = mysql.connector.connect(
            host=os.getenv('DB_HOST', 'db'),
            user=os.getenv('DB_USER', 'db'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME', 'db')
        )
        
        cursor = connection.cursor(dictionary=True)
        
        # Ensure Isaac's user exists
        print(f"📧 Ensuring user exists: {ISAAC_EMAIL}")
        cursor.execute("SELECT id FROM users WHERE email = %s", (ISAAC_EMAIL,))
        user = cursor.fetchone()
        
        if not user:
            cursor.execute(
                "INSERT INTO users (email, created_at) VALUES (%s, NOW())",
                (ISAAC_EMAIL,)
            )
            connection.commit()
            cursor.execute("SELECT id FROM users WHERE email = %s", (ISAAC_EMAIL,))
            user = cursor.fetchone()
        
        isaac_user_id = user['id']
        print(f"✅ User ID: {isaac_user_id}")
        
        # Add user_id column to boards table
        print("\n📊 Adding user_id to boards table...")
        try:
            cursor.execute("""
                ALTER TABLE boards 
                ADD COLUMN user_id INT NOT NULL DEFAULT %s,
                ADD INDEX idx_user_id (user_id),
                ADD FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            """ % isaac_user_id)
            print("✅ Added user_id to boards")
        except mysql.connector.Error as e:
            if "Duplicate column name" in str(e):
                print("⚠️  Column user_id already exists in boards")
            else:
                raise
        
        # Add user_id column to pins table
        print("\n📌 Adding user_id to pins table...")
        try:
            cursor.execute("""
                ALTER TABLE pins 
                ADD COLUMN user_id INT NOT NULL DEFAULT %s,
                ADD INDEX idx_user_id (user_id),
                ADD FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            """ % isaac_user_id)
            print("✅ Added user_id to pins")
        except mysql.connector.Error as e:
            if "Duplicate column name" in str(e):
                print("⚠️  Column user_id already exists in pins")
            else:
                raise
        
        # Update existing boards to belong to Isaac
        cursor.execute("UPDATE boards SET user_id = %s WHERE user_id = 0 OR user_id IS NULL", (isaac_user_id,))
        boards_updated = cursor.rowcount
        print(f"✅ Updated {boards_updated} boards to belong to {ISAAC_EMAIL}")
        
        # Update existing pins to belong to Isaac
        cursor.execute("UPDATE pins SET user_id = %s WHERE user_id = 0 OR user_id IS NULL", (isaac_user_id,))
        pins_updated = cursor.rowcount
        print(f"✅ Updated {pins_updated} pins to belong to {ISAAC_EMAIL}")
        
        connection.commit()
        
        # Verify migration
        print("\n📊 Verification:")
        cursor.execute("SELECT COUNT(*) as count FROM boards WHERE user_id = %s", (isaac_user_id,))
        board_count = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM pins WHERE user_id = %s", (isaac_user_id,))
        pin_count = cursor.fetchone()['count']
        
        print(f"✅ {ISAAC_EMAIL} now owns:")
        print(f"   - {board_count} boards")
        print(f"   - {pin_count} pins")
        
        cursor.close()
        connection.close()
        
        return True
        
    except mysql.connector.Error as err:
        print(f"❌ Error migrating to multi-user: {err}")
        return False

if __name__ == "__main__":
    print("🚀 Starting multi-user migration...\n")
    success = migrate_to_multi_user()
    if success:
        print("\n✅ Migration complete! All existing content now belongs to isaac@leemail.com.au")
        print("🔐 Users can now create their own accounts and will only see their own data")
    else:
        print("\n❌ Migration failed")
