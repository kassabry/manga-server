#!/usr/bin/env bash
#
# mangashelf-db-backup.sh
# Consistent, timestamped backups of the MangaShelf SQLite database.
#
#   - Uses SQLite's online ".backup" (safe with WAL + concurrent writes;
#     a plain cp of the .db can capture a torn state and miss the -wal file).
#   - Verifies integrity before keeping each backup; a bad copy is discarded.
#   - Writes backups to the SD card (a *different* physical device than the
#     4.5TB data drive), so a drive failure cannot take the backups with it.
#   - Skips safely if the data drive is not mounted, so it never backs up the
#     empty SD-card placeholder that appears when the drive detaches.
#
# Restore (see also notes at the bottom):
#   docker stop orvault
#   gunzip -c /var/backups/mangashelf/mangashelf-YYYYMMDD-HHMMSS.db.gz \
#     > /mnt/manga-storage/manga-server/mangashelf/data/mangashelf.db
#   rm -f /mnt/manga-storage/manga-server/mangashelf/data/mangashelf.db-wal \
#         /mnt/manga-storage/manga-server/mangashelf/data/mangashelf.db-shm
#   cd /mnt/manga-storage/manga-server && docker compose up -d

set -euo pipefail

DB="${MANGASHELF_DB:-/mnt/manga-storage/manga-server/mangashelf/data/mangashelf.db}"
MOUNT="${MANGASHELF_MOUNT:-/mnt/manga-storage}"
DEST="${MANGASHELF_BACKUP_DIR:-/var/backups/mangashelf}"
RETENTION_DAYS="${MANGASHELF_BACKUP_RETENTION:-14}"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') | $*"; }

# 1. Refuse to run if the data drive is not mounted. When the drive detaches,
#    an empty placeholder appears at the mountpoint; backing that up would
#    overwrite good backups with garbage over the retention window.
if ! mountpoint -q "$MOUNT"; then
  log "SKIP: $MOUNT is not mounted; not backing up a placeholder."
  exit 0
fi

if [ ! -f "$DB" ]; then
  log "SKIP: DB not found at $DB."
  exit 0
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  log "ERROR: sqlite3 not installed. Install with: sudo apt-get install -y sqlite3"
  exit 1
fi

mkdir -p "$DEST"
ts="$(date '+%Y%m%d-%H%M%S')"
tmp="$DEST/mangashelf-$ts.db"

# 2. Consistent online snapshot (handles WAL correctly).
sqlite3 "$DB" ".backup '$tmp'"

# 3. Integrity-check the backup; discard rather than keep a corrupt copy.
res="$(sqlite3 "$tmp" 'PRAGMA integrity_check;' | head -n1 || true)"
if [ "$res" != "ok" ]; then
  log "ERROR: integrity check failed for $tmp (got: '$res'). Discarding."
  rm -f "$tmp"
  exit 1
fi

# 4. Compress (SQLite dumps compress well) and report size.
gzip -f "$tmp"
log "OK: $tmp.gz ($(du -h "$tmp.gz" | cut -f1))"

# 5. Prune backups older than the retention window.
find "$DEST" -maxdepth 1 -name 'mangashelf-*.db.gz' -type f -mtime +"$RETENTION_DAYS" -print -delete \
  | while read -r f; do log "pruned $f"; done

log "done."
