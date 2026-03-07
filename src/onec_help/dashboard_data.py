"""Dashboard data aggregation: ingest, Qdrant, snippets, standards/snippets loading markers.
No Rich dependency; pure data for render_dashboard()."""

import json
import os
from pathlib import Path
from typing import Any

from .indexer import get_all_collections_status, get_index_status
from .ingest import (
    _ingest_cache_path,
    read_ingest_failed_log,
    read_ingest_status,
    read_last_ingest_failed,
    read_last_ingest_run,
)
from .mcp_metrics import get_metrics as get_mcp_metrics
from .snippets_cache import read_last_snippets_run

# Markers older than this (seconds) are treated as stale (crashed process); don't show "loading"
_LOAD_MARKER_STALE_SEC = 600  # 10 min


def _load_marker_exists(name: str) -> bool:
    """True if load_<name>.running marker exists and is not stale (recent mtime)."""
    try:
        import time

        cache_dir = Path(_ingest_cache_path()).parent
        path = cache_dir / f"load_{name}.running"
        if not path.exists():
            return False
        try:
            mtime = path.stat().st_mtime
            if (time.time() - mtime) > _LOAD_MARKER_STALE_SEC:
                return False  # stale: process likely crashed without removing marker
        except OSError:
            return False
        return True
    except Exception:
        return False


def _read_load_status(name: str) -> dict[str, Any] | None:
    """Read load_<name>.status.json (loaded, total, phase?). phase: 'parsing' | 'embedding'."""
    try:
        cache_dir = Path(_ingest_cache_path()).parent
        path = cache_dir / f"load_{name}.status.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        out: dict[str, Any] = {}
        if "loaded" in data and "total" in data:
            out["loaded"] = int(data["loaded"])
            out["total"] = int(data["total"])
        if "phase" in data and isinstance(data["phase"], str):
            out["phase"] = data["phase"]
        if out:
            return out
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def _storage_path_mb() -> float | None:
    """DB size in MB from QDRANT_STORAGE_PATH if set and dir exists."""
    path = os.environ.get("QDRANT_STORAGE_PATH")
    if not path or not os.path.isdir(path):
        return None
    try:
        from ._utils import dir_size_on_disk

        return round(dir_size_on_disk(path) / (1024 * 1024), 1)
    except OSError:
        return None


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
    if not failed_tasks and (ingest_last_run or {}).get("failed_count", 0) > 0:
        failed_tasks = read_ingest_failed_log(limit=failed_tasks_limit)
    index_status = get_index_status(qdrant_host=qdrant_host, qdrant_port=qdrant_port)
    collections = get_all_collections_status(qdrant_host=qdrant_host, qdrant_port=qdrant_port)
    snippets_last = read_last_snippets_run()
    standards_loading = _load_marker_exists("standards")
    snippets_loading = _load_marker_exists("snippets")
    standards_loading_pts = _read_load_status("standards") if standards_loading else None
    snippets_loading_pts = _read_load_status("snippets") if snippets_loading else None
    storage_path_mb = _storage_path_mb()
    mcp_metrics = get_mcp_metrics()

    return {
        "ingest": ingest_current,
        "ingest_last_run": ingest_last_run,
        "failed_tasks": failed_tasks,
        "index_status": index_status,
        "collections": collections,
        "snippets": snippets_last,
        "standards_loading": standards_loading,
        "snippets_loading": snippets_loading,
        "standards_loading_pts": standards_loading_pts,
        "snippets_loading_pts": snippets_loading_pts,
        "storage_path_mb": storage_path_mb,
        "mcp_metrics": mcp_metrics,
    }
