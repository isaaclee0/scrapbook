from flask import Flask, render_template, jsonify, request, send_from_directory, redirect, url_for, make_response, g
import mysql.connector
import os
from mysql.connector import pooling
import random
import threading
from werkzeug.routing import BaseConverter
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import html
import unicodedata
import time
import base64
import hashlib
from functools import wraps
from datetime import datetime
from contextlib import contextmanager
import traceback

# Import authentication modules
from auth_utils import generate_magic_link_token, generate_session_token, verify_token, refresh_session_token, generate_otp, store_otp, verify_otp
from email_service import send_otp_email, send_welcome_email
from audit_helpers import record_audit, snapshot_board, snapshot_pin, snapshot_section

# Try to import redis, but make it optional
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("Redis module not available, running without cache")

# Load version from VERSION file
try:
    with open('VERSION', 'r') as f:
        VERSION = f.read().strip()
except FileNotFoundError:
    VERSION = 'unknown'

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
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Skip caching in development mode
            if os.getenv('FLASK_ENV') == 'development':
                return f(*args, **kwargs)
            if not redis_client:
                return f(*args, **kwargs)
            # Include user_id in key so each user has their own cached view
            token = request.cookies.get('session_token')
            user_id = 'anon'
            if token:
                try:
                    payload = verify_token(token, token_type='session')
                    if payload:
                        user_id = str(payload.get('user_id', 'anon'))
                except Exception:
                    pass
            qs = request.query_string.decode('utf-8')
            cache_key = f"view:{user_id}:{request.path}{'?' + qs if qs else ''}"
            cached_data = redis_client.get(cache_key)
            if cached_data:
                return cached_data
            response = f(*args, **kwargs)
            # Don't cache error tuples — pass them through unchanged
            if isinstance(response, tuple):
                return response
            # Store and return HTML responses
            if hasattr(response, 'data'):
                redis_client.setex(cache_key, timeout, response.data.decode('utf-8'))
            elif isinstance(response, str):
                redis_client.setex(cache_key, timeout, response)
            return response
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
    
    url = url.strip()
    
    # Check for data URLs (for pasted images) - these should be handled by save_pasted_image() function
    if url.startswith('data:image/'):
        # Data URLs should not reach this function anymore, but handle gracefully
        return ''
    
    # Check for relative URLs (for default images)
    if url.startswith('/static/'):
        return url
    
    # Basic URL validation regex for HTTP/HTTPS URLs
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
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

def calculate_image_dimensions(image_url, timeout=2):
    """Calculate image dimensions for a given URL - optimized for speed"""
    try:
        # For local/cached images - these are fast and reliable
        if image_url.startswith('/'):
            if image_url.startswith('/cached/'):
                cached_path = os.path.join('static', 'cached_images', image_url[8:])
                if os.path.exists(cached_path):
                    from PIL import Image
                    with Image.open(cached_path) as img:
                        return img.size  # Returns (width, height)
            elif image_url.startswith('/static/'):
                static_path = image_url[1:]  # Remove leading slash
                if os.path.exists(static_path):
                    from PIL import Image
                    with Image.open(static_path) as img:
                        return img.size
            return None
        
        # For external URLs - use intelligent defaults based on common Pinterest patterns
        # This avoids slow network requests that can block the UI
        if image_url.startswith('http'):
            # Return intelligent defaults based on URL patterns or random selection
            import random
            # Common Pinterest aspect ratios
            aspect_ratios = [
                (400, 600),   # Portrait: 2:3 ratio (most common)
                (400, 500),   # Portrait: 4:5 ratio
                (400, 400),   # Square: 1:1 ratio
                (400, 300),   # Landscape: 4:3 ratio
                (400, 533),   # Portrait: 3:4 ratio
                (400, 800),   # Tall portrait: 1:2 ratio
            ]
            # Use a deterministic but varied selection based on URL hash
            url_hash = hash(image_url) % len(aspect_ratios)
            return aspect_ratios[url_hash]
            
        return None
        
    except Exception as e:
        print(f"Error calculating dimensions for {image_url}: {e}")
        return None

