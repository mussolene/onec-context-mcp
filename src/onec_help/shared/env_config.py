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
HELP_SOURCE_BASE_DEFAULT = ""
HELP_LANGUAGES_DEFAULT = "ru"
HELP_FILE_ENCODING_DEFAULT = ""
HELP_HTML_MAX_BYTES_DEFAULT = 10 * 1024 * 1024  # 10 MB


def get_help_source_base() -> str:
    """Root dir for versioned .hbk (e.g. /opt/1cv8)."""
    return (os.environ.get("HELP_SOURCE_BASE") or HELP_SOURCE_BASE_DEFAULT).strip()


def get_help_languages() -> str:
    """Comma-separated languages for ingest (ru, en). Default: ru."""
    return (os.environ.get("HELP_LANGUAGES") or HELP_LANGUAGES_DEFAULT).strip()


def get_help_source_dirs() -> str:
    """Comma-separated paths alternative to HELP_SOURCE_BASE."""
    return (os.environ.get("HELP_SOURCE_DIRS") or "").strip()


def get_help_file_encoding() -> str:
    """Encoding for help files (utf-8, cp1251). Empty = auto."""
    return (os.environ.get("HELP_FILE_ENCODING") or HELP_FILE_ENCODING_DEFAULT).strip().lower()


def get_help_html_max_bytes() -> int:
    """Max HTML file size in bytes. Default 10 MB."""
    v = (os.environ.get("HELP_HTML_MAX_BYTES") or "").strip()
    if not v:
        return HELP_HTML_MAX_BYTES_DEFAULT
    try:
        return max(1024 * 100, int(v))
    except ValueError:
        return HELP_HTML_MAX_BYTES_DEFAULT


# --- Redis ---
REDIS_URL_DEFAULT = ""
REDIS_HOST_DEFAULT = ""
REDIS_PORT_DEFAULT = 6379
REDIS_URL_FALLBACK_DEFAULT = "redis://localhost:6379/0"


def get_redis_url() -> str:
    """Redis URL. Empty = use REDIS_HOST+REDIS_PORT or fallback."""
    return (os.environ.get("REDIS_URL") or REDIS_URL_DEFAULT).strip()


def get_redis_host() -> str:
    """Redis host when REDIS_URL not set."""
    return (os.environ.get("REDIS_HOST") or REDIS_HOST_DEFAULT).strip()


def get_redis_port() -> int:
    """Redis port when REDIS_HOST set."""
    try:
        return int(os.environ.get("REDIS_PORT", str(REDIS_PORT_DEFAULT)))
    except ValueError:
        return REDIS_PORT_DEFAULT


def get_redis_url_fallback() -> str:
    """URL used when REDIS_URL and REDIS_HOST both unset."""
    return REDIS_URL_FALLBACK_DEFAULT


# --- Embedding (same defaults as docker-compose and embedding.py) ---
EMBEDDING_BACKEND_DEFAULT = "openai_api"
EMBEDDING_MODEL_DEFAULT = "nomic-embed-text-v2-moe"
EMBEDDING_API_URL_DEFAULT = "http://localhost:11434/v1"
EMBEDDING_API_KEY_DEFAULT = ""
EMBEDDING_DIMENSION_DEFAULT = ""
EMBEDDING_TIMEOUT_DEFAULT = 180
EMBEDDING_BATCH_SIZE_DEFAULT = 32
EMBEDDING_WORKERS_DEFAULT = 6
EMBEDDING_FORCE_BATCH_DEFAULT = "0"
EMBEDDING_CACHE_SIZE_DEFAULT = "10000"


def get_embedding_backend() -> str:
    return (os.environ.get("EMBEDDING_BACKEND") or EMBEDDING_BACKEND_DEFAULT).strip().lower()


def get_embedding_model() -> str:
    return (os.environ.get("EMBEDDING_MODEL") or EMBEDDING_MODEL_DEFAULT).strip()


