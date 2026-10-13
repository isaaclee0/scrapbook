"""Ordered pin images and durable uploads.

Callers authenticate ownership and commit or roll back their transaction. Each
gallery operation locks the parent pin so legacy initialization and mutations
serialize together. Image files survive removal for shared references and undo.
"""
import io
import uuid
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGES = 20
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_PIXELS = 40_000_000
DEFAULT_IMAGE_URL = '/static/images/default_pin.png'
IMAGE_COLUMNS = ('id', 'pin_id', 'image_url', 'preview_url', 'width', 'height',
                 'cached_image_id', 'uses_cached_image', 'position')
COLOUR_COLUMNS = ('dominant_color', 'palette_color_1', 'palette_color_2',
                  'palette_color_3', 'palette_color_4', 'palette_color_5')


class GalleryError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _dictionary(cursor, row):
    if row is None or isinstance(row, dict):
        return row
    return dict(zip((column[0] for column in cursor.description), row))


def _fetchone(cursor):
    return _dictionary(cursor, cursor.fetchone())


def _fetchall(cursor):
    return [_dictionary(cursor, row) for row in cursor.fetchall()]


def _locked_pin(cursor, pin_id):
    cursor.execute('''
        SELECT id, image_url, cached_image_id, uses_cached_image, images_initialized
        FROM pins WHERE id = %s FOR UPDATE
    ''', (pin_id,))
    pin = _fetchone(cursor)
    if pin is None:
        raise GalleryError('Pin not found.', 404)
    return pin


def _stored_images(cursor, pin_id):
    # Auditing may already have established a REPEATABLE READ view before the
    # parent lock. A locking read sees the latest committed gallery after that
    # lock, so snapshots and mutation state cannot use an obsolete collection.
    cursor.execute(f"SELECT {', '.join(IMAGE_COLUMNS)} FROM pin_images WHERE pin_id = %s ORDER BY position, id FOR UPDATE", (pin_id,))
    return _fetchall(cursor)


def _image_fields(image):
    if not isinstance(image, dict) or not isinstance(image.get('image_url'), str) or not image['image_url'].strip():
        raise GalleryError('Choose an image to upload.')
    if image['image_url'] == DEFAULT_IMAGE_URL:
        raise GalleryError('The default placeholder cannot be added as an image.')
    return {
        'image_url': image['image_url'],
        'preview_url': image.get('preview_url') or None,
        'width': max(0, int(image.get('width') or 0)),
        'height': max(0, int(image.get('height') or 0)),
        'cached_image_id': image.get('cached_image_id'),
        'uses_cached_image': bool(image.get('uses_cached_image', False)),
    }


def _insert_image(cursor, pin_id, image, position, stable_id=None):
    fields = _image_fields(image)
    columns = ['pin_id', *fields, 'position']
    values = [pin_id, *fields.values(), position]
    if stable_id is not None:
        columns.insert(0, 'id')
        values.insert(0, stable_id)
    cursor.execute(f"INSERT INTO pin_images ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(values))})", tuple(values))


def ensure_pin_images(cursor, pin):
    """Backfill a legacy cover once, reloading under a parent-row lock.

    The durable marker distinguishes a deliberately empty gallery from a legacy
    pin, including when the caller still holds an obsolete cover dictionary.
    """
    current = _locked_pin(cursor, pin['id'])
    if not current['images_initialized']:
        existing = _stored_images(cursor, current['id'])
        if not existing and current['image_url'] and current['image_url'] != DEFAULT_IMAGE_URL:
            image = dict(current, preview_url=None, width=0, height=0)
            if current['cached_image_id']:
                cursor.execute('SELECT cached_filename, width, height, cache_status FROM cached_images WHERE id = %s', (current['cached_image_id'],))
                cached = _fetchone(cursor)
                # Pending/failed cache rows can contain layout estimates rather
                # than decoded dimensions. Leave those gallery dimensions unset
                # so list/card queries can use the completed cache record later.
                if cached and cached['cache_status'] == 'cached':
                    image.update(width=cached['width'] or 0, height=cached['height'] or 0)
                    if current['uses_cached_image'] and cached['cached_filename']:
                        image['preview_url'] = '/cached/' + cached['cached_filename']
            _insert_image(cursor, current['id'], image, 0)
        cursor.execute('UPDATE pins SET images_initialized = TRUE WHERE id = %s', (current['id'],))
    pin['images_initialized'] = True