def update_pin_dimensions(pin_id, image_url):
    """
    Update pin dimensions by storing them in cached_images table.
    Creates a cached_images record if one doesn't exist, with dimensions only.
    This is used for immediate dimension availability before full caching completes.
    """
    db = None
    cursor = None
    try:
        dimensions = calculate_image_dimensions(image_url)
        if not dimensions:
            return False
        
        width, height = dimensions
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # First, check if a cached_images record already exists for this URL
        cursor.execute("""
            SELECT id, width, height FROM cached_images 
            WHERE original_url = %s AND quality_level = 'low'
            LIMIT 1
        """, (image_url,))
        cached_record = cursor.fetchone()
        
        if cached_record:
            cache_id = cached_record['id']
            # Only update dimensions if they're not already set
            if not cached_record['width'] or not cached_record['height']:
                cursor.execute("""
                    UPDATE cached_images 
                    SET width = %s, height = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (width, height, cache_id))
        else:
            # Create a new cached_images record with dimensions only
            # The actual image caching will happen in the background
            import hashlib
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:16]
            placeholder_filename = f"{url_hash}_pending.placeholder"
            
            cursor.execute("""
                INSERT INTO cached_images 
                (original_url, cached_filename, file_size, width, height, quality_level, cache_status)
                VALUES (%s, %s, 0, %s, %s, 'low', 'pending')
            """, (image_url, placeholder_filename, width, height))
            cache_id = cursor.lastrowid
        
        # Link the pin to the cached_images record
        cursor.execute("""
            UPDATE pins 
            SET cached_image_id = %s 
            WHERE id = %s AND cached_image_id IS NULL
        """, (cache_id, pin_id))
        
        db.commit()
        return True
        
    except Exception as e:
        print(f"Error updating pin dimensions: {e}")
        if db:
            try:
                db.rollback()
            except Exception:
                pass
        return False
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if db:
            try:
                db.close()
            except Exception:
                pass

# Database connection pool configuration
dbconfig = {
    "host": os.getenv('DB_HOST', 'db'),
    "user": os.getenv('DB_USER', 'db'),
    "password": os.getenv('DB_PASSWORD') or os.getenv('MYSQL_PASSWORD'),
    "database": os.getenv('DB_NAME', 'db'),
    "pool_name": "mypool",
    "pool_size": 20,  # Increased from 10 to handle more concurrent requests
    "pool_reset_session": True,  # Reset session state when returning connection to pool
    "autocommit": True,
    "charset": 'utf8mb4',
    "collation": 'utf8mb4_unicode_ci',
    "connection_timeout": 5,  # Timeout for getting connection from pool
    "use_unicode": True
}

# Create connection pool
try:
    cnxpool = mysql.connector.pooling.MySQLConnectionPool(**dbconfig)
    print("Database connection pool created successfully")
except mysql.connector.Error as err:
    print(f"Error creating connection pool: {err}")
    cnxpool = None

# ---------------------------------------------------------------------------
# Background image caching
# Triggered when the browser successfully loads an image from an external URL.
# Downloads the file to static/cached_images/ in a daemon thread so the pin
# serves locally on all future page loads.
# ---------------------------------------------------------------------------

# Cap concurrent background downloads so a busy board doesn't flood outbound.
_bg_cache_semaphore = threading.Semaphore(4)

# Matches what image_cache_service.py uses so cached files are interchangeable.
_CACHE_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.pinterest.com/',  # helps bypass Pinterest CDN checks
    'Sec-Fetch-Dest': 'image',
    'Sec-Fetch-Mode': 'no-cors',
    'Sec-Fetch-Site': 'cross-site',
}

def _bg_download_and_cache(pin_id, image_url, width, height, cache_id):
    """
    Download an external image to local cache. Runs in a daemon thread.
    Updates cached_images and pins so future loads hit /cached/ instead of
    the external CDN.
    """
    if not _bg_cache_semaphore.acquire(blocking=False):
        # All slots busy — skip for now, browser will retry on next page load.
        return
    try:
        url_hash = hashlib.md5(image_url.encode()).hexdigest()[:16]
        cache_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'static', 'cached_images'
        )
        os.makedirs(cache_dir, exist_ok=True)

        # Download with a browser-like session
        resp = requests.get(image_url, headers=_CACHE_HEADERS, timeout=30, stream=True)
        resp.raise_for_status()

        content_type = resp.headers.get('content-type', '').lower()
        if not content_type.startswith('image/'):
            return  # Not an image — don't cache

        # Derive extension from content-type, fall back to URL
        if 'png' in content_type:
            ext = 'png'
        elif 'webp' in content_type:
            ext = 'webp'
        elif 'gif' in content_type:
            ext = 'gif'
        else:
            ext = 'jpg'

        filename = f"{url_hash}_low.{ext}"
        filepath = os.path.join(cache_dir, filename)

        # Write to disk (skip if already present from a previous attempt)
        if not os.path.exists(filepath):
            with open(filepath, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

        file_size = os.path.getsize(filepath)

        # Update DB: mark as fully cached and link pin to local file
        db = get_db_connection()
        cursor = db.cursor()
        try:
            if cache_id:
                cursor.execute("""
                    UPDATE cached_images
                       SET cached_filename = %s,
                           file_size       = %s,
                           width           = %s,
                           height          = %s,
                           cache_status    = 'cached',
                           updated_at      = NOW()
                     WHERE id = %s
                """, (filename, file_size, width, height, cache_id))
            else:
                cursor.execute("""
                    INSERT INTO cached_images
                        (original_url, cached_filename, file_size, width, height,
                         quality_level, cache_status)
                    VALUES (%s, %s, %s, %s, %s, 'low', 'cached')
                    ON DUPLICATE KEY UPDATE
                        cached_filename = VALUES(cached_filename),
                        file_size       = VALUES(file_size),
                        width           = VALUES(width),
                        height          = VALUES(height),
                        cache_status    = 'cached',
                        updated_at      = NOW()
                """, (image_url, filename, file_size, width, height))
                cache_id = cursor.lastrowid

            cursor.execute("""
                UPDATE pins
                   SET cached_image_id    = %s,
                       uses_cached_image  = TRUE
                 WHERE id = %s
            """, (cache_id, pin_id))
            db.commit()
            print(f"[cache] pin {pin_id} → {filename} ({file_size:,} bytes)")
        finally:
            cursor.close()
            db.close()

    except Exception as e:
        print(f"[cache] pin {pin_id} failed: {e}")
    finally:
        _bg_cache_semaphore.release()

def get_db_connection():
    """
    Get a database connection from the pool.
    Raises an exception if connection cannot be obtained.
    """
    try:
        if cnxpool:
            try:
                return cnxpool.get_connection()
            except mysql.connector.pooling.PoolError as pool_err:
                # Pool exhausted - log and re-raise with more context
                print(f"Database connection pool exhausted: {pool_err}")
                print(f"Pool size: {cnxpool.pool_size}, active connections may be leaked")
                raise mysql.connector.Error(f"Database connection pool exhausted. Please try again in a moment.")
        else:
            return mysql.connector.connect(**dbconfig)
    except mysql.connector.Error as err:
        print(f"Error getting database connection: {err}")
        raise


@contextmanager
def tx(dictionary=False):
    """
    Transactional context manager. The pool default is autocommit=True; this
    helper explicitly disables autocommit for the duration of the block so all
    statements run inside a single transaction that either commits as a whole
    or rolls back on exception.

    Usage:
        with tx() as (db, cursor):
            cursor.execute(...)
            cursor.execute(...)

    Pass dictionary=True for a dict cursor.
    """
    db = get_db_connection()
    db.autocommit = False
    cursor = db.cursor(dictionary=dictionary, buffered=True)
    try:
        yield db, cursor
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            # Restore the pool default before returning the connection.
            db.autocommit = True
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass

# ============================================================================
# AUTHENTICATION FUNCTIONS
# ============================================================================

def get_current_user():
    """
    Get the currently authenticated user from session cookie
    Returns user dict or None
    """
    token = request.cookies.get('session_token')
    if not token:
        return None
    
    payload = verify_token(token, token_type='session')
    if not payload:
        return None
    
    return {
        'id': payload.get('user_id'),
        'email': payload.get('email')
    }

@app.before_request
def refresh_token_if_needed():
    """
    Automatically refresh session tokens that are close to expiring.
    This extends user sessions so they don't have to log in every 30 days.
    """
    # Skip token refresh for auth routes and health check
    if request.path.startswith('/auth/') or request.path == '/health':
        return
    
    token = request.cookies.get('session_token')
    if token:
        # Try to refresh the token if it's close to expiring
        new_token = refresh_session_token(token)
        if new_token and new_token != token:
            # Store the refreshed token to set in after_request
            g.refreshed_token = new_token
        else:
            g.refreshed_token = None
    else:
        g.refreshed_token = None

@app.after_request
def set_refreshed_token_cookie(response):
    """
    Set refreshed token cookie if token was refreshed in before_request
    """
    if hasattr(g, 'refreshed_token') and g.refreshed_token:
        set_session_cookie(response, g.refreshed_token)
    return response

@app.context_processor
def inject_version():
    """Make VERSION available to all templates"""
    return {'VERSION': VERSION}

def login_required(f):
    """
    Decorator to require authentication for a route
    For API endpoints, returns JSON error instead of redirecting
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            # Check if this is an API endpoint (starts with /api/)
            # or a POST/PUT/DELETE request with JSON content
            is_api_endpoint = request.path.startswith('/api/')
            is_json_request = request.method in ['POST', 'PUT', 'DELETE'] and request.is_json
            if is_api_endpoint or is_json_request:
                return jsonify({"error": "Authentication required", "success": False}), 401
            # For non-API routes, redirect to login
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

def set_session_cookie(response, token):
    """
    Set secure session cookie with JWT token
    """
    is_production = os.getenv('FLASK_ENV') != 'development'
    
    response.set_cookie(
        'session_token',
        token,
        max_age=int(os.getenv('SESSION_EXPIRY', 2592000)),  # 30 days default
        secure=is_production,  # Only send over HTTPS in production
        httponly=True,  # Prevent JavaScript access
        samesite='Lax'  # CSRF protection
    )
    return response

# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

@app.route('/auth/login', methods=['GET', 'POST'])
def login_page():
    """
    Login page - show form, send OTP, or verify OTP
    """
    if request.method == 'GET':
        # Show login page
        return render_template('login.html')
    
    # POST - handle OTP generation or verification
    data = request.get_json()
    action = data.get('action', 'request')  # 'request' or 'verify'
    email = sanitize_string(data.get('email', ''), max_length=255).lower().strip()
    
    if not email or '@' not in email:
        return jsonify({"error": "Valid email address is required"}), 400
    
    db = None
    cursor = None
    
    try:
        # Check if user exists, create if not
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True, buffered=True)
            
            cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            
            if not user:
                # Create new user
                cursor.execute(
                    "INSERT INTO users (email, created_at) VALUES (%s, NOW())",
                    (email,)
                )
                db.commit()
                
                # Send welcome email
                send_welcome_email(email)
        except mysql.connector.Error as db_err:
            print(f"Database error in login: {str(db_err)}")
            return jsonify({"error": "Database temporarily unavailable. Please try again in a moment."}), 503
        finally:
            if cursor:
                try:
                    try:
                        cursor.fetchall()
                    except Exception:
                        pass
                    cursor.close()
                except Exception:
                    pass
            if db:
                try:
                    db.close()
                except Exception:
                    pass
        
        if action == 'request':
            # Generate and send OTP
            otp = generate_otp()
            
            # Store OTP (prefer Redis, fallback to database)
            if redis_client:
                store_otp(email, otp, redis_client)
            else:
                # Store in database with expiration
                db = get_db_connection()
                cursor = db.cursor()
                try:
                    from auth_utils import OTP_EXPIRY
                    from datetime import datetime, timedelta
                    expires_at = datetime.utcnow() + timedelta(seconds=OTP_EXPIRY)
                    cursor.execute(
                        "INSERT INTO otp_codes (email, otp, expires_at) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE otp = %s, expires_at = %s",
                        (email, otp, expires_at, otp, expires_at)
                    )
                    db.commit()
                except mysql.connector.Error as e:
                    # Table might not exist, create it
                    if e.errno == 1146:  # Table doesn't exist
                        cursor.execute("""
                            CREATE TABLE IF NOT EXISTS otp_codes (
                                email VARCHAR(255) NOT NULL,
                                otp VARCHAR(6) NOT NULL,
                                expires_at TIMESTAMP NOT NULL,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                PRIMARY KEY (email),
                                INDEX idx_otp_expires_at (expires_at)
                            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                        """)
                        db.commit()
                        # Retry the insert
                        from auth_utils import OTP_EXPIRY
                        from datetime import datetime, timedelta
                        expires_at = datetime.utcnow() + timedelta(seconds=OTP_EXPIRY)
                        cursor.execute(
                            "INSERT INTO otp_codes (email, otp, expires_at) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE otp = %s, expires_at = %s",
                            (email, otp, expires_at, otp, expires_at)
                        )
                        db.commit()
                    else:
                        raise
                finally:
                    cursor.close()
                    db.close()
            
            # Send OTP email
            if send_otp_email(email, otp):
                return jsonify({
                    "success": True,
                    "message": "OTP sent! Check your email.",
                    "action": "verify"  # Signal to show OTP input
                })
            else:
                return jsonify({"error": "Failed to send email"}), 500
        
        elif action == 'verify':
            # Verify OTP
            otp = data.get('otp', '').strip()
            
            if not otp or len(otp) != 6 or not otp.isdigit():
                return jsonify({"error": "Please enter a valid 6-digit code"}), 400
            
            # Verify OTP (prefer Redis, fallback to database)
            is_valid = False
            if redis_client:
                is_valid = verify_otp(email, otp, redis_client)
            else:
                # Verify from database
                db = get_db_connection()
                cursor = db.cursor(dictionary=True)
                try:
                    cursor.execute(
                        "SELECT otp FROM otp_codes WHERE email = %s AND expires_at > NOW()",
                        (email,)
                    )
                    result = cursor.fetchone()
                    if result and result['otp'] == otp:
                        is_valid = True
                        # Delete OTP after use
                        cursor.execute("DELETE FROM otp_codes WHERE email = %s", (email,))
                        db.commit()
                except mysql.connector.Error as e:
                    # Table might not exist
                    if e.errno == 1146:  # Table doesn't exist
                        cursor.execute("""
                            CREATE TABLE IF NOT EXISTS otp_codes (
                                email VARCHAR(255) NOT NULL,
                                otp VARCHAR(6) NOT NULL,
                                expires_at TIMESTAMP NOT NULL,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                PRIMARY KEY (email),
                                INDEX idx_otp_expires_at (expires_at)
                            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                        """)
                        db.commit()
                    else:
                        raise
                finally:
                    cursor.close()
                    db.close()
            
            if not is_valid:
                return jsonify({"error": "Invalid or expired code. Please try again."}), 400
            
            # OTP verified - create session
            db = None
            cursor = None
            try:
                db = get_db_connection()
                cursor = db.cursor(dictionary=True, buffered=True)
                cursor.execute("SELECT id, email FROM users WHERE email = %s", (email,))
                user = cursor.fetchone()
                
                if not user:
                    return jsonify({"error": "User not found"}), 404
                
                # Update last login
                cursor.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user['id'],))
                db.commit()
            finally:
                if cursor:
                    try:
                        cursor.close()
                    except Exception:
                        pass
                if db:
                    try:
                        db.close()
                    except Exception:
                        pass
            
            # Generate session token
            session_token = generate_session_token(user['id'], user['email'])
            
            # Create response and set cookie
            response = make_response(jsonify({
                "success": True,
                "message": "Login successful",
                "redirect": url_for('gallery')
            }))
            set_session_cookie(response, session_token)
            
            return response
        
        else:
            return jsonify({"error": "Invalid action"}), 400
            
    except Exception as e:
        print(f"Error in login: {str(e)}")
        traceback.print_exc()
        # Ensure cleanup on any error
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if db:
            try:
                db.close()
            except Exception:
                pass
        return jsonify({"error": "An error occurred"}), 500

@app.route('/auth/verify')
def verify_magic_link():
    """
    Magic link login is no longer used — login is OTP-based.
    Route kept so old bookmarked magic-link URLs redirect gracefully instead of 404ing.
    """
    return redirect(url_for('login_page'))

@app.route('/auth/logout')
def logout():
    """
    Logout user by clearing session cookie
    """
    response = make_response(redirect(url_for('login_page')))
    response.set_cookie('session_token', '', expires=0)
    return response

@app.route('/health')
def health_check():
    """
    Health check endpoint for Docker and monitoring systems.
    Returns 200 OK without requiring authentication.
    """
    return jsonify({"status": "ok"}), 200

