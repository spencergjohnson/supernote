#!/usr/bin/env bash
#
# reset-local.sh — Safely wipe all server-side Supernote data so the next
# device sync performs a clean full re-upload (init mode).
#
# What it deletes (inside DATA_DIR):
#   system/supernote.db      – SQLite database (files, users, KV store)
#   supernote-user-data/     – uploaded note/document blobs
#   supernote-cache/         – derived PNG/PDF caches
#
# What it KEEPS:
#   config/.jwt_secret       – persistent JWT secret so device logins survive
#
# Usage:
#   ./reset-local.sh           # prompts for confirmation, backs up first
#   ./reset-local.sh -y        # skip confirmation prompt
#   ./reset-local.sh --no-backup   # skip backup (faster, irreversible)
#   ./reset-local.sh -y --no-backup
#
# Override the data directory or container name with env vars, e.g.:
#   DATA_DIR=/mnt/nas/supernote CONTAINER_NAME=sn ./reset-local.sh
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (override via env vars)
# ---------------------------------------------------------------------------
DATA_DIR="${DATA_DIR:-$(pwd)/data}"
CONTAINER_NAME="${CONTAINER_NAME:-supernote-server}"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
YES=0
BACKUP=1
for arg in "$@"; do
  case "$arg" in
    -y|--yes)      YES=1 ;;
    --no-backup)   BACKUP=0 ;;
    -h|--help)
      sed -n '2,/^set /p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      printf '[error] Unknown argument: %s\n' "$arg" >&2
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

hr() { printf '%0.s-' {1..72}; printf '\n'; }

# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------
[ -d "$DATA_DIR" ] || die "DATA_DIR '$DATA_DIR' does not exist. Nothing to reset."

# Items we will delete (only if they exist).
DB_FILE="$DATA_DIR/system/supernote.db"
USER_DATA_DIR="$DATA_DIR/supernote-user-data"
CACHE_DIR="$DATA_DIR/supernote-cache"

# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------
hr
printf '\033[1;31mWARNING: DESTRUCTIVE OPERATION\033[0m\n'
hr
printf 'This will permanently delete:\n'
printf '  %s\n' "$DB_FILE"
printf '  %s/\n' "$USER_DATA_DIR"
printf '  %s/\n' "$CACHE_DIR"
printf '\n'
printf 'The sync_initialized marker in the DB will also be cleared,\n'
printf 'so the NEXT device sync will be a full re-upload (safe init mode).\n'
printf 'The device is treated as the source of truth – its files will NOT\n'
printf 'be deleted by this reset.\n'
printf '\n'
printf 'The following is preserved:\n'
printf '  %s  (device logins survive)\n' "$DATA_DIR/config/.jwt_secret"
hr

if [ "$YES" -eq 0 ]; then
  printf 'Type "reset" to confirm: '
  read -r confirm
  if [ "$confirm" != "reset" ]; then
    printf 'Aborted.\n'
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Optional backup
# ---------------------------------------------------------------------------
if [ "$BACKUP" -eq 1 ]; then
  BACKUP_DIR="$DATA_DIR/backups"
  mkdir -p "$BACKUP_DIR"
  TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
  BACKUP_FILE="$BACKUP_DIR/supernote-${TIMESTAMP}.tgz"
  log "Backing up to $BACKUP_FILE ..."

  # Build the list of items to archive (only existing ones).
  ITEMS_TO_BACKUP=()
  [ -f "$DB_FILE" ]       && ITEMS_TO_BACKUP+=("system/supernote.db")
  [ -d "$USER_DATA_DIR" ] && ITEMS_TO_BACKUP+=("supernote-user-data")
  [ -d "$CACHE_DIR" ]     && ITEMS_TO_BACKUP+=("supernote-cache")

  if [ "${#ITEMS_TO_BACKUP[@]}" -gt 0 ]; then
    tar -czf "$BACKUP_FILE" -C "$DATA_DIR" "${ITEMS_TO_BACKUP[@]}" \
      && log "Backup written to $BACKUP_FILE" \
      || warn "Backup failed – continuing anyway (use --no-backup to skip)."
  else
    log "Nothing to back up (data directories are already empty)."
  fi
fi

# ---------------------------------------------------------------------------
# Stop container
# ---------------------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    log "Stopping and removing container '$CONTAINER_NAME' ..."
    docker rm -f "$CONTAINER_NAME" >/dev/null
  else
    log "Container '$CONTAINER_NAME' is not running – skipping docker rm."
  fi
else
  warn "docker not found – skipping container removal."
fi

# ---------------------------------------------------------------------------
# Delete data
# ---------------------------------------------------------------------------
log "Deleting database ..."
rm -f "$DB_FILE"

log "Deleting user data ..."
rm -rf "$USER_DATA_DIR"

log "Deleting cache ..."
rm -rf "$CACHE_DIR"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
hr
printf '\033[1;32mReset complete.\033[0m\n'
hr
printf '\nNext steps:\n'
printf '\n'
printf '  1. Start the server:\n'
printf '       ./run-local.sh\n'
printf '\n'
printf '  2. Trigger a sync on your Supernote device.\n'
printf '     The server will respond with synType=false (init mode) until\n'
printf '     the device completes its first full upload.  The device is\n'
printf '     the source of truth – its files will be uploaded, NOT deleted.\n'
printf '\n'
if [ "$BACKUP" -eq 1 ] && [ -f "${BACKUP_FILE:-}" ]; then
  printf '  To restore from backup:\n'
  printf '       tar -xzf %s -C %s\n' "$BACKUP_FILE" "$DATA_DIR"
  printf '\n'
fi
