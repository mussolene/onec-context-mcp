"""Tests for env_config (data dir, Qdrant, defaults)."""

import os
from unittest.mock import patch

from onec_help import env_config


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