def get_embedding_api_url() -> str:
    v = (os.environ.get("EMBEDDING_API_URL") or "").strip().rstrip("/")
    return v or EMBEDDING_API_URL_DEFAULT


def get_embedding_api_key() -> str:
    return (os.environ.get("EMBEDDING_API_KEY") or EMBEDDING_API_KEY_DEFAULT).strip()


def get_embedding_dimension_env() -> str:
    """Raw env value; empty = determine from model/API/Qdrant."""
    return (os.environ.get("EMBEDDING_DIMENSION") or EMBEDDING_DIMENSION_DEFAULT).strip()


def get_embedding_timeout() -> int:
    try:
        return max(5, int(os.environ.get("EMBEDDING_TIMEOUT", str(EMBEDDING_TIMEOUT_DEFAULT))))
    except ValueError:
        return EMBEDDING_TIMEOUT_DEFAULT


def get_embedding_batch_timeout_raw() -> str:
    """Raw env; empty = use formula in embedding module."""
    return (os.environ.get("EMBEDDING_BATCH_TIMEOUT") or "").strip()


def get_embedding_force_batch() -> bool:
    v = (os.environ.get("EMBEDDING_FORCE_BATCH") or EMBEDDING_FORCE_BATCH_DEFAULT).strip().lower()
    return v in ("1", "true", "yes", "on")


def get_embedding_batch_size_default() -> int:
    try:
        return max(
            1,
            min(
                256, int(os.environ.get("EMBEDDING_BATCH_SIZE", str(EMBEDDING_BATCH_SIZE_DEFAULT)))
            ),
        )
    except ValueError:
        return EMBEDDING_BATCH_SIZE_DEFAULT


def get_embedding_workers_default() -> int:
    try:
        return max(
            1, min(150, int(os.environ.get("EMBEDDING_WORKERS", str(EMBEDDING_WORKERS_DEFAULT))))
        )
    except ValueError:
        return EMBEDDING_WORKERS_DEFAULT


def get_embedding_max_concurrent_raw() -> str:
    return (os.environ.get("EMBEDDING_MAX_CONCURRENT") or "").strip()


def get_embedding_cache_size() -> str:
    return (os.environ.get("EMBEDDING_CACHE_SIZE") or EMBEDDING_CACHE_SIZE_DEFAULT).strip()


# --- BM25 ---
BM25_ENABLED_DEFAULT = "1"
BM25_STEMMING_DEFAULT = "1"


def get_bm25_enabled() -> bool:
    v = (os.environ.get("BM25_ENABLED") or BM25_ENABLED_DEFAULT).strip().lower()
    return v in ("1", "true", "yes")


def get_bm25_stemming() -> bool:
    v = (os.environ.get("BM25_STEMMING") or BM25_STEMMING_DEFAULT).strip().lower()
    return v in ("1", "true", "yes")


# --- Unpack ---
UNPACK_TIMEOUT_DEFAULT = 1800


def get_unpack_timeout() -> int:
    v = (os.environ.get("UNPACK_TIMEOUT") or str(UNPACK_TIMEOUT_DEFAULT)).strip()
    try:
        return max(60, int(v))
    except ValueError:
        return UNPACK_TIMEOUT_DEFAULT


# --- Index status ---
INDEX_STATUS_SAMPLE_SIZE_DEFAULT = 100
INDEX_STATUS_INTERVAL_SEC_DEFAULT = 2.0


def get_index_status_sample_size() -> int:
    try:
        return max(
            50,
            min(
                2000,
                int(
                    os.environ.get(
                        "INDEX_STATUS_SAMPLE_SIZE", str(INDEX_STATUS_SAMPLE_SIZE_DEFAULT)
                    )
                ),
            ),
        )
    except ValueError:
        return INDEX_STATUS_SAMPLE_SIZE_DEFAULT


