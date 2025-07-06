from flask import Flask, render_template, jsonify, request, send_from_directory, redirect, url_for
import mysql.connector
import os
from mysql.connector import pooling
import random
from werkzeug.routing import BaseConverter
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import html
import unicodedata
import time

# Try to import redis, but make it optional
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("Redis module not available, running without cache")

app = Flask(__name__, static_folder='static')

# Redis configuration
if REDIS_AVAILABLE:
    try:
        redis_client = redis.Redis(
            host='redis',
            port=6379,
            db=0,
            decode_responses=True
        )
        redis_client.ping()  # Test the connection
        print("Redis connection successful")
    except (redis.ConnectionError, redis.ResponseError):
        print("Redis not available, running without cache")
        redis_client = None
else:
    redis_client = None

# Cache decorator
def cache_view(timeout=300):
    def decorator(f):
        def wrapper(*args, **kwargs):
            if not redis_client:
                return f(*args, **kwargs)
            cache_key = f"view/{request.path}"
            cached_data = redis_client.get(cache_key)
            if cached_data:
                return cached_data
            response = f(*args, **kwargs)
            # Handle tuple responses (like from render_template)
            if isinstance(response, tuple):
                response = response[0]  # Get the actual content
            # Convert response to string if it's a Response object
            if hasattr(response, 'data'):
                response = response.data.decode('utf-8')
            redis_client.setex(cache_key, timeout, response)
            return response
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator

# Cache configuration
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 5 minutes

# Define and register SlugConverter
class SlugConverter(BaseConverter):
    regex = r'[a-zA-Z0-9-]+'

app.url_map.converters['slug'] = SlugConverter

# Input sanitization utilities
def sanitize_string(s, max_length=None):
    if not isinstance(s, str):
        return ''
    
    # Convert to string and normalize unicode
    s = str(s)
    s = unicodedata.normalize('NFKC', s)
    
    # Remove any HTML entities
    s = html.escape(s)
    
    # Remove any control characters
    s = ''.join(char for char in s if unicodedata.category(char)[0] != 'C')
    
    # Trim whitespace
    s = s.strip()
    
    # Apply length limit if specified
    if max_length and len(s) > max_length:
        s = s[:max_length]
    
    return s

def sanitize_url(url, max_length=2048):
    if not isinstance(url, str):
        return ''
    
    # Basic URL validation regex
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    url = url.strip()
    if not url_pattern.match(url):
        return ''
    
    # Apply length limit
    if len(url) > max_length:
        return ''
    
    return url

def sanitize_integer(value, min_value=None, max_value=None):
    try:
        value = int(value)
        if min_value is not None and value < min_value:
            return min_value
        if max_value is not None and value > max_value:
            return max_value
        return value
    except (TypeError, ValueError):
        return None

# Database connection pool configuration
dbconfig = {
    "host": os.getenv('DB_HOST', 'db'),
    "user": os.getenv('DB_USER', 'db'),
            "password": os.getenv('DB_PASSWORD'),
    "database": os.getenv('DB_NAME', 'db'),
    "pool_name": "mypool",
    "pool_size": 10,
    "autocommit": True,
    "charset": 'utf8mb4',
    "collation": 'utf8mb4_unicode_ci'
}

# Create connection pool
try:
    cnxpool = mysql.connector.pooling.MySQLConnectionPool(**dbconfig)
    print("Database connection pool created successfully")
except mysql.connector.Error as err:
    print(f"Error creating connection pool: {err}")
    cnxpool = None

def get_db_connection():
    try:
        if cnxpool:
            return cnxpool.get_connection()
        else:
            return mysql.connector.connect(**dbconfig)
    except mysql.connector.Error as err:
        print(f"Error getting database connection: {err}")
        raise

