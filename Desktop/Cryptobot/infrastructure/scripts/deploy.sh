#!/bin/bash
set -e

echo "Deploying TBX Trade Terminal..."

docker compose -f infrastructure/docker-compose.yml build backend
docker compose -f infrastructure/docker-compose.yml up -d postgres redis
sleep 5
docker compose -f infrastructure/docker-compose.yml run --rm backend bash /app/scripts/init_db.sh
docker compose -f infrastructure/docker-compose.yml up -d backend

echo "Deploy complete."
