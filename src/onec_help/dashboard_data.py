"""Dashboard data aggregation: ingest, Qdrant, snippets, standards/snippets loading markers.
No Rich dependency; pure data for render_dashboard()."""

from pathlib import Path
from typing import Any

from .ingest import (
    _ingest_cache_path,
    read_ingest_status,
    read_last_ingest_failed,
    read_last_ingest_run,
)
from .indexer import get_all_collections_status, get_index_status
from .snippets_cache import read_last_snippets_run


def _load_marker_exists(name: str) -> bool:
    """True if load_<name>.running marker exists in ingest cache dir."""
    try:
        cache_dir = Path(_ingest_cache_path()).parent
        return (cache_dir / f"load_{name}.running").exists()
    except Exception:
        return False


def get_dashboard_data(
    *,
    failed_tasks_limit: int = 20,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
) -> dict[str, Any]:
    """Aggregate data for dashboard: ingest, collections, index_status, snippets, loading flags, failed_tasks."""
    ingest_current = read_ingest_status()
    ingest_last_run = read_last_ingest_run()
    failed_tasks = read_last_ingest_failed(limit=failed_tasks_limit)
    index_status = get_index_status(qdrant_host=qdrant_host, qdrant_port=qdrant_port)
    collections = get_all_collections_status(qdrant_host=qdrant_host, qdrant_port=qdrant_port)
    snippets_last = read_last_snippets_run()
    standards_loading = _load_marker_exists("standards")
    snippets_loading = _load_marker_exists("snippets")

    return {
        "ingest": ingest_current,
        "ingest_last_run": ingest_last_run,
        "failed_tasks": failed_tasks,
        "index_status": index_status,
        "collections": collections,
        "snippets": snippets_last,
        "standards_loading": standards_loading,
        "snippets_loading": snippets_loading,
    }
