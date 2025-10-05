-- Scrapbook Database Initialization Script v1.5.0
-- This script creates all necessary tables and indexes for the scrapbook application
-- Compatible with Scrapbook v1.5.0+

CREATE DATABASE IF NOT EXISTS db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE db;

-- Users table (for authentication and multi-tenancy)
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP NULL,
    is_active BOOLEAN DEFAULT TRUE,
    INDEX idx_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert default user for initial setup
-- Change this email to your production user email if needed
INSERT IGNORE INTO users (email, created_at) VALUES ('shelley@leemail.com.au', NOW());

-- Boards table
CREATE TABLE IF NOT EXISTS boards (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_boards_user_id (user_id),
    INDEX idx_boards_name (name),
    INDEX idx_boards_slug (slug),
    INDEX idx_boards_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Sections table
CREATE TABLE IF NOT EXISTS sections (
    id INT AUTO_INCREMENT PRIMARY KEY,
    board_id INT NOT NULL,
    user_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_sections_board_id (board_id),
    INDEX idx_sections_user_id (user_id),
    INDEX idx_sections_name (name),
    INDEX idx_sections_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Pins table
CREATE TABLE IF NOT EXISTS pins (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    board_id INT NOT NULL,
    section_id INT,
    pin_id VARCHAR(300),
    link TEXT,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    notes TEXT,
    image_url TEXT NOT NULL,
    cached_image_id INT DEFAULT NULL,
    uses_cached_image BOOLEAN DEFAULT FALSE,
    dominant_color VARCHAR(7) DEFAULT NULL,
    palette_color_1 VARCHAR(7) DEFAULT NULL,
    palette_color_2 VARCHAR(7) DEFAULT NULL,
    palette_color_3 VARCHAR(7) DEFAULT NULL,
    palette_color_4 VARCHAR(7) DEFAULT NULL,
    palette_color_5 VARCHAR(7) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE,
    FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE SET NULL,
    INDEX idx_pins_user_id (user_id),
    INDEX idx_pins_board_id (board_id),
    INDEX idx_pins_section_id (section_id),
    INDEX idx_pins_created_at (created_at),
    INDEX idx_pins_updated_at (updated_at),
    INDEX idx_pins_title (title(100))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Cached images table (for image optimization)
CREATE TABLE IF NOT EXISTS cached_images (
    id INT AUTO_INCREMENT PRIMARY KEY,
    original_url VARCHAR(2048) NOT NULL,
    cached_filename VARCHAR(255) NOT NULL,
    file_size INT DEFAULT 0,
    width INT DEFAULT 0,
    height INT DEFAULT 0,
    quality_level ENUM('thumbnail', 'low', 'medium') DEFAULT 'low',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    cache_status ENUM('pending', 'cached', 'failed', 'expired') DEFAULT 'pending',
    retry_count INT DEFAULT 0,
    last_retry_at TIMESTAMP NULL,
    UNIQUE KEY unique_url_quality (original_url(500), quality_level),
    INDEX idx_cached_images_original_url (original_url(500)),
    INDEX idx_cached_images_status (cache_status),
    INDEX idx_cached_images_created_at (created_at),
    INDEX idx_cached_images_retry (retry_count, last_retry_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- URL Health tracking table
CREATE TABLE IF NOT EXISTS url_health (
    id INT AUTO_INCREMENT PRIMARY KEY,
    pin_id INT NOT NULL,
    url VARCHAR(2048) NOT NULL,
    last_checked DATETIME,
    status ENUM('unknown', 'live', 'broken', 'archived') DEFAULT 'unknown',
    archive_url VARCHAR(2048),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (pin_id) REFERENCES pins(id) ON DELETE CASCADE,
    INDEX idx_url_health_pin_id (pin_id),
    INDEX idx_url_health_status (status),
    INDEX idx_url_health_last_checked (last_checked)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert some default data if tables are empty (for demo/development)
-- Note: These will be owned by the default user
SET @default_user_id = (SELECT id FROM users WHERE email = 'shelley@leemail.com.au' LIMIT 1);

INSERT IGNORE INTO boards (user_id, name, slug) VALUES 
(@default_user_id, 'My First Board', 'my-first-board'),
(@default_user_id, 'Inspiration', 'inspiration'),
(@default_user_id, 'To Do', 'to-do');

-- Create sections for the default boards
INSERT IGNORE INTO sections (board_id, user_id, name) 
SELECT b.id, @default_user_id, 'General' 
FROM boards b 
WHERE b.name = 'My First Board' 
AND NOT EXISTS (SELECT 1 FROM sections s WHERE s.board_id = b.id AND s.name = 'General');

INSERT IGNORE INTO sections (board_id, user_id, name) 
SELECT b.id, @default_user_id, 'Ideas' 
FROM boards b 
WHERE b.name = 'Inspiration' 
AND NOT EXISTS (SELECT 1 FROM sections s WHERE s.board_id = b.id AND s.name = 'Ideas');

INSERT IGNORE INTO sections (board_id, user_id, name) 
SELECT b.id, @default_user_id, 'Tasks' 
FROM boards b 
WHERE b.name = 'To Do' 
AND NOT EXISTS (SELECT 1 FROM sections s WHERE s.board_id = b.id AND s.name = 'Tasks'); 