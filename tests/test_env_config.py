"""Tests for env_config (data dir, Qdrant, defaults, metadata graph)."""

import os
from unittest.mock import patch

from onec_help.shared import env_config


def test_get_data_dir_default() -> None:
    """get_data_dir returns default when DATA_DIR unset or empty."""
    with patch.dict(os.environ, {"DATA_DIR": ""}, clear=False):
        assert env_config.get_data_dir() == "data"


def test_get_data_unpacked_dir_default() -> None:
    """get_data_unpacked_dir returns data/unpacked when DATA_UNPACKED_DIR unset."""
    with patch.dict(os.environ, {"DATA_UNPACKED_DIR": "", "DATA_DIR": "data"}, clear=False):
        out = env_config.get_data_unpacked_dir()
    assert "unpacked" in out
    assert out == os.path.join("data", "unpacked")


def test_get_ingest_cache_file_default() -> None:
    """get_ingest_cache_file returns path under data when INGEST_CACHE_FILE unset."""
    with patch.dict(os.environ, {"INGEST_CACHE_FILE": "", "DATA_DIR": "data"}, clear=False):
        out = env_config.get_ingest_cache_file()
    assert "ingest_cache" in out
    assert out.endswith("ingest_cache.db")


def test_get_qdrant_port_invalid_returns_default() -> None:
    """get_qdrant_port returns default when QDRANT_PORT is not a number."""
    with patch.dict(os.environ, {"QDRANT_PORT": "not_a_number"}, clear=False):
        out = env_config.get_qdrant_port()
    assert out == 6333


def test_get_qdrant_collection_empty_strip_returns_default() -> None:
    """get_qdrant_collection returns default when QDRANT_COLLECTION is empty or whitespace."""
    with patch.dict(os.environ, {"QDRANT_COLLECTION": "  "}, clear=False):
        out = env_config.get_qdrant_collection()
    assert out == "onec_help"


def test_get_help_path_default() -> None:
    """get_help_path returns DATA_DIR when HELP_PATH unset or empty."""
    with patch.dict(os.environ, {"HELP_PATH": "", "DATA_DIR": "data"}, clear=False):
        assert env_config.get_help_path() == "data"


def test_get_help_path_from_env() -> None:
    """get_help_path returns HELP_PATH when set."""
    with patch.dict(os.environ, {"HELP_PATH": "/custom/help"}, clear=False):
        assert env_config.get_help_path() == "/custom/help"


def test_get_help_html_max_bytes_invalid_returns_default() -> None:
    """get_help_html_max_bytes returns default when value is not a number."""
    with patch.dict(os.environ, {"HELP_HTML_MAX_BYTES": "not_a_number"}, clear=False):
        assert env_config.get_help_html_max_bytes() == 10 * 1024 * 1024


def test_get_redis_port_invalid_returns_default() -> None:
    """get_redis_port returns default when REDIS_PORT is not a number."""
    with patch.dict(os.environ, {"REDIS_PORT": "abc"}, clear=False):
        assert env_config.get_redis_port() == 6379


def test_get_redis_url_from_env() -> None:
    """get_redis_url returns REDIS_URL when set."""
    with patch.dict(os.environ, {"REDIS_URL": "redis://host:6379/1"}, clear=False):
        assert env_config.get_redis_url() == "redis://host:6379/1"


def test_get_redis_host_from_env() -> None:
    """get_redis_host returns REDIS_HOST when set."""
    with patch.dict(os.environ, {"REDIS_HOST": "redis.example.com"}, clear=False):
        assert env_config.get_redis_host() == "redis.example.com"


def test_get_redis_url_fallback() -> None:
    """get_redis_url_fallback returns default fallback URL."""
    assert "localhost" in env_config.get_redis_url_fallback()
    assert "6379" in env_config.get_redis_url_fallback()


def test_get_config_source_dir_env() -> None:
    """get_config_source_dir uses ONEC_CONFIG_SOURCE_DIR or falls back to data/kd2."""
    with patch.dict(os.environ, {}, clear=True):
        assert env_config.get_config_source_dir().endswith("data/kd2")
    with patch.dict(os.environ, {"ONEC_CONFIG_SOURCE_DIR": "/path/to/cfg"}, clear=True):
        assert env_config.get_config_source_dir() == "/path/to/cfg"
