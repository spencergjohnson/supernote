#!/usr/bin/env bash
# start.sh — Start the llamaswap container (build image first if missing).
#
# Override any defaults via environment variables, e.g.:
#   MODELS_DIR=/mnt/models CUDA_ARCH=89 ./start.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE="${IMAGE:-llamaswap:latest}"
CONTAINER="${LLM_CONTAINER:-llamaswap}"
PORT="${LLAMA_SWAP_PORT:-8080}"
MODELS_DIR="${MODELS_DIR:-$HOME/ai/models}"
CONFIG_FILE="${CONFIG_FILE:-$SCRIPT_DIR/llama-swap.yaml}"
NETWORK="${LLM_NETWORK:-supernote-net}"
CUDA_ARCH="${CUDA_ARCH:-86}"

if ! docker image inspect "$IMAGE" &>/dev/null; then
  echo "Building image $IMAGE (CUDA_ARCH=${CUDA_ARCH})..."
  docker build \
    --build-arg CUDA_ARCH="$CUDA_ARCH" \
    -f "$SCRIPT_DIR/Dockerfile" \
    -t "$IMAGE" \
    "$SCRIPT_DIR"
fi

docker rm -f "$CONTAINER" 2>/dev/null || true
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

echo "llamaswap started on port ${PORT}"
