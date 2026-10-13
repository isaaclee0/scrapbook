"""Find image files that cache maintenance must preserve.

Gallery originals live in their own durable subdirectory. Legacy uploads and
cached files can also be the only remaining copy of a live or undoable image.
"""

import json


def _rows(cursor):
    names = [column[0] for column in cursor.description]
    return [row if isinstance(row, dict) else dict(zip(names, row))
            for row in cursor.fetchall()]


def retained_cache_filenames(cursor):
    """Return relative cache filenames referenced by content or retained audits.

    Audit retention is enforced by audit_cleanup; every snapshot still present
    here must remain restorable. Query failures intentionally abort cleanup.
    """
    filenames, cache_ids = set(), set()

    def collect(value):
        if isinstance(value, dict):
            cache_id = value.get('cached_image_id')
            if isinstance(cache_id, int) and not isinstance(cache_id, bool):
                cache_ids.add(cache_id)
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)
        elif isinstance(value, str):
            for prefix in ('/cached/', '/static/cached_images/'):
                if value.startswith(prefix):
                    filenames.add(value[len(prefix):])
                    break

    for query in (
        'SELECT image_url, preview_url, cached_image_id FROM pin_images',
        "SELECT image_url, cached_image_id FROM pins WHERE image_url LIKE '/cached/%' OR image_url LIKE '/static/cached_images/%'",
        'SELECT default_image_url FROM boards',
        'SELECT default_image_url FROM sections',
    ):
        cursor.execute(query)
        collect(_rows(cursor))

    cursor.execute('SELECT before_data, after_data FROM audit_log')
    for row in _rows(cursor):
        for document in row.values():
            if isinstance(document, (str, bytes, bytearray)):
                try:
                    document = json.loads(document)
                except (ValueError, UnicodeDecodeError):
                    continue
            collect(document)

    # Iteration avoids adapter-specific placeholder syntax and also includes
    # direct URL references whose cache metadata has since expired.
    if cache_ids:
        cursor.execute('SELECT id, cached_filename FROM cached_images')
        for row in _rows(cursor):
            if row['id'] in cache_ids and row['cached_filename']:
                filenames.add(row['cached_filename'])
    return filenames
