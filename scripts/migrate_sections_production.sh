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

# Step 1: Apply section assignments from Pinterest data
echo "Step 1: Restoring Pinterest section assignments..."
mysql -udb -p$DB_PASSWORD db < scripts/section_assignments.sql

echo "✅ Section assignments restored"
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