@app.route('/')
@cache_view(timeout=300)  # Cache for 5 minutes
def gallery():
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # Get boards with pin count and random pin image in a single query
        cursor.execute("""
            SELECT 
                b.*,
                COUNT(p.id) as pin_count,
                b.created_at,
                (
                    SELECT p2.image_url 
                    FROM pins p2 
                    WHERE p2.board_id = b.id 
                    ORDER BY RAND() 
                    LIMIT 1
                ) as random_pin_image_url
            FROM boards b
            LEFT JOIN pins p ON b.id = p.board_id
            GROUP BY b.id
            ORDER BY b.name
        """)
        boards = cursor.fetchall()
        
        # Set default image for boards without pins
        for board in boards:
            if not board['random_pin_image_url']:
                board['random_pin_image_url'] = '/static/images/default_board.png'
                
        # Invalidate gallery cache if Redis is available
        if redis_client:
            redis_client.delete('view//')
                
    except mysql.connector.Error as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        db.close()

    return render_template('boards.html', boards=boards)

@app.route('/board/<int:board_id>')
def board(board_id):
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # Get board details
        cursor.execute("SELECT * FROM boards WHERE id = %s", (board_id,))
        board = cursor.fetchone()
        if not board:
            return "Board not found", 404
            
        # Get sections for this board
        cursor.execute("SELECT * FROM sections WHERE board_id = %s ORDER BY name", (board_id,))
        sections = cursor.fetchall()
        
        # Get pins for this board
        cursor.execute("""
            SELECT p.*, s.name as section_name 
            FROM pins p 
            LEFT JOIN sections s ON p.section_id = s.id 
            WHERE p.board_id = %s 
            ORDER BY p.created_at DESC
        """, (board_id,))
        pins = cursor.fetchall()
        
        # Get all boards for the move board functionality
        cursor.execute("SELECT * FROM boards ORDER BY name")
        all_boards = cursor.fetchall()
        
        cursor.close()
        db.close()
        
        return render_template('board.html', board=board, sections=sections, pins=pins, all_boards=all_boards)
    except Exception as e:
        print(f"Error in board route: {str(e)}")
        return "An error occurred", 500

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('q', '').strip()
    if not query:
        return render_template('search.html', matching_boards=[], matching_pins=[], query=query)

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        board_sql = "SELECT * FROM boards WHERE name LIKE %s"
        search_term = f"%{query}%"
        cursor.execute(board_sql, (search_term,))
        matching_boards = cursor.fetchall()
        
        for board in matching_boards:
            cursor.execute("SELECT image_url FROM pins WHERE board_id = %s ORDER BY RAND() LIMIT 1", (board['id'],))
            pin = cursor.fetchone()
            board['random_pin_image_url'] = pin['image_url'] if pin else 'path/to/default_image.jpg'

        pin_sql = """
            SELECT p.*, b.name as board_name 
            FROM pins p 
            LEFT JOIN boards b ON p.board_id = b.id 
            WHERE p.title LIKE %s OR p.description LIKE %s
        """
        cursor.execute(pin_sql, (search_term, search_term))
        matching_pins = cursor.fetchall()
    except mysql.connector.Error as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        db.close()

    return render_template('search.html', matching_boards=matching_boards, matching_pins=matching_pins, query=query)

@app.route('/add-content')
def add_content():
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM boards")
        boards = cursor.fetchall()
        cursor.close()
        db.close()
        return render_template('add_content.html', boards=boards)
    except mysql.connector.Error as e:
        print(f"Database error in add_content: {e}")
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        print(f"Unexpected error in add_content: {e}")
        return jsonify({"error": "An unexpected error occurred"}), 500
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'db' in locals():
            try:
                db.close()
            except:
                pass  # Ignore errors during cleanup

@app.route('/scrape-website', methods=['POST'])
def scrape_website():
    data = request.get_json()
    url = sanitize_url(data.get('url', ''))
    
    if not url:
        return jsonify({"error": "Valid URL is required"}), 400
    
    try:
        # Add proper headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        images = []
        seen_urls = set()  # To avoid duplicates
        
        # Look for img tags with src or data-src (for lazy loading)
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src')
            if src:
                # Convert relative URLs to absolute and sanitize
                absolute_url = sanitize_url(urljoin(url, src))
                if absolute_url and absolute_url not in seen_urls:
                    seen_urls.add(absolute_url)
                    images.append({
                        'url': absolute_url,
                        'alt': sanitize_string(img.get('alt', ''), max_length=200)
                    })
        
        # Also look for meta tags with og:image or twitter:image
        for meta in soup.find_all('meta'):
            if meta.get('property') in ['og:image', 'twitter:image']:
                image_url = meta.get('content')
                if image_url:
                    absolute_url = sanitize_url(urljoin(url, image_url))
                    if absolute_url and absolute_url not in seen_urls:
                        seen_urls.add(absolute_url)
                        images.append({
                            'url': absolute_url,
                            'alt': 'Social media preview image'
                        })
        
        return jsonify({'images': images})
    except Exception as e:
        print(f"Error scraping website: {str(e)}")  # Add logging
        return jsonify({'error': str(e)}), 500