def list_images(cursor, pin):
    """Return only JSON-ready API fields in cover-first order."""
    ensure_pin_images(cursor, pin)
    images = _stored_images(cursor, pin['id'])
    cache_ids = sorted({image['cached_image_id'] for image in images if image['cached_image_id']})
    cached_images = {}
    if cache_ids:
        # Cache metadata does not determine gallery membership. Do not acquire
        # cache locks after the parent pin lock: background caching can acquire
        # those locks in the reverse order. Original URLs remain valid if this
        # transaction's read view cannot yet see a newly created cache record.
        cursor.execute(f'''SELECT id, cached_filename, cache_status, width, height
            FROM cached_images WHERE id IN ({', '.join(['%s'] * len(cache_ids))})''', tuple(cache_ids))
        cached_images = {row['id']: row for row in _fetchall(cursor)}
    result = []
    for image in images:
        cached = cached_images.get(image['cached_image_id'], {})
        display_url = image['image_url']
        if image['uses_cached_image'] and cached.get('cache_status') == 'cached' and cached.get('cached_filename'):
            display_url = '/cached/' + cached['cached_filename']
        result.append({
            'id': int(image['id']), 'image_url': image['image_url'],
            'display_url': display_url, 'preview_url': image['preview_url'] or display_url,
            'width': int(image['width'] or cached.get('width') or 0),
            'height': int(image['height'] or cached.get('height') or 0),
            'position': int(image['position']),
        })
    return result


def _project_cover(cursor, pin, old_cover=None):
    images = _stored_images(cursor, pin['id'])
    cover = images[0] if images else None
    image_url = cover['image_url'] if cover else DEFAULT_IMAGE_URL
    cached_id = cover['cached_image_id'] if cover else None
    uses_cache = bool(cover['uses_cached_image']) if cover else False
    changed = (pin.get('image_url'), pin.get('cached_image_id'), bool(pin.get('uses_cached_image'))) != (image_url, cached_id, uses_cache)
    if old_cover is not None and cover is not None:
        changed = changed or old_cover['id'] != cover['id']
    colour_reset = ''.join(f', {column} = NULL' for column in COLOUR_COLUMNS) if changed else ''
    cursor.execute(f'''UPDATE pins SET image_url = %s, cached_image_id = %s,
        uses_cached_image = %s, images_initialized = TRUE{colour_reset} WHERE id = %s''',
        (image_url, cached_id, uses_cache, pin['id']))
    pin.update(image_url=image_url, cached_image_id=cached_id,
               uses_cached_image=uses_cache, images_initialized=True)
    if changed:
        pin.update({column: None for column in COLOUR_COLUMNS})


def _set_order(cursor, pin_id, images):
    # Two phases avoid collisions with the unique (pin_id, position) constraint.
    # Positions are signed so a temporary negative range can be used safely.
    for index, image in enumerate(images):
        cursor.execute('UPDATE pin_images SET position = %s WHERE id = %s AND pin_id = %s', (-index - 1, image['id'], pin_id))
    for index, image in enumerate(images):
        cursor.execute('UPDATE pin_images SET position = %s WHERE id = %s AND pin_id = %s', (index, image['id'], pin_id))


