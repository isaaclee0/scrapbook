#!/usr/bin/env python3

import mysql.connector
import os
import sys
import json
from datetime import datetime

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

class DatabaseVersionManager:
    def __init__(self):
        self.upgrades = [
            {
                'version': '1.0.0',
                'name': 'Initial Schema',
                'description': 'Base tables for boards, sections, pins, and URL health',
                'applied': True  # Assume base schema is already applied
            },
            {
                'version': '1.1.0',
                'name': 'Pin Colors',
                'description': 'Add dominant color columns for pin color extraction',
                'script': 'add_pin_colors_schema.py',
                'applied': False
            },
            {
                'version': '1.2.0',
                'name': 'Cached Images',
                'description': 'Add cached images table for storing low-quality image copies',
                'script': 'add_cached_images_schema.py',
                'applied': False
            }
        ]
    
    def ensure_version_table(self):
        """Create the database version tracking table if it doesn't exist"""
        try:
            db = get_db_connection()
            cursor = db.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS db_versions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    version VARCHAR(50) NOT NULL UNIQUE,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_db_versions_version (version)
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """)
            
            # Insert initial version if table was just created
            cursor.execute("SELECT COUNT(*) FROM db_versions")
            count = cursor.fetchone()[0]
            
            if count == 0:
                cursor.execute("""
                    INSERT INTO db_versions (version, name, description) 
                    VALUES ('1.0.0', 'Initial Schema', 'Base tables for boards, sections, pins, and URL health')
                """)
            
            db.commit()
            return True
            
        except Exception as e:
            print(f"Error creating version table: {e}")
            return False
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'db' in locals():
                db.close()
    
    def get_applied_versions(self):
        """Get list of applied database versions"""
        try:
            if not self.ensure_version_table():
                return []
            
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            
            cursor.execute("SELECT version FROM db_versions ORDER BY applied_at")
            applied = [row['version'] for row in cursor.fetchall()]
            
            return applied
            
        except Exception as e:
            print(f"Error getting applied versions: {e}")
            return []
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'db' in locals():
                db.close()
    
    def get_pending_upgrades(self):
        """Get list of pending database upgrades"""
        applied_versions = self.get_applied_versions()
        
        pending = []
        for upgrade in self.upgrades:
            if upgrade['version'] not in applied_versions:
                pending.append(upgrade)
        
        return pending
    
    def check_column_exists(self, table, column):
        """Check if a column exists in a table"""
        try:
            db = get_db_connection()
            cursor = db.cursor()
            
            cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = %s 
                AND COLUMN_NAME = %s
            """, (table, column))
            
            return cursor.fetchone()[0] > 0
            
        except Exception as e:
            print(f"Error checking column existence: {e}")
            return False
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'db' in locals():
                db.close()
    
    def check_table_exists(self, table):
        """Check if a table exists"""
        try:
            db = get_db_connection()
            cursor = db.cursor()
            
            cursor.execute("SHOW TABLES LIKE %s", (table,))
            return cursor.fetchone() is not None
            
        except Exception as e:
            print(f"Error checking table existence: {e}")
            return False
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'db' in locals():
                db.close()
    
    def detect_applied_upgrades(self):
        """Detect which upgrades have already been applied based on schema"""
        applied = []
        
        # Check for pin colors upgrade
        if (self.check_column_exists('pins', 'dominant_color_1') and 
            self.check_column_exists('pins', 'dominant_color_2') and 
            self.check_column_exists('pins', 'colors_extracted')):
            applied.append('1.1.0')
        
        # Check for cached images upgrade
        if (self.check_table_exists('cached_images') and 
            self.check_column_exists('pins', 'cached_image_id') and 
            self.check_column_exists('pins', 'uses_cached_image')):
            applied.append('1.2.0')
        
        return applied
    
    def sync_versions(self):
        """Sync the version table with detected applied upgrades"""
        try:
            if not self.ensure_version_table():
                return False
            
            detected_versions = self.detect_applied_upgrades()
            applied_versions = self.get_applied_versions()
            
            db = get_db_connection()
            cursor = db.cursor()
            
            # Add detected versions that aren't in the version table
            for version in detected_versions:
                if version not in applied_versions:
                    upgrade = next((u for u in self.upgrades if u['version'] == version), None)
                    if upgrade:
                        cursor.execute("""
                            INSERT INTO db_versions (version, name, description) 
                            VALUES (%s, %s, %s)
                        """, (version, upgrade['name'], upgrade['description']))
                        print(f"✅ Synced version {version}: {upgrade['name']}")
            
            db.commit()
            return True
            
        except Exception as e:
            print(f"Error syncing versions: {e}")
            return False
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'db' in locals():
                db.close()
    
    def apply_upgrade(self, version):
        """Apply a specific database upgrade"""
        upgrade = next((u for u in self.upgrades if u['version'] == version), None)
        if not upgrade:
            return {'success': False, 'error': f'Upgrade {version} not found'}
        
        if not upgrade.get('script'):
            return {'success': False, 'error': f'No script defined for upgrade {version}'}
        
        try:
            # Import and run the upgrade script
            script_path = f"scripts.{upgrade['script'].replace('.py', '')}"
            
            if upgrade['script'] == 'add_pin_colors_schema.py':
                from scripts.add_pin_colors_schema import add_color_columns
                success = add_color_columns()
            elif upgrade['script'] == 'add_cached_images_schema.py':
                from scripts.add_cached_images_schema import add_cached_images_table
                success = add_cached_images_table()
            else:
                return {'success': False, 'error': f'Unknown upgrade script: {upgrade["script"]}'}
            
            if success:
                # Mark as applied in version table
                db = get_db_connection()
                cursor = db.cursor()
                
                cursor.execute("""
                    INSERT INTO db_versions (version, name, description) 
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE applied_at = CURRENT_TIMESTAMP
                """, (version, upgrade['name'], upgrade['description']))
                
                db.commit()
                
                return {
                    'success': True, 
                    'message': f'Successfully applied upgrade {version}: {upgrade["name"]}'
                }
            else:
                return {'success': False, 'error': f'Failed to apply upgrade {version}'}
                
        except Exception as e:
            return {'success': False, 'error': f'Error applying upgrade {version}: {str(e)}'}
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'db' in locals():
                db.close()
    
    def get_upgrade_status(self):
        """Get comprehensive upgrade status"""
        try:
            self.sync_versions()
            applied_versions = self.get_applied_versions()
            pending_upgrades = self.get_pending_upgrades()
            
            return {
                'applied_versions': applied_versions,
                'pending_upgrades': pending_upgrades,
                'needs_upgrade': len(pending_upgrades) > 0,
                'current_version': applied_versions[-1] if applied_versions else '0.0.0'
            }
            
        except Exception as e:
            return {
                'error': str(e),
                'needs_upgrade': False,
                'current_version': 'unknown'
            }

def main():
    """Main function for command line usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Database Version Manager')
    parser.add_argument('--status', action='store_true', help='Show upgrade status')
    parser.add_argument('--sync', action='store_true', help='Sync version table with detected schema')
    parser.add_argument('--apply', help='Apply specific upgrade version')
    
    args = parser.parse_args()
    
    manager = DatabaseVersionManager()
    
    if args.status:
        status = manager.get_upgrade_status()
        print(json.dumps(status, indent=2))
    elif args.sync:
        success = manager.sync_versions()
        print("✅ Version sync completed" if success else "❌ Version sync failed")
    elif args.apply:
        result = manager.apply_upgrade(args.apply)
        if result['success']:
            print(f"✅ {result['message']}")
        else:
            print(f"❌ {result['error']}")
    else:
        print("Use --status, --sync, or --apply <version>")

if __name__ == "__main__":
    main() 