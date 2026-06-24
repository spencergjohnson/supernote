#!/usr/bin/env bash
# restart.sh — Stop and restart the llamaswap container (reuses existing image).
#
# Override any defaults via environment variables, e.g.:
#   MODELS_DIR=/mnt/models ./restart.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE="${IMAGE:-llamaswap:latest}"
CONTAINER="${LLM_CONTAINER:-llamaswap}"
PORT="${LLAMA_SWAP_PORT:-8080}"
MODELS_DIR="${MODELS_DIR:-$HOME/ai/models}"
CONFIG_FILE="${CONFIG_FILE:-$SCRIPT_DIR/llama-swap.yaml}"
NETWORK="${LLM_NETWORK:-supernote-net}"

echo "Stopping $CONTAINER..."
docker stop "$CONTAINER" 2>/dev/null || true
docker rm "$CONTAINER" 2>/dev/null || true

echo "Starting $CONTAINER..."
docker run -d \
  --name "$CONTAINER" \
  --gpus all \
  --runtime=nvidia \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
  -p "${PORT}:8080" \
  -v "${MODELS_DIR}:/models" \
  -v "${CONFIG_FILE}:/config/llama-swap.yaml:ro" \
  --restart unless-stopped \
  "$IMAGE" \
  -config /config/llama-swap.yaml \
  -listen 0.0.0.0:8080

docker network create "$NETWORK" 2>/dev/null || true
docker network connect "$NETWORK" "$CONTAINER" 2>/dev/null || true

echo "llamaswap restarted on port ${PORT}"
