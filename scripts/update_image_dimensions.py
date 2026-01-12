#!/usr/bin/env python3
"""
Image Dimensions Update Script

This script crawls through all pins in the database and ensures they have
image dimensions stored in the cached_images table. This prevents layout
shift when images load in the browser.

For pins that already have cached images with dimensions, they are skipped.
For pins without dimensions, this script will:
1. Check if a cached_images record exists for the image URL
2. If not, create one with cache_status='pending' (just for dimensions)
3. Try to fetch actual dimensions from the image URL
4. Update the cached_images record with the dimensions
5. Link the pin to the cached_images record if not already linked

Usage:
    python scripts/update_image_dimensions.py              # Process all pins
    python scripts/update_image_dimensions.py --limit 100  # Process up to 100 pins
    python scripts/update_image_dimensions.py --dry-run    # Show what would be done
    python scripts/update_image_dimensions.py --board-id 5 # Process specific board
"""

import os
import sys
import time
import argparse
import requests
from io import BytesIO
from urllib.parse import urlparse
import concurrent.futures
from datetime import datetime
import hashlib

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow")
    sys.exit(1)

try:
    import mysql.connector
except ImportError:
    print("Error: mysql-connector-python is required. Install with: pip install mysql-connector-python")
    sys.exit(1)

# Database configuration
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'db'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME', 'db'),
        charset='utf8mb4',
        collation='utf8mb4_unicode_ci'
    )


