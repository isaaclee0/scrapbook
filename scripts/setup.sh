#!/bin/bash

# Wait for MariaDB to be ready
echo "Waiting for MariaDB to be ready..."
until docker exec scrapbook-db-1 mariadb -u db -p"${DB_PASSWORD}" -e "SELECT 1" >/dev/null 2>&1; do
    sleep 2
done

# Initialize the database
echo "Initializing database..."
docker exec -i scrapbook-db-1 mariadb -u db -p"${DB_PASSWORD}" db < scripts/init.sql

# Wait for the web container to be ready
echo "Waiting for web container to be ready..."
until docker exec scrapbook-web-1 python3 -c "import mysql.connector; mysql.connector.connect(host='db', user='db', password='\${DB_PASSWORD}', database='db')" >/dev/null 2>&1; do
    sleep 2
done

# Import data from pins.zip
echo "Importing data from pins.zip..."
docker exec -it scrapbook-web-1 python3 scripts/add_missing_boards.py

echo "Setup complete!" 