def get_index_status_interval_sec() -> float:
    try:
        return max(
            0.5,
            float(
                os.environ.get("INDEX_STATUS_INTERVAL_SEC", str(INDEX_STATUS_INTERVAL_SEC_DEFAULT))
            ),
        )
    except ValueError:
        return INDEX_STATUS_INTERVAL_SEC_DEFAULT


# --- ITS / v8std ---
ITS_V8STD_MAX_BROWSE_PAGES_DEFAULT = 0
ITS_V8STD_DELAY_DEFAULT = 0.5
ITS_AUTH_COOKIE_DEFAULT = ""


def get_its_v8std_max_browse_pages() -> int:
    try:
        return max(
            0,
            int(
                os.environ.get(
                    "ITS_V8STD_MAX_BROWSE_PAGES", str(ITS_V8STD_MAX_BROWSE_PAGES_DEFAULT)
                )
            ),
        )
    except ValueError:
        return ITS_V8STD_MAX_BROWSE_PAGES_DEFAULT


def get_its_v8std_delay() -> float:
    try:
        return max(0.0, float(os.environ.get("ITS_V8STD_DELAY", str(ITS_V8STD_DELAY_DEFAULT))))
    except ValueError:
        return ITS_V8STD_DELAY_DEFAULT


def get_its_auth_cookie() -> str:
    return (os.environ.get("ITS_AUTH_COOKIE") or ITS_AUTH_COOKIE_DEFAULT).strip()


def get_standards_its_v8std() -> bool:
    v = (os.environ.get("STANDARDS_ITS_V8STD") or "").strip().lower()
    return v in ("1", "true", "yes")


def get_its_v8std_max_content_raw() -> str:
    return (os.environ.get("ITS_V8STD_MAX_CONTENT") or "").strip()


# --- MCP ---
MCP_TRANSPORT_DEFAULT = "multi"
MCP_HOST_DEFAULT = "0.0.0.0"
MCP_PORT_DEFAULT = 8050
MCP_PATH_DEFAULT = "/mcp"
MCP_SNIPPET_MAX_CHARS_DEFAULT = 1200
MCP_MAX_TOPIC_CHARS_DEFAULT = 4000
MCP_RATE_LIMIT_PER_MIN_DEFAULT = 6000


def get_mcp_transport() -> str:
    return (os.environ.get("MCP_TRANSPORT") or MCP_TRANSPORT_DEFAULT).strip()


def get_mcp_host() -> str:
    return (os.environ.get("MCP_HOST") or MCP_HOST_DEFAULT).strip()


def get_mcp_port() -> int:
    v = os.environ.get("MCP_PORT", str(MCP_PORT_DEFAULT))
    try:
        return int(v)
    except ValueError:
        return MCP_PORT_DEFAULT


def get_mcp_path() -> str:
    return (os.environ.get("MCP_PATH") or MCP_PATH_DEFAULT).strip()


def get_mcp_snippet_max_chars() -> int:
    try:
        v = int(os.environ.get("MCP_SNIPPET_MAX_CHARS", str(MCP_SNIPPET_MAX_CHARS_DEFAULT)))
        return max(100, min(5000, v))
    except (TypeError, ValueError):
        return MCP_SNIPPET_MAX_CHARS_DEFAULT


def get_mcp_max_topic_chars() -> int:
    try:
        v = int(os.environ.get("MCP_MAX_TOPIC_CHARS", str(MCP_MAX_TOPIC_CHARS_DEFAULT)))
        return max(500, min(50000, v))
    except (TypeError, ValueError):
        return MCP_MAX_TOPIC_CHARS_DEFAULT


def get_mcp_rate_limit_per_min() -> int:
    """0 = disabled."""
    try:
        return int(os.environ.get("MCP_RATE_LIMIT_PER_MIN", str(MCP_RATE_LIMIT_PER_MIN_DEFAULT)))
    except ValueError:
        return MCP_RATE_LIMIT_PER_MIN_DEFAULT


