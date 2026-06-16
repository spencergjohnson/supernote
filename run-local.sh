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

# Tailscale integration. When enabled (and tailscale is installed + logged in),
# we expose the web UI over HTTPS on your tailnet via `tailscale serve`. This
# gives the browser a real cert and a *secure context*, so the native Web Crypto
# login path works (plain http:// to a LAN IP is NOT a secure context).
#   ENABLE_TAILSCALE=auto  -> use it if available (default)
#   ENABLE_TAILSCALE=1     -> require it (error out if unavailable)
#   ENABLE_TAILSCALE=0     -> skip it entirely
ENABLE_TAILSCALE="${ENABLE_TAILSCALE:-auto}"

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
# Tailscale detection
# ---------------------------------------------------------------------------
# Resolve the node's MagicDNS name (e.g. myhost.tailnet-name.ts.net) without
# requiring jq. Tries jq, then python3, then a grep/sed fallback on the JSON.
tailscale_dns_name() {
  local json name=""
  json="$(tailscale status --json 2>/dev/null)" || return 1
  [ -n "$json" ] || return 1

  # Note: `|| true` keeps a non-zero pipeline (e.g. grep finding nothing under
  # `set -o pipefail`) from aborting the whole script.
  if command -v jq >/dev/null 2>&1; then
    name="$(printf '%s' "$json" | jq -r '.Self.DNSName // empty' 2>/dev/null)" || true
  fi
  if [ -z "$name" ] && command -v python3 >/dev/null 2>&1; then
    name="$(printf '%s' "$json" | python3 -c \
      'import sys,json; print(json.load(sys.stdin).get("Self",{}).get("DNSName",""))' \
      2>/dev/null)" || true
  fi
  if [ -z "$name" ]; then
    # Fallback: first DNSName in the JSON belongs to the Self node.
    name="$(printf '%s' "$json" \
      | grep -o '"DNSName"[[:space:]]*:[[:space:]]*"[^"]*"' \
      | head -n1 | sed -E 's/.*"DNSName"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/')" || true
  fi

  name="${name%.}"   # strip trailing dot
  [ -n "$name" ] || return 1
  printf '%s' "$name"
}

# Decide whether we'll use tailscale. Sets TS_ENABLED + TS_DNS.
TS_ENABLED=0
TS_DNS=""
if [ "$ENABLE_TAILSCALE" != "0" ]; then
  if ! command -v tailscale >/dev/null 2>&1; then
    [ "$ENABLE_TAILSCALE" = "1" ] && die "ENABLE_TAILSCALE=1 but 'tailscale' is not installed."
    warn "tailscale not found on PATH; skipping HTTPS exposure (LAN HTTP still works)."
  elif ! tailscale status >/dev/null 2>&1; then
    [ "$ENABLE_TAILSCALE" = "1" ] && die "ENABLE_TAILSCALE=1 but tailscale is not running/logged in. Run 'tailscale up' first."
    warn "tailscale is installed but not running/logged in; skipping HTTPS exposure. Run 'tailscale up' to enable it."
  elif ! TS_DNS="$(tailscale_dns_name)"; then
    [ "$ENABLE_TAILSCALE" = "1" ] && die "ENABLE_TAILSCALE=1 but could not resolve the tailnet DNS name."
    warn "Could not resolve tailnet DNS name; skipping HTTPS exposure."
  else
    TS_ENABLED=1
  fi
fi

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

# NOTE: SUPERNOTE_BASE_URL / SUPERNOTE_MCP_BASE_URL are the MCP OAuth issuer URLs.
# The MCP SDK rejects any non-HTTPS issuer unless the host is localhost/127.0.0.1,
# so we keep these on localhost. They are NOT used for device sync or the web UI
# (those use the LAN address you connect to directly), so LAN access is unaffected.
# Exposing MCP to remote agents over the LAN would require terminating HTTPS via a
# reverse proxy and pointing these at that https:// URL.

# When fronted by `tailscale serve` (a TLS-terminating reverse proxy), tell the
# app to honor X-Forwarded-Proto/Host so the absolute upload URLs it generates
# come out as https://<node>.ts.net/... instead of http://... (which a browser
# on an https page would block as mixed content). tailscale serve hardcodes
# these forwarded headers, so 'relaxed' is safe here. Direct LAN/localhost
# requests send no such headers, so they are unaffected.
PROXY_ENV_ARGS=()
if [ "$TS_ENABLED" = "1" ]; then
  PROXY_ENV_ARGS=(-e SUPERNOTE_PROXY_MODE=relaxed)
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
  -e SUPERNOTE_BASE_URL="http://localhost:${PORT}" \
  -e SUPERNOTE_MCP_BASE_URL="http://localhost:${MCP_PORT}" \
  -e SUPERNOTE_LOCAL_MODE=true \
  -e SUPERNOTE_LOCAL_LLM_URL="$LLM_URL" \
  -e SUPERNOTE_LOCAL_LLM_MODEL="$LLM_MODEL" \
  -e SUPERNOTE_LOCAL_EMBEDDING_MODEL="$EMBEDDING_MODEL" \
  "${PROXY_ENV_ARGS[@]}" \
  "$IMAGE_NAME" >/dev/null

# Give it a moment, then confirm it stayed up.
sleep 2
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  warn "Container is not running. Recent logs:"
  docker logs --tail 40 "$CONTAINER_NAME" || true
  die "Startup failed. See logs above."
fi

# ---------------------------------------------------------------------------
# Expose the web UI over HTTPS on the tailnet (secure context for the browser)
# ---------------------------------------------------------------------------
TS_URL=""
if [ "$TS_ENABLED" = "1" ]; then
  log "Configuring 'tailscale serve' to expose the web UI over HTTPS ..."
  # Map https://<node>.ts.net/  ->  http://127.0.0.1:${PORT} (this host's port).
  # --bg persists the mapping in the background across restarts. Re-running
  # overwrites the "/" mount, so this is idempotent.
  if serve_err="$(tailscale serve --bg --https=443 "http://127.0.0.1:${PORT}" 2>&1)"; then
    TS_URL="https://${TS_DNS}"
    log "Web UI now served over HTTPS at ${TS_URL}"
  else
    warn "tailscale serve failed; continuing with LAN HTTP only."
    warn "Reason: ${serve_err}"
    case "$serve_err" in
      *[Hh][Tt][Tt][Pp][Ss]*|*[Cc]ert*)
        warn "Enable HTTPS for your tailnet: admin console -> DNS -> 'Enable HTTPS', then re-run." ;;
    esac
  fi
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
$(if [ -n "$TS_URL" ]; then printf '  Tailnet (HTTPS) : %s   <-- recommended for browsers\n' "$TS_URL"; fi)
  MCP (AI agents) : http://localhost:${MCP_PORT}/mcp  (local only; remote MCP needs HTTPS)