@app.route('/get-sections/<int:board_id>')
def get_sections(board_id):
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM sections WHERE board_id = %s", (board_id,))
        sections = cursor.fetchall()
    except mysql.connector.Error as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        db.close()
    
    return jsonify(sections)

@app.route('/add-pin', methods=['POST'])
def add_pin():
    try:
        data = request.get_json()
        board_id = sanitize_integer(data.get('board_id'))
        section_id = sanitize_integer(data.get('section_id'))
        title = sanitize_string(data.get('title', ''), max_length=255)
        description = sanitize_string(data.get('description', ''))
        notes = sanitize_string(data.get('notes', ''))
        image_url = sanitize_url(data.get('image_url', ''))
        source_url = sanitize_url(data.get('source_url', ''))  # Add source URL
        
        if not board_id or not title:
            return jsonify({"error": "Board ID and title are required"}), 400
            
        # Use default image if no image URL is provided
        if not image_url:
            image_url = '/static/images/default_pin.png'
            
        db = get_db_connection()
        cursor = db.cursor()
        
        cursor.execute("""
            INSERT INTO pins (board_id, section_id, title, description, notes, image_url, link)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (board_id, section_id, title, description, notes, image_url, source_url))
        
        pin_id = cursor.lastrowid
        db.commit()
        
        return jsonify({
            'success': True,
            'pin_id': pin_id
        })
    except Exception as e:
        print(f"Error adding pin: {str(e)}")
        return jsonify({"error": "Failed to add pin"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/update-pin/<int:pin_id>', methods=['POST'])
def update_pin(pin_id):
    try:
        data = request.get_json()
        # print(f"Received update request for pin {pin_id}: {data}")  # Debug log
        
        if not data:
            # print("No data provided in request")  # Debug log
            return jsonify({"error": "No data provided"}), 400
            
        # Get only the fields that are provided
        title = sanitize_string(data.get('title', ''), max_length=255) if 'title' in data else None
        description = sanitize_string(data.get('description', '')) if 'description' in data else None
        notes = sanitize_string(data.get('notes', '')) if 'notes' in data else None
        
        # print(f"Processed data - title: '{title}', description: '{description}', notes: '{notes}'")  # Debug log
        # print(f"Raw title from request: '{data.get('title', '')}'")  # Debug log
        # print(f"Is title in data? {'title' in data}")  # Debug log
        
        db = get_db_connection()
        cursor = db.cursor()
        
        # First verify the pin exists
        cursor.execute("SELECT title FROM pins WHERE id = %s", (pin_id,))
        result = cursor.fetchone()
        if not result:
            # print(f"Pin {pin_id} not found")  # Debug log
            return jsonify({"error": "Pin not found"}), 404
            
        current_title = result[0]
        # print(f"Current title in database: '{current_title}'")  # Debug log
        
        # Build the update query dynamically based on what fields are provided
        update_fields = []
        update_values = []
        
        if title is not None:
            # print(f"Title is different from current: {title != current_title}")  # Debug log
            update_fields.append("title = %s")
            update_values.append(title)
            
        if description is not None:
            update_fields.append("description = %s")
            update_values.append(description)
            
        if notes is not None:
            update_fields.append("notes = %s")
            update_values.append(notes)
            
        if not update_fields:
            # print("No fields to update")  # Debug log
            return jsonify({"error": "No fields to update"}), 400
            
        # Add the pin_id to the values list
        update_values.append(pin_id)
        
        # Build and execute the update query
        update_query = f"""
            UPDATE pins
            SET {', '.join(update_fields)}
            WHERE id = %s
        """
        
        # print(f"Executing query: {update_query}")  # Debug log
        # print(f"With values: {update_values}")  # Debug log
        
        cursor.execute(update_query, tuple(update_values))
        db.commit()
        # print(f"Successfully updated pin {pin_id}")  # Debug log
        
        return jsonify({
            'success': True,
            'pin_id': pin_id
        })
    except mysql.connector.Error as e:
        print(f"Database error updating pin: {str(e)}")
        return jsonify({"error": "Database error occurred"}), 500
    except Exception as e:
        print(f"Error updating pin: {str(e)}")
        return jsonify({"error": "Failed to update pin"}), 500
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'db' in locals():
            db.close()

@app.route('/pin/<int:pin_id>')
def view_pin(pin_id):
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # Get pin details with board and section names
        cursor.execute("""
            SELECT p.*, b.name as board_name, s.name as section_name,
                   uh.status as link_status, uh.archive_url
            FROM pins p
            LEFT JOIN boards b ON p.board_id = b.id
            LEFT JOIN sections s ON p.section_id = s.id
            LEFT JOIN url_health uh ON p.id = uh.pin_id
            WHERE p.id = %s
        """, (pin_id,))
        
        pin = cursor.fetchone()
        
        if not pin:
            return "Pin not found", 404
            
        # Get all boards for the board selector
        cursor.execute("SELECT * FROM boards ORDER BY name")
        boards = cursor.fetchall()
        
        # Get all sections for the current board
        cursor.execute("SELECT * FROM sections WHERE board_id = %s ORDER BY name", (pin['board_id'],))
        sections = cursor.fetchall()
        
        cursor.close()
        db.close()
        
        return render_template('pin.html', pin=pin, boards=boards, sections=sections)
    except Exception as e:
        print(f"Error in view_pin route: {str(e)}")
        return "An error occurred", 500

@app.route('/create-board', methods=['POST'])
def create_board():
    try:
        data = request.get_json()
        if data is None:
            return jsonify({"error": "Invalid JSON data"}), 400
            
        board_name = sanitize_string(data.get('name', ''), max_length=100)
        
        if not board_name:
            return jsonify({"error": "Board name is required"}), 400
        
        db = get_db_connection()
        cursor = db.cursor()
        
        try:
            # Create URL-friendly slug
            slug = re.sub(r'[^a-z0-9]+', '-', board_name.lower()).strip('-')
            
            # Check if board with same name exists
            cursor.execute("SELECT id FROM boards WHERE name = %s", (board_name,))
            existing_board = cursor.fetchone()
            if existing_board:
                return jsonify({"error": "A board with this name already exists"}), 409
            
            # Create the new board
            cursor.execute("""
                INSERT INTO boards (name, slug)
                VALUES (%s, %s)
            """, (board_name, slug))
            
            board_id = cursor.lastrowid
            db.commit()
            
            # Fetch the created board to confirm
            cursor.execute("SELECT id, name, slug FROM boards WHERE id = %s", (board_id,))
            new_board = cursor.fetchone()
            
            if not new_board:
                return jsonify({"error": "Failed to create board"}), 500
                
            # Invalidate gallery cache if Redis is available
            if redis_client:
                redis_client.delete('view//')
            return jsonify({
                'success': True,
                'board_id': board_id,
                'name': board_name,
                'slug': slug
            })
            
        except mysql.connector.Error as db_error:
            # Log the specific database error
            print(f"Database error in create_board: {str(db_error)}")
            db.rollback()
            return jsonify({"error": "Database error occurred"}), 500
            
    except Exception as e:
        # Log the general error
        print(f"Error in create_board: {str(e)}")
        return jsonify({"error": "Server error occurred"}), 500
        
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'db' in locals():
            db.close()

@app.route('/move-pin/<int:pin_id>', methods=['POST'])
def move_pin(pin_id):
    data = request.get_json()
    board_id = sanitize_integer(data.get('board_id'), min_value=1)
    pin_id = sanitize_integer(pin_id, min_value=1)
    
    if not board_id:
        return jsonify({"error": "Valid board ID is required"}), 400
    
    if not pin_id:
        return jsonify({"error": "Valid pin ID is required"}), 400
    
    try:
        db = get_db_connection()
        cursor = db.cursor()
        
        # First verify the pin exists
        cursor.execute("SELECT id FROM pins WHERE id = %s", (pin_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Pin not found"}), 404
        
        # Then verify the target board exists
        cursor.execute("SELECT id FROM boards WHERE id = %s", (board_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Target board not found"}), 404
        
        # Move the pin to the new board
        cursor.execute("""
            UPDATE pins 
            SET board_id = %s,
                section_id = NULL
            WHERE id = %s
        """, (board_id, pin_id))
        
        db.commit()
        
        # Invalidate gallery cache if Redis is available
        if redis_client:
            redis_client.delete('view//')
        return jsonify({'success': True})
    except mysql.connector.Error as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/create-section', methods=['POST'])
def create_section():
    try:
        data = request.get_json()
        board_id = sanitize_integer(data.get('board_id'))
        name = sanitize_string(data.get('name', ''), max_length=255)
        
        if not board_id or not name:
            return jsonify({"error": "Board ID and section name are required"}), 400
            
        db = get_db_connection()
        cursor = db.cursor()
        
        cursor.execute("""
            INSERT INTO sections (board_id, name)
            VALUES (%s, %s)
        """, (board_id, name))
        
        section_id = cursor.lastrowid
        db.commit()
        
        return jsonify({
            'success': True,
            'section': {
                'id': section_id,
                'name': name,
                'board_id': board_id
            }
        })
    except Exception as e:
        print(f"Error creating section: {str(e)}")
        return jsonify({"error": "Failed to create section"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/update-section/<int:section_id>', methods=['POST'])
def update_section(section_id):
    try:
        data = request.get_json()
        name = sanitize_string(data.get('name', ''), max_length=255)
        
        if not name:
            return jsonify({"error": "Section name is required"}), 400
            
        db = get_db_connection()
        cursor = db.cursor()
        
        cursor.execute("""
            UPDATE sections
            SET name = %s
            WHERE id = %s
        """, (name, section_id))
        
        db.commit()
        
        return jsonify({
            'success': True,
            'section': {
                'id': section_id,
                'name': name
            }
        })
    except Exception as e:
        print(f"Error updating section: {str(e)}")
        return jsonify({"error": "Failed to update section"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/delete-section/<int:section_id>', methods=['POST'])
def delete_section(section_id):
    try:
        db = get_db_connection()
        cursor = db.cursor()
        
        # First get the board_id for this section
        cursor.execute("SELECT board_id FROM sections WHERE id = %s", (section_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "Section not found"}), 404
            
        board_id = result[0]
        
        # Delete the section (this will set section_id to NULL for any pins in this section due to ON DELETE SET NULL)
        cursor.execute("DELETE FROM sections WHERE id = %s", (section_id,))
        db.commit()
        
        return jsonify({
            'success': True,
            'board_id': board_id
        })
    except Exception as e:
        print(f"Error deleting section: {str(e)}")
        return jsonify({"error": "Failed to delete section"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/move-pin-to-section/<int:pin_id>', methods=['POST'])
def move_pin_to_section(pin_id):
    try:
        data = request.get_json()
        section_id = sanitize_integer(data.get('section_id'))
        
        if section_id is None:  # Allow NULL section_id to remove from section
            section_id = None
            
        db = get_db_connection()
        cursor = db.cursor()
        
        # Verify the pin exists
        cursor.execute("SELECT board_id FROM pins WHERE id = %s", (pin_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "Pin not found"}), 404
            
        board_id = result[0]
        
        # If section_id is provided, verify it belongs to the same board
        if section_id:
            cursor.execute("SELECT id FROM sections WHERE id = %s AND board_id = %s", (section_id, board_id))
            if not cursor.fetchone():
                return jsonify({"error": "Section not found or belongs to different board"}), 400
        
        # Update the pin's section
        cursor.execute("""
            UPDATE pins
            SET section_id = %s
            WHERE id = %s
        """, (section_id, pin_id))
        
        db.commit()
        
        return jsonify({
            'success': True,
            'pin_id': pin_id,
            'section_id': section_id
        })
    except Exception as e:
        print(f"Error moving pin to section: {str(e)}")
        return jsonify({"error": "Failed to move pin"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/rename-board/<int:board_id>', methods=['POST'])
def rename_board(board_id):
    try:
        data = request.get_json()
        new_name = data.get('name', '').strip()
        
        if not new_name:
            return jsonify({"error": "Board name is required"}), 400
            
        db = get_db_connection()
        cursor = db.cursor()
        
        cursor.execute("UPDATE boards SET name = %s WHERE id = %s", (new_name, board_id))
        db.commit()
        
        cursor.close()
        db.close()
        
        # Invalidate gallery cache if Redis is available
        if redis_client:
            redis_client.delete('view//')
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error renaming board: {str(e)}")
        return jsonify({"error": "Failed to rename board"}), 500

@app.route('/move-board/<int:board_id>', methods=['POST'])
def move_board(board_id):
    try:
        data = request.get_json()
        target_board_id = data.get('target_board_id')
        
        if not target_board_id:
            return jsonify({"error": "Target board ID is required"}), 400
            
        db = get_db_connection()
        cursor = db.cursor()
        
        # First, move all pins to the target board
        cursor.execute("UPDATE pins SET board_id = %s WHERE board_id = %s", (target_board_id, board_id))
        
        # Then, move all sections to the target board
        cursor.execute("UPDATE sections SET board_id = %s WHERE board_id = %s", (target_board_id, board_id))
        
        # Finally, delete the original board
        cursor.execute("DELETE FROM boards WHERE id = %s", (board_id,))
        
        db.commit()
        
        cursor.close()
        db.close()
        
        # Invalidate gallery cache if Redis is available
        if redis_client:
            redis_client.delete('view//')
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error moving board: {str(e)}")
        return jsonify({"error": "Failed to move board"}), 500

@app.route('/delete-board/<int:board_id>', methods=['POST'])
def delete_board(board_id):
    try:
        db = get_db_connection()
        cursor = db.cursor()
        
        # First, delete all pins in the board
        cursor.execute("DELETE FROM pins WHERE board_id = %s", (board_id,))
        
        # Then, delete all sections in the board
        cursor.execute("DELETE FROM sections WHERE board_id = %s", (board_id,))
        
        # Finally, delete the board itself
        cursor.execute("DELETE FROM boards WHERE id = %s", (board_id,))
        
        db.commit()
        
        cursor.close()
        db.close()
        
        # Invalidate gallery cache if Redis is available
        if redis_client:
            redis_client.delete('view//')
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error deleting board: {str(e)}")
        return jsonify({"error": "Failed to delete board"}), 500

@app.route('/random')
def random_pin():
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # First get the total count of pins
        cursor.execute("SELECT COUNT(*) as count FROM pins")
        total_pins = cursor.fetchone()['count']
        
        if total_pins == 0:
            return "No pins found", 404
            
        # Get a random offset
        random_offset = random.randint(0, total_pins - 1)
        
        # Get the random pin with a single efficient query
        cursor.execute("""
            SELECT p.*, b.name as board_name, s.name as section_name
            FROM pins p
            LEFT JOIN boards b ON p.board_id = b.id
            LEFT JOIN sections s ON p.section_id = s.id
            LIMIT 1 OFFSET %s
        """, (random_offset,))
        
        pin = cursor.fetchone()
        
        cursor.close()
        db.close()
        
        return redirect(url_for('view_pin', pin_id=pin['id']))
    except Exception as e:
        print(f"Error in random pin route: {str(e)}")
        return "An error occurred", 500

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

@app.route('/delete-pin/<int:pin_id>', methods=['POST'])
def delete_pin(pin_id):
    try:
        db = get_db_connection()
        cursor = db.cursor()
        
        # First get the board_id for this pin
        cursor.execute("SELECT board_id FROM pins WHERE id = %s", (pin_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "Pin not found"}), 404
            
        board_id = result[0]
        
        # Delete the pin
        cursor.execute("DELETE FROM pins WHERE id = %s", (pin_id,))
        db.commit()
        
        return jsonify({
            'success': True,
            'board_id': board_id
        })
    except Exception as e:
        print(f"Error deleting pin: {str(e)}")
        return jsonify({"error": "Failed to delete pin"}), 500
    finally:
        cursor.close()
        db.close()

def create_indexes():
    try:
        db = get_db_connection()
        cursor = db.cursor()
        
        # Create indexes for frequently queried columns
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_boards_name ON boards(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pins_board_id ON pins(board_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pins_section_id ON pins(section_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sections_board_id ON sections(board_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pins_created_at ON pins(created_at)")
        
        # Create URL health tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS url_health (
                id INT AUTO_INCREMENT PRIMARY KEY,
                pin_id INT NOT NULL,
                url VARCHAR(2048) NOT NULL,
                last_checked DATETIME,
                status ENUM('unknown', 'live', 'broken', 'archived') DEFAULT 'unknown',
                archive_url VARCHAR(2048),
                FOREIGN KEY (pin_id) REFERENCES pins(id) ON DELETE CASCADE
            )
        """)
        
        db.commit()
        print("✅ Database indexes and URL health table created successfully")
    except mysql.connector.Error as err:
        print(f"❌ Error creating indexes: {err}")
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'db' in locals():
            try:
                db.close()
            except:
                pass  # Ignore errors during cleanup

