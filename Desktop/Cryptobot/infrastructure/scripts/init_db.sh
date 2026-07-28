#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
until pg_isready -h postgres -U tbx -d tbx; do
    sleep 1
done

echo "Running migrations..."
alembic upgrade head

echo "Database initialized."
