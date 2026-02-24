"""
Application configuration with Docker secrets support.

Secrets are read using the _read_secret() pattern:
  1. Direct env var (e.g., OMNIA_API_KEY)
  2. File-based env var (e.g., OMNIA_API_KEY_FILE → reads file path)
  3. Raises ValueError if neither is set
"""

import os
import logging

logger = logging.getLogger(__name__)


def _read_secret(env_var: str, file_env_var: str | None = None) -> str:
    """Read a secret from env var or Docker secrets file.

    Args:
        env_var: Direct environment variable name (e.g., OMNIA_API_KEY)
        file_env_var: File path env var name (e.g., OMNIA_API_KEY_FILE).
                      If None, defaults to env_var + '_FILE'.

    Returns:
        The secret value.

    Raises:
        ValueError: If neither source provides a value.
    """
    if file_env_var is None:
        file_env_var = f"{env_var}_FILE"

    # Priority 1: Direct env var
    value = os.environ.get(env_var)
    if value:
        return value

    # Priority 2: File-based (Docker secrets pattern)
    file_path = os.environ.get(file_env_var)
    if file_path:
        try:
            with open(file_path, "r") as f:
                value = f.read().strip()
            if value:
                return value
        except FileNotFoundError:
            logger.error(f"Secret file not found: {file_path} (from {file_env_var})")
        except PermissionError:
            logger.error(f"Permission denied reading: {file_path} (from {file_env_var})")

    raise ValueError(
        f"Secret not configured. Set {env_var} env var or {file_env_var} pointing to a file."
    )


class Settings:
    """Application settings loaded from environment and Docker secrets."""

    def __init__(self):
        # Database
        self.database_url = self._build_database_url()
        self.redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

        # Secrets (loaded lazily on first access via properties)
        self._omnia_api_key: str | None = None
        self._llm_api_key: str | None = None
        self._embedding_api_key: str | None = None
        self._app_secret_key: str | None = None
        self._google_client_id: str | None = None
        self._google_client_secret: str | None = None

        # Public config
        self.public_base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
        self.omnia_voice_name = os.environ.get("OMNIA_VOICE_NAME", "Mark")
        self.omnia_language_code = os.environ.get("OMNIA_LANGUAGE_CODE", "en")
        self.llm_model = os.environ.get("LLM_MODEL", "gpt-4o")
        self.embedding_model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
        self.embedding_dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))

        # Vision / YOLO settings
        self.yolo_model = os.environ.get("YOLO_MODEL", "yolov8n.pt")
        self.yolo_confidence = float(os.environ.get("YOLO_CONFIDENCE", "0.35"))
        self.vision_change_cooldown = float(os.environ.get("VISION_CHANGE_COOLDOWN", "10"))

    def _build_database_url(self) -> str:
        """Build async database URL with password from secrets."""
        base_url = os.environ.get(
            "DATABASE_URL", "postgresql+asyncpg://memchat@postgres:5432/memchat"
        )
        try:
            password = _read_secret("POSTGRES_PASSWORD")
            # Insert password into URL: postgresql+asyncpg://user@host → user:pass@host
            if "://" in base_url and "@" in base_url:
                scheme_user, rest = base_url.split("@", 1)
                if ":" not in scheme_user.split("://")[1]:
                    # No password in URL yet, add it
                    base_url = f"{scheme_user}:{password}@{rest}"
        except ValueError:
            logger.warning("POSTGRES_PASSWORD not set, using DATABASE_URL as-is")
        return base_url

    @property
    def omnia_api_key(self) -> str:
        if self._omnia_api_key is None:
            self._omnia_api_key = _read_secret("OMNIA_API_KEY")
        return self._omnia_api_key

    @property
    def llm_api_key(self) -> str:
        if self._llm_api_key is None:
            self._llm_api_key = _read_secret("LLM_API_KEY")
        return self._llm_api_key

    @property
    def embedding_api_key(self) -> str:
        if self._embedding_api_key is None:
            self._embedding_api_key = _read_secret("EMBEDDING_API_KEY")
        return self._embedding_api_key

    @property
    def app_secret_key(self) -> str:
        if self._app_secret_key is None:
            self._app_secret_key = _read_secret("APP_SECRET_KEY")
        return self._app_secret_key

    @property
    def google_client_id(self) -> str:
        if self._google_client_id is None:
            self._google_client_id = _read_secret("GOOGLE_CLIENT_ID")
        return self._google_client_id

    @property
    def google_client_secret(self) -> str:
        if self._google_client_secret is None:
            self._google_client_secret = _read_secret("GOOGLE_CLIENT_SECRET")
        return self._google_client_secret

    @property
    def google_redirect_uri(self) -> str:
        return os.environ.get(
            "GOOGLE_REDIRECT_URI",
            f"{self.public_base_url}/api/auth/google/callback",
        )


settings = Settings()