def get_mcp_metrics_db() -> str:
    """Path to SQLite for MCP metrics. Empty = do not persist."""
    return (os.environ.get("MCP_METRICS_DB") or "").strip()


# --- Ingest ---
INGEST_FAILED_LOG_DEFAULT = ""
INGEST_SKIP_CACHE_DEFAULT = "0"
INGEST_TEMP_DIR_DEFAULT = ""
INGEST_USE_TEMP_DEFAULT = "0"
INGEST_MAX_WORKERS_DEFAULT = 4
HBK_LABELS_DEFAULT = ""


def get_ingest_failed_log() -> str:
    return (os.environ.get("INGEST_FAILED_LOG") or INGEST_FAILED_LOG_DEFAULT).strip()


def get_ingest_skip_cache() -> bool:
    v = (os.environ.get("INGEST_SKIP_CACHE") or INGEST_SKIP_CACHE_DEFAULT).strip().lower()
    return v in ("1", "true", "yes")


def get_ingest_temp_dir() -> str:
    return (os.environ.get("INGEST_TEMP_DIR") or INGEST_TEMP_DIR_DEFAULT).strip()


def get_ingest_use_temp() -> bool:
    v = (os.environ.get("INGEST_USE_TEMP") or INGEST_USE_TEMP_DEFAULT).strip().lower()
    return v in ("1", "true", "yes")


def get_ingest_max_workers() -> int:
    v = (os.environ.get("INGEST_MAX_WORKERS") or str(INGEST_MAX_WORKERS_DEFAULT)).strip()
    try:
        return max(1, int(v))
    except ValueError:
        return INGEST_MAX_WORKERS_DEFAULT


def get_hbk_labels() -> str:
    return (os.environ.get("HBK_LABELS") or HBK_LABELS_DEFAULT).strip()


# --- Snippets / metadata graph ---
SNIPPETS_DIR_DEFAULT = "data/snippets"
SAVE_SNIPPET_TO_FILES_DEFAULT = "1"
SNIPPETS_JSON_PATH_DEFAULT = ""
SNIPPETS_SKIP_CACHE_DEFAULT = "0"
CONFIG_SOURCE_DIR_DEFAULT = "data/kd2_snapshot"


def get_snippets_dir() -> str:
    return (os.environ.get("SNIPPETS_DIR") or SNIPPETS_DIR_DEFAULT).strip()


def get_snippets_json_path() -> str:
    return (os.environ.get("SNIPPETS_JSON_PATH") or SNIPPETS_JSON_PATH_DEFAULT).strip()


def get_snippets_skip_cache() -> bool:
    v = (os.environ.get("SNIPPETS_SKIP_CACHE") or SNIPPETS_SKIP_CACHE_DEFAULT).strip().lower()
    return v in ("1", "true", "yes")


def get_save_snippet_to_files() -> bool:
    v = (os.environ.get("SAVE_SNIPPET_TO_FILES") or SAVE_SNIPPET_TO_FILES_DEFAULT).strip().lower()
    return v in ("1", "true", "yes")


def get_config_source_dir() -> str:
    """Metadata source path for metadata graph.

    Primary route: KD2 snapshot dir (default).
    Also supports KD2 XML file path and deprecated file-export config dir.
    Uses ONEC_CONFIG_SOURCE_DIR env var; falls back to data/kd2_snapshot when unset.
    """

    return (os.environ.get("ONEC_CONFIG_SOURCE_DIR") or CONFIG_SOURCE_DIR_DEFAULT).strip()


# --- Standards ---
STANDARDS_REPOS_DEFAULT = ""
STANDARDS_SUBPATH_DEFAULT = "docs"
STANDARDS_BRANCH_DEFAULT = "master"
STANDARDS_DIR_DEFAULT = "data/standards"


def get_standards_repos() -> str:
    return (os.environ.get("STANDARDS_REPOS") or STANDARDS_REPOS_DEFAULT).strip()


