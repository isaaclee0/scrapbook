-- Scrapbook Database Initialization Script
-- This script creates all necessary tables and indexes for the scrapbook application

CREATE DATABASE IF NOT EXISTS db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE db;

-- Boards table
CREATE TABLE IF NOT EXISTS boards (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_boards_name (name),
    INDEX idx_boards_slug (slug)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Sections table
CREATE TABLE IF NOT EXISTS sections (
    id INT AUTO_INCREMENT PRIMARY KEY,
    board_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE,
    INDEX idx_sections_board_id (board_id),
    INDEX idx_sections_name (name)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Pins table
CREATE TABLE IF NOT EXISTS pins (
    id INT AUTO_INCREMENT PRIMARY KEY,
    board_id INT NOT NULL,
    section_id INT,
    pin_id VARCHAR(300),
    link TEXT,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    notes TEXT,
    image_url TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE,
    FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE SET NULL,
    INDEX idx_pins_board_id (board_id),
    INDEX idx_pins_section_id (section_id),
    INDEX idx_pins_created_at (created_at),
    INDEX idx_pins_title (title(100))
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

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
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Create additional indexes for performance
CREATE INDEX IF NOT EXISTS idx_boards_created_at ON boards(created_at);
CREATE INDEX IF NOT EXISTS idx_sections_created_at ON sections(created_at);
CREATE INDEX IF NOT EXISTS idx_pins_updated_at ON pins(updated_at);

-- Insert some default data if tables are empty
INSERT IGNORE INTO boards (name, slug) VALUES 
('My First Board', 'my-first-board'),
('Inspiration', 'inspiration'),
('To Do', 'to-do');

-- Create sections for the default boards
INSERT IGNORE INTO sections (board_id, name) 
SELECT b.id, 'General' 
FROM boards b 
WHERE b.name = 'My First Board' 
AND NOT EXISTS (SELECT 1 FROM sections s WHERE s.board_id = b.id AND s.name = 'General');

INSERT IGNORE INTO sections (board_id, name) 
SELECT b.id, 'Ideas' 
FROM boards b 
WHERE b.name = 'Inspiration' 
AND NOT EXISTS (SELECT 1 FROM sections s WHERE s.board_id = b.id AND s.name = 'Ideas');

INSERT IGNORE INTO sections (board_id, name) 
SELECT b.id, 'Tasks' 
FROM boards b 
WHERE b.name = 'To Do' 
AND NOT EXISTS (SELECT 1 FROM sections s WHERE s.board_id = b.id AND s.name = 'Tasks'); 