#!/bin/bash

# Wait for MariaDB to be ready
until docker exec scrapbook-db-1 mariadb -u db -p"${DB_PASSWORD}" -e "SELECT 1" >/dev/null 2>&1; do
    echo "Waiting for MariaDB to be ready..."
    sleep 2
done

# Initialize the database
echo "Initializing database..."
docker exec -i scrapbook-db-1 mariadb -u db -p"${DB_PASSWORD}" db < init.sql

echo "Database initialized!" 