class ImageDimensionUpdater:
    def __init__(self, dry_run=False, verbose=False):
        self.dry_run = dry_run
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        self.stats = {
            'total_pins': 0,
            'pins_with_dimensions': 0,
            'pins_missing_dimensions': 0,
            'dimensions_fetched': 0,
            'dimensions_failed': 0,
            'cached_images_created': 0,
            'cached_images_updated': 0,
            'pins_linked': 0,
            'skipped_local': 0,
        }
    
    def log(self, message, level='info'):
        """Print log message with timestamp"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        prefix = {
            'info': '📌',
            'success': '✅',
            'error': '❌',
            'warning': '⚠️',
            'progress': '🔄',
        }.get(level, '')
        print(f"[{timestamp}] {prefix} {message}")
    
    def get_pins_without_dimensions(self, limit=None, board_id=None):
        """Get all pins that don't have dimensions in cached_images"""
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        try:
            # Find pins where:
            # - They have no cached_image_id, OR
            # - Their cached_images record has width=0 or height=0
            query = """
                SELECT p.id as pin_id, p.image_url, p.cached_image_id,
                       ci.id as cache_id, ci.width as cached_width, ci.height as cached_height,
                       ci.cache_status
                FROM pins p
                LEFT JOIN cached_images ci ON p.cached_image_id = ci.id
                WHERE p.image_url IS NOT NULL
                  AND p.image_url != ''
                  AND (
                      p.cached_image_id IS NULL
                      OR ci.width IS NULL
                      OR ci.width = 0
                      OR ci.height IS NULL
                      OR ci.height = 0
                  )
            """
            params = []
            
            if board_id:
                query += " AND p.board_id = %s"
                params.append(board_id)
            
            query += " ORDER BY p.id DESC"
            
            if limit:
                query += f" LIMIT {int(limit)}"
            
            cursor.execute(query, params)
            pins = cursor.fetchall()
            return pins
            
        finally:
            cursor.close()
            db.close()
    
    def get_total_pins_count(self):
        """Get total number of pins and those with dimensions"""
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        try:
            # Total pins
            cursor.execute("SELECT COUNT(*) as count FROM pins WHERE image_url IS NOT NULL AND image_url != ''")
            total = cursor.fetchone()['count']
            
            # Pins with dimensions
            cursor.execute("""
                SELECT COUNT(*) as count 
                FROM pins p
                JOIN cached_images ci ON p.cached_image_id = ci.id
                WHERE ci.width > 0 AND ci.height > 0
            """)
            with_dims = cursor.fetchone()['count']
            
            return total, with_dims
            
        finally:
            cursor.close()
            db.close()
    
    def fetch_image_dimensions(self, image_url, timeout=10):
        """
        Fetch image dimensions from URL.
        Uses partial download to get dimensions without downloading entire image.
        """
        try:
            # Handle local/cached images
            if image_url.startswith('/'):
                if image_url.startswith('/cached/'):
                    local_path = os.path.join('static', 'cached_images', image_url[8:])
                elif image_url.startswith('/static/'):
                    local_path = image_url[1:]
                else:
                    return None
                
                if os.path.exists(local_path):
                    with Image.open(local_path) as img:
                        return img.size
                return None
            
            # For external URLs, try to get dimensions efficiently
            response = self.session.get(
                image_url,
                timeout=timeout,
                stream=True,
                headers={'Range': 'bytes=0-65535'}  # Request first 64KB only
            )
            response.raise_for_status()
            
            # Read partial content
            content = b''
            for chunk in response.iter_content(chunk_size=8192):
                content += chunk
                if len(content) > 65535:
                    break
            
            # Try to parse image from partial content
            try:
                with Image.open(BytesIO(content)) as img:
                    return img.size
            except Exception:
                # If partial download didn't work, try full download
                response = self.session.get(image_url, timeout=timeout)
                response.raise_for_status()
                with Image.open(BytesIO(response.content)) as img:
                    return img.size
                    
        except requests.exceptions.Timeout:
            if self.verbose:
                self.log(f"Timeout fetching {image_url[:60]}...", 'warning')
            return None
        except requests.exceptions.RequestException as e:
            if self.verbose:
                self.log(f"Request error for {image_url[:60]}...: {e}", 'warning')
            return None
        except Exception as e:
            if self.verbose:
                self.log(f"Error getting dimensions for {image_url[:60]}...: {e}", 'warning')
            return None
    
    def get_or_create_cached_image(self, image_url, db, cursor):
        """
        Get existing cached_images record or create a new one.
        Returns the cache_id.
        """
        # Check if record exists
        cursor.execute("""
            SELECT id, width, height FROM cached_images 
            WHERE original_url = %s AND quality_level = 'low'
            LIMIT 1
        """, (image_url,))
        result = cursor.fetchone()
        
        if result:
            return result['id'], result['width'], result['height']
        
        # Create new record with pending status (dimensions only, not cached file)
        if not self.dry_run:
            # Generate a placeholder filename
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:16]
            placeholder_filename = f"{url_hash}_dims_only.placeholder"
            
            cursor.execute("""
                INSERT INTO cached_images 
                (original_url, cached_filename, file_size, width, height, quality_level, cache_status)
                VALUES (%s, %s, 0, 0, 0, 'low', 'pending')
            """, (image_url, placeholder_filename))
            db.commit()
            self.stats['cached_images_created'] += 1
            return cursor.lastrowid, 0, 0
        
        return None, 0, 0
    
    def update_dimensions(self, cache_id, width, height, db, cursor):
        """Update dimensions in cached_images table"""
        if not self.dry_run:
            cursor.execute("""
                UPDATE cached_images 
                SET width = %s, height = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (width, height, cache_id))
            db.commit()
            self.stats['cached_images_updated'] += 1
    
    def link_pin_to_cache(self, pin_id, cache_id, db, cursor):
        """Link a pin to its cached_images record"""
        if not self.dry_run:
            cursor.execute("""
                UPDATE pins 
                SET cached_image_id = %s
                WHERE id = %s AND (cached_image_id IS NULL OR cached_image_id != %s)
            """, (cache_id, pin_id, cache_id))
            if cursor.rowcount > 0:
                db.commit()
                self.stats['pins_linked'] += 1
    
    def process_pin(self, pin):
        """Process a single pin to get/store its dimensions"""
        pin_id = pin['pin_id']
        image_url = pin['image_url']
        cache_id = pin['cached_image_id'] or pin['cache_id']
        
        # Skip local images for now (they're fast to load anyway)
        if image_url.startswith('/static/images/'):
            self.stats['skipped_local'] += 1
            return True
        
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        try:
            # Get or create cached_images record
            if cache_id:
                # Record exists, just need to update dimensions
                pass
            else:
                cache_id, _, _ = self.get_or_create_cached_image(image_url, db, cursor)
            
            if cache_id is None and self.dry_run:
                # In dry run, we'd create a record
                self.stats['cached_images_created'] += 1
                return True
            
            # Fetch actual dimensions from image
            dimensions = self.fetch_image_dimensions(image_url)
            
            if dimensions:
                width, height = dimensions
                if self.verbose:
                    self.log(f"Pin {pin_id}: {width}x{height}", 'success')
                
                self.update_dimensions(cache_id, width, height, db, cursor)
                self.link_pin_to_cache(pin_id, cache_id, db, cursor)
                self.stats['dimensions_fetched'] += 1
                return True
            else:
                self.stats['dimensions_failed'] += 1
                return False
                
        except Exception as e:
            self.log(f"Error processing pin {pin_id}: {e}", 'error')
            self.stats['dimensions_failed'] += 1
            return False
        finally:
            cursor.close()
            db.close()
    
    def run(self, limit=None, board_id=None, workers=4):
        """Run the dimension update process"""
        self.log("=" * 60)
        self.log("Image Dimensions Update Script")
        self.log("=" * 60)
        
        if self.dry_run:
            self.log("DRY RUN MODE - No changes will be made", 'warning')
        
        # Get counts
        total_pins, pins_with_dims = self.get_total_pins_count()
        self.log(f"Total pins: {total_pins:,}")
        self.log(f"Pins with dimensions: {pins_with_dims:,}")
        self.log(f"Pins without dimensions: {total_pins - pins_with_dims:,}")
        
        self.stats['total_pins'] = total_pins
        self.stats['pins_with_dimensions'] = pins_with_dims
        
        # Get pins needing dimensions
        pins = self.get_pins_without_dimensions(limit=limit, board_id=board_id)
        self.stats['pins_missing_dimensions'] = len(pins)
        
        if not pins:
            self.log("No pins need dimension updates!", 'success')
            return self.stats
        
        self.log(f"Processing {len(pins)} pins...")
        
        # Process pins with thread pool for faster execution
        start_time = time.time()
        processed = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self.process_pin, pin): pin for pin in pins}
            
            for future in concurrent.futures.as_completed(futures):
                processed += 1
                if processed % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = processed / elapsed if elapsed > 0 else 0
                    self.log(f"Progress: {processed}/{len(pins)} ({rate:.1f} pins/sec)", 'progress')
        
        # Final stats
        elapsed = time.time() - start_time
        self.log("=" * 60)
        self.log("COMPLETED", 'success')
        self.log("=" * 60)
        self.log(f"Time elapsed: {elapsed:.1f} seconds")
        self.log(f"Pins processed: {processed}")
        self.log(f"Dimensions fetched: {self.stats['dimensions_fetched']}")
        self.log(f"Dimensions failed: {self.stats['dimensions_failed']}")
        self.log(f"Cached images created: {self.stats['cached_images_created']}")
        self.log(f"Cached images updated: {self.stats['cached_images_updated']}")
        self.log(f"Pins linked to cache: {self.stats['pins_linked']}")
        self.log(f"Local images skipped: {self.stats['skipped_local']}")
        
        return self.stats


def main():
    parser = argparse.ArgumentParser(description='Update image dimensions for pins')
    parser.add_argument('--limit', type=int, help='Limit number of pins to process')
    parser.add_argument('--board-id', type=int, help='Process only pins from specific board')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed progress')
    parser.add_argument('--workers', type=int, default=4, help='Number of parallel workers (default: 4)')
    
    args = parser.parse_args()
    
    updater = ImageDimensionUpdater(dry_run=args.dry_run, verbose=args.verbose)
    updater.run(limit=args.limit, board_id=args.board_id, workers=args.workers)


if __name__ == "__main__":
    main()