@app.route('/')
@login_required
@cache_view(timeout=300)  # Cache for 5 minutes
def gallery():
    user = get_current_user()
    db = None
    cursor = None
    try:
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True, buffered=True)
        except mysql.connector.Error as db_err:
            # Database unavailable - return user-friendly error
            print(f"Database error in gallery: {str(db_err)}")
            return render_template('auth_error.html', message="Database temporarily unavailable. Please try again in a moment."), 503
        
        # Get boards with pin count and image (user-scoped)
        cursor.execute("""
            SELECT 
                b.*,
                COUNT(p.id) as pin_count,
                b.created_at
            FROM boards b
            LEFT JOIN pins p ON b.id = p.board_id AND p.user_id = %s
            WHERE b.user_id = %s
            GROUP BY b.id
            ORDER BY b.name
        """, (user['id'], user['id']))
        boards = cursor.fetchall()
        
        # For each board, determine and save the display image
        # Use buffered cursor to prevent "Unread result found" errors when executing multiple queries
        for board in boards:
            if board['default_image_url']:
                # Use the custom default image
                board['random_pin_image_url'] = board['default_image_url']
            elif board['pin_count'] > 0:
                # No default set, but has pins - select a random one and save it
                try:
                    cursor.execute("""
                        SELECT image_url 
                        FROM pins 
                        WHERE board_id = %s AND user_id = %s
                        ORDER BY RAND() 
                        LIMIT 1
                    """, (board['id'], user['id']))
                    pin = cursor.fetchone()
                    
                    if pin and pin['image_url']:
                        # Save this random selection as the default so it doesn't change
                        cursor.execute("""
                            UPDATE boards 
                            SET default_image_url = %s 
                            WHERE id = %s AND user_id = %s AND default_image_url IS NULL
                        """, (pin['image_url'], board['id'], user['id']))
                        db.commit()
                        board['random_pin_image_url'] = pin['image_url']
                    else:
                        board['random_pin_image_url'] = '/static/images/default_board.png'
                except mysql.connector.Error as e:
                    # If there's an error in the loop, log it but continue
                    print(f"Error processing board {board['id']} in gallery: {str(e)}")
                    board['random_pin_image_url'] = '/static/images/default_board.png'
            else:
                # No pins, use default image
                board['random_pin_image_url'] = '/static/images/default_board.png'
                
        # Invalidate gallery cache if Redis is available
        if redis_client:
            redis_client.delete(f"view:{user['id']}:/")

    except mysql.connector.Error as e:
        print(f"Database error in gallery: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            try:
                # Ensure all results are consumed before closing
                try:
                    cursor.fetchall()
                except Exception:
                    pass
                cursor.close()
            except Exception as cursor_close_error:
                print(f"gallery: error closing cursor: {cursor_close_error}")
        if db:
            try:
                db.close()
            except Exception as db_close_error:
                print(f"gallery: error closing db connection: {db_close_error}")

    return render_template('boards.html', boards=boards)

@app.route('/board/<int:board_id>')
@login_required
def board(board_id):
    user = get_current_user()
    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True, buffered=True)
        
        # Get board details (user-scoped)
        cursor.execute("SELECT * FROM boards WHERE id = %s AND user_id = %s", (board_id, user['id']))
        board = cursor.fetchone()
        if not board:
            return "Board not found", 404
            
        # Get sections for this board with pin count
        cursor.execute("""
            SELECT s.*,
                   COUNT(p.id) as pin_count
            FROM sections s
            LEFT JOIN pins p ON p.section_id = s.id
                             AND p.board_id = s.board_id
                             AND p.user_id = %s
            WHERE s.board_id = %s
            GROUP BY s.id
            ORDER BY s.name
        """, (user['id'], board_id))
        sections = cursor.fetchall()
        
        # Check if this is a featured view (from search) - load all pins if so
        is_featured = request.args.get('featured') or request.args.get('highlight')
        
        # Get total pin count for pagination
        cursor.execute("""
            SELECT COUNT(*) as total
            FROM pins p
            WHERE p.board_id = %s AND p.user_id = %s
        """, (board_id, user['id']))
        total_pins = cursor.fetchone()['total']
        
        # Determine initial limit: 1.5 screens (~30-45 pins) unless featured
        if is_featured:
            initial_limit = total_pins  # Load all if featured
        else:
            initial_limit = 40  # ~1.5 screens worth of pins
        
        # Get initial pins for this board (simplified - no dimension queries)
        try:
            # Check if cached_images table exists
            cursor.execute("SHOW TABLES LIKE 'cached_images'")
            result = cursor.fetchone()
            cached_images_exists = result is not None
            # Consume any remaining results
            cursor.fetchall()
            
            if cached_images_exists:
                # Include cached images data with dimensions for layout stability
                cursor.execute("""
                    SELECT p.*, s.name as section_name, 
                           ci.cached_filename, ci.cache_status,
                           ci.width as cached_width, ci.height as cached_height
                    FROM pins p 
                    LEFT JOIN sections s ON p.section_id = s.id 
                    LEFT JOIN cached_images ci ON p.cached_image_id = ci.id AND ci.cache_status = 'cached'
                    WHERE p.board_id = %s AND p.user_id = %s
                    ORDER BY p.created_at DESC, p.id ASC
                    LIMIT %s
                """, (board_id, user['id'], initial_limit))
            else:
                # Fallback query without cached images
                cursor.execute("""
                    SELECT p.*, s.name as section_name, 
                           NULL as cached_filename, NULL as cache_status
                    FROM pins p 
                    LEFT JOIN sections s ON p.section_id = s.id 
                    WHERE p.board_id = %s AND p.user_id = %s
                    ORDER BY p.created_at DESC, p.id ASC
                    LIMIT %s
                """, (board_id, user['id'], initial_limit))
        except Exception as e:
            # Fallback to basic query if there are any issues
            print(f"Warning: Could not check cached_images table, using fallback query: {e}")
            cursor.execute("""
                SELECT p.*, s.name as section_name, 
                       NULL as cached_filename, NULL as cache_status
                FROM pins p 
                LEFT JOIN sections s ON p.section_id = s.id 
                WHERE p.board_id = %s AND p.user_id = %s
                ORDER BY p.created_at DESC, p.id ASC
                LIMIT %s
            """, (board_id, user['id'], initial_limit))
        pins = cursor.fetchall()
        
        # Get all boards for the move board functionality (user-scoped)
        cursor.execute("SELECT * FROM boards WHERE user_id = %s ORDER BY name", (user['id'],))
        all_boards = cursor.fetchall()
        
        # Pass environment info to template
        flask_env = os.getenv('FLASK_ENV', 'production')
        is_development = flask_env in ['development', 'debug']
        
        # Create response with appropriate caching headers
        from flask import make_response, Response
        response = make_response(render_template('board.html', board=board, sections=sections, pins=pins, all_boards=all_boards, is_development=is_development, total_pin_count=total_pins, is_featured=is_featured))
        
        if is_development:
            # Cache-busting headers in development
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        else:
            # Enable browser caching in production for faster subsequent loads
            # Use ETag based on board_id + user_id + board updated_at timestamp + total pins
            board_updated = board.get('updated_at') or board.get('created_at') or ''
            etag_data = f"{board_id}_{user['id']}_{board_updated}_{total_pins}"
            etag = hashlib.md5(etag_data.encode()).hexdigest()
            
            # Check if client has a matching ETag (304 Not Modified)
            if request.headers.get('If-None-Match') == etag:
                return Response(status=304)
            
            response.headers['ETag'] = etag
            response.headers['Cache-Control'] = 'private, max-age=300'  # Cache for 5 minutes
            response.headers['Vary'] = 'Cookie'  # Vary by user session
        
        return response
    except Exception as e:
        print(f"Error in board route: {str(e)}")
        traceback.print_exc()
        return "An error occurred", 500
    finally:
        if cursor:
            try:
                # Ensure all results are consumed before closing
                try:
                    cursor.fetchall()
                except Exception:
                    pass
                cursor.close()
            except Exception as cursor_close_error:
                print(f"board: error closing cursor: {cursor_close_error}")
        if db:
            try:
                db.close()
            except Exception as db_close_error:
                print(f"board: error closing db connection: {db_close_error}")

@app.route('/search', methods=['GET'])
@login_required
def search():
    user = get_current_user()
    query = request.args.get('q', '').strip()
    if not query:
        return render_template('search.html', matching_boards=[], matching_pins=[], query=query, total_pin_count=0, total_board_count=0)

    # Initialize variables to prevent NameError if exception occurs
    matching_boards = []
    matching_pins = []
    total_count = 0
    total_board_count = 0
    
    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True, buffered=True)
        
        search_term = f"%{query}%"
        
        # Optimized: Get total board count first (for pagination)
        board_count_sql = """
            SELECT COUNT(*) as total
            FROM boards b
            WHERE b.name LIKE %s AND b.user_id = %s
        """
        cursor.execute(board_count_sql, (search_term, user['id']))
        total_board_count = cursor.fetchone()['total']
        
        # Optimized: Get boards with their first pin image, limit to first 10 for initial load
        board_sql = """
            SELECT b.*, 
                   (SELECT p.image_url FROM pins p 
                    WHERE p.board_id = b.id AND p.user_id = %s 
                    LIMIT 1) as random_pin_image_url
            FROM boards b
            WHERE b.name LIKE %s AND b.user_id = %s
            ORDER BY b.created_at DESC
            LIMIT 10
        """
        cursor.execute(board_sql, (user['id'], search_term, user['id']))
        matching_boards = cursor.fetchall()
        
        # Set default image for boards without pins
        for board in matching_boards:
            if not board['random_pin_image_url']:
                board['random_pin_image_url'] = 'path/to/default_image.jpg'

        # Optimized: Get total pin count first (for pagination)
        count_sql = """
            SELECT COUNT(*) as total
            FROM pins p 
            WHERE (p.title LIKE %s OR p.description LIKE %s) AND p.user_id = %s
        """
        cursor.execute(count_sql, (search_term, search_term, user['id']))
        total_count = cursor.fetchone()['total']
        
        # Optimized: Single query with all joins, limit to first 10 pins for initial load
        pin_sql = """
            SELECT p.*, b.name as board_name, s.name as section_name,
                   ci.cached_filename, ci.cache_status
            FROM pins p 
            LEFT JOIN boards b ON p.board_id = b.id 
            LEFT JOIN sections s ON p.section_id = s.id
            LEFT JOIN cached_images ci ON p.cached_image_id = ci.id AND ci.cache_status = 'cached'
            WHERE (p.title LIKE %s OR p.description LIKE %s) AND p.user_id = %s
            ORDER BY p.created_at DESC
            LIMIT 10
        """
        
        cursor.execute(pin_sql, (search_term, search_term, user['id']))
        matching_pins = cursor.fetchall()
        
        # REMOVED: Blocking dimension calculation - let the background processor handle it
        
    except mysql.connector.Error as e:
        print(f"Database error in search: {str(e)}")
        # Return empty results instead of JSON error for better UX
        return render_template('search.html', matching_boards=[], matching_pins=[], query=query, total_pin_count=0, total_board_count=0)
    except Exception as e:
        print(f"Error in search route: {str(e)}")
        # Log the full traceback for debugging
        print(traceback.format_exc())
        # Return empty results instead of crashing
        return render_template('search.html', matching_boards=[], matching_pins=[], query=query, total_pin_count=0, total_board_count=0)
    finally:
        if cursor:
            try:
                # Ensure all results are consumed before closing
                try:
                    cursor.fetchall()
                except Exception:
                    pass
                cursor.close()
            except Exception as cursor_close_error:
                print(f"search: error closing cursor: {cursor_close_error}")
        if db:
            try:
                db.close()
            except Exception as db_close_error:
                print(f"search: error closing db connection: {db_close_error}")

    return render_template('search.html', matching_boards=matching_boards, matching_pins=matching_pins, query=query, total_pin_count=total_count, total_board_count=total_board_count)

