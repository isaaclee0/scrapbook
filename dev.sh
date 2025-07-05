#!/bin/bash

# Build the Docker image
echo "Building Docker image..."
docker build -t scrapbookimage:latest .

# Start the containers
echo "Starting containers..."
docker-compose -f scrapbook.yml up -d

# Wait for the database to be ready
echo "Waiting for database to be ready..."
sleep 10

# Initialize the database
echo "Initializing database..."
docker-compose -f scrapbook.yml exec db mysql -u db -p'3Uy@7SGMAHVyC^Oo' db < init.sql

echo "Setup complete! The application is running at http://localhost:8001"
echo "To stop the containers, run: docker-compose -f scrapbook.yml down" 