#!/usr/bin/env python3

import mysql.connector
import os
import sys
import requests
import hashlib
import time
from PIL import Image
import io
import subprocess
import tempfile
from urllib.parse import urlparse, urljoin
import threading
import queue
import logging
from datetime import datetime, timedelta

# Add the parent directory to Python path to import from app.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app import get_db_connection
except ImportError:
    print("Could not import from app.py, using direct connection")
    
    # Fallback database connection
    def get_db_connection():
        return mysql.connector.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            user=os.getenv('DB_USER', 'db'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME', 'db'),
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci'
        )

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ImageCacheService:
    def __init__(self, cache_dir='static/cached_images', max_workers=3):
        self.cache_dir = cache_dir
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Create cache directory if it doesn't exist
        os.makedirs(cache_dir, exist_ok=True)
        
        # Task queue for background processing
        self.task_queue = queue.Queue()
        self.workers = []
        self.running = False
        
        # Check if ffmpeg is available for video processing
        self.ffmpeg_available = self._check_ffmpeg_available()
        if self.ffmpeg_available:
            logger.info("ffmpeg detected - video frame extraction enabled")
        else:
            logger.warning("ffmpeg not found - video URLs will be skipped")
    
    def _check_ffmpeg_available(self):
        """Check if ffmpeg is available on the system"""
        try:
            subprocess.run(['ffmpeg', '-version'], 
                         capture_output=True, check=True, timeout=5)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def _is_video_url(self, url):
        """Check if URL points to a video file"""
        url_lower = url.lower()
        
        # Check for video file extensions
        video_extensions = ['.mp4', '.webm', '.mov', '.avi', '.mkv', '.m4v']
        for ext in video_extensions:
            if ext in url_lower:
                return True
        
        # Check for known video hosting patterns
        video_patterns = [
            'v1.pinimg.com/videos/',
            '/videos/',
            'video.',
            '.mp4',
            '.webm'
        ]
        
        for pattern in video_patterns:
            if pattern in url_lower:
                return True
        
        return False
    
    def _extract_video_frame(self, video_url, output_path, timestamp='00:00:01'):
        """Extract a frame from video using ffmpeg"""
        if not self.ffmpeg_available:
            raise Exception("ffmpeg not available for video processing")
        
        try:
            # Create a temporary file for the video
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_video:
                temp_video_path = temp_video.name
            
            try:
                # Download video to temp file
                logger.info(f"Downloading video: {video_url}")
                response = self.session.get(video_url, timeout=60, stream=True)
                response.raise_for_status()
                
                # Write video data to temp file
                with open(temp_video_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                # Extract frame using ffmpeg
                logger.info(f"Extracting frame at {timestamp} from video")
                cmd = [
                    'ffmpeg',
                    '-i', temp_video_path,
                    '-ss', timestamp,
                    '-vframes', '1',
                    '-f', 'image2',
                    '-y',  # Overwrite output file
                    output_path
                ]
                
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                
                if result.returncode != 0:
                    raise Exception(f"ffmpeg failed: {result.stderr.decode()}")
                
                # Verify the frame was created
                if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                    raise Exception("No frame was extracted")
                
                logger.info(f"Successfully extracted video frame: {output_path}")
                return True
                
            finally:
                # Clean up temp video file
                if os.path.exists(temp_video_path):
                    os.unlink(temp_video_path)
                    
        except Exception as e:
            logger.error(f"Failed to extract video frame: {e}")
            raise
    
    def start_workers(self):
        """Start background worker threads"""
        self.running = True
        for i in range(self.max_workers):
            worker = threading.Thread(target=self._worker, name=f'ImageCacheWorker-{i}')
            worker.daemon = True
            worker.start()
            self.workers.append(worker)
        logger.info(f"Started {self.max_workers} image cache workers")
    
    def stop_workers(self):
        """Stop background worker threads"""
        self.running = False
        # Add stop signals to queue
        for _ in range(self.max_workers):
            self.task_queue.put(None)
        
        # Wait for workers to finish
        for worker in self.workers:
            worker.join(timeout=5)
        
        logger.info("Stopped image cache workers")
    
    def _worker(self):
        """Background worker thread function"""
        while self.running:
            try:
                task = self.task_queue.get(timeout=1)
                if task is None:  # Stop signal
                    break
                
                pin_id, image_url, quality_level = task
                self._cache_image(pin_id, image_url, quality_level)
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in worker thread: {e}")
            finally:
                self.task_queue.task_done()
    
    def queue_image_for_caching(self, pin_id, image_url, quality_level='low'):
        """Queue an image for background caching"""
        if not self.running:
            self.start_workers()
        
        self.task_queue.put((pin_id, image_url, quality_level))
        logger.info(f"Queued image for caching: pin_id={pin_id}, url={image_url[:50]}...")
    
    def _generate_cache_filename(self, original_url, quality_level):
        """Generate a unique filename for cached image"""
        # Create hash from URL
        url_hash = hashlib.md5(original_url.encode()).hexdigest()[:16]
        
        # Get file extension from URL (fallback to jpg)
        parsed_url = urlparse(original_url)
        path = parsed_url.path.lower()
        
        # For video URLs, always use jpg extension for the extracted frame
        if self._is_video_url(original_url):
            ext = 'jpg'
        elif path.endswith(('.jpg', '.jpeg')):
            ext = 'jpg'
        elif path.endswith('.png'):
            ext = 'png'
        elif path.endswith('.webp'):
            ext = 'webp'
        elif path.endswith('.gif'):
            ext = 'gif'
        else:
            ext = 'jpg'  # Default fallback
        
        return f"{url_hash}_{quality_level}.{ext}"
    
    def _get_retry_count(self, image_url, quality_level):
        """Get current retry count for an image"""
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT retry_count, last_retry_at FROM cached_images 
                WHERE original_url = %s AND quality_level = %s
            """, (image_url, quality_level))
            
            result = cursor.fetchone()
            cursor.close()
            db.close()
            
            if result:
                return result['retry_count'] or 0, result['last_retry_at']
            return 0, None
            
        except Exception as e:
            logger.error(f"Error getting retry count: {e}")
            return 0, None
    
    def _should_retry(self, image_url, quality_level, max_retries=3):
        """Check if we should retry caching this image"""
        retry_count, last_retry = self._get_retry_count(image_url, quality_level)
        
        # Don't retry if we've exceeded max attempts
        if retry_count >= max_retries:
            logger.info(f"Max retries ({max_retries}) exceeded for {image_url}")
            return False
        
        # If we've retried recently, use exponential backoff
        if last_retry:
            # Wait time: 1 hour * (2^retry_count)
            wait_hours = 1 * (2 ** retry_count)
            next_retry_time = last_retry + timedelta(hours=wait_hours)
            
            if datetime.now() < next_retry_time:
                logger.info(f"Too soon to retry {image_url}, next retry at {next_retry_time}")
                return False
        
        return True
    
    def _cache_image(self, pin_id, image_url, quality_level='low'):
        """Download and cache an image or extract frame from video"""
        try:
            # Check retry logic first
            if not self._should_retry(image_url, quality_level):
                return None
            
            # Check if already cached
            cached_filename = self._generate_cache_filename(image_url, quality_level)
            cached_path = os.path.join(self.cache_dir, cached_filename)
            
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            
            # Check if already in database
            cursor.execute("""
                SELECT id, cache_status FROM cached_images 
                WHERE original_url = %s AND quality_level = %s
            """, (image_url, quality_level))
            
            cached_record = cursor.fetchone()
            
            if cached_record and cached_record['cache_status'] == 'cached' and os.path.exists(cached_path):
                # Update last accessed time
                cursor.execute("""
                    UPDATE cached_images 
                    SET last_accessed = CURRENT_TIMESTAMP 
                    WHERE id = %s
                """, (cached_record['id'],))
                
                # Update pin to use cached image
                cursor.execute("""
                    UPDATE pins 
                    SET cached_image_id = %s, uses_cached_image = TRUE 
                    WHERE id = %s
                """, (cached_record['id'], pin_id))
                
                db.commit()
                logger.info(f"Image already cached: {cached_filename}")
                return cached_record['id']
            
            # Determine if this is a video URL
            is_video = self._is_video_url(image_url)
            
            if is_video and not self.ffmpeg_available:
                logger.warning(f"Skipping video URL (ffmpeg not available): {image_url}")
                self._mark_cache_failed(image_url, quality_level, "ffmpeg not available for video processing")
                return None
            
            if is_video:
                # Extract frame from video
                logger.info(f"Processing video URL: {image_url}")
                
                # Create temporary file for extracted frame
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_frame:
                    temp_frame_path = temp_frame.name
                
                try:
                    # Extract frame using ffmpeg
                    self._extract_video_frame(image_url, temp_frame_path)
                    
                    # Load the extracted frame
                    with Image.open(temp_frame_path) as img:
                        # Process the frame like a regular image
                        img = self._process_image(img, quality_level)
                        img.save(cached_path, 'JPEG', quality=70, optimize=True)
                        
                        # Get file size
                        file_size = os.path.getsize(cached_path)
                        width, height = img.size
                        
                        logger.info(f"Cached video frame: {cached_filename} ({file_size} bytes, {width}x{height})")
                        
                finally:
                    # Clean up temp frame
                    if os.path.exists(temp_frame_path):
                        os.unlink(temp_frame_path)
            else:
                # Download regular image
                logger.info(f"Downloading image: {image_url}")
                response = self.session.get(image_url, timeout=30, stream=True)
                response.raise_for_status()
                
                # Check content type
                content_type = response.headers.get('content-type', '').lower()
                if not content_type.startswith('image/'):
                    raise ValueError(f"Not an image: {content_type}")
                
                # Read image data
                image_data = response.content
                if len(image_data) == 0:
                    raise ValueError("Empty image data")
                
                # Process image with PIL
                with Image.open(io.BytesIO(image_data)) as img:
                    img = self._process_image(img, quality_level)
                    img.save(cached_path, 'JPEG', quality=70, optimize=True)
                    
                    # Get file size
                    file_size = os.path.getsize(cached_path)
                    width, height = img.size
                    
                    logger.info(f"Cached image: {cached_filename} ({file_size} bytes, {width}x{height})")
            
            # Save to database
            if cached_record:
                # Update existing record
                cursor.execute("""
                    UPDATE cached_images 
                    SET cached_filename = %s, file_size = %s, width = %s, height = %s,
                        cache_status = 'cached', updated_at = CURRENT_TIMESTAMP,
                        last_accessed = CURRENT_TIMESTAMP, retry_count = 0, last_retry_at = NULL
                    WHERE id = %s
                """, (cached_filename, file_size, width, height, cached_record['id']))
                cache_id = cached_record['id']
            else:
                # Insert new record
                cursor.execute("""
                    INSERT INTO cached_images 
                    (original_url, cached_filename, file_size, width, height, quality_level, cache_status, retry_count)
                    VALUES (%s, %s, %s, %s, %s, %s, 'cached', 0)
                """, (image_url, cached_filename, file_size, width, height, quality_level))
                cache_id = cursor.lastrowid
            
            # Update pin to use cached image
            cursor.execute("""
                UPDATE pins 
                SET cached_image_id = %s, uses_cached_image = TRUE 
                WHERE id = %s
            """, (cache_id, pin_id))
            
            db.commit()
            logger.info(f"Successfully cached {'video frame' if is_video else 'image'} for pin {pin_id}")
            return cache_id
            
        except requests.RequestException as e:
            logger.error(f"Failed to download {'video' if self._is_video_url(image_url) else 'image'} {image_url}: {e}")
            self._mark_cache_failed(image_url, quality_level, str(e))
        except Exception as e:
            logger.error(f"Failed to cache {'video' if self._is_video_url(image_url) else 'image'} {image_url}: {e}")
            self._mark_cache_failed(image_url, quality_level, str(e))
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'db' in locals():
                db.close()
        
        return None
    
    def _process_image(self, img, quality_level):
        """Process image (resize, convert) based on quality level"""
        # Convert to RGB if necessary
        if img.mode in ('RGBA', 'LA', 'P'):
            # Create white background for transparency
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Resize based on quality level
        if quality_level == 'thumbnail':
            max_size = (150, 150)
        elif quality_level == 'low':
            max_size = (400, 400)
        elif quality_level == 'medium':
            max_size = (800, 800)
        else:
            max_size = (400, 400)
        
        # Resize maintaining aspect ratio
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        return img
    
    def _mark_cache_failed(self, image_url, quality_level, error_msg):
        """Mark an image as failed to cache with retry tracking"""
        try:
            db = get_db_connection()
            cursor = db.cursor()
            
            # Get current retry count
            retry_count, _ = self._get_retry_count(image_url, quality_level)
            new_retry_count = retry_count + 1
            
            cursor.execute("""
                INSERT INTO cached_images 
                (original_url, cached_filename, quality_level, cache_status, retry_count, last_retry_at)
                VALUES (%s, %s, %s, 'failed', %s, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE 
                cache_status = 'failed', 
                retry_count = %s,
                last_retry_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            """, (image_url, f"failed_{quality_level}", quality_level, new_retry_count, new_retry_count))
            
            db.commit()
            logger.warning(f"Marked {'video' if self._is_video_url(image_url) else 'image'} as failed (attempt {new_retry_count}): {image_url} - {error_msg}")
            
        except Exception as e:
            logger.error(f"Failed to mark image as failed: {e}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'db' in locals():
                db.close()
    
    def cache_all_external_images(self, limit=None, board_id=None):
        """Cache all external images for pins that don't have cached versions"""
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            
            # Get all pins with external images that aren't cached and haven't exceeded retry limits
            query = """
                SELECT p.id, p.image_url, p.board_id
                FROM pins p 
                LEFT JOIN cached_images ci ON p.cached_image_id = ci.id 
                WHERE p.image_url LIKE 'http%' 
                AND (p.cached_image_id IS NULL OR ci.cache_status != 'cached')
                AND (ci.retry_count IS NULL OR ci.retry_count < 3 OR 
                     ci.last_retry_at < DATE_SUB(NOW(), INTERVAL POWER(2, ci.retry_count) HOUR))
            """
            
            params = []
            if board_id:
                query += " AND p.board_id = %s"
                params.append(board_id)
            
            query += " ORDER BY p.created_at DESC"
            
            if limit:
                query += f" LIMIT {limit}"
            
            cursor.execute(query, params)
            pins = cursor.fetchall()
            
            board_message = f" for board {board_id}" if board_id else ""
            logger.info(f"Found {len(pins)} pins with external images to cache{board_message}")
            
            for pin in pins:
                is_video = self._is_video_url(pin['image_url'])
                media_type = "video" if is_video else "image"
                logger.info(f"Queuing {media_type} for caching: pin {pin['id']} - {pin['image_url'][:60]}...")
                
                self.queue_image_for_caching(pin['id'], pin['image_url'], 'low')
                time.sleep(0.1)  # Small delay to avoid overwhelming the queue
            
            # Wait for all tasks to complete
            self.task_queue.join()
            
        except Exception as e:
            logger.error(f"Error caching all external images: {e}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'db' in locals():
                db.close()
    
    def cleanup_old_cache(self, days_old=30):
        """Clean up old cached images that haven't been accessed recently"""
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            
            # Find old cached images
            cursor.execute("""
                SELECT id, cached_filename 
                FROM cached_images 
                WHERE last_accessed < DATE_SUB(NOW(), INTERVAL %s DAY)
                AND cache_status = 'cached'
            """, (days_old,))
            
            old_images = cursor.fetchall()
            
            for image in old_images:
                # Delete file
                file_path = os.path.join(self.cache_dir, image['cached_filename'])
                if os.path.exists(file_path):
                    os.remove(file_path)
                
                # Update database
                cursor.execute("""
                    UPDATE cached_images 
                    SET cache_status = 'expired' 
                    WHERE id = %s
                """, (image['id'],))
                
                # Update pins that used this cached image
                cursor.execute("""
                    UPDATE pins 
                    SET cached_image_id = NULL, uses_cached_image = FALSE 
                    WHERE cached_image_id = %s
                """, (image['id'],))
            
            db.commit()
            logger.info(f"Cleaned up {len(old_images)} old cached images")
            
        except Exception as e:
            logger.error(f"Error cleaning up old cache: {e}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'db' in locals():
                db.close()

def main():
    """Main function for running the image cache service"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Image Cache Service')
    parser.add_argument('--cache-all', action='store_true', help='Cache all external images')
    parser.add_argument('--limit', type=int, help='Limit number of images to cache')
    parser.add_argument('--cleanup', action='store_true', help='Clean up old cached images')
    parser.add_argument('--days-old', type=int, default=30, help='Days old for cleanup')
    
    args = parser.parse_args()
    
    cache_service = ImageCacheService()
    
    try:
        if args.cache_all:
            cache_service.cache_all_external_images(limit=args.limit)
        elif args.cleanup:
            cache_service.cleanup_old_cache(days_old=args.days_old)
        else:
            print("Use --cache-all to cache external images or --cleanup to clean old cache")
    finally:
        cache_service.stop_workers()

if __name__ == "__main__":
    main() 