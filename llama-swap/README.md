# llama-swap inference backend

Reference setup for running [llama-swap](https://github.com/mostlygeek/llama-swap) +
[llama.cpp](https://github.com/ggml-org/llama.cpp) as the local inference backend for
[Supernote Knowledge Hub](../README.md). Both are built into a single Docker image from
source so you get CUDA acceleration without any host Python/Go/CMake setup.

The container exposes a standard OpenAI-compatible API (`/v1/chat/completions`,
`/v1/embeddings`) that `run-local.sh` connects to by name over a shared Docker network.

## Prerequisites

- **NVIDIA driver** ≥ 525 on the host (`nvidia-smi` should work).
- **nvidia-container-toolkit** installed and Docker configured to use it
  (`--gpus all` must work — follow the
  [NVIDIA Container Toolkit install guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)).
- Docker ≥ 20.10.

## Model files

The two models supernote uses must be present on the host before starting.
Default location: `$HOME/ai/models` (override with `MODELS_DIR=...`).

```
$HOME/ai/models/
├── Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf          # vision chat — OCR + summaries
├── Qwen2.5-VL-7B-Instruct-mmproj-F16.gguf       # vision projector (required with the above)
└── embeddings/
    └── Qwen3-Embedding-8B-f16.gguf              # embeddings — semantic search
```

Download with the Hugging Face CLI:

```bash
pip install huggingface_hub

# Vision chat model (Qwen2.5-VL 7B, Q4_K_M quant)
huggingface-cli download \
  bartowski/Qwen2.5-VL-7B-Instruct-GGUF \
  Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf \
  Qwen2.5-VL-7B-Instruct-mmproj-F16.gguf \
  --local-dir "$HOME/ai/models"

# Embedding model (Qwen3-Embedding 8B, F16)
mkdir -p "$HOME/ai/models/embeddings"
huggingface-cli download \
  Qwen/Qwen3-Embedding-GGUF \
  Qwen3-Embedding-8B-f16.gguf \
  --local-dir "$HOME/ai/models/embeddings"
```

## Quick start

```bash
# From the repo root — build the image and start the container:
./llama-swap/start.sh

# Then start supernote (it will find llamaswap on the shared Docker network):
./run-local.sh
```

`run-local.sh` warns if the `llamaswap` container isn't running before it starts
supernote, so always start llama-swap first.

## Available scripts

| Script | What it does |
|--------|--------------|
| `start.sh` | Start the container (builds image if missing). |
| `rebuild.sh` | Tear down, rebuild image from scratch, restart. |
| `restart.sh` | Stop and restart with the existing image. |
| `stop.sh` | Stop and remove the container. |

## Configuration overrides

All scripts read these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MODELS_DIR` | `$HOME/ai/models` | Host path bind-mounted to `/models` inside the container. |
| `CONFIG_FILE` | `<script dir>/llama-swap.yaml` | Host path to the llama-swap config. |
| `LLAMA_SWAP_PORT` | `8080` | Host port the container publishes. |
| `LLM_CONTAINER` | `llamaswap` | Docker container name. |
| `LLM_NETWORK` | `supernote-net` | Shared Docker network for container-to-container routing. |
| `IMAGE` | `llamaswap:latest` | Docker image tag to build/run. |
| `CUDA_ARCH` | `86` | CUDA compute capability passed to CMake at build time. |

Examples:

```bash
# RTX 40xx (Ada Lovelace)
CUDA_ARCH=89 ./llama-swap/rebuild.sh

# Custom model directory
MODELS_DIR=/mnt/fast-ssd/models ./llama-swap/start.sh

# Pin upstream source for a reproducible build
LLAMA_CPP_REF=b5000 LLAMA_SWAP_REF=v0.10.0 ./llama-swap/rebuild.sh
```

## GPU architecture reference

| `CUDA_ARCH` | GPU generation | Example cards |
|-------------|---------------|---------------|
| `75` | Turing | RTX 20xx, T4 |
| `86` | Ampere (default) | RTX 30xx, A10 |
| `89` | Ada Lovelace | RTX 40xx |
| `90` | Hopper | H100 |
| `120` | Blackwell | RTX 50xx |

Building with the wrong arch still produces a working binary (CUDA falls back to PTX
JIT), but using the right value gives measurably better performance.

## Attribution

- **llama-swap** — [github.com/mostlygeek/llama-swap](https://github.com/mostlygeek/llama-swap), MIT licence.
- **llama.cpp** — [github.com/ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp), MIT licence.

This folder contains only build and configuration glue; all inference code comes from
those upstream projects.