# Background task for URL health checking (enabled in all environments)
import threading
import time
import requests
from datetime import datetime, timedelta
from urllib.parse import quote

def check_url_health():
    # Run URL health checking in all environments
    while True:
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            
            # Get URLs that haven't been checked in the last week
            cursor.execute("""
                SELECT p.id as pin_id, p.link as url
                FROM pins p
                LEFT JOIN url_health uh ON p.id = uh.pin_id
                WHERE p.link IS NOT NULL 
                AND (uh.last_checked IS NULL OR uh.last_checked < DATE_SUB(NOW(), INTERVAL 1 WEEK))
                LIMIT 10
            """)
            
            urls_to_check = cursor.fetchall()
            
            for url_data in urls_to_check:
                try:
                    # Set up headers to mimic a browser
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (compatible; ScrapbookBot/1.0; +https://github.com/isaaclee0/scrapbook)',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                    }
                    
                    # Check if URL is accessible
                    response = requests.head(url_data['url'], headers=headers, timeout=3, allow_redirects=True)
                    status = 'live' if response.status_code < 400 else 'broken'
                    archive_url = None
                    
                    # If broken, try to find an archive.is version
                    if status == 'broken':
                        try:
                            # First check if the URL is already archived
                            archive_check = requests.get(
                                f"https://archive.is/{quote(url_data['url'])}",
                                headers=headers,
                                timeout=2,
                                allow_redirects=True
                            )
                            if archive_check.status_code == 200 and 'archive.is' in archive_check.url:
                                archive_url = archive_check.url
                                status = 'archived'
                            else:
                                # If not archived, create an archive.is link
                                archive_url = f"https://archive.is/{quote(url_data['url'])}"
                        except:
                            # If archive check fails, keep status as 'broken'
                            pass
                    
                    # Ensure status is one of the allowed ENUM values
                    if status not in ['unknown', 'live', 'broken', 'archived']:
                        status = 'unknown'
                    
                    # Update or insert URL health record
                    cursor.execute("""
                        INSERT INTO url_health (pin_id, url, last_checked, status, archive_url)
                        VALUES (%s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                        last_checked = VALUES(last_checked),
                        status = VALUES(status),
                        archive_url = VALUES(archive_url)
                    """, (
                        url_data['pin_id'],
                        url_data['url'],
                        datetime.now(),
                        status,
                        archive_url
                    ))
                    
                    db.commit()
                    
                except Exception as e:
                    print(f"Error checking URL {url_data['url']}: {str(e)}")
                    continue
                
                # Sleep for 5 seconds between checks (much faster)
                time.sleep(5)
            
        except Exception as e:
            print(f"Error in URL health check background task: {str(e)}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'db' in locals():
                try:
                    db.close()
                except:
                    pass
        
        # Sleep for 2 minutes before next batch (much faster)
        time.sleep(120)

# Start the background task when the app starts
def start_background_tasks():
    url_check_thread = threading.Thread(target=check_url_health, daemon=True)
    url_check_thread.start()

# Call this at the end of the file, before app.run()
start_background_tasks()

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_ENV') == 'development'
    app.run(debug=debug_mode, host='0.0.0.0', port=8000)