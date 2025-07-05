import mysql.connector
from mysql.connector import pooling
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database configuration
db_config = {
    'host': os.getenv('DB_HOST', 'db'),
    'user': os.getenv('DB_USER', 'db'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME', 'scrapbook'),
    'pool_name': 'mypool',
    'pool_size': 5
}

# Create connection pool
connection_pool = mysql.connector.pooling.MySQLConnectionPool(**db_config)

def check_board():
    try:
        # Get connection from pool
        connection = connection_pool.get_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Query board and pins
        query = """
        SELECT b.name as board_name, 
               COUNT(p.id) as pin_count,
               SUM(CASE WHEN p.title IS NULL OR p.title = '' THEN 1 ELSE 0 END) as empty_pins,
               GROUP_CONCAT(p.title) as pin_titles
        FROM boards b 
        LEFT JOIN pins p ON b.id = p.board_id 
        WHERE b.name = '1 Samuel' 
        GROUP BY b.id;
        """
        
        cursor.execute(query)
        result = cursor.fetchone()
        
        if result:
            print(f"\nBoard: {result['board_name']}")
            print(f"Total pins: {result['pin_count']}")
            print(f"Empty pins: {result['empty_pins']}")
            print("\nPin titles:")
            if result['pin_titles']:
                for title in result['pin_titles'].split(','):
                    print(f"- {title}")
            else:
                print("No pins found")
        else:
            print("Board '1 Samuel' not found")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals():
            connection.close()

if __name__ == "__main__":
    check_board() 