def _identifier(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GalleryError('Image ID must be a positive integer.')
    return value


def mutate_gallery(cursor, pin, action, image_id=None, image_ids=None, upload=None):
    """Mutate in the caller's transaction; never delete retained image bytes."""
    ensure_pin_images(cursor, pin)
    current = _locked_pin(cursor, pin['id'])
    images = _stored_images(cursor, pin['id'])
    old_cover = images[0] if images else None
    by_id = {image['id']: image for image in images}
    if action not in ('add', 'replace', 'cover', 'remove', 'reorder'):
        raise GalleryError('Unknown gallery action.')
    if action in ('replace', 'cover', 'remove'):
        image_id = _identifier(image_id)
        if image_id not in by_id:
            raise GalleryError('This image is no longer in the pin. Reload the gallery.', 404)
    if action == 'add':
        if len(images) >= MAX_IMAGES:
            raise GalleryError(f'A pin can contain at most {MAX_IMAGES} images.', 409)
        _insert_image(cursor, pin['id'], upload, len(images))
    elif action == 'replace':
        fields = _image_fields(upload)
        cursor.execute(f"UPDATE pin_images SET {', '.join(column + ' = %s' for column in fields)} WHERE id = %s AND pin_id = %s", (*fields.values(), image_id, pin['id']))
    elif action == 'cover':
        images = [by_id[image_id]] + [image for image in images if image['id'] != image_id]
        _set_order(cursor, pin['id'], images)
    elif action == 'remove':
        cursor.execute('DELETE FROM pin_images WHERE id = %s AND pin_id = %s', (image_id, pin['id']))
        _set_order(cursor, pin['id'], [image for image in images if image['id'] != image_id])
    elif action == 'reorder':
        if (not isinstance(image_ids, (list, tuple)) or
                any(isinstance(value, bool) or not isinstance(value, int) for value in image_ids) or
                len(image_ids) != len(images) or len(set(image_ids)) != len(image_ids) or
                set(image_ids) != set(by_id)):
            raise GalleryError('The image list has changed. Reload the gallery before reordering.', 409)
        if images and image_ids[0] != images[0]['id']:
            raise GalleryError('Use Make cover to change the first image.', 409)
        _set_order(cursor, pin['id'], [by_id[value] for value in image_ids])
    _project_cover(cursor, current, old_cover)
    pin.update(current)
    return list_images(cursor, pin)


def snapshot_images(cursor, pin_id):
    """Snapshot full stored rows, including legacy pins and tuple cursors."""
    ensure_pin_images(cursor, {'id': pin_id})
    return _stored_images(cursor, pin_id)


def restore_images(cursor, pin_id, images):
    """Restore stable image IDs after undo in the caller's transaction."""
    pin = _locked_pin(cursor, pin_id)
    normalized = []
    seen = set()
    for image in images:
        fields = _image_fields(image)
        stable_id = _identifier(image.get('id'))
        if stable_id in seen:
            raise GalleryError('The saved gallery contains duplicate image IDs.', 409)
        seen.add(stable_id)
        cursor.execute('SELECT pin_id FROM pin_images WHERE id = %s FOR UPDATE', (stable_id,))
        existing = _fetchone(cursor)
        if existing and existing['pin_id'] != pin_id:
            raise GalleryError('A saved image ID belongs to another pin.', 409)
        normalized.append((int(image['position']), stable_id, fields))
    normalized.sort(key=lambda item: item[0])
    cursor.execute('DELETE FROM pin_images WHERE pin_id = %s', (pin_id,))
    for position, (_, stable_id, fields) in enumerate(normalized):
        _insert_image(cursor, pin_id, fields, position, stable_id)
    _project_cover(cursor, pin)


def save_upload(file, storage_root, max_bytes=MAX_UPLOAD_BYTES, max_pixels=MAX_UPLOAD_PIXELS):
    """Decode a raster image, normalize orientation, and retain its full size.

    ``storage_root`` is the gallery directory inside the persistent cache volume.
    Caller filenames and MIME labels are never used for validation or paths.
    """
    stream = getattr(file, 'stream', file)
    data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise GalleryError(f'Image exceeds the {max_bytes // (1024 * 1024)} MiB upload limit.', 413)
    if not data:
        raise GalleryError('Choose a non-empty image file.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as decoded:
                if decoded.format not in ('JPEG', 'PNG', 'GIF', 'WEBP', 'BMP', 'TIFF'):
                    raise GalleryError('Choose a supported raster image (JPEG, PNG, WebP, GIF, BMP or TIFF).')
                if decoded.width * decoded.height > max_pixels:
                    raise GalleryError(f'Image exceeds the {max_pixels:,} pixel limit.', 413)
                decoded.verify()
            with Image.open(io.BytesIO(data)) as decoded:
                decoded.load()
                original = ImageOps.exif_transpose(decoded)
                original = original.convert('RGBA' if 'A' in original.getbands() or 'transparency' in original.info else 'RGB')
    except GalleryError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise GalleryError('Image exceeds the decoded image size limit.', 413) from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise GalleryError('This file could not be decoded as a valid image.') from exc

    storage_root = Path(storage_root)
    token = uuid.uuid4().hex
    original_name, preview_name = token + '.png', token + '-preview.webp'
    original_path, preview_path = storage_root / original_name, storage_root / preview_name
    try:
        storage_root.mkdir(parents=True, exist_ok=True)
        original.save(original_path, format='PNG')
        preview = original.copy()
        preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        preview.save(preview_path, format='WEBP', quality=85)
    except OSError as exc:
        original_path.unlink(missing_ok=True)
        preview_path.unlink(missing_ok=True)
        raise GalleryError('The image could not be stored. Please try again.', 500) from exc
    return {
        'image_url': '/cached/gallery/' + original_name,
        'preview_url': '/cached/gallery/' + preview_name,
        'width': original.width, 'height': original.height,
        'cached_image_id': None, 'uses_cached_image': False,
    }
