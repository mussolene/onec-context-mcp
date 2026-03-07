"""Centralized environment variable defaults. Single source for env names and defaults."""

from __future__ import annotations

import os
from pathlib import Path

# --- Data paths (one root: DATA_DIR) ---
DATA_DIR_DEFAULT = "data"


def get_data_dir() -> str:
    """Project data root (BM25 vocab, ingest markers parent). Default: data."""
    return (os.environ.get("DATA_DIR") or DATA_DIR_DEFAULT).strip() or DATA_DIR_DEFAULT


def get_data_unpacked_dir() -> str:
    """Unpacked help output dir. Default: data/unpacked (or DATA_DIR/unpacked)."""
    v = os.environ.get("DATA_UNPACKED_DIR", "").strip()
    if v:
        return v
    return os.path.join(get_data_dir(), "unpacked")


def get_ingest_cache_file() -> str:
    """Path whose parent is used for markers (load_*.running, etc.). Redis holds cache. Default: DATA_DIR/ingest_cache/ingest_cache.db."""
    v = os.environ.get("INGEST_CACHE_FILE", "").strip()
    if v:
        return v
    return str(Path(get_data_dir()) / "ingest_cache" / "ingest_cache.db")


# --- Help path (MCP: directory for get_1c_help_topic from disk) ---
def get_help_path() -> str:
    """Base directory for MCP to read help topics from disk. Default: data (or DATA_DIR)."""
    v = (os.environ.get("HELP_PATH") or "").strip()
    return v or get_data_dir()


# --- Help sources ---
def get_help_source_base() -> str:
    """Root dir for versioned .hbk (e.g. /opt/1cv8)."""
    return (os.environ.get("HELP_SOURCE_BASE") or "").strip()


# --- Embedding (default backend: same as embedding.py and docker-compose) ---
EMBEDDING_BACKEND_DEFAULT = "openai_api"

# --- Qdrant ---
QDRANT_HOST_DEFAULT = "localhost"
QDRANT_PORT_DEFAULT = 6333
QDRANT_COLLECTION_DEFAULT = "onec_help"


def get_qdrant_host() -> str:
    return os.environ.get("QDRANT_HOST", QDRANT_HOST_DEFAULT).strip() or QDRANT_HOST_DEFAULT


def get_qdrant_port() -> int:
    try:
        return int(os.environ.get("QDRANT_PORT", str(QDRANT_PORT_DEFAULT)))
    except ValueError:
        return QDRANT_PORT_DEFAULT


def get_qdrant_collection() -> str:
    return (
        os.environ.get("QDRANT_COLLECTION", QDRANT_COLLECTION_DEFAULT).strip()
        or QDRANT_COLLECTION_DEFAULT
    )


def get_qdrant_storage_path() -> str | None:
    """Path to Qdrant storage dir for dashboard (optional)."""
    v = (os.environ.get("QDRANT_STORAGE_PATH") or "").strip()
    return v or None


QDRANT_TIMEOUT_DEFAULT = 300


def get_qdrant_timeout() -> int:
    """Timeout in seconds for Qdrant HTTP/gRPC requests. Default 300 (for add-bm25 on large collections)."""
    v = (os.environ.get("QDRANT_TIMEOUT") or "").strip()
    if not v:
        return QDRANT_TIMEOUT_DEFAULT
    try:
        return max(5, int(v))
    except ValueError:
        return QDRANT_TIMEOUT_DEFAULT
