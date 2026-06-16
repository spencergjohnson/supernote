import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from mashumaro.config import TO_DICT_ADD_OMIT_NONE_FLAG, BaseConfig
from mashumaro.mixins.yaml import DataClassYAMLMixin

logger = logging.getLogger(__name__)


def _get_bool_env(name: str, default: bool) -> bool:
    """Get a boolean value from an environment variable."""
    val = os.getenv(name)
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes", "on")


@dataclass
class AuthConfig(DataClassYAMLMixin):
    """Authentication configuration."""

    secret_key: str = ""
    """JWT secret key.

    Env Var: `SUPERNOTE_JWT_SECRET`
    """

    expiration_hours: int = 24
    """JWT expiration time in hours."""

    device_expiration_hours: int = 87600
    """JWT expiration time for devices in hours (default: 10 years)."""

    enable_registration: bool = False
    """When disabled, registration is only allowed if there are no users in the system.

    Env Var: `SUPERNOTE_ENABLE_REGISTRATION`
    """

    enable_remote_password_reset: bool = False
    """When disabled, the public password reset endpoint returns 403.

    Env Var: `SUPERNOTE_ENABLE_REMOTE_PASSWORD_RESET`
    """

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]


@dataclass
class ServerConfig(DataClassYAMLMixin):
    host: str = "0.0.0.0"
    """Host to bind the server to.

    Env Var: `SUPERNOTE_HOST`
    """

    port: int = 8080
    """Port to bind the server to.

    Env Var: `SUPERNOTE_PORT`
    """

    mcp_port: int = 8081
    """Port to bind the MCP server to.

    Env Var: `SUPERNOTE_MCP_PORT`
    """

    tls_cert_file: str | None = None
    """Path to the TLS certificate (PEM). When set together with tls_key_file,
    the main server is served over HTTPS instead of HTTP.

    Env Var: `SUPERNOTE_TLS_CERT_FILE`
    """

    tls_key_file: str | None = None
    """Path to the TLS private key (PEM). Required to enable HTTPS.

    Env Var: `SUPERNOTE_TLS_KEY_FILE`
    """

    internal_http_port: int = 8079
    """Loopback-only (127.0.0.1) plain-HTTP port.

    Only bound when TLS is enabled. It lets in-process / same-container tooling
    (e.g. the admin CLI) reach the API without dealing with the self-signed
    certificate. It is never exposed beyond localhost.

    Env Var: `SUPERNOTE_INTERNAL_HTTP_PORT`
    """

    _base_url: str | None = field(default=None, metadata={"name": "base_url"})
    """Base URL for the main server (port 8080).
    Used for generating links and for the MCP Authorization Server issuer.
    """

    _mcp_base_url: str | None = field(default=None, metadata={"name": "mcp_base_url"})
    """Base URL for the MCP server (port 8081).

    Used for RFC 9728 discovery if the server is behind a proxy.
    """

    trace_log_file: str | None = None
    """Path to trace log file.

    This will default to a file in the storage directory if unset.

    Env Var: `SUPERNOTE_TRACE_LOG_FILE`
    """

    storage_dir: str = "storage"
    """Directory for storing files and database.

    Env Var: `SUPERNOTE_STORAGE_DIR`
    """

    proxy_mode: str | None = None
    """Proxy header handling mode: None/'disabled' (ignore proxy headers), 'relaxed' (trust immediate upstream), or 'strict' (require specific trusted IPs). Defaults to None for security.

    Env Var: `SUPERNOTE_PROXY_MODE`
    """

    trusted_proxies: list[str] = field(
        default_factory=lambda: ["127.0.0.1", "::1", "172.17.0.0/16"]
    )
    """List of trusted proxy IPs/networks (used in strict mode). Supports CIDR notation.

    Env Var: `SUPERNOTE_TRUSTED_PROXIES` (comma-separated)
    """

    auth: AuthConfig = field(default_factory=AuthConfig)

    gemini_api_key: str | None = None
    """Google Gemini API Key for OCR and Embeddings.

    Env Var: `SUPERNOTE_GEMINI_API_KEY`
    """

    gemini_ocr_model: str = "gemini-3-flash-preview"
    """Gemini model to use for OCR.

    Env Var: `SUPERNOTE_GEMINI_OCR_MODEL`
    """

    gemini_embedding_model: str = "gemini-embedding-001"
    """Gemini model to use for Embeddings.
BaseConfig
    Env Var: `SUPERNOTE_GEMINI_EMBEDDING_MODEL`
    """

    gemini_max_concurrency: int = 5
    """Maximum number of concurrent Gemini API calls.

    Env Var: `SUPERNOTE_GEMINI_MAX_CONCURRENCY`
    """

    local_mode: bool = False
    """Enable local LLM mode, disables Gemini.

    Env Var: `SUPERNOTE_LOCAL_MODE`
    """

    local_llm_url: str = "http://localhost:8080"
    """Base URL for local OpenAI-compatible inference server.

    Env Var: `SUPERNOTE_LOCAL_LLM_URL`
    """

    local_llm_model: str = "qwen2.5-vl-7b"
    """Model name to pass in local chat completions requests.

    Env Var: `SUPERNOTE_LOCAL_LLM_MODEL`
    """

    local_embedding_model: str = "nomic-embed-text"
    """Model name to pass in local embedding requests.

    Env Var: `SUPERNOTE_LOCAL_EMBEDDING_MODEL`
    """

    @property
    def tls_enabled(self) -> bool:
        """Whether HTTPS should be used for the main server."""
        return bool(self.tls_cert_file and self.tls_key_file)

    @property
    def base_url(self) -> str:
        """Get the base URL for the main server.

        Env Var: `SUPERNOTE_BASE_URL`
        """
        if self._base_url:
            return self._base_url.rstrip("/")
        host = "localhost" if self.host == "0.0.0.0" else self.host
        scheme = "https" if self.tls_enabled else "http"
        return f"{scheme}://{host}:{self.port}"

    @property
    def mcp_base_url(self) -> str:
        """Get the base URL for the MCP server.

        Env Var: `SUPERNOTE_MCP_BASE_URL`
        """
        if self._mcp_base_url:
            return self._mcp_base_url.rstrip("/")
        host = "localhost" if self.host == "0.0.0.0" else self.host
        return f"http://{host}:{self.mcp_port}"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.storage_dir}/system/supernote.db"

    @property
    def storage_root(self) -> Path:
        return Path(self.storage_dir)

    @property
    def ephemeral(self) -> bool:
        """Whether the server is running in ephemeral mode."""
        return _get_bool_env("SUPERNOTE_EPHEMERAL", False)

    @classmethod
    def load(
        cls, config_dir: str | Path | None = None, config_file: str | Path | None = None
    ) -> "ServerConfig":
        """Load configuration from directory. READ-ONLY."""
        if config_file is not None:
            config_file = Path(config_file)
        else:
            if config_dir is None:
                config_dir = os.getenv("SUPERNOTE_CONFIG_DIR", "config")
                logger.info(f"Using SUPERNOTE_CONFIG_DIR: {config_dir}")
            config_dir_path = Path(config_dir)
            config_file = config_dir_path / "config.yaml"
            logger.info(f"Using config file: {config_file}")

        config = cls()
        if config_file.exists():
            try:
                with open(config_file, "r") as f:
                    config = cls.from_yaml(f.read())
            except Exception as e:
                logger.warning(f"Failed to load config file {config_file}: {e}")

        # 4. JWT Secret priority: Env > Config > Random(in-memory only)
        env_secret = os.getenv("SUPERNOTE_JWT_SECRET")
        if env_secret:
            logger.info("Using SUPERNOTE_JWT_SECRET")
            config.auth.secret_key = env_secret

        if not config.auth.secret_key:
            logger.warning(
                "No JWT secret key configured. Using a temporary in-memory key."
            )
            config.auth.secret_key = secrets.token_hex(32)

        # Apply other env var overrides
        if os.getenv("SUPERNOTE_HOST"):
            config.host = os.getenv("SUPERNOTE_HOST", config.host)
            logger.info(f"Using SUPERNOTE_HOST: {config.host}")

        if os.getenv("SUPERNOTE_PORT"):
            try:
                config.port = int(os.getenv("SUPERNOTE_PORT", str(config.port)))
                logger.info(f"Using SUPERNOTE_PORT: {config.port}")
            except ValueError:
                pass

        if os.getenv("SUPERNOTE_MCP_PORT"):
            try:
                config.mcp_port = int(
                    os.getenv("SUPERNOTE_MCP_PORT", str(config.mcp_port))
                )
                logger.info(f"Using SUPERNOTE_MCP_PORT: {config.mcp_port}")
            except ValueError:
                pass

        if os.getenv("SUPERNOTE_TLS_CERT_FILE"):
            config.tls_cert_file = os.getenv("SUPERNOTE_TLS_CERT_FILE")
            logger.info(f"Using SUPERNOTE_TLS_CERT_FILE: {config.tls_cert_file}")

        if os.getenv("SUPERNOTE_TLS_KEY_FILE"):
            config.tls_key_file = os.getenv("SUPERNOTE_TLS_KEY_FILE")
            logger.info(f"Using SUPERNOTE_TLS_KEY_FILE: {config.tls_key_file}")

        if os.getenv("SUPERNOTE_INTERNAL_HTTP_PORT"):
            try:
                config.internal_http_port = int(
                    os.getenv(
                        "SUPERNOTE_INTERNAL_HTTP_PORT", str(config.internal_http_port)
                    )
                )
                logger.info(
                    f"Using SUPERNOTE_INTERNAL_HTTP_PORT: {config.internal_http_port}"
                )
            except ValueError:
                pass

        if os.getenv("SUPERNOTE_STORAGE_DIR"):
            config.storage_dir = os.getenv("SUPERNOTE_STORAGE_DIR", config.storage_dir)
            logger.info(f"Using SUPERNOTE_STORAGE_DIR: {config.storage_dir}")

        if os.getenv("SUPERNOTE_BASE_URL"):
            config._base_url = os.getenv("SUPERNOTE_BASE_URL")
            logger.info(f"Using SUPERNOTE_BASE_URL: {config._base_url}")

        if os.getenv("SUPERNOTE_MCP_BASE_URL"):
            config._mcp_base_url = os.getenv("SUPERNOTE_MCP_BASE_URL")
            logger.info(f"Using SUPERNOTE_MCP_BASE_URL: {config._mcp_base_url}")

        # Legacy support/compatibility if USER sets SUPERNOTE_AUTH_URL_BASE
        if os.getenv("SUPERNOTE_AUTH_URL_BASE"):
            if not config._base_url:
                config._base_url = os.getenv("SUPERNOTE_AUTH_URL_BASE")
                logger.info(
                    f"Using legacy SUPERNOTE_AUTH_URL_BASE as base_url: {config._base_url}"
                )

        if os.getenv("SUPERNOTE_ENABLE_REGISTRATION"):
            config.auth.enable_registration = _get_bool_env(
                "SUPERNOTE_ENABLE_REGISTRATION", config.auth.enable_registration
            )
            logger.info(f"Registration Enabled: {config.auth.enable_registration}")

        if os.getenv("SUPERNOTE_ENABLE_REMOTE_PASSWORD_RESET"):
            config.auth.enable_remote_password_reset = _get_bool_env(
                "SUPERNOTE_ENABLE_REMOTE_PASSWORD_RESET",
                config.auth.enable_remote_password_reset,
            )
            logger.info(
                f"Remote Password Reset Enabled: {config.auth.enable_remote_password_reset}"
            )

        if os.getenv("SUPERNOTE_PROXY_MODE"):
            config.proxy_mode = os.getenv("SUPERNOTE_PROXY_MODE")
            logger.info(f"Using SUPERNOTE_PROXY_MODE: {config.proxy_mode}")

        if os.getenv("SUPERNOTE_TRUSTED_PROXIES"):
            val = os.getenv("SUPERNOTE_TRUSTED_PROXIES", "")
            config.trusted_proxies = [p.strip() for p in val.split(",") if p.strip()]
            logger.info(f"Using SUPERNOTE_TRUSTED_PROXIES: {config.trusted_proxies}")

        if gemini_api_key := os.getenv("SUPERNOTE_GEMINI_API_KEY"):
            config.gemini_api_key = gemini_api_key
            logger.info(
                f"Using SUPERNOTE_GEMINI_API_KEY: xxx...{config.gemini_api_key[-3:]}"
            )

        if gemini_ocr_model := os.getenv("SUPERNOTE_GEMINI_OCR_MODEL"):
            config.gemini_ocr_model = gemini_ocr_model
            logger.info(f"Using SUPERNOTE_GEMINI_OCR_MODEL: {config.gemini_ocr_model}")

        if gemini_embedding_model := os.getenv("SUPERNOTE_GEMINI_EMBEDDING_MODEL"):
            config.gemini_embedding_model = gemini_embedding_model
            logger.info(
                f"Using SUPERNOTE_GEMINI_EMBEDDING_MODEL: {config.gemini_embedding_model}"
            )

        if gemini_max_concurrency := os.getenv("SUPERNOTE_GEMINI_MAX_CONCURRENCY"):
            try:
                config.gemini_max_concurrency = int(gemini_max_concurrency)
                logger.info(
                    f"Using SUPERNOTE_GEMINI_MAX_CONCURRENCY: {config.gemini_max_concurrency}"
                )
            except ValueError:
                pass

        if os.getenv("SUPERNOTE_LOCAL_MODE"):
            config.local_mode = _get_bool_env("SUPERNOTE_LOCAL_MODE", config.local_mode)
            logger.info(f"Local LLM Mode Enabled: {config.local_mode}")

        if local_llm_url := os.getenv("SUPERNOTE_LOCAL_LLM_URL"):
            config.local_llm_url = local_llm_url
            logger.info(f"Using SUPERNOTE_LOCAL_LLM_URL: {config.local_llm_url}")

        if local_llm_model := os.getenv("SUPERNOTE_LOCAL_LLM_MODEL"):
            config.local_llm_model = local_llm_model
            logger.info(f"Using SUPERNOTE_LOCAL_LLM_MODEL: {config.local_llm_model}")

        if local_embedding_model := os.getenv("SUPERNOTE_LOCAL_EMBEDDING_MODEL"):
            config.local_embedding_model = local_embedding_model
            logger.info(f"Using SUPERNOTE_LOCAL_EMBEDDING_MODEL: {config.local_embedding_model}")

        if config.trace_log_file is None:
            config.trace_log_file = str(
                Path(config.storage_dir) / "system" / "trace.log"
            )

        if not config_file.exists():
            logger.info(f"Saving config to {config_file}")
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text(cast(str, config.to_yaml()))

        return config

    class Config(BaseConfig):
        omit_none = True
        code_generation_options = [TO_DICT_ADD_OMIT_NONE_FLAG]  # type: ignore[list-item]
