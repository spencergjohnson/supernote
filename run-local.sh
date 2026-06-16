#!/usr/bin/env bash
#
# run-local.sh — Build and run the Supernote Knowledge Hub in Docker using
# LOCAL AI mode (your own OpenAI-compatible inference server instead of Gemini),
# accessible on your LAN. Prints web UI + device connection instructions.
#
# Usage:
#   ./run-local.sh
#
# Override any of these via environment variables, e.g.:
#   LLM_URL=http://host.docker.internal:8090 LLM_MODEL=qwen2.5-vl-7b ./run-local.sh
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (override via env vars)
# ---------------------------------------------------------------------------
IMAGE_NAME="${IMAGE_NAME:-supernote}"
CONTAINER_NAME="${CONTAINER_NAME:-supernote-server}"

PORT="${PORT:-9991}"          # main web UI / sync API (host port; container is 8080)
MCP_PORT="${MCP_PORT:-8081}"  # MCP server (for AI agents)

# Host directory bind-mounted to /data inside the container (DB + config + files).
DATA_DIR="${DATA_DIR:-$(pwd)/data}"

# Local inference server (OpenAI-compatible). From inside the container the host
# is reachable as host.docker.internal (mapped to host-gateway below).
# Defaults assume llama-swap on the host (:8080). This is the host's port and does
# NOT clash with the container's own internal 8080 (host.docker.internal resolves
# to the host gateway, not the container). For Ollama use :11434, etc.
LLM_URL="${LLM_URL:-http://host.docker.internal:8080}"
LLM_MODEL="${LLM_MODEL:-qwen2.5-vl-7b}"        # MUST be vision-capable (OCR)
EMBEDDING_MODEL="${EMBEDDING_MODEL:-nomic-embed-text}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker is not installed or not on PATH."

# Detect the host's primary LAN IP (the address your Supernote should connect to).
detect_lan_ip() {
  local ip=""
  if command -v ip >/dev/null 2>&1; then
    ip="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
  fi
  if [ -z "$ip" ] && command -v hostname >/dev/null 2>&1; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  printf '%s' "${ip:-127.0.0.1}"
}
LAN_IP="${LAN_IP:-$(detect_lan_ip)}"

# ---------------------------------------------------------------------------
# Persistent JWT secret (so device logins survive container restarts)
# ---------------------------------------------------------------------------
mkdir -p "$DATA_DIR/config"
SECRET_FILE="$DATA_DIR/config/.jwt_secret"
if [ ! -f "$SECRET_FILE" ]; then
  log "Generating persistent JWT secret at $SECRET_FILE"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32 > "$SECRET_FILE"
  else
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$SECRET_FILE"
  fi
  chmod 600 "$SECRET_FILE"
fi
JWT_SECRET="$(cat "$SECRET_FILE")"

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
log "Building image '$IMAGE_NAME' ..."
docker build -t "$IMAGE_NAME" .

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  log "Removing existing container '$CONTAINER_NAME' ..."
  docker rm -f "$CONTAINER_NAME" >/dev/null
fi

log "Starting container '$CONTAINER_NAME' in LOCAL AI mode ..."
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --add-host=host.docker.internal:host-gateway \
  -p "${PORT}:8080" \
  -p "${MCP_PORT}:8081" \
  -v "${DATA_DIR}:/data" \
  -e SUPERNOTE_JWT_SECRET="$JWT_SECRET" \
  -e SUPERNOTE_BASE_URL="http://${LAN_IP}:${PORT}" \
  -e SUPERNOTE_MCP_BASE_URL="http://${LAN_IP}:${MCP_PORT}" \
  -e SUPERNOTE_LOCAL_MODE=true \
  -e SUPERNOTE_LOCAL_LLM_URL="$LLM_URL" \
  -e SUPERNOTE_LOCAL_LLM_MODEL="$LLM_MODEL" \
  -e SUPERNOTE_LOCAL_EMBEDDING_MODEL="$EMBEDDING_MODEL" \
  "$IMAGE_NAME" >/dev/null

# Give it a moment, then confirm it stayed up.
sleep 2
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  warn "Container is not running. Recent logs:"
  docker logs --tail 40 "$CONTAINER_NAME" || true
  die "Startup failed. See logs above."
fi

# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------
cat <<EOF

$(printf '\033[1;32m')Supernote Knowledge Hub is running (LOCAL AI mode).$(printf '\033[0m')

  Container : $CONTAINER_NAME
  Data dir  : $DATA_DIR        (DB, config, and synced files live here)
  Local LLM : $LLM_URL  (chat: $LLM_MODEL, embeddings: $EMBEDDING_MODEL)
  Logs      : docker logs -f $CONTAINER_NAME

--------------------------------------------------------------------------
1) Open the Web UI
--------------------------------------------------------------------------
  On this machine : http://localhost:${PORT}
  From your LAN   : http://${LAN_IP}:${PORT}
  MCP (AI agents) : http://${LAN_IP}:${MCP_PORT}/mcp

--------------------------------------------------------------------------
2) Create your admin account (first user becomes admin)
--------------------------------------------------------------------------
  Run this once, then enter a password when prompted. The command runs INSIDE
  the container, so it targets the container's own port 8080 (this is correct
  and unrelated to the host port ${PORT} you use from a browser/device):

    docker exec -it $CONTAINER_NAME \\
      supernote admin user add you@example.com --url http://localhost:8080

--------------------------------------------------------------------------
3) Connect your Supernote device
--------------------------------------------------------------------------
  Make sure the device is on the same Wi-Fi/LAN as this machine, then:
    a. Settings > Sync > Private Cloud (custom server)
    b. Server address : http://${LAN_IP}:${PORT}
    c. Log in with the email + password from step 2
    d. Tap Sync, then choose folders to sync under
       Settings > Drive > Private Cloud (e.g. Note, Document, EXPORT)

--------------------------------------------------------------------------
Notes
--------------------------------------------------------------------------
  * LOCAL AI mode is on: OCR, summaries, and search use your own inference
    server at $LLM_URL (no Gemini, no API key).
  * The chat model MUST be vision-capable for OCR (e.g. llava, qwen2.5-vl).
  * If the host firewall blocks it, allow inbound TCP ${PORT} (and ${MCP_PORT}).
  * To point at a different inference server, re-run with e.g. (Ollama):
      LLM_URL=http://host.docker.internal:11434 LLM_MODEL=llava ./run-local.sh

EOF
