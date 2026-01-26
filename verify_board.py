import mysql.connector
import os

def check_board():
    try:
        conn = mysql.connector.connect(
            host='db',
            user='db',
            password='3Uy@7SGMAHVyC^Oo',
            database='db'
        )
        cursor = conn.cursor(dictionary=True)
        
        # Search for boards with many pins
        print("\nSearching for boards with > 500 pins...")
        cursor.execute("""
            SELECT b.id, b.name, COUNT(p.id) as pin_count 
            FROM boards b 
            LEFT JOIN pins p ON b.id = p.board_id 
            GROUP BY b.id 
            HAVING pin_count > 500
            ORDER BY pin_count DESC
        """)
        large_boards = cursor.fetchall()
        for b in large_boards:
            print(f"- '{b['name']}' (ID: {b['id']}): {b['pin_count']} pins")
            
        # Search for boards starting with 'E'
        print("\nSearching for boards starting with 'E'...")
        cursor.execute("SELECT id, name FROM boards WHERE name LIKE 'E%' LIMIT 50")
        e_boards = cursor.fetchall()
        for b in e_boards:
            print(f"- '{b['name']}' (ID: {b['id']})")
            
        cursor.close()
        conn.close()
        
    except mysql.connector.Error as err:
        print(f"Error: {err}")

if __name__ == "__main__":
    check_board()