def get_standards_subpath() -> str:
    return (os.environ.get("STANDARDS_SUBPATH") or STANDARDS_SUBPATH_DEFAULT).strip() or "docs"


def get_standards_branch() -> str:
    return (os.environ.get("STANDARDS_BRANCH") or STANDARDS_BRANCH_DEFAULT).strip() or "master"


def get_standards_dir() -> str:
    return (os.environ.get("STANDARDS_DIR") or STANDARDS_DIR_DEFAULT).strip()


# --- Memory ---
MEMORY_ENABLED_DEFAULT = "0"
MEMORY_BASE_PATH_DEFAULT = ""
MEMORY_SHORT_LIMIT_DEFAULT = 50
MEMORY_MEDIUM_LIMIT_DEFAULT = 500
MEMORY_MEDIUM_TTL_DAYS_DEFAULT = 7


def get_memory_enabled() -> bool:
    v = (os.environ.get("MEMORY_ENABLED") or MEMORY_ENABLED_DEFAULT).strip().lower()
    return v in ("1", "true", "yes", "on")


def get_memory_base_path() -> str:
    return (os.environ.get("MEMORY_BASE_PATH") or MEMORY_BASE_PATH_DEFAULT).strip()


def get_memory_short_limit() -> int:
    try:
        return max(1, int(os.environ.get("MEMORY_SHORT_LIMIT", str(MEMORY_SHORT_LIMIT_DEFAULT))))
    except ValueError:
        return MEMORY_SHORT_LIMIT_DEFAULT


def get_memory_medium_limit() -> int:
    try:
        return max(1, int(os.environ.get("MEMORY_MEDIUM_LIMIT", str(MEMORY_MEDIUM_LIMIT_DEFAULT))))
    except ValueError:
        return MEMORY_MEDIUM_LIMIT_DEFAULT


def get_memory_medium_ttl_days() -> int:
    try:
        return max(
            1, int(os.environ.get("MEMORY_MEDIUM_TTL_DAYS", str(MEMORY_MEDIUM_TTL_DAYS_DEFAULT)))
        )
    except ValueError:
        return MEMORY_MEDIUM_TTL_DAYS_DEFAULT


# --- Watchdog ---
# Сниженный порог по умолчанию (2 мин), чтобы папки (hbk, standards, snippets, config) проверялись чаще.
WATCHDOG_POLL_INTERVAL_DEFAULT = 120
WATCHDOG_PENDING_INTERVAL_DEFAULT = 120
WATCHDOG_INGEST_TIMEOUT_DEFAULT = 10800


def get_watchdog_poll_interval() -> int:
    try:
        return max(
            30, int(os.environ.get("WATCHDOG_POLL_INTERVAL", str(WATCHDOG_POLL_INTERVAL_DEFAULT)))
        )
    except ValueError:
        return WATCHDOG_POLL_INTERVAL_DEFAULT


def get_watchdog_pending_interval() -> int:
    try:
        return max(
            30,
            int(
                os.environ.get("WATCHDOG_PENDING_INTERVAL", str(WATCHDOG_PENDING_INTERVAL_DEFAULT))
            ),
        )
    except ValueError:
        return WATCHDOG_PENDING_INTERVAL_DEFAULT


def get_watchdog_ingest_timeout() -> int:
    try:
        v = (
            os.environ.get("WATCHDOG_INGEST_TIMEOUT") or str(WATCHDOG_INGEST_TIMEOUT_DEFAULT)
        ).strip()
        return max(0, int(v))
    except (ValueError, TypeError):
        return WATCHDOG_INGEST_TIMEOUT_DEFAULT


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


# --- Production / utils ---
PRODUCTION_DEFAULT = "0"


def get_production() -> bool:
    return (os.environ.get("PRODUCTION") or PRODUCTION_DEFAULT).strip().lower() in (
        "1",
        "true",
        "yes",
    )
