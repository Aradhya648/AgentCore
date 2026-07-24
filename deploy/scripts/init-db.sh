#!/bin/bash
set -e

echo "Waiting for PostgreSQL to be ready..."
until pg_isready -h localhost -U agentcore; do
  sleep 1
done

echo "Creating agentcore database (if not exists)..."
psql -h localhost -U agentcore -tc "SELECT 1 FROM pg_database WHERE datname = 'agentcore'" | grep -q 1 || \
  psql -h localhost -U agentcore -c "CREATE DATABASE agentcore"

echo "Enabling pgvector extension..."
psql -h localhost -U agentcore -d agentcore -c "CREATE EXTENSION IF NOT EXISTS vector"

echo "Database initialization complete."
