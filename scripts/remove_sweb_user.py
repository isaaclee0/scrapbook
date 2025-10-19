#!/usr/bin/env python3
"""
Remove s.web@leemail.com.au user from the database
"""

import mysql.connector
import os
import sys

def remove_sweb_user():
    """Remove the s.web user from the database"""
    
    # Database configuration
    dbconfig = {
        "host": os.getenv('DB_HOST', 'db'),
        "user": os.getenv('DB_USER', 'db'),
        "password": os.getenv('DB_PASSWORD'),
        "database": os.getenv('DB_NAME', 'db'),
        "charset": 'utf8mb4',
        "collation": 'utf8mb4_unicode_ci'
    }
    
    try:
        print("Connecting to database...")
        db = mysql.connector.connect(**dbconfig)
        cursor = db.cursor(dictionary=True)
        
        # First, check if the user exists and get details
        cursor.execute("SELECT * FROM users WHERE email = %s", ('s.web@leemail.com.au',))
        user = cursor.fetchone()
        
        if not user:
            print("❌ User 's.web@leemail.com.au' not found in database")
            return
        
        user_id = user['id']
        print(f"✓ Found user: {user['email']} (ID: {user_id})")
        
        # Check if this user owns any boards
        cursor.execute("SELECT COUNT(*) as count FROM boards WHERE user_id = %s", (user_id,))
        board_count = cursor.fetchone()['count']
        
        # Check if this user owns any pins
        cursor.execute("SELECT COUNT(*) as count FROM pins WHERE user_id = %s", (user_id,))
        pin_count = cursor.fetchone()['count']
        
        print(f"  - Boards owned: {board_count}")
        print(f"  - Pins owned: {pin_count}")
        
        if board_count > 0 or pin_count > 0:
            print("\n⚠️  WARNING: This user owns boards or pins!")
            print("   Deleting this user will also delete their content.")
            response = input("   Continue? (yes/no): ")
            if response.lower() != 'yes':
                print("❌ Cancelled")
                return
        
        # Delete the user (CASCADE will handle related records)
        print(f"\nDeleting user {user['email']}...")
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        db.commit()
        
        print(f"✅ Successfully deleted user '{user['email']}' (ID: {user_id})")
        
        # Show remaining users
        cursor.execute("SELECT id, email, created_at, last_login FROM users ORDER BY id")
        remaining_users = cursor.fetchall()
        
        print("\n📋 Remaining users in database:")
        for u in remaining_users:
            print(f"  - ID {u['id']}: {u['email']} (created: {u['created_at']}, last login: {u['last_login']})")
        
        cursor.close()
        db.close()
        
    except mysql.connector.Error as err:
        print(f"❌ Database error: {err}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    print("=" * 60)
    print("Remove s.web@leemail.com.au User")
    print("=" * 60)
    print()
    remove_sweb_user()

