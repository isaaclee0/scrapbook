-- Reassign all app content to isaac@leemail.com.au after a dump import.
-- Used by scripts/import_sqldump_docker.sh

INSERT INTO users (email, created_at)
SELECT 'isaac@leemail.com.au', NOW()
WHERE NOT EXISTS (
    SELECT 1 FROM users WHERE email = 'isaac@leemail.com.au'
);

SET @isaac_id = (SELECT id FROM users WHERE email = 'isaac@leemail.com.au' LIMIT 1);

UPDATE boards
SET user_id = @isaac_id
WHERE user_id IS NULL OR user_id != @isaac_id;

UPDATE sections
SET user_id = @isaac_id
WHERE user_id IS NULL OR user_id != @isaac_id;

UPDATE pins
SET user_id = @isaac_id
WHERE user_id IS NULL OR user_id != @isaac_id;
