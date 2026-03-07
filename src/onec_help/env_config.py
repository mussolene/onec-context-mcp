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


# --- Help sources (single name: HELP_SOURCE_BASE; HELP_SOURCES_DIR is legacy alias) ---
def get_help_source_base() -> str:
    """Root dir for versioned .hbk (e.g. /opt/1cv8). HELP_SOURCES_DIR is deprecated alias."""
    return (os.environ.get("HELP_SOURCE_BASE") or os.environ.get("HELP_SOURCES_DIR") or "").strip()


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
