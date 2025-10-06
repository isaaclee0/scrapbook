#!/usr/bin/env python3
"""
Migrate all existing content to isaac@leemail.com.au
This is for local development/testing
"""

import mysql.connector
import os
import sys

ISAAC_EMAIL = "isaac@leemail.com.au"

# ANSI color codes
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
BOLD = '\033[1m'
END = '\033[0m'

def log(message, color=''):
    print(f"{color}{message}{END}")

def migrate_to_isaac():
    """Migrate all content to Isaac's account"""
    try:
        # Connect to database
        log(f"\n{BOLD}{'='*60}{END}")
        log(f"{BOLD}🔄 Migrating all content to {ISAAC_EMAIL}{END}")
        log(f"{BOLD}{'='*60}{END}\n")
        
        connection = mysql.connector.connect(
            host=os.getenv('DB_HOST', 'db'),
            user=os.getenv('DB_USER', 'db'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME', 'db')
        )
        
        cursor = connection.cursor(dictionary=True)
        
        # Ensure Isaac's user exists
        log(f"{BLUE}📧 Ensuring user exists: {ISAAC_EMAIL}{END}")
        cursor.execute("SELECT id FROM users WHERE email = %s", (ISAAC_EMAIL,))
        user = cursor.fetchone()
        
        if not user:
            log(f"{YELLOW}Creating new user: {ISAAC_EMAIL}{END}")
            cursor.execute(
                "INSERT INTO users (email, created_at) VALUES (%s, NOW())",
                (ISAAC_EMAIL,)
            )
            connection.commit()
            cursor.execute("SELECT id FROM users WHERE email = %s", (ISAAC_EMAIL,))
            user = cursor.fetchone()
        
        isaac_user_id = user['id']
        log(f"{GREEN}✓ User ID: {isaac_user_id}{END}\n")
        
        # Count current content
        cursor.execute("SELECT COUNT(*) as count FROM boards")
        total_boards = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM pins")
        total_pins = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM sections")
        total_sections = cursor.fetchone()['count']
        
        log(f"{BLUE}📊 Current content:{END}")
        log(f"   Boards:   {total_boards}")
        log(f"   Sections: {total_sections}")
        log(f"   Pins:     {total_pins}\n")
        
        # Update all boards
        log(f"{BLUE}📊 Updating boards...{END}")
        cursor.execute(
            "UPDATE boards SET user_id = %s WHERE user_id != %s OR user_id IS NULL",
            (isaac_user_id, isaac_user_id)
        )
        boards_updated = cursor.rowcount
        log(f"{GREEN}✓ Updated {boards_updated} boards{END}")
        
        # Update all sections
        log(f"{BLUE}📂 Updating sections...{END}")
        cursor.execute(
            "UPDATE sections SET user_id = %s WHERE user_id != %s OR user_id IS NULL",
            (isaac_user_id, isaac_user_id)
        )
        sections_updated = cursor.rowcount
        log(f"{GREEN}✓ Updated {sections_updated} sections{END}")
        
        # Update all pins
        log(f"{BLUE}📌 Updating pins...{END}")
        cursor.execute(
            "UPDATE pins SET user_id = %s WHERE user_id != %s OR user_id IS NULL",
            (isaac_user_id, isaac_user_id)
        )
        pins_updated = cursor.rowcount
        log(f"{GREEN}✓ Updated {pins_updated} pins{END}")
        
        connection.commit()
        
        # Verify migration
        log(f"\n{BLUE}📊 Verification:{END}")
        cursor.execute("SELECT COUNT(*) as count FROM boards WHERE user_id = %s", (isaac_user_id,))
        board_count = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM sections WHERE user_id = %s", (isaac_user_id,))
        section_count = cursor.fetchone()['count']
        cursor.execute("SELECT COUNT(*) as count FROM pins WHERE user_id = %s", (isaac_user_id,))
        pin_count = cursor.fetchone()['count']
        
        log(f"{GREEN}✅ {ISAAC_EMAIL} now owns:{END}")
        log(f"   {GREEN}✓{END} {board_count} boards")
        log(f"   {GREEN}✓{END} {section_count} sections")
        log(f"   {GREEN}✓{END} {pin_count} pins")
        
        cursor.close()
        connection.close()
        
        log(f"\n{BOLD}{GREEN}{'='*60}{END}")
        log(f"{BOLD}{GREEN}✅ Migration complete!{END}")
        log(f"{BOLD}{GREEN}{'='*60}{END}\n")
        
        return True
        
    except mysql.connector.Error as err:
        log(f"{RED}❌ Error: {err}{END}", RED)
        return False
    except Exception as e:
        log(f"{RED}❌ Unexpected error: {e}{END}", RED)
        return False

if __name__ == "__main__":
    success = migrate_to_isaac()
    sys.exit(0 if success else 1)

