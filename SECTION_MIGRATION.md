# Section Features Migration Guide

This guide covers the new section features added in v1.5.8+

## What's New

1. **Circular Section Thumbnails** - Beautiful circular UI for sections at the top of boards
2. **Section Cover Images** - Each section displays a representative image
3. **Set Section Cover** - Ability to customize which image represents each section
4. **Restored Pinterest Sections** - 4,222 pins reassigned to their original Pinterest sections

## For Production Deployment

### Prerequisites
- Scrapbook v1.5.8 or higher deployed (contains schema changes and new UI)
- Access to production Docker container

### Migration Command

After deploying the new v1.5.8 Docker image, run:

```bash
docker-compose exec web bash scripts/migrate_sections_production.sh
```

This will:
1. Assign 4,222 pins to their correct sections based on original Pinterest data

### What the Migration Does

- **Restores assignments**: Updates 4,222 pins with their Pinterest section assignments
- **Note**: Schema changes (`default_image_url` column) are already in v1.5.8 Docker image
- **Note**: Section cover images will auto-populate from assigned pins

### Expected Results

After migration:
- ✅ 321 sections will have cover images
- ✅ 4,222 pins will be organized into sections (~2.9% of all pins)
- ✅ Circular section UI will be fully functional
- ✅ Users can customize section covers via "Set as Section Cover" in pin menu

### File Sizes

- `section_assignments.sql`: 981 KB
- Total migration time: ~30-60 seconds

### Rollback

If needed, to remove section assignments:

```sql
UPDATE pins SET section_id = NULL WHERE section_id IS NOT NULL;
ALTER TABLE sections DROP COLUMN default_image_url;
```

## Notes

- The original Pinterest export had only ~2.9% of pins in sections
- This is normal - most Pinterest pins are not organized into board sections
- The 4,222 pins represent the complete section data from the original export
- New pins can be manually assigned to sections via the web UI