@app.route('/api/search/pins', methods=['GET'])
@login_required
def search_pins_api():
    """API endpoint to load more search results with pagination"""
    user = get_current_user()
    query = request.args.get('q', '').strip()
    offset = int(request.args.get('offset', 10))
    limit = int(request.args.get('limit', 10))
    
    if not query:
        return jsonify({"success": False, "error": "Query parameter required"}), 400
    
    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True, buffered=True)
        
        search_term = f"%{query}%"
        
        # Optimized: Single query with all joins, with pagination
        pin_sql = """
            SELECT p.*, b.name as board_name, s.name as section_name,
                   ci.cached_filename, ci.cache_status
            FROM pins p 
            LEFT JOIN boards b ON p.board_id = b.id 
            LEFT JOIN sections s ON p.section_id = s.id
            LEFT JOIN cached_images ci ON p.cached_image_id = ci.id AND ci.cache_status = 'cached'
            WHERE (p.title LIKE %s OR p.description LIKE %s) AND p.user_id = %s
            ORDER BY p.created_at DESC
            LIMIT %s OFFSET %s
        """
        
        cursor.execute(pin_sql, (search_term, search_term, user['id'], limit, offset))
        matching_pins = cursor.fetchall()
        
        return jsonify({
            "success": True,
            "pins": matching_pins,
            "has_more": len(matching_pins) == limit  # If we got a full page, there might be more
        })
        
    except mysql.connector.Error as e:
        print(f"Database error in search_pins_api: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        print(f"Error in search_pins_api: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cursor:
            try:
                # Ensure all results are consumed before closing
                try:
                    cursor.fetchall()
                except Exception:
                    pass
                cursor.close()
            except Exception as cursor_close_error:
                print(f"search_pins_api: error closing cursor: {cursor_close_error}")
        if db:
            try:
                db.close()
            except Exception as db_close_error:
                print(f"search_pins_api: error closing db connection: {db_close_error}")

@app.route('/api/search/boards', methods=['GET'])
@login_required
def search_boards_api():
    """API endpoint to load more search results for boards with pagination"""
    user = get_current_user()
    query = request.args.get('q', '').strip()
    offset = int(request.args.get('offset', 10))
    limit = int(request.args.get('limit', 10))
    
    if not query:
        return jsonify({"success": False, "error": "Query parameter required"}), 400
    
    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True, buffered=True)
        
        search_term = f"%{query}%"
        
        # Optimized: Get boards with their first pin image, with pagination
        board_sql = """
            SELECT b.*, 
                   (SELECT p.image_url FROM pins p 
                    WHERE p.board_id = b.id AND p.user_id = %s 
                    LIMIT 1) as random_pin_image_url
            FROM boards b
            WHERE b.name LIKE %s AND b.user_id = %s
            ORDER BY b.created_at DESC
            LIMIT %s OFFSET %s
        """
        
        cursor.execute(board_sql, (user['id'], search_term, user['id'], limit, offset))
        matching_boards = cursor.fetchall()
        
        # Set default image for boards without pins
        for board in matching_boards:
            if not board['random_pin_image_url']:
                board['random_pin_image_url'] = 'path/to/default_image.jpg'
        
        return jsonify({
            "success": True,
            "boards": matching_boards,
            "has_more": len(matching_boards) == limit  # If we got a full page, there might be more
        })
        
    except mysql.connector.Error as e:
        print(f"Database error in search_boards_api: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        print(f"Error in search_boards_api: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cursor:
            try:
                # Ensure all results are consumed before closing
                try:
                    cursor.fetchall()
                except Exception:
                    pass
                cursor.close()
            except Exception as cursor_close_error:
                print(f"search_boards_api: error closing cursor: {cursor_close_error}")
        if db:
            try:
                db.close()
            except Exception as db_close_error:
                print(f"search_boards_api: error closing db connection: {db_close_error}")

@app.route('/add-content')
@login_required
def add_content():
    user = get_current_user()
    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM boards WHERE user_id = %s", (user['id'],))
        boards = cursor.fetchall()
        return render_template('add_content.html', boards=boards)
    except mysql.connector.Error as e:
        print(f"Database error in add_content: {e}")
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        print(f"Unexpected error in add_content: {e}")
        return jsonify({"error": "An unexpected error occurred"}), 500
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if db:
            try:
                db.close()
            except Exception:
                pass

@app.route('/scrape-website', methods=['POST'])
@login_required
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
@login_required
def get_sections(board_id):
    user = get_current_user()
    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True, buffered=True)
        # Verify board belongs to user, then get sections
        cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s", (board_id, user['id']))
        if not cursor.fetchone():
            return jsonify({"error": "Board not found"}), 404
        cursor.execute("SELECT * FROM sections WHERE board_id = %s", (board_id,))
        sections = cursor.fetchall()
    except mysql.connector.Error as e:
        print(f"Database error in get_board_sections: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            try:
                # Ensure all results are consumed before closing
                try:
                    cursor.fetchall()
                except Exception:
                    pass
                cursor.close()
            except Exception as cursor_close_error:
                print(f"get_board_sections: error closing cursor: {cursor_close_error}")
        if db:
            try:
                db.close()
            except Exception as db_close_error:
                print(f"get_board_sections: error closing db connection: {db_close_error}")
    
    return jsonify(sections)

def save_pasted_image(data_url):
    """Save a pasted image (data URL) to the cached_images directory"""
    try:
        # Parse the data URL to extract format and data
        if not data_url.startswith('data:image/'):
            return None
            
        # Extract the image format and base64 data
        header, encoded = data_url.split(',', 1)
        format_info = header.split(';')[0].split('/')[1]  # e.g., 'png', 'jpeg'
        
        # Decode the base64 data
        image_data = base64.b64decode(encoded)
        
        # Generate a hash-based filename similar to the existing system
        hash_obj = hashlib.md5(image_data)
        filename_hash = hash_obj.hexdigest()[:16]  # Use first 16 chars like existing files
        
        # Use the original format for the extension
        if format_info == 'jpeg':
            format_info = 'jpg'
        filename = f"{filename_hash}_pasted.{format_info}"
        
        # Save to the cached_images directory
        cache_dir = 'static/cached_images'
        os.makedirs(cache_dir, exist_ok=True)
        filepath = os.path.join(cache_dir, filename)
        
        # Write the image data to file
        with open(filepath, 'wb') as f:
            f.write(image_data)
        
        # Create a cached image record in the database
        db = None
        cursor = None
        try:
            db = get_db_connection()
            cursor = db.cursor()
            
            # Check if cached_images table exists
            cursor.execute("SHOW TABLES LIKE 'cached_images'")
            result = cursor.fetchone()
            # Consume any remaining results
            cursor.fetchall()
            if result:
                # Insert into cached_images table
                cursor.execute("""
                    INSERT INTO cached_images (
                        original_url, cached_filename, file_size, 
                        quality_level, cache_status, created_at, last_accessed
                    ) VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (
                    f"pasted_image_{filename_hash}",  # Use hash as original_url for pasted images
                    filename,
                    len(image_data),
                    'low',
                    'cached'
                ))
                
                cached_image_id = cursor.lastrowid
                db.commit()
            else:
                cached_image_id = None
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if db:
                try:
                    db.close()
                except Exception:
                    pass
        
        # Return the relative path to the cached image
        return f"/cached/{filename}", cached_image_id
        
    except Exception as e:
        return None, None

@app.route('/add-pin', methods=['POST'])
@login_required
def add_pin():
    user = get_current_user()
    try:
        data = request.get_json()

        board_id = sanitize_integer(data.get('board_id'))
        section_id = sanitize_integer(data.get('section_id'))
        title = sanitize_string(data.get('title', ''), max_length=255)
        description = sanitize_string(data.get('description', ''))
        notes = sanitize_string(data.get('notes', ''))
        raw_image_url = data.get('image_url', '')
        source_url = sanitize_url(data.get('source_url', ''))
        cached_image_id = None

        if raw_image_url.startswith('data:image/'):
            image_url, cached_image_id = save_pasted_image(raw_image_url)
            if image_url is None:
                image_url = '/static/images/default_pin.png'
        else:
            image_url = sanitize_url(raw_image_url)

        if not board_id or not title:
            return jsonify({"error": "Board ID and title are required"}), 400

        if not image_url:
            image_url = '/static/images/default_pin.png'

        with tx() as (db, cursor):
            cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s",
                           (board_id, user['id']))
            if not cursor.fetchone():
                return jsonify({"error": "Board not found"}), 404

            if section_id:
                cursor.execute(
                    "SELECT id FROM sections WHERE id = %s AND board_id = %s",
                    (section_id, board_id),
                )
                if not cursor.fetchone():
                    return jsonify({"error": "Section not found or belongs to a different board"}), 400

            cursor.execute("SHOW COLUMNS FROM pins LIKE 'cached_image_id'")
            result = cursor.fetchone()
            has_cached_columns = result is not None
            cursor.fetchall()

            if has_cached_columns and cached_image_id:
                cursor.execute("""
                    INSERT INTO pins (board_id, section_id, title, description, notes, image_url, link, cached_image_id, uses_cached_image, user_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (board_id, section_id, title, description, notes, image_url, source_url, cached_image_id, True, user['id']))
            else:
                cursor.execute("""
                    INSERT INTO pins (board_id, section_id, title, description, notes, image_url, link, user_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (board_id, section_id, title, description, notes, image_url, source_url, user['id']))

            pin_id = cursor.lastrowid

            record_audit(cursor, action='pin.create', entity_type='pin',
                         entity_id=pin_id, user_id=user['id'],
                         actor_email=user.get('email'), before=None,
                         after={'id': pin_id, 'board_id': board_id,
                                'section_id': section_id, 'image_url': image_url,
                                'title': title},
                         metadata={'route': request.path},
                         ip_address=request.remote_addr)

        # Post-commit side effects (best-effort, do not roll back the pin if these fail)
        try:
            update_pin_dimensions(pin_id, image_url)
        except Exception as e:
            print(f"Error calculating dimensions for new pin {pin_id}: {e}")

        if image_url.startswith('http'):
            try:
                from scripts.image_cache_service import ImageCacheService
                cache_service = ImageCacheService()
                cache_service.queue_image_for_caching(pin_id, image_url, 'low')
            except Exception as e:
                print(f"Failed to queue image for caching: {e}")

        return jsonify({'success': True, 'pin_id': pin_id})
    except Exception as e:
        print(f"Error adding pin: {str(e)}")
        return jsonify({"error": "Failed to add pin"}), 500

@app.route('/update-pin/<int:pin_id>', methods=['POST'])
@login_required
def update_pin(pin_id):
    user = get_current_user()
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
        
    # Get only the fields that are provided
    title = sanitize_string(data.get('title', ''), max_length=255) if 'title' in data else None
    description = sanitize_string(data.get('description', '')) if 'description' in data else None
    notes = sanitize_string(data.get('notes', '')) if 'notes' in data else None
    link = sanitize_string(data.get('link', ''), max_length=2048) if 'link' in data else None
    
    
    try:
        with tx(dictionary=True) as (db, cursor):
            cursor.execute(
                "SELECT title, description, notes, link FROM pins WHERE id = %s AND user_id = %s",
                (pin_id, user['id']),
            )
            current = cursor.fetchone()
            if not current:
                return jsonify({"error": "Pin not found"}), 404

            update_fields = []
            update_values = []
            before_changes = {}
            after_changes = {}

            if title is not None:
                update_fields.append("title = %s"); update_values.append(title)
                before_changes['title'] = current['title']; after_changes['title'] = title
            if description is not None:
                update_fields.append("description = %s"); update_values.append(description)
                before_changes['description'] = current['description']; after_changes['description'] = description
            if notes is not None:
                update_fields.append("notes = %s"); update_values.append(notes)
                before_changes['notes'] = current['notes']; after_changes['notes'] = notes
            if link is not None:
                update_fields.append("link = %s"); update_values.append(link)
                before_changes['link'] = current['link']; after_changes['link'] = link

            if not update_fields:
                return jsonify({"error": "No fields to update"}), 400

            update_values.append(pin_id)
            update_values.append(user['id'])

            cursor.execute(
                f"UPDATE pins SET {', '.join(update_fields)} WHERE id = %s AND user_id = %s",
                tuple(update_values),
            )

            if link is not None:
                cursor.execute("DELETE FROM url_health WHERE pin_id = %s", (pin_id,))
                if link:
                    cursor.execute("""
                        INSERT INTO url_health (pin_id, url, status, last_checked)
                        VALUES (%s, %s, 'unknown', NULL)
                    """, (pin_id, link))

            record_audit(cursor, action='pin.update', entity_type='pin',
                         entity_id=pin_id, user_id=user['id'],
                         actor_email=user.get('email'),
                         before=before_changes, after=after_changes,
                         metadata={'route': request.path},
                         ip_address=request.remote_addr)

        return jsonify({'success': True, 'pin_id': pin_id})
    except mysql.connector.Error as e:
        print(f"Database error updating pin: {str(e)}")
        return jsonify({"error": "Database error occurred"}), 500
    except Exception as e:
        print(f"Error updating pin: {str(e)}")
        return jsonify({"error": "Failed to update pin"}), 500

@app.route('/pin/<int:pin_id>')
@login_required
def view_pin(pin_id):
    user = get_current_user()
    db = None
    cursor = None
    try:
        print(f"view_pin: start pin_id={pin_id}, user_id={user['id']}")
        db = get_db_connection()
        cursor = db.cursor(dictionary=True, buffered=True)

        # Get pin details with board and section names (user-scoped)
        cursor.execute("""
            SELECT p.*, b.name as board_name, s.name as section_name,
                   uh.status as link_status, uh.archive_url
            FROM pins p
            LEFT JOIN boards b ON p.board_id = b.id
            LEFT JOIN sections s ON p.section_id = s.id
            LEFT JOIN url_health uh ON p.id = uh.pin_id
            WHERE p.id = %s AND p.user_id = %s
        """, (pin_id, user['id']))

        pin = cursor.fetchone()
        print(f"view_pin: fetched pin record? {'yes' if pin else 'no'}")

        if not pin:
            print(f"view_pin: pin {pin_id} not found for user {user['id']}")
            # Ensure cursor is fully consumed before closing
            try:
                cursor.fetchall()  # Consume any remaining results
            except Exception:
                pass
            return "Pin not found", 404

        # Get all boards for the board selector (user-scoped)
        cursor.execute("SELECT * FROM boards WHERE user_id = %s ORDER BY name", (user['id'],))
        boards = cursor.fetchall()
        print(f"view_pin: boards fetched count={len(boards)}")

        # Get all sections for the current board
        cursor.execute("SELECT * FROM sections WHERE board_id = %s ORDER BY name", (pin['board_id'],))
        sections = cursor.fetchall()
        print(f"view_pin: sections fetched count={len(sections)}")

        return render_template('pin.html', pin=pin, boards=boards, sections=sections)
    except mysql.connector.errors.InterfaceError as e:
        # Handle "Unread result found" errors specifically
        if "Unread result found" in str(e):
            print(f"Unread result found error in view_pin, attempting to recover: {str(e)}")
            # Try to consume any remaining results
            if cursor:
                try:
                    cursor.fetchall()
                except Exception:
                    pass
            # Return error but don't crash
            return "An error occurred while loading the pin. Please try again.", 500
        else:
            print(f"Database interface error in view_pin route: {str(e)}")
            traceback.print_exc()
            return "An error occurred", 500
    except Exception as e:
        print(f"Error in view_pin route: {str(e)}")
        traceback.print_exc()
        return "An error occurred", 500
    finally:
        if cursor:
            try:
                # Ensure all results are consumed before closing
                try:
                    cursor.fetchall()
                except Exception:
                    pass
                cursor.close()
            except Exception as cursor_close_error:
                print(f"view_pin: error closing cursor: {cursor_close_error}")
        if db:
            try:
                db.close()
            except Exception as db_close_error:
                print(f"view_pin: error closing db connection: {db_close_error}")

@app.route('/create-board', methods=['POST'])
@login_required
def create_board():
    user = get_current_user()
    try:
        data = request.get_json()
        if data is None:
            return jsonify({"error": "Invalid JSON data"}), 400
            
        board_name = sanitize_string(data.get('name', ''), max_length=100)
        
        if not board_name:
            return jsonify({"error": "Board name is required"}), 400
        
        try:
            slug = re.sub(r'[^a-z0-9]+', '-', board_name.lower()).strip('-')

            with tx() as (db, cursor):
                cursor.execute("SELECT id FROM boards WHERE name = %s AND user_id = %s",
                               (board_name, user['id']))
                if cursor.fetchone():
                    return jsonify({"error": "You already have a board with this name"}), 409

                cursor.execute("""
                    INSERT INTO boards (name, slug, user_id)
                    VALUES (%s, %s, %s)
                """, (board_name, slug, user['id']))
                board_id = cursor.lastrowid

                record_audit(cursor, action='board.create', entity_type='board',
                             entity_id=board_id, user_id=user['id'],
                             actor_email=user.get('email'), before=None,
                             after={'id': board_id, 'name': board_name, 'slug': slug},
                             metadata={'route': request.path},
                             ip_address=request.remote_addr)

            if redis_client:
                redis_client.delete(f"view:{user['id']}:/")
            return jsonify({
                'success': True,
                'board_id': board_id,
                'name': board_name,
                'slug': slug,
            })

        except mysql.connector.Error as db_error:
            print(f"Database error in create_board: {str(db_error)}")
            return jsonify({"error": "Database error occurred"}), 500

    except Exception as e:
        print(f"Error in create_board: {str(e)}")
        return jsonify({"error": "Server error occurred"}), 500

@app.route('/move-pin/<int:pin_id>', methods=['POST'])
@login_required
def move_pin(pin_id):
    user = get_current_user()
    data = request.get_json()
    board_id = sanitize_integer(data.get('board_id'), min_value=1)
    pin_id = sanitize_integer(pin_id, min_value=1)
    
    if not board_id:
        return jsonify({"error": "Valid board ID is required"}), 400
    
    if not pin_id:
        return jsonify({"error": "Valid pin ID is required"}), 400
    
    try:
        with tx(dictionary=True) as (db, cursor):
            cursor.execute("SELECT id, board_id, section_id FROM pins WHERE id = %s AND user_id = %s",
                           (pin_id, user['id']))
            pin_before = cursor.fetchone()
            if not pin_before:
                return jsonify({"error": "Pin not found"}), 404

            cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s",
                           (board_id, user['id']))
            if not cursor.fetchone():
                return jsonify({"error": "Target board not found"}), 404

            cursor.execute("""
                UPDATE pins
                SET board_id = %s, section_id = NULL
                WHERE id = %s AND user_id = %s
            """, (board_id, pin_id, user['id']))

            record_audit(cursor, action='pin.move', entity_type='pin',
                         entity_id=pin_id, user_id=user['id'],
                         actor_email=user.get('email'),
                         before={'board_id': pin_before['board_id'],
                                 'section_id': pin_before['section_id']},
                         after={'board_id': board_id, 'section_id': None},
                         metadata={'route': request.path},
                         ip_address=request.remote_addr)

        if redis_client:
            redis_client.delete(f"view:{user['id']}:/")
        return jsonify({'success': True})
    except mysql.connector.Error as e:
        return jsonify({"error": str(e)}), 500

@app.route('/create-section', methods=['POST'])
@login_required
def create_section():
    user = get_current_user()
    try:
        data = request.get_json()
        board_id = sanitize_integer(data.get('board_id'))
        name = sanitize_string(data.get('name', ''), max_length=255)

        if not board_id or not name:
            return jsonify({"error": "Board ID and section name are required"}), 400

        with tx() as (db, cursor):
            cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s",
                           (board_id, user['id']))
            if not cursor.fetchone():
                return jsonify({"error": "Board not found"}), 404

            cursor.execute("""
                INSERT INTO sections (board_id, name, user_id)
                VALUES (%s, %s, %s)
            """, (board_id, name, user['id']))
            section_id = cursor.lastrowid

            record_audit(cursor, action='section.create', entity_type='section',
                         entity_id=section_id, user_id=user['id'],
                         actor_email=user.get('email'), before=None,
                         after={'id': section_id, 'name': name, 'board_id': board_id},
                         metadata={'route': request.path},
                         ip_address=request.remote_addr)

        return jsonify({
            'success': True,
            'section': {
                'id': section_id,
                'name': name,
                'board_id': board_id,
            },
        })
    except Exception as e:
        print(f"Error creating section: {str(e)}")
        return jsonify({"error": "Failed to create section"}), 500

@app.route('/update-section/<int:section_id>', methods=['POST'])
@login_required
def update_section(section_id):
    user = get_current_user()
    try:
        data = request.get_json()
        name = sanitize_string(data.get('name', ''), max_length=255)

        if not name:
            return jsonify({"error": "Section name is required"}), 400

        with tx(dictionary=True) as (db, cursor):
            cursor.execute("""
                SELECT s.id, s.name FROM sections s
                JOIN boards b ON s.board_id = b.id
                WHERE s.id = %s AND b.user_id = %s
            """, (section_id, user['id']))
            row = cursor.fetchone()
            if not row:
                return jsonify({"error": "Section not found"}), 404
            old_name = row['name']

            cursor.execute("UPDATE sections SET name = %s WHERE id = %s", (name, section_id))

            record_audit(cursor, action='section.rename', entity_type='section',
                         entity_id=section_id, user_id=user['id'],
                         actor_email=user.get('email'),
                         before={'name': old_name}, after={'name': name},
                         metadata={'route': request.path},
                         ip_address=request.remote_addr)

        return jsonify({
            'success': True,
            'section': {'id': section_id, 'name': name},
        })
    except Exception as e:
        print(f"Error updating section: {str(e)}")
        return jsonify({"error": "Failed to update section"}), 500

@app.route('/delete-section/<int:section_id>', methods=['POST'])
@login_required
def delete_section(section_id):
    user = get_current_user()
    try:
        with tx(dictionary=True) as (db, cursor):
            cursor.execute("""
                SELECT s.id, s.board_id FROM sections s
                JOIN boards b ON s.board_id = b.id
                WHERE s.id = %s AND b.user_id = %s
            """, (section_id, user['id']))
            result = cursor.fetchone()
            if not result:
                return jsonify({"error": "Section not found"}), 404
            board_id = result['board_id']

            # Snapshot section + its pins before delete (pins survive with section_id=NULL
            # via ON DELETE SET NULL, but the snapshot lets us re-link them on undo).
            before = snapshot_section(cursor, section_id)

            cursor.execute("DELETE FROM sections WHERE id = %s", (section_id,))

            record_audit(cursor, action='section.delete', entity_type='section',
                         entity_id=section_id, user_id=user['id'],
                         actor_email=user.get('email'),
                         before=before, after=None,
                         metadata={'route': request.path, 'board_id': board_id},
                         ip_address=request.remote_addr)

        return jsonify({'success': True, 'board_id': board_id})
    except Exception as e:
        print(f"Error deleting section: {str(e)}")
        return jsonify({"error": "Failed to delete section"}), 500

@app.route('/move-pin-to-section/<int:pin_id>', methods=['POST'])
@login_required
def move_pin_to_section(pin_id):
    user = get_current_user()
    try:
        data = request.get_json()
        section_id = sanitize_integer(data.get('section_id'))
        if section_id is None:
            section_id = None

        with tx(dictionary=True) as (db, cursor):
            cursor.execute("SELECT board_id, section_id FROM pins WHERE id = %s AND user_id = %s",
                           (pin_id, user['id']))
            result = cursor.fetchone()
            if not result:
                return jsonify({"error": "Pin not found"}), 404
            board_id = result['board_id']
            old_section_id = result['section_id']

            if section_id:
                cursor.execute("SELECT id FROM sections WHERE id = %s AND board_id = %s",
                               (section_id, board_id))
                if not cursor.fetchone():
                    return jsonify({"error": "Section not found or belongs to different board"}), 400

            cursor.execute("""
                UPDATE pins SET section_id = %s WHERE id = %s AND user_id = %s
            """, (section_id, pin_id, user['id']))

            record_audit(cursor, action='pin.move_to_section', entity_type='pin',
                         entity_id=pin_id, user_id=user['id'],
                         actor_email=user.get('email'),
                         before={'section_id': old_section_id},
                         after={'section_id': section_id},
                         metadata={'route': request.path, 'board_id': board_id},
                         ip_address=request.remote_addr)

        return jsonify({
            'success': True,
            'pin_id': pin_id,
            'section_id': section_id,
        })
    except Exception as e:
        print(f"Error moving pin to section: {str(e)}")
        return jsonify({"error": "Failed to move pin"}), 500

@app.route('/rename-board/<int:board_id>', methods=['POST'])
@login_required
def rename_board(board_id):
    user = get_current_user()
    try:
        data = request.get_json()
        new_name = data.get('name', '').strip()

        if not new_name:
            return jsonify({"error": "Board name is required"}), 400

        with tx(dictionary=True) as (db, cursor):
            cursor.execute("SELECT name FROM boards WHERE id = %s AND user_id = %s",
                           (board_id, user['id']))
            row = cursor.fetchone()
            if not row:
                return jsonify({"error": "Board not found"}), 404
            old_name = row['name']

            cursor.execute("UPDATE boards SET name = %s WHERE id = %s AND user_id = %s",
                           (new_name, board_id, user['id']))

            record_audit(cursor, action='board.rename', entity_type='board',
                         entity_id=board_id, user_id=user['id'],
                         actor_email=user.get('email'),
                         before={'name': old_name}, after={'name': new_name},
                         metadata={'route': request.path},
                         ip_address=request.remote_addr)

        if redis_client:
            redis_client.delete(f"view:{user['id']}:/")
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error renaming board: {str(e)}")
        return jsonify({"error": "Failed to rename board"}), 500

@app.route('/move-board/<int:board_id>', methods=['POST'])
@login_required
def move_board(board_id):
    user = get_current_user()
    try:
        data = request.get_json() or {}
        target_board_id = data.get('target_board_id')

        if not target_board_id:
            return jsonify({"error": "Target board ID is required"}), 400

        with tx(dictionary=True) as (db, cursor):
            cursor.execute("SELECT id, name FROM boards WHERE id = %s AND user_id = %s",
                           (board_id, user['id']))
            source_board = cursor.fetchone()
            if not source_board:
                return jsonify({"error": "Source board not found"}), 404
            source_board_name = source_board['name']

            cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s",
                           (target_board_id, user['id']))
            if not cursor.fetchone():
                return jsonify({"error": "Target board not found"}), 404

            before = snapshot_board(cursor, board_id)

            # Create a new section in the target board with the source board's name
            cursor.execute("""
                INSERT INTO sections (board_id, name, user_id)
                VALUES (%s, %s, %s)
            """, (target_board_id, source_board_name, user['id']))
            new_section_id = cursor.lastrowid

            # Move all pins from source to target, assigning them to the new section
            cursor.execute("""
                UPDATE pins
                SET board_id = %s, section_id = %s
                WHERE board_id = %s AND user_id = %s
            """, (target_board_id, new_section_id, board_id, user['id']))

            # Move any pre-existing sections from source to target (excluding the
            # one we just inserted), user-scoped to avoid cross-tenant moves.
            cursor.execute("""
                UPDATE sections
                SET board_id = %s
                WHERE board_id = %s AND user_id = %s AND id != %s
            """, (target_board_id, board_id, user['id'], new_section_id))

            cursor.execute("DELETE FROM boards WHERE id = %s AND user_id = %s",
                           (board_id, user['id']))

            record_audit(cursor, action='board.move', entity_type='board',
                         entity_id=board_id, user_id=user['id'],
                         actor_email=user.get('email'),
                         before=before,
                         after={'target_board_id': target_board_id,
                                'new_section_id': new_section_id},
                         metadata={'route': request.path},
                         ip_address=request.remote_addr)

        if redis_client:
            redis_client.delete(f"view:{user['id']}:/")
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error moving board: {str(e)}")
        return jsonify({"error": "Failed to move board"}), 500

@app.route('/delete-board/<int:board_id>', methods=['POST'])
@login_required
def delete_board(board_id):
    user = get_current_user()
    try:
        with tx() as (db, cursor):
            cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s",
                           (board_id, user['id']))
            if not cursor.fetchone():
                return jsonify({"error": "Board not found"}), 404

            # Snapshot before mutation so the audit row contains everything needed
            # to undo the delete.
            before = snapshot_board(cursor, board_id)

            cursor.execute("DELETE FROM pins WHERE board_id = %s AND user_id = %s",
                           (board_id, user['id']))
            cursor.execute("DELETE FROM sections WHERE board_id = %s AND user_id = %s",
                           (board_id, user['id']))
            cursor.execute("DELETE FROM boards WHERE id = %s AND user_id = %s",
                           (board_id, user['id']))

            record_audit(cursor, action='board.delete', entity_type='board',
                         entity_id=board_id, user_id=user['id'],
                         actor_email=user.get('email'), before=before, after=None,
                         metadata={'route': request.path},
                         ip_address=request.remote_addr)

        if redis_client:
            redis_client.delete(f"view:{user['id']}:/")
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error deleting board: {str(e)}")
        return jsonify({"error": "Failed to delete board"}), 500

@app.route('/set-board-image/<int:board_id>', methods=['POST'])
@login_required
def set_board_image(board_id):
    user = get_current_user()
    try:
        data = request.get_json()
        image_url = data.get('image_url', '').strip()

        with tx(dictionary=True) as (db, cursor):
            cursor.execute("SELECT default_image_url FROM boards WHERE id = %s AND user_id = %s",
                           (board_id, user['id']))
            row = cursor.fetchone()
            if not row:
                return jsonify({"error": "Board not found"}), 404
            old_image_url = row['default_image_url']

            if image_url:
                cursor.execute(
                    "UPDATE boards SET default_image_url = %s WHERE id = %s AND user_id = %s",
                    (image_url, board_id, user['id']),
                )
            else:
                cursor.execute(
                    "UPDATE boards SET default_image_url = NULL WHERE id = %s AND user_id = %s",
                    (board_id, user['id']),
                )

            record_audit(cursor, action='board.update_image', entity_type='board',
                         entity_id=board_id, user_id=user['id'],
                         actor_email=user.get('email'),
                         before={'default_image_url': old_image_url},
                         after={'default_image_url': image_url or None},
                         metadata={'route': request.path},
                         ip_address=request.remote_addr)

        if redis_client:
            redis_client.delete(f"view:{user['id']}:/")

        return jsonify({"success": True, "message": "Board image updated successfully"})
    except Exception as e:
        print(f"Error setting board image: {str(e)}")
        return jsonify({"error": "Failed to set board image"}), 500

@app.route('/set-section-image/<int:section_id>', methods=['POST'])
@login_required
def set_section_image(section_id):
    user = get_current_user()
    try:
        data = request.get_json()
        image_url = data.get('image_url', '').strip()

        with tx(dictionary=True) as (db, cursor):
            cursor.execute("""
                SELECT s.id, s.board_id, s.default_image_url
                FROM sections s
                JOIN boards b ON s.board_id = b.id
                WHERE s.id = %s AND b.user_id = %s
            """, (section_id, user['id']))
            section = cursor.fetchone()
            if not section:
                return jsonify({"error": "Section not found"}), 404
            old_image_url = section['default_image_url']

            if image_url:
                cursor.execute("""
                    UPDATE sections SET default_image_url = %s
                    WHERE id = %s AND user_id = %s
                """, (image_url, section_id, user['id']))
            else:
                cursor.execute("""
                    UPDATE sections SET default_image_url = NULL
                    WHERE id = %s AND user_id = %s
                """, (section_id, user['id']))

            record_audit(cursor, action='section.update_image', entity_type='section',
                         entity_id=section_id, user_id=user['id'],
                         actor_email=user.get('email'),
                         before={'default_image_url': old_image_url},
                         after={'default_image_url': image_url or None},
                         metadata={'route': request.path, 'board_id': section['board_id']},
                         ip_address=request.remote_addr)

        if redis_client:
            redis_client.delete(f"view:{user['id']}:/")

        return jsonify({
            "success": True,
            "message": "Section cover updated successfully",
            "board_id": section["board_id"],
        })
    except Exception as e:
        print(f"Error setting section image: {str(e)}")
        return jsonify({"error": "Failed to set section cover"}), 500

@app.route('/link-health')
@login_required
def link_health():
    """Dashboard to monitor URL health checking activity"""
    user = get_current_user()
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # Get overall statistics
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT p.id) as total_pins_with_links,
                COUNT(DISTINCT CASE WHEN uh.status = 'live' THEN p.id END) as live_count,
                COUNT(DISTINCT CASE WHEN uh.status = 'broken' THEN p.id END) as broken_count,
                COUNT(DISTINCT CASE WHEN uh.status = 'archived' THEN p.id END) as archived_count,
                COUNT(DISTINCT CASE WHEN uh.status = 'unknown' OR uh.status IS NULL THEN p.id END) as unknown_count,
                COUNT(DISTINCT CASE WHEN uh.last_checked IS NOT NULL THEN p.id END) as checked_count
            FROM pins p
            LEFT JOIN url_health uh ON p.id = uh.pin_id
            WHERE p.user_id = %s AND p.link IS NOT NULL AND p.link != ''
        """, (user['id'],))
        stats = cursor.fetchone()
        
        cursor.close()
        db.close()
        
        # Don't load all_links on initial page load for performance
        # It will be loaded via AJAX when the "All Links" tab is clicked
        return render_template('link_health.html', stats=stats)
        
    except Exception as e:
        print(f"Error in link_health: {str(e)}")
        return "Error loading link health dashboard", 500

@app.route('/api/link-health/recent')
@login_required
def link_health_recent():
    """API endpoint for recent link health checks"""
    user = get_current_user()
    try:
        limit = request.args.get('limit', 10, type=int)
        # Cap the limit to reasonable values
        limit = min(max(limit, 1), 500)
        
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # Get recent checks
        cursor.execute("""
            SELECT 
                p.id as pin_id,
                p.title,
                p.link,
                b.name as board_name,
                uh.status,
                uh.last_checked,
                uh.archive_url
            FROM url_health uh
            JOIN pins p ON uh.pin_id = p.id
            JOIN boards b ON p.board_id = b.id
            WHERE p.user_id = %s
            ORDER BY uh.last_checked DESC
            LIMIT %s
        """, (user['id'], limit))
        recent_checks = cursor.fetchall()
        
        cursor.close()
        db.close()
        
        # Convert datetime objects to strings
        for check in recent_checks:
            if check['last_checked']:
                check['last_checked'] = check['last_checked'].strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify({'success': True, 'recent_checks': recent_checks})
        
    except Exception as e:
        print(f"Error in link_health_recent: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/random')
@login_required
def random_pin():
    user = get_current_user()
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # First get the total count of pins (user-scoped)
        cursor.execute("SELECT COUNT(*) as count FROM pins WHERE user_id = %s", (user['id'],))
        total_pins = cursor.fetchone()['count']
        
        if total_pins == 0:
            return "No pins found", 404
            
        # Get a random offset
        random_offset = random.randint(0, total_pins - 1)
        
        # Get the random pin with a single efficient query (user-scoped)
        cursor.execute("""
            SELECT p.*, b.name as board_name, s.name as section_name
            FROM pins p
            LEFT JOIN boards b ON p.board_id = b.id
            LEFT JOIN sections s ON p.section_id = s.id
            WHERE p.user_id = %s
            LIMIT 1 OFFSET %s
        """, (user['id'], random_offset))
        
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

@app.route('/cached/<path:filename>')
def serve_cached_image(filename):
    """Serve cached images from the cache directory"""
    try:
        cache_dir = os.path.join('static', 'cached_images')
        return send_from_directory(cache_dir, filename)
    except FileNotFoundError:
        # If cached file doesn't exist, return 404
        return "Cached image not found", 404

# Global singleton for image cache service to prevent thread accumulation
_image_cache_service = None
_image_cache_lock = threading.Lock()
_image_caching_in_progress = False

@app.route('/cache-images', methods=['POST'])
@login_required
def cache_images():
    """Trigger image caching for external images"""
    global _image_cache_service, _image_caching_in_progress
    
    user = get_current_user()
    try:
        # Check if caching is already in progress
        with _image_cache_lock:
            if _image_caching_in_progress:
                return jsonify({
                    'success': True,
                    'message': 'Image caching already in progress'
                })
            _image_caching_in_progress = True
        
        data = request.get_json()
        limit = data.get('limit', 10) if data else 10
        board_id = data.get('board_id') if data else None
        
        # Import and use the image cache service (singleton)
        from scripts.image_cache_service import ImageCacheService
        
        with _image_cache_lock:
            if _image_cache_service is None:
                _image_cache_service = ImageCacheService()
            cache_service = _image_cache_service
        
        # Queue images for caching in background
        def cache_in_background():
            global _image_caching_in_progress
            try:
                cache_service.cache_all_external_images(limit=limit, board_id=board_id)
                cache_service.stop_workers()
            finally:
                with _image_cache_lock:
                    _image_caching_in_progress = False
        
        thread = threading.Thread(target=cache_in_background, name='ImageCacheBackground')
        thread.daemon = True
        thread.start()
        
        board_message = f" for board {board_id}" if board_id else ""
        
        return jsonify({
            'success': True,
            'message': f'Started caching images and processing dimensions{board_message} in background'
        })
    except Exception as e:
        with _image_cache_lock:
            _image_caching_in_progress = False
        print(f"Error starting image caching: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/board/<int:board_id>/pins')
@login_required
def get_board_pins(board_id):
    """
    Get pins for a specific board with pagination and optional section filtering
    Returns JSON
    """
    user = get_current_user()
    offset = request.args.get('offset', 0, type=int)
    limit = request.args.get('limit', 40, type=int)
    section_id = request.args.get('section_id')
    
    # Cap limit to prevent massive queries
    limit = min(limit, 200)
    
    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True, buffered=True)
        
        # Verify board belongs to user
        cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s", (board_id, user['id']))
        if not cursor.fetchone():
            return jsonify({"error": "Board not found"}), 404
        
        # Build query
        query = """
            SELECT p.*, s.name as section_name, b.name as board_name,
                   ci.cached_filename, ci.cache_status,
                   ci.width as cached_width, ci.height as cached_height
            FROM pins p
            LEFT JOIN sections s ON p.section_id = s.id
            LEFT JOIN boards b ON p.board_id = b.id
            LEFT JOIN cached_images ci ON p.cached_image_id = ci.id AND ci.cache_status = 'cached'
            WHERE p.board_id = %s AND p.user_id = %s
        """
        params = [board_id, user['id']]
        
        # Add section filtering
        if section_id:
            if section_id == 'all':
                pass # No filter
            elif section_id == 'undefined':
                query += " AND p.section_id IS NULL"
            else:
                try:
                    s_id = int(section_id)
                    query += " AND p.section_id = %s"
                    params.append(s_id)
                except ValueError:
                    pass # Invalid section ID, ignore
                    
        # Add ordering and pagination
        query += " ORDER BY p.created_at DESC, p.id ASC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        try:
            cursor.execute(query, tuple(params))
        except Exception as query_err:
            # cached_images table may not exist on older installs — retry without that join
            print(f"Board pins query error, retrying without cached_images join: {query_err}")
            fallback_query = """
                SELECT p.*, s.name as section_name, b.name as board_name,
                       NULL as cached_filename, NULL as cache_status,
                       NULL as cached_width, NULL as cached_height
                FROM pins p
                LEFT JOIN sections s ON p.section_id = s.id
                LEFT JOIN boards b ON p.board_id = b.id
                WHERE p.board_id = %s AND p.user_id = %s
            """
            fallback_params = [board_id, user['id']]
            if section_id:
                if section_id == 'all':
                    pass
                elif section_id == 'undefined':
                    fallback_query += " AND p.section_id IS NULL"
                else:
                    try:
                        s_id = int(section_id)
                        fallback_query += " AND p.section_id = %s"
                        fallback_params.append(s_id)
                    except ValueError:
                        pass
            fallback_query += " ORDER BY p.created_at DESC, p.id ASC LIMIT %s OFFSET %s"
            fallback_params.extend([limit, offset])
            cursor.execute(fallback_query, tuple(fallback_params))

        pins = cursor.fetchall()

        return jsonify({
            'success': True,
            'pins': pins,
            'has_more': len(pins) == limit
        })

    except Exception as e:
        print(f"Error fetching board pins: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if db:
            try:
                db.close()
            except Exception:
                pass

@app.route('/api/boards')
@login_required
def api_boards():
    """Get all boards for API (user-scoped)"""
    user = get_current_user()
    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM boards WHERE user_id = %s ORDER BY name", (user['id'],))
        boards = cursor.fetchall()
        return jsonify(boards)
    except Exception as e:
        print(f"Error getting boards: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if db:
            try:
                db.close()
            except Exception:
                pass

@app.route('/api/board-status/<int:board_id>')
@login_required
def board_status(board_id):
    user = get_current_user()
    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # Verify board belongs to user
        cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s", (board_id, user['id']))
        if not cursor.fetchone():
            return jsonify({"error": "Board not found"}), 404
        
        # Get board stats including URL health (user-scoped)
        cursor.execute("""
            SELECT 
                COUNT(*) as total_pins,
                COUNT(CASE WHEN p.uses_cached_image = 1 THEN 1 END) as cached_count,
                COUNT(CASE WHEN p.colors_extracted = 1 THEN 1 END) as extracted_count,
                COUNT(CASE WHEN p.link IS NOT NULL THEN 1 END) as pins_with_links,
                COUNT(CASE WHEN uh.status IS NOT NULL THEN 1 END) as health_checked_count,
                COUNT(CASE WHEN uh.status = 'live' THEN 1 END) as live_links,
                COUNT(CASE WHEN uh.status = 'broken' THEN 1 END) as broken_links,
                COUNT(CASE WHEN uh.status = 'archived' THEN 1 END) as archived_links
            FROM pins p
            LEFT JOIN url_health uh ON p.id = uh.pin_id
            WHERE p.board_id = %s AND p.user_id = %s
        """, (board_id, user['id']))
        
        stats = cursor.fetchone()
        
        # Get detailed cached pin information for dynamic updates (user-scoped)
        cursor.execute("""
            SELECT p.id, ci.cached_filename
            FROM pins p
            LEFT JOIN cached_images ci ON p.cached_image_id = ci.id AND ci.cache_status = 'cached'
            WHERE p.board_id = %s AND p.user_id = %s AND p.uses_cached_image = 1 AND ci.cached_filename IS NOT NULL
        """, (board_id, user['id']))
        
        cached_pins = cursor.fetchall()
        
        # Get detailed color extraction information (user-scoped)
        cursor.execute("""
            SELECT id, dominant_color_1, dominant_color_2
            FROM pins
            WHERE board_id = %s AND user_id = %s AND colors_extracted = 1
        """, (board_id, user['id']))
        
        extracted_pins = cursor.fetchall()
        
        return jsonify({
            "success": True,
            "total_pins": stats['total_pins'],
            "cached_count": stats['cached_count'],
            "extracted_count": stats['extracted_count'],
            "pins_with_links": stats['pins_with_links'],
            "health_checked_count": stats['health_checked_count'],
            "live_links": stats['live_links'],
            "broken_links": stats['broken_links'],
            "archived_links": stats['archived_links'],
            "cached_pins": [{"id": pin["id"], "cached_filename": pin["cached_filename"]} for pin in cached_pins],
            "extracted_pins": [{"id": pin["id"], "color1": pin["dominant_color_1"], "color2": pin["dominant_color_2"]} for pin in extracted_pins]
        })
        
    except mysql.connector.Error as e:
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if db:
            try:
                db.close()
            except Exception:
                pass

@app.route('/api/check-url-health/<int:board_id>', methods=['POST'])
@login_required
def check_url_health_for_board(board_id):
    user = get_current_user()
    try:
        data = request.get_json() or {}
        limit = data.get('limit', 50)  # Default to checking 50 URLs at a time (increased from 10)
        
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # Verify board belongs to user
        cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s", (board_id, user['id']))
        if not cursor.fetchone():
            return jsonify({"error": "Board not found"}), 404
        
        # Get pins with URLs that haven't been checked recently (or at all) (user-scoped)
        cursor.execute("""
            SELECT p.id as pin_id, p.link as url
            FROM pins p
            LEFT JOIN url_health uh ON p.id = uh.pin_id
            WHERE p.board_id = %s AND p.user_id = %s
            AND p.link IS NOT NULL 
            AND (uh.last_checked IS NULL OR uh.last_checked < DATE_SUB(NOW(), INTERVAL 1 MONTH))
            LIMIT %s
        """, (board_id, user['id'], limit))
        
        urls_to_check = cursor.fetchall()
        
        if not urls_to_check:
            return jsonify({
                "success": True,
                "message": "No URLs need checking",
                "checked": 0
            })
        
        # Check URLs concurrently for better performance
        import requests
        import concurrent.futures
        from threading import Lock
        
        checked_count = 0
        db_lock = Lock()  # Lock for thread-safe database access
        
        # Set up headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; ScrapbookBot/1.0; +https://github.com/isaaclee0/scrapbook)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        def check_wayback_archive(url):
            """Check if Wayback Machine has an archive of the URL"""
            try:
                # Wayback Machine availability API
                wayback_api = f"https://archive.org/wayback/available?url={url}"
                response = requests.get(wayback_api, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('archived_snapshots', {}).get('closest', {}).get('available'):
                        return data['archived_snapshots']['closest']['url']
            except Exception as e:
                print(f"Error checking Wayback Machine for {url}: {e}")
            return None
        
        def check_single_url(url_data):
            nonlocal checked_count
            archive_url = None
            
            try:
                # Quick HEAD request to check if URL is accessible
                response = requests.head(url_data['url'], headers=headers, timeout=3, allow_redirects=True)
                status = 'live' if response.status_code < 400 else 'broken'
                
                # If broken, check Wayback Machine for archives
                if status == 'broken':
                    archive_url = check_wayback_archive(url_data['url'])
                    if archive_url:
                        status = 'archived'
                
                # Thread-safe database update
                with db_lock:
                    cursor.execute("""
                        INSERT INTO url_health (pin_id, url, last_checked, status, archive_url)
                        VALUES (%s, %s, NOW(), %s, %s)
                        ON DUPLICATE KEY UPDATE
                        last_checked = NOW(),
                        status = VALUES(status),
                        archive_url = VALUES(archive_url)
                    """, (url_data['pin_id'], url_data['url'], status, archive_url))
                    checked_count += 1
                    
            except Exception as e:
                # Mark as unknown if check fails, but still check for archive
                archive_url = check_wayback_archive(url_data['url'])
                status = 'archived' if archive_url else 'unknown'
                
                with db_lock:
                    cursor.execute("""
                        INSERT INTO url_health (pin_id, url, last_checked, status, archive_url)
                        VALUES (%s, %s, NOW(), %s, %s)
                        ON DUPLICATE KEY UPDATE
                        last_checked = NOW(),
                        status = VALUES(status),
                        archive_url = VALUES(archive_url)
                    """, (url_data['pin_id'], url_data['url'], status, archive_url))
                    checked_count += 1
        
        # Use ThreadPoolExecutor for concurrent checks (max 10 concurrent requests)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(check_single_url, urls_to_check)
        
        db.commit()
        cursor.close()
        db.close()
        
        return jsonify({
            "success": True,
            "message": f"Checked {checked_count} URLs",
            "checked": checked_count
        })
        
    except mysql.connector.Error as e:
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/check-pin-url/<int:pin_id>', methods=['POST'])
@login_required
def check_pin_url(pin_id):
    """Manually check URL health for a single pin"""
    user = get_current_user()
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # Verify pin belongs to user
        cursor.execute("SELECT id, link, board_id FROM pins WHERE id = %s AND user_id = %s", (pin_id, user['id']))
        pin = cursor.fetchone()
        
        if not pin:
            return jsonify({"success": False, "error": "Pin not found"}), 404
        
        if not pin['link']:
            return jsonify({"success": False, "error": "Pin has no URL to check"}), 400
        
        # Check the URL
        import requests
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; ScrapbookBot/1.0; +https://github.com/isaaclee0/scrapbook)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        def check_wayback_archive(url):
            """Check if Wayback Machine has an archive of the URL"""
            try:
                wayback_api = f"https://archive.org/wayback/available?url={url}"
                response = requests.get(wayback_api, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('archived_snapshots', {}).get('closest', {}).get('available'):
                        return data['archived_snapshots']['closest']['url']
            except Exception as e:
                print(f"Error checking Wayback Machine for {url}: {e}")
            return None
        
        status = 'unknown'
        archive_url = None
        
        try:
            # Quick HEAD request to check if URL is accessible
            response = requests.head(pin['link'], headers=headers, timeout=5, allow_redirects=True)
            status = 'live' if response.status_code < 400 else 'broken'
            
            # If broken, check Wayback Machine for archives
            if status == 'broken':
                archive_url = check_wayback_archive(pin['link'])
                if archive_url:
                    status = 'archived'
        except Exception as e:
            # Mark as unknown if check fails, but still check for archive
            archive_url = check_wayback_archive(pin['link'])
            status = 'archived' if archive_url else 'unknown'
        
        # Update database
        cursor.execute("""
            INSERT INTO url_health (pin_id, url, last_checked, status, archive_url)
            VALUES (%s, %s, NOW(), %s, %s)
            ON DUPLICATE KEY UPDATE
            last_checked = NOW(),
            status = VALUES(status),
            archive_url = VALUES(archive_url)
        """, (pin_id, pin['link'], status, archive_url))
        
        db.commit()
        cursor.close()
        db.close()
        
        return jsonify({
            "success": True,
            "status": status,
            "archive_url": archive_url
        })
        
    except mysql.connector.Error as e:
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        print(f"Error checking pin URL: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/debug-url-health/<int:board_id>')
@login_required
def debug_url_health(board_id):
    """Debug endpoint to check URL health status for a specific board"""
    user = get_current_user()
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # Verify board belongs to user
        cursor.execute("SELECT id FROM boards WHERE id = %s AND user_id = %s", (board_id, user['id']))
        if not cursor.fetchone():
            return jsonify({"error": "Board not found"}), 404
        
        # Get all pins with links on this board (user-scoped)
        cursor.execute("""
            SELECT p.id, p.title, p.link, uh.status, uh.last_checked
            FROM pins p
            LEFT JOIN url_health uh ON p.id = uh.pin_id
            WHERE p.board_id = %s AND p.user_id = %s AND p.link IS NOT NULL
            ORDER BY p.id
        """, (board_id, user['id']))
        
        pins_with_links = cursor.fetchall()
        
        # Get pins that would be checked by the health checker (user-scoped)
        cursor.execute("""
            SELECT p.id as pin_id, p.link as url, uh.last_checked, uh.status
            FROM pins p
            LEFT JOIN url_health uh ON p.id = uh.pin_id
            WHERE p.board_id = %s AND p.user_id = %s
            AND p.link IS NOT NULL 
            AND (uh.last_checked IS NULL OR uh.last_checked < DATE_SUB(NOW(), INTERVAL 1 MONTH))
            LIMIT 20
        """, (board_id, user['id']))
        
        urls_to_check = cursor.fetchall()
        
        # Get counts (user-scoped)
        cursor.execute("""
            SELECT 
                COUNT(CASE WHEN p.link IS NOT NULL THEN 1 END) as pins_with_links,
                COUNT(CASE WHEN uh.status IS NOT NULL THEN 1 END) as health_checked_count,
                COUNT(CASE WHEN uh.status = 'live' THEN 1 END) as live_links,
                COUNT(CASE WHEN uh.status = 'broken' THEN 1 END) as broken_links,
                COUNT(CASE WHEN uh.status = 'archived' THEN 1 END) as archived_links,
                COUNT(CASE WHEN uh.status = 'unknown' THEN 1 END) as unknown_links
            FROM pins p
            LEFT JOIN url_health uh ON p.id = uh.pin_id
            WHERE p.board_id = %s AND p.user_id = %s
        """, (board_id, user['id']))
        
        stats = cursor.fetchone()
        
        cursor.close()
        db.close()
        
        return jsonify({
            "success": True,
            "board_id": board_id,
            "stats": stats,
            "pins_with_links": pins_with_links,
            "urls_that_would_be_checked": urls_to_check,
            "needs_health_checking": len(urls_to_check) > 0
        })
        
    except mysql.connector.Error as e:
        return jsonify({"success": False, "error": f"Database error: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": f"Error: {str(e)}"}), 500

@app.route('/save-pin-colors/<int:pin_id>', methods=['POST'])
@login_required
def save_pin_colors(pin_id):
    user = get_current_user()
    try:
        data = request.get_json()
        dominant_color_1 = data.get('dominant_color_1')
        dominant_color_2 = data.get('dominant_color_2')
        
        if not dominant_color_1 or not dominant_color_2:
            return jsonify({"error": "Both colors are required"}), 400
        
        db = get_db_connection()
        cursor = db.cursor()
        
        # Verify pin belongs to user
        cursor.execute("SELECT id FROM pins WHERE id = %s AND user_id = %s", (pin_id, user['id']))
        if not cursor.fetchone():
            return jsonify({"error": "Pin not found"}), 404
        
        # Update the pin with extracted colors
        cursor.execute("""
            UPDATE pins 
            SET dominant_color_1 = %s, 
                dominant_color_2 = %s, 
                colors_extracted = TRUE
            WHERE id = %s
        """, (dominant_color_1, dominant_color_2, pin_id))
        
        db.commit()
        
        return jsonify({
            'success': True,
            'pin_id': pin_id
        })
    except Exception as e:
        print(f"Error saving pin colors: {str(e)}")
        return jsonify({"error": "Failed to save colors"}), 500
    finally:
        cursor.close()
        db.close()

@app.route('/save-pin-dimensions/<int:pin_id>', methods=['POST'])
@login_required
def save_pin_dimensions(pin_id):
    """
    Store image dimensions reported by the browser after a successful load.
    Used for pins whose images can't be fetched server-side (e.g. Pinterest CDN).
    On the next page load the stored dims are rendered into the aspect-ratio CSS
    property, so no layout shift occurs.
    """
    user = get_current_user()
    db = None
    cursor = None
    try:
        data = request.get_json()
        width = sanitize_integer(data.get('width'), min_value=1, max_value=20000)
        height = sanitize_integer(data.get('height'), min_value=1, max_value=20000)

        if not width or not height:
            return jsonify({"error": "Invalid dimensions"}), 400

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # Fetch pin + its cached_images record (if any) in one query
        cursor.execute("""
            SELECT p.id, p.image_url, p.cached_image_id,
                   ci.cached_filename, ci.cache_status
              FROM pins p
              LEFT JOIN cached_images ci ON ci.id = p.cached_image_id
             WHERE p.id = %s AND p.user_id = %s
        """, (pin_id, user['id']))
        pin = cursor.fetchone()
        if not pin:
            return jsonify({"error": "Pin not found"}), 404

        image_url = pin['image_url'] or ''
        cache_id = pin['cached_image_id']

        # Determine whether a real local file already exists
        already_cached = (
            pin['cached_filename']
            and not pin['cached_filename'].endswith('.placeholder')
            and pin['cache_status'] == 'cached'
        )

        if cache_id:
            # Update dims on the existing record (even if already_cached, dims may need fixing)
            cursor.execute(
                "UPDATE cached_images SET width=%s, height=%s, updated_at=NOW() WHERE id=%s",
                (width, height, cache_id)
            )
        else:
            # No record yet — create a dims-only placeholder so the template
            # renders the correct aspect-ratio on the very next page load.
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:16]
            placeholder = f"{url_hash}_dims_only.placeholder"
            cursor.execute("""
                INSERT INTO cached_images
                    (original_url, cached_filename, file_size, width, height, quality_level, cache_status)
                VALUES (%s, %s, 0, %s, %s, 'low', 'pending')
                ON DUPLICATE KEY UPDATE width=%s, height=%s, updated_at=NOW()
            """, (image_url, placeholder, width, height, width, height))
            cache_id = cursor.lastrowid
            cursor.execute(
                "UPDATE pins SET cached_image_id=%s WHERE id=%s AND cached_image_id IS NULL",
                (cache_id, pin_id)
            )

        db.commit()

        # Kick off a background download if the file isn't already on disk.
        # The thread updates cached_images + pins once complete, so future
        # page loads serve from /cached/ and never touch the external URL.
        if not already_cached and image_url.startswith('http'):
            t = threading.Thread(
                target=_bg_download_and_cache,
                args=(pin_id, image_url, width, height, cache_id),
                daemon=True
            )
            t.start()

        return jsonify({'success': True})

    except Exception as e:
        print(f"Error saving pin dimensions: {e}")
        return jsonify({"error": "Failed to save dimensions"}), 500
    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


@app.route('/delete-pin/<int:pin_id>', methods=['POST'])
@login_required
def delete_pin(pin_id):
    user = get_current_user()
    try:
        with tx() as (db, cursor):
            cursor.execute("SELECT id FROM pins WHERE id = %s AND user_id = %s",
                           (pin_id, user['id']))
            if not cursor.fetchone():
                return jsonify({"error": "Pin not found"}), 404

            before = snapshot_pin(cursor, pin_id)
            board_id = before['board_id'] if before else None

            cursor.execute("DELETE FROM pins WHERE id = %s AND user_id = %s",
                           (pin_id, user['id']))

            record_audit(cursor, action='pin.delete', entity_type='pin',
                         entity_id=pin_id, user_id=user['id'],
                         actor_email=user.get('email'),
                         before=before, after=None,
                         metadata={'route': request.path, 'board_id': board_id},
                         ip_address=request.remote_addr)

        if redis_client:
            redis_client.delete(f"view:{user['id']}:/")

        return jsonify({'success': True, 'board_id': board_id})
    except Exception as e:
        print(f"Error deleting pin: {str(e)}")
        return jsonify({"error": "Failed to delete pin"}), 500

@app.route('/check-archive/<int:pin_id>', methods=['POST'])
@login_required
def check_archive(pin_id):
    """Manually check Wayback Machine for an archived version of a pin's URL"""
    user = get_current_user()
    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        # Get the pin and verify ownership
        cursor.execute("""
            SELECT p.link, uh.status, uh.archive_url
            FROM pins p
            LEFT JOIN url_health uh ON p.id = uh.pin_id
            WHERE p.id = %s AND p.user_id = %s
        """, (pin_id, user['id']))
        
        pin = cursor.fetchone()
        if not pin or not pin['link']:
            return jsonify({"error": "Pin not found or has no link"}), 404
        
        url = pin['link']
        
        # Check Wayback Machine for archives
        try:
            wayback_api = f"https://archive.org/wayback/available?url={url}"
            response = requests.get(wayback_api, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                archived_snapshots = data.get('archived_snapshots', {})
                closest = archived_snapshots.get('closest', {})
                
                if closest.get('available'):
                    archive_url = closest['url']
                    timestamp = closest.get('timestamp', '')
                    
                    # Update the database
                    cursor.execute("""
                        INSERT INTO url_health (pin_id, url, last_checked, status, archive_url)
                        VALUES (%s, %s, NOW(), 'archived', %s)
                        ON DUPLICATE KEY UPDATE
                        last_checked = NOW(),
                        status = 'archived',
                        archive_url = VALUES(archive_url)
                    """, (pin_id, url, archive_url))
                    db.commit()
                    
                    return jsonify({
                        'success': True,
                        'archived': True,
                        'archive_url': archive_url,
                        'timestamp': timestamp,
                        'message': 'Archive found on Wayback Machine!'
                    })
                else:
                    # No archive found
                    cursor.execute("""
                        INSERT INTO url_health (pin_id, url, last_checked, status, archive_url)
                        VALUES (%s, %s, NOW(), 'broken', NULL)
                        ON DUPLICATE KEY UPDATE
                        last_checked = NOW(),
                        status = 'broken',
                        archive_url = NULL
                    """, (pin_id, url))
                    db.commit()
                    
                    return jsonify({
                        'success': True,
                        'archived': False,
                        'message': 'No archive found on Wayback Machine'
                    })
            else:
                return jsonify({"error": "Failed to contact Wayback Machine"}), 500
                
        except requests.RequestException as e:
            print(f"Error checking Wayback Machine: {str(e)}")
            return jsonify({"error": "Failed to check Wayback Machine"}), 500
            
    except Exception as e:
        print(f"Error in check_archive: {str(e)}")
        return jsonify({"error": "An error occurred"}), 500
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if db:
            try:
                db.close()
            except Exception:
                pass

# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

def create_indexes():
    db = None
    cursor = None
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
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if db:
            try:
                db.close()
            except Exception:
                pass

# Note: Background URL health checking has been disabled in favor of JavaScript-based processing
# The check_url_health_for_board API endpoint is used instead for on-demand checking

# Start the background task when the app starts
def start_background_tasks():
    # Create database indexes and tables first
    create_indexes()
    
    # Note: URL health checking is now handled by the JavaScript automatic processing system
    # No background thread needed

# Call this at the end of the file, before app.run()
start_background_tasks()

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_ENV') == 'development'
    app.run(debug=debug_mode, host='0.0.0.0', port=8000)