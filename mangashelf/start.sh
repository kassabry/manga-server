#!/bin/sh
# MangaShelf startup script
# Runs as root to fix permissions and apply migrations, then drops to nextjs

DB_PATH="/app/data/mangashelf.db"

# Fix permissions on mounted volumes
chown -R nextjs:nodejs /app/data /app/public/covers 2>/dev/null || true

echo "Ensuring database schema..."

# Apply full schema (all CREATE TABLE IF NOT EXISTS — safe on existing DB)
if [ -f /app/prisma/init.sql ]; then
  sqlite3 "$DB_PATH" < /app/prisma/init.sql 2>/dev/null
  if [ $? -eq 0 ]; then
    echo "Schema applied successfully"
  else
    echo "Warning: some schema statements failed (likely already exist — this is normal)"
  fi
else
  echo "ERROR: /app/prisma/init.sql not found!"
fi

# Add columns that may be missing from older databases
sqlite3 "$DB_PATH" "ALTER TABLE \"Series\" ADD COLUMN \"lastChapterAt\" DATETIME;" 2>/dev/null || true
sqlite3 "$DB_PATH" "ALTER TABLE \"Chapter\" ADD COLUMN \"source\" TEXT;" 2>/dev/null || true
sqlite3 "$DB_PATH" "ALTER TABLE \"Chapter\" ADD COLUMN \"sourceUrl\" TEXT;" 2>/dev/null || true

# Ensure DB is writable by nextjs
chown nextjs:nodejs "$DB_PATH" 2>/dev/null || true

echo "Database ready"

# Drop privileges and start server
exec su-exec nextjs node server.js