$(if [ -n "$TS_URL" ]; then cat <<TSNOTE
  Tip: prefer the Tailnet HTTPS URL in a browser. Plain http:// to a LAN IP is
  not a "secure context", so some browser features are restricted. The login
  page still works over LAN HTTP (it falls back automatically), but HTTPS is
  the smoother experience.
TSNOTE
fi)

--------------------------------------------------------------------------
2) Create your admin account (first user becomes admin)
--------------------------------------------------------------------------
  Run this once, then enter a password when prompted. The command runs INSIDE
  the container, so it targets the container's own port 8080 (this is correct
  and unrelated to the host port ${PORT} you use from a browser/device):

    docker exec -it $CONTAINER_NAME \\
      supernote admin --url http://localhost:8080 user add you@example.com

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
$(if [ -n "$TS_URL" ]; then cat <<TSNOTE
  * Tailscale HTTPS is enabled (tailscale serve -> 127.0.0.1:${PORT}). Disable
    with: ENABLE_TAILSCALE=0 ./run-local.sh  (and 'tailscale serve --https=443 off').
  * Keep the Supernote DEVICE on the LAN URL above; e-ink devices generally
    can't join the tailnet, and device sync doesn't need HTTPS.
TSNOTE
else
  echo '  * Tailscale HTTPS not active. Install + "tailscale up", then re-run to'
  echo '    serve the web UI at https://<node>.ts.net (a proper secure context).'
fi)

EOF
