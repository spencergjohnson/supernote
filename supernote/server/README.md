# Supernote Private Cloud Server

This package provides a self-hosted implementation of the Supernote Cloud server, enhanced with AI-powered insights, a modern Web UI, and robust background processing.

## Core Features

-   **Seamless Sync**: Implements the native Supernote sync protocol.
-   **AI Synthesis**: Automatically transcribes handwriting and identifies key insights using Google Gemini.
-   **Knowledge Exploration**: Cross-notebook semantic search and web-based file browsing.
-   **Private & Local**: Store your notes and metadata on your own infrastructure.

## Getting Started

See the main [README.md](../../README.md) for a quick start guide.

### Prerequisites

-   A Supernote device (Nomad, A5 X, A6 X, etc.)
-   Python 3.13+ or Docker.
-   (Recommended) **Gemini API Key** for OCR and Summarization.

### Configuration

The server is configured via `config/config.yaml` or environment variables.

For a comprehensive reference, see the [ServerConfig documentation](https://allenporter.github.io/supernote/supernote/server.html#ServerConfig).

#### AI Configuration
To enable AI features, set the Gemini API key:
```bash
export SUPERNOTE_GEMINI_API_KEY="your-api-key"
```

### Running the Server

Start the server using the unified `supernote` CLI:

```bash
# Start the server on port 8080
supernote serve
```

To override settings via environment:

```bash
export SUPERNOTE_PORT=8080
export SUPERNOTE_HOST=0.0.0.0
supernote serve
```

### Running with Docker (Local AI mode)

Use the helper script at the repo root for a one-shot build + run + instructions, in
**Local LLM mode** (your own inference server, no Gemini):

```bash
./run-local.sh
```

Or run it manually. Note the volume is `/data` (not `/storage`), and the default
command already starts the server, so do **not** pass `serve`:

```bash
# Build the image
docker build -t supernote .

# Shared network so the container can reach the inference server by name.
docker network create supernote-net 2>/dev/null || true
docker network connect supernote-net llamaswap 2>/dev/null || true

# Run the container (Local AI mode)
docker run -d \
  --name supernote-server \
  --restart unless-stopped \
  --add-host=host.docker.internal:host-gateway \
  --network supernote-net \
  -p 8080:8080 -p 8081:8081 \
  -v "$(pwd)/data:/data" \
  -e SUPERNOTE_JWT_SECRET="$(openssl rand -hex 32)" \
  -e SUPERNOTE_BASE_URL="http://localhost:8080" \
  -e SUPERNOTE_LOCAL_MODE=true \
  -e SUPERNOTE_LOCAL_LLM_URL="http://llamaswap:8080" \
  -e SUPERNOTE_LOCAL_LLM_MODEL="qwen2.5-vl-7b" \
  -e SUPERNOTE_LOCAL_EMBEDDING_MODEL="qwen3-embedding-8b" \
  supernote
```

`SUPERNOTE_LOCAL_LLM_URL` points at your OpenAI-compatible inference server. The
cleanest way to reach it from inside the container is to put both containers on a
shared user-defined network (`supernote-net`) and address it by container name
(`http://llamaswap:8080`). This avoids `host.docker.internal`, which is unreliable on
Linux because the host firewall often drops container->host traffic. Attaching the
inference container to the network is additive (it keeps its published port and other
networks), but it must rejoin `supernote-net` if recreated. The chat model must be
**vision-capable** for OCR. A fixed `SUPERNOTE_JWT_SECRET` keeps your device logged in
across restarts.

Keep `SUPERNOTE_BASE_URL` on `localhost` rather than your LAN IP. It is the MCP OAuth
issuer URL, and the MCP SDK rejects a non-HTTPS issuer unless the host is
`localhost`/`127.0.0.1` (you'll otherwise get `ValueError: Issuer URL must be HTTPS`
on startup). This setting does not affect the web UI or device sync, which use the
address you connect to directly.

### Connecting Your Device

1. Review the [official Private Cloud setup guide](https://support.supernote.com/Whats-New/setting-up-your-own-supernote-private-cloud-beta).
2. Ensure your Supernote device and server are on the same Wi-Fi network.
3. Create your admin user (first user becomes admin):
   ```bash
   docker exec -it supernote-server \
     supernote admin --url http://localhost:8080 user add you@example.com
   ```
4. On your Supernote device, go to **Settings** > **Sync** > **Supernote Cloud**.
5. Select **Private Cloud** and enter your server's IP and port (e.g., `192.168.1.100:8080`).
6. Log in using the credentials created in step 3.
7. Configure folders to sync (e.g., `Note`, `Document`, `EXPORT`) in **Settings** > **Drive** > **Private Cloud**.

## Robustness & Maintenance

Supernote Knowledge Hub is built for long-term stability:

- **Database Migrations**: Uses Alembic for seamless schema updates.
- **Background Polling**: Automatically recovers stalled processing tasks.
- **Integrity Checks**: Periodically verifies file storage consistency.
- **Storage Quotas**: Manage user storage limits effectively.

## Debugging & Tracing

The server logs all incoming requests to `storage/system/server_trace.log`:

```bash
tail -f storage/system/server_trace.log
```

## Development

- **Entry Point**: `supernote/server/app.py`
- **Tests**: `tests/server/`
- **Ephemeral Mode**: Run `supernote serve --ephemeral` for a transient, pre-configured test instance.

For contribution guidelines, see [CONTRIBUTING.md](../docs/CONTRIBUTING.md).
