"""Tests for config._read_secret() and Settings._build_database_url()."""

import os
from unittest.mock import patch

import pytest

from config import _read_secret


class TestReadSecret:
    """_read_secret() reads from env var or file, in priority order."""

    def test_direct_env_var(self):
        with patch.dict(os.environ, {"MY_SECRET": "direct-value"}, clear=False):
            assert _read_secret("MY_SECRET") == "direct-value"

    def test_file_env_var(self, tmp_path):
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("file-value\n")
        env = {"MY_SECRET_FILE": str(secret_file)}
        with patch.dict(os.environ, env, clear=False):
            # Remove direct var if present
            os.environ.pop("MY_SECRET", None)
            assert _read_secret("MY_SECRET") == "file-value"

    def test_direct_takes_priority_over_file(self, tmp_path):
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("file-value")
        env = {"PRIO_SECRET": "direct-value", "PRIO_SECRET_FILE": str(secret_file)}
        with patch.dict(os.environ, env, clear=False):
            assert _read_secret("PRIO_SECRET") == "direct-value"

    def test_raises_when_neither_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MISSING_SECRET", None)
            os.environ.pop("MISSING_SECRET_FILE", None)
            with pytest.raises(ValueError, match="Secret not configured"):
                _read_secret("MISSING_SECRET")

    def test_file_not_found(self, tmp_path):
        env = {"GONE_SECRET_FILE": str(tmp_path / "nonexistent.txt")}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("GONE_SECRET", None)
            with pytest.raises(ValueError, match="Secret not configured"):
                _read_secret("GONE_SECRET")

    def test_custom_file_env_var_name(self, tmp_path):
        secret_file = tmp_path / "custom.txt"
        secret_file.write_text("custom-value")
        env = {"CUSTOM_PATH": str(secret_file)}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("CUSTOM_SECRET", None)
            assert _read_secret("CUSTOM_SECRET", file_env_var="CUSTOM_PATH") == "custom-value"


class TestSettingsBuildDatabaseUrl:
    """Settings._build_database_url() inserts password from secrets."""

    def test_inserts_password_into_url(self):
        env = {
            "DATABASE_URL": "postgresql+asyncpg://myuser@dbhost:5432/mydb",
            "POSTGRES_PASSWORD": "s3cret",
        }
        with patch.dict(os.environ, env, clear=False):
            from config import Settings
            s = Settings()
            assert s.database_url == "postgresql+asyncpg://myuser:s3cret@dbhost:5432/mydb"

    def test_no_password_uses_url_as_is(self):
        env = {"DATABASE_URL": "sqlite+aiosqlite://"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("POSTGRES_PASSWORD", None)
            os.environ.pop("POSTGRES_PASSWORD_FILE", None)
            from config import Settings
            s = Settings()
            assert s.database_url == "sqlite+aiosqlite://"
