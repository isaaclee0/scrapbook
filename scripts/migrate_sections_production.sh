#!/bin/bash
# Production migration script to restore Pinterest section assignments and populate section covers
# Run this AFTER deploying the new Docker image with section features (v1.5.8+)
#
# Usage: docker-compose exec web bash scripts/migrate_sections_production.sh

set -e  # Exit on error

echo "================================================================================"
echo "SECTION DATA MIGRATION FOR PRODUCTION"
echo "================================================================================"
echo ""
echo "This migration will:"
echo "  1. Assign 4,222 pins to sections (Pinterest data)"
echo "  2. Populate section cover images (from assigned pins)"
echo ""
echo "Note: The schema (default_image_url column) is already in v1.5.8 Docker image"
echo ""

# Step 1: Apply section assignments from Pinterest data using Python
echo "Step 1: Restoring Pinterest section assignments..."
python3 -c "
import mysql.connector
import os

db = mysql.connector.connect(
    host=os.getenv('DB_HOST', 'db'),
    user=os.getenv('DB_USER', 'db'),
    password=os.getenv('DB_PASSWORD', ''),
    database=os.getenv('DB_NAME', 'db'),
    charset='utf8mb4',
    collation='utf8mb4_unicode_ci'
)
cursor = db.cursor()

# Read and execute SQL file
with open('scripts/section_assignments.sql', 'r') as f:
    sql_statements = f.read().split(';')
    
count = 0
for statement in sql_statements:
    statement = statement.strip()
    if statement and not statement.startswith('--'):
        cursor.execute(statement)
        count += 1
        if count % 500 == 0:
            print(f'  Processed {count} statements...')
            db.commit()

db.commit()
print(f'✅ Applied {count} section assignments')

cursor.close()
db.close()
"

echo ""

# Step 2: Populate section cover images
echo "Step 2: Populating section cover images..."
python3 scripts/add_section_images.py

echo ""
echo "================================================================================"
echo "MIGRATION COMPLETE!"
echo "================================================================================"
echo ""
echo "✅ 4,222 pins assigned to their original Pinterest sections"
echo "✅ Section cover images populated for all sections"
echo ""
echo "The circular section UI is now fully functional!"
echo ""

