# Supernote Knowledge Hub

**The AI-powered intelligence layer for your Ratta Supernote.**

This toolkit is a self-hosted implementation of the **Supernote Private Cloud** protocol. While Ratta's official private cloud provides a solid and reliable sync foundation, this project extends that experience with an **AI-driven synthesis engine**—transforming your handwritten notes into structured, searchable knowledge using Google Gemini.

<p align="center">
  <img src="docs/static-assets/hero-overview.jpg" alt="Supernote Overview" width="800">
</p>

[![Documentation](https://img.shields.io/badge/docs-manual-blue.svg)](https://allenporter.github.io/supernote/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

## Why Supernote Knowledge Hub?

This project is designed to be **fully compatible** with the official Supernote Private Cloud protocol, while adding specialized features for knowledge workers and researchers:

- **📜 AI Synthesis**: Automatically transcribes handwriting and generates high-level summaries (Daily, Weekly, Monthly).
- **🔍 Semantic Search**: Find concepts across all your notebooks—not just filenames—using vectorized content.
- **🛡️ Private & Secure**: You own your database. Run it on your NAS, local PC, or a low-power server, just like Supernote Private Cloud.
- **🖥️ Modern Web UI**: A sleek, reactive frontend to browse, review, and search your notes from any browser.
- **🤖 Agent Ready (MCP)**: Securely connect your notes to AI agents (Claude, ChatGPT) via the built-in [Model Context Protocol](https://modelcontextprotocol.io/) server. Supports dynamic **IndieAuth** for secure, remote access.

## Synthesis & AI in Action

Beyond simple storage, Supernote provides an active processing pipeline to increase the utility of your notes:

1.  **Sync**: Your device uploads `.note` files using the official Private Cloud protocol.
2.  **Transcribe**: The server extract pages and use Gemini Vision to OCR your handwriting.
3.  **Synthesize**: AI Analyzers review your journals to find tasks, themes, and summaries.
4.  **Index**: Every word is vectorized, enabling semantic search across your entire library.

### Web Interface

The integrated frontend allows you to review your notes and AI insights side-by-side.

<p align="center">
  <img src="docs/static-assets/note-synthesis-1.jpg" alt="Note Synthesis View" width="400">
  <img src="docs/static-assets/note-synthesis-2.jpg" alt="Notebook Explorer" width="400">
</p>

## Quick Start

### 1. Launch the Cloud

The easiest way to start is with the `all` bundle and a Gemini API key:

```bash
export SUPERNOTE_GEMINI_API_KEY="your-api-key"
pip install "supernote[all]"
supernote serve
```

### 2. Bootstrap Your User

```bash
# Create the initial admin account
supernote admin --url http://localhost:8080 user add you@example.com

# Authenticate your CLI
supernote cloud login you@example.com --url http://localhost:8080
```

### 3. Connect Your Device

1. On your Supernote, go to **Settings > Sync > Private Cloud**.
2. Enter your server URL (e.g., `http://192.168.1.5:8080`).
3. Log in with the email and password you created in Step 2.
4. Tap **Sync** to begin processing your notes.

### 4. Explore Your Insights

Once your notes sync and process, you can view the AI synthesis from the terminal or browser:

```bash
# Get a high-level summary and transcription
supernote cloud insights /Notes/NOTE/Journal.note

# Semantic search across all notebooks
supernote cloud search "What were my project goals for February?"
```

<p align="center">
  <img src="docs/static-assets/cli-insights.jpg" alt="CLI AI Insights" width="700">
</p>

You can access the insights from the MCP server at `http://<your ip:port>/mcp`

> [!TIP]
> **Semantic Search**: Supernote doesn't just look for words—it understands concepts. Searching for "budget" will find notes about "expenses" or "money," even if the specific word isn't there.

## Local LLM Mode

By default the synthesis engine uses Google Gemini, but you can run the **entire** pipeline—OCR, summaries, and semantic search embeddings—against your own OpenAI-compatible inference server instead. This keeps every page of your handwriting on your own hardware and means **no API key is required**, at the cost of providing the compute yourself.

### Prerequisites

Any inference server that exposes the standard OpenAI endpoints (`POST /v1/chat/completions` and `POST /v1/embeddings`) works out of the box, including [llama-swap](https://github.com/mostlygeek/llama-swap), [Ollama](https://ollama.com/), [LM Studio](https://lmstudio.ai/), and [vLLM](https://github.com/vllm-project/vllm). You will need two models available: a **vision-capable** chat model for OCR and summaries (e.g. `qwen2.5-vl-7b`, `llava`) and an embedding model for semantic search (e.g. `qwen3-embedding-8b`, `mxbai-embed-large`).

### Configuration

Local mode is controlled by four settings. Each can be set as an environment variable or in `config.yaml`; environment variables take precedence.

| Environment Variable | Config Key | Description |
|----------------------|------------|-------------|
| `SUPERNOTE_LOCAL_MODE` | `local_mode` | Set to `true` to enable local mode and disable Gemini. |
| `SUPERNOTE_LOCAL_LLM_URL` | `local_llm_url` | Base URL of your OpenAI-compatible server. Use a port other than `8080`. |
| `SUPERNOTE_LOCAL_LLM_MODEL` | `local_llm_model` | Model name for chat completions. **Must be vision-capable** for OCR. |
| `SUPERNOTE_LOCAL_EMBEDDING_MODEL` | `local_embedding_model` | Model name for semantic search embeddings. |

### Quick Start

```bash
# Option A: llama-swap (hot-swaps llama.cpp models on :8090)
llama-swap --config llama-swap-config.yaml --port 8090
export SUPERNOTE_LOCAL_LLM_URL=http://localhost:8090
export SUPERNOTE_LOCAL_LLM_MODEL=qwen2.5-vl-7b

# Option B: Ollama (OpenAI-compatible API on :11434)
ollama pull llava && ollama pull qwen3-embedding-8b
export SUPERNOTE_LOCAL_LLM_URL=http://localhost:11434
export SUPERNOTE_LOCAL_LLM_MODEL=llava

# Then enable local mode and serve (shared by both options)
export SUPERNOTE_LOCAL_MODE=true
export SUPERNOTE_LOCAL_EMBEDDING_MODEL=qwen3-embedding-8b
supernote serve
```

> [!TIP]
> OCR requires a **vision-capable** model (one that accepts `image_url` content parts). Text-only models will not transcribe handwritten pages, though they can still be used as the embedding model.

## Features Deep Dive

- **Official Protocol Compatibility**: Implements the official **Supernote Private Cloud** protocol for seamless device synchronization. While Ratta's official service provides a robust and managed sync experience, this project allows for local data ownership and custom background processing.
- **Notebook Parsing**: Native, high-fidelity conversion of `.note` files to PDF, PNG, SVG, or plain text.
- **Developer API**: Modern `asyncio` client to build your own automation around Supernote data.
- **Observability**: Built-in request tracing and background task monitoring.

<p align="center">
  <img src="docs/static-assets/admin-processing-status.jpg" alt="Admin Task Monitor" width="450">
  <img src="docs/static-assets/mobile-friendly.jpg" alt="Mobile View" width="250">
</p>

## Installation

```bash
# Install specific components
pip install supernote              # Notebook parsing only
pip install supernote[server]      # + Private server & AI features
pip install supernote[client]      # + API Client

# Full installation (recommended for server users)
pip install supernote[all]
```

## Local Development Setup

To set up the project for development, please refer to the [Contributing Guide](docs/CONTRIBUTING.md).

### Parse a Notebook (Local)

```python
from supernote.notebook import parse_notebook

notebook = parse_notebook("mynote.note")
notebook.to_pdf("output.pdf")
```

The notebook parser is a fork and slightly lighter dependency version of [supernote-tool](https://github.com/jya-dev/supernote-tool). All credit goes to the original authors for providing an amazing low-level utility.

### Run with Docker (Local AI mode)

The quickest way to build, run, and get LAN + device connection instructions is the
helper script, which runs entirely in **Local LLM mode** (your own inference server,
no Gemini, no API key):

```bash
# Defaults to an Ollama server on the host (:11434).
# Override the inference server with LLM_URL / LLM_MODEL / EMBEDDING_MODEL.
./run-local.sh
```

It builds the image, starts the container bound to your LAN, persists a JWT secret,
and prints the Web UI URL plus the steps to create your admin user and connect the
device.

To do it by hand instead:

```bash
docker build -t supernote .

docker run -d \
  --name supernote-server \
  --restart unless-stopped \
  --add-host=host.docker.internal:host-gateway \
  -p 8080:8080 -p 8081:8081 \
  -v "$(pwd)/data:/data" \
  -e SUPERNOTE_JWT_SECRET="$(openssl rand -hex 32)" \
  -e SUPERNOTE_BASE_URL="http://localhost:8080" \
  -e SUPERNOTE_LOCAL_MODE=true \
  -e SUPERNOTE_LOCAL_LLM_URL="http://host.docker.internal:8080" \
  -e SUPERNOTE_LOCAL_LLM_MODEL="qwen2.5-vl-7b" \
  -e SUPERNOTE_LOCAL_EMBEDDING_MODEL="qwen3-embedding-8b" \
  supernote
```

> [!NOTE]
> The image's storage/config volume is `/data` (not `/storage`), and the default
> command already starts the server, so do **not** append `serve`. Setting a fixed
> `SUPERNOTE_JWT_SECRET` keeps your device logged in across restarts. The chat model
> must be **vision-capable** for OCR.
>
> Keep `SUPERNOTE_BASE_URL` on `localhost` (not your LAN IP): it's the MCP OAuth
> issuer, and the MCP SDK rejects a non-HTTPS issuer unless the host is `localhost`.
> It does not affect the web UI or device sync, which use the address you connect to
> directly. `SUPERNOTE_LOCAL_LLM_URL` assumes llama-swap on the host at `:8080`
> (reached via `host.docker.internal`); use `:11434`/`llava` for Ollama.

Then create your admin user and connect the device:

```bash
docker exec -it supernote-server \
  supernote admin --url http://localhost:8080 user add you@example.com
```

On the Supernote: **Settings > Sync > Private Cloud**, enter `http://<your-lan-ip>:8080`,
and log in with that email/password.

See [Server Documentation](https://github.com/allenporter/supernote/blob/main/supernote/server/README.md) for details.

### Developer API

Integrate Supernote into your own Python applications:

```python
from supernote.client import Supernote
# See library docstrings for usage examples
```


## CLI Usage

```bash
# Server & Admin
supernote serve                      # Start the cloud
supernote admin user list           # Manage your users

# AI Synthesis & Insights
supernote cloud insights /Note.note # View synthesis from CLI

# File Operations
supernote cloud ls /                # List remote files
supernote cloud download /Note.note # Download to local machine
```

## Notebook Operations (Local)

You can use the built-in parser outside of the cloud server:

```python
from supernote.notebook import parse_notebook

note = parse_notebook("journal.note")
note.to_pdf("journal.pdf") # Multi-layer PDF conversion
```

The notebook parser is a fork of the excellent [supernote-tool](https://github.com/jya-dev/supernote-tool) with updated dependencies and modern type hints.

## Contributing

We welcome contributions! Please see our [Contributing Guide](docs/CONTRIBUTING.md) for details on:
- Local development setup
- Project architecture
- Using **Ephemeral Mode** for fast testing
- AI Skills for agentic interaction

## Acknowledgments

This project is in support of the amazing [Ratta Supernote](https://supernote.com/) product and community. It aims to be a complementary, unofficial offering that is fully compatible with the official [Private Cloud protocol](https://support.supernote.com/Whats-New/setting-up-your-own-supernote-private-cloud-beta).

### Choosing Your Private Cloud Experience

The official Supernote Private Cloud by Ratta is a rock-solid, production-grade implementation of the protocol. This toolkit serves as a **community-driven extension** for users who need deep data analysis and advanced integrations.

| Capability | Official Private Cloud (Ratta) | Supernote Hub (This Project) |
|------------|-------------------------------|-----------------------------|
| **Core Sync** | ✅ Robust & Validated | ✅ Protocol Compatible |
| **AI Analysis** | Basic OCR (Device-side) | **Adv. OCR & Multi-stage Synthesis** |
| **Search** | Path/Filename | **Semantic Concept Search** |
| **Stack** | Java / Spring Boot | Python / Asyncio |
| **Focus** | Stability & Stability | Innovation & Extensibility |

**This toolkit is a great fit if:**
- You want **AI-generated summaries** and insights from your notebooks.
- You want to perform **semantic searches** across your entire handwriting library.
- You want to integrate your notes into local scripts via a Python API or CLI.
- You want to use the **Model Context Protocol (MCP)** to [chat with your notes](docs/mcp.md) using AI agents.

## Community Projects

- [jya-dev/supernote-tool](https://github.com/jya-dev/supernote-tool) - Original parser foundation.
- [awesome-supernote](https://github.com/fharper/awesome-supernote) - Curated resource list.
- [sn2md](https://github.com/dsummersl/sn2md) - Supernote to text/image converter.
