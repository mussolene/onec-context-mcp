"""Redis backend for ingest cache and status. Replaces SQLite when running with ingest-worker and mcp.

Keys: ingest:cache (hash), ingest:current, ingest:run:next_id, ingest:runs (list), ingest:run:{id}, ingest:failed:{id};
      snippets:cache (hash), snippets:last_run.
REDIS_URL or REDIS_HOST required. Used by ingest.py and snippets_cache.py.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

_LOG = logging.getLogger(__name__)

_INGEST_CACHE = "ingest:cache"
_INGEST_CURRENT = "ingest:current"
_INGEST_RUN_NEXT = "ingest:run:next_id"
_INGEST_RUNS_LIST = "ingest:runs"
_INGEST_RUN_PREFIX = "ingest:run:"
_INGEST_FAILED_PREFIX = "ingest:failed:"
_INGEST_ERRORS_LOG = "ingest:errors"
_INGEST_ERRORS_MAX = 200
_INGEST_RUNS_LIMIT = 20

_SNIPPETS_CACHE = "snippets:cache"
_SNIPPETS_LAST_RUN = "snippets:last_run"

_client: Any = None


def get_redis():
    """Return Redis client. Uses REDIS_URL or REDIS_HOST+REDIS_PORT. Cached. Raises if Redis unavailable."""
    global _client
    if _client is not None:
        return _client
    try:
        import redis as redis_mod
    except ImportError as e:
        raise RuntimeError(
            "Redis required for ingest cache. Install: pip install redis. Set REDIS_URL or REDIS_HOST."
        ) from e
    url = os.environ.get("REDIS_URL", "").strip()
    if url:
        _client = redis_mod.from_url(url, decode_responses=True)
    else:
        host = os.environ.get("REDIS_HOST", "").strip()
        if not host:
            raise RuntimeError("REDIS_URL or REDIS_HOST required for ingest cache.")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        _client = redis_mod.Redis(host=host, port=port, decode_responses=True)
    _client.ping()
    return _client


def clear_all() -> bool:
    """Delete all ingest, snippets and watchdog keys. Returns True on success."""
    try:
        r = get_redis()
        keys = (
            list(r.scan_iter(match="ingest:*"))
            + list(r.scan_iter(match="snippets:*"))
            + list(r.scan_iter(match="watchdog:*"))
        )
        if keys:
            r.delete(*keys)
        return True
    except Exception as e:
        _LOG.warning("redis_cache clear_all failed: %s", e)
        return False


# --- Ingest cache (which files indexed) ---


def ingest_cache_get_all() -> dict[str, dict[str, Any]]:
    """Return dict key -> {hash, indexed, points}. Same shape as _load_ingest_cache."""
    out: dict[str, dict[str, Any]] = {}
    try:
        r = get_redis()
        raw = r.hgetall(_INGEST_CACHE) or {}
        for k, v in raw.items():
            try:
                obj = json.loads(v)
                out[k] = {
                    "hash": obj.get("hash", ""),
                    "indexed": bool(obj.get("indexed", True)),
                    "points": int(obj.get("points", 0)),
                }
            except (TypeError, ValueError):
                pass
    except Exception as e:
        _LOG.debug("ingest_cache_get_all: %s", e)
    return out


def ingest_cache_get_indexed_set() -> set[tuple[str, str, str]]:
    """Set of (version, language, hash) for indexed entries."""
    out: set[tuple[str, str, str]] = set()
    try:
        r = get_redis()
        raw = r.hgetall(_INGEST_CACHE) or {}
        for k, v in raw.items():
            try:
                obj = json.loads(v)
                if not obj.get("indexed", True) or not obj.get("hash"):
                    continue
                parts = k.split("|", 1)[0].split("/")
                if len(parts) >= 2:
                    out.add((parts[0], parts[1], obj["hash"]))
            except (TypeError, ValueError, KeyError):
                pass
    except Exception as e:
        _LOG.debug("ingest_cache_get_indexed_set: %s", e)
    return out


def ingest_cache_set_entry(key: str, file_hash: str, points: int) -> None:
    """Set one cache entry (indexed=1)."""
    try:
        r = get_redis()
        val = json.dumps({"hash": file_hash, "indexed": 1, "points": points})
        r.hset(_INGEST_CACHE, key, val)
    except Exception as e:
        _LOG.debug("ingest_cache_set_entry: %s", e)


def ingest_cache_entries(limit: int = 100) -> list[dict[str, Any]]:
    """List of cached indexed files for display. Each item: {path, version, language, points, status}."""
    entries: list[dict[str, Any]] = []
    try:
        r = get_redis()
        raw = r.hgetall(_INGEST_CACHE) or {}
        for key, v in raw.items():
            if len(entries) >= limit:
                break
            try:
                obj = json.loads(v)
                if not obj.get("indexed", True):
                    continue
                parts = key.split("/", 2)
                version = parts[0] if len(parts) > 0 else ""
                language = parts[1] if len(parts) > 1 else ""
                path_name = parts[2] if len(parts) > 2 else key
                entries.append(
                    {
                        "path": path_name,
                        "version": version,
                        "language": language,
                        "points": int(obj.get("points", 0)),
                        "status": "cached",
                    }
                )
            except (TypeError, ValueError, KeyError):
                pass
        entries.sort(key=lambda x: (x.get("version", ""), x.get("language", ""), x.get("path", "")))
    except Exception as e:
        _LOG.debug("ingest_cache_entries: %s", e)
    return entries[:limit]


# --- Ingest current status ---


def ingest_current_set(payload: dict[str, Any], ttl_sec: int = 3600) -> None:
    """Write current run status. TTL so key expires if worker dies."""
    try:
        r = get_redis()
        r.set(_INGEST_CURRENT, json.dumps(payload, ensure_ascii=False), ex=ttl_sec)
    except Exception as e:
        _LOG.debug("ingest_current_set: %s", e)


def ingest_current_get() -> dict[str, Any] | None:
    """Read current status. Returns None if missing or invalid."""
    try:
        r = get_redis()
        raw = r.get(_INGEST_CURRENT)
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict) or "status" not in data:
            return None
        if data.get("status") == "in_progress":
            started = data.get("started_at_ts")
            if isinstance(started, (int, float)):
                data = {**data, "elapsed_sec": round(time.time() - started, 1)}
        return data
    except Exception as e:
        _LOG.debug("ingest_current_get: %s", e)
        return None


# --- Ingest runs and failed ---


def ingest_run_create(started_at: float, embedding_backend: str, total_tasks: int) -> int | None:
    """Create new run row; return run_id. Returns None on error."""
    try:
        r = get_redis()
        run_id = r.incr(_INGEST_RUN_NEXT)
        row = {
            "started_at": started_at,
            "finished_at": started_at,
            "status": "in_progress",
            "total_tasks": total_tasks,
            "done_tasks": 0,
            "total_points": 0,
            "failed_count": 0,
            "embedding_backend": embedding_backend or "none",
            "total_elapsed_sec": None,
        }
        r.set(f"{_INGEST_RUN_PREFIX}{run_id}", json.dumps(row))
        r.lpush(_INGEST_RUNS_LIST, str(run_id))
        r.ltrim(_INGEST_RUNS_LIST, 0, _INGEST_RUNS_LIMIT - 1)
        return run_id
    except Exception as e:
        _LOG.warning("ingest_run_create failed: %s", e)
        return None


def ingest_run_update(
    run_id: int,
    finished_at: float,
    status: str,
    done_tasks: int,
    total_points: int,
    failed_count: int,
    total_elapsed_sec: float | None,
) -> None:
    """Update run row on completion."""
    try:
        r = get_redis()
        raw = r.get(f"{_INGEST_RUN_PREFIX}{run_id}")
        if not raw:
            return
        row = json.loads(raw)
        row["finished_at"] = finished_at
        row["status"] = status
        row["done_tasks"] = done_tasks
        row["total_points"] = total_points
        row["failed_count"] = failed_count
        row["total_elapsed_sec"] = total_elapsed_sec
        r.set(f"{_INGEST_RUN_PREFIX}{run_id}", json.dumps(row))
    except Exception as e:
        _LOG.debug("ingest_run_update: %s", e)


def ingest_run_append_failed(
    run_id: int,
    version: str,
    language: str,
    path: str,
    error: str,
) -> None:
    """Append one failed task to run."""
    try:
        r = get_redis()
        key = f"{_INGEST_FAILED_PREFIX}{run_id}"
        item = json.dumps({"version": version, "language": language, "path": path, "error": error[:500]})
        r.rpush(key, item)
    except Exception as e:
        _LOG.debug("ingest_run_append_failed: %s", e)


def ingest_last_run() -> dict[str, Any] | None:
    """Last run (any status). Same shape as read_last_ingest_run."""
    try:
        r = get_redis()
        run_ids = r.lrange(_INGEST_RUNS_LIST, 0, 0)
        if not run_ids:
            return None
        raw = r.get(f"{_INGEST_RUN_PREFIX}{run_ids[0]}")
        if not raw:
            return None
        row = json.loads(raw)
        return {
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "status": row.get("status", ""),
            "total_tasks": row.get("total_tasks", 0),
            "done_tasks": row.get("done_tasks", 0),
            "total_points": row.get("total_points", 0),
            "failed_count": row.get("failed_count", 0),
            "embedding_backend": row.get("embedding_backend"),
            "total_elapsed_sec": row.get("total_elapsed_sec"),
            "finished_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(row["finished_at"]))
            if row.get("finished_at")
            else None,
        }
    except Exception as e:
        _LOG.debug("ingest_last_run: %s", e)
        return None


def ingest_last_failed(limit: int = 20) -> list[dict[str, str]]:
    """Failed tasks for the latest run. Same shape as read_last_ingest_failed."""
    try:
        r = get_redis()
        run_ids = r.lrange(_INGEST_RUNS_LIST, 0, 0)
        if not run_ids:
            return []
        key = f"{_INGEST_FAILED_PREFIX}{run_ids[0]}"
        items = r.lrange(key, 0, limit - 1) or []
        out = []
        for raw in items:
            try:
                obj = json.loads(raw)
                out.append(
                    {
                        "version": obj.get("version", ""),
                        "language": obj.get("language", ""),
                        "path": obj.get("path", ""),
                        "error": (obj.get("error") or "")[:500],
                    }
                )
            except (TypeError, ValueError):
                pass
        return out
    except Exception as e:
        _LOG.debug("ingest_last_failed: %s", e)
        return []


def ingest_errors_append(version: str, language: str, path: str, error: str) -> None:
    """Append one error to the accumulated log (ingest:errors). Kept for dashboard and always available."""
    try:
        r = get_redis()
        item = json.dumps(
            {
                "version": (version or "")[:32],
                "language": (language or "")[:16],
                "path": (path or "")[:500],
                "error": (error or "")[:500],
                "ts": time.time(),
            },
            ensure_ascii=False,
        )
        r.lpush(_INGEST_ERRORS_LOG, item)
        r.ltrim(_INGEST_ERRORS_LOG, 0, _INGEST_ERRORS_MAX - 1)
    except Exception as e:
        _LOG.debug("ingest_errors_append: %s", e)


def ingest_errors_list(limit: int = 50) -> list[dict[str, str]]:
    """Return last N errors from accumulated log. Same shape as read_last_ingest_failed for dashboard."""
    try:
        r = get_redis()
        items = r.lrange(_INGEST_ERRORS_LOG, 0, limit - 1) or []
        out = []
        for raw in items:
            try:
                obj = json.loads(raw)
                out.append(
                    {
                        "version": obj.get("version", ""),
                        "language": obj.get("language", ""),
                        "path": obj.get("path", ""),
                        "error": (obj.get("error") or "")[:500],
                    }
                )
            except (TypeError, ValueError):
                pass
        return out
    except Exception as e:
        _LOG.debug("ingest_errors_list: %s", e)
        return []


def ingest_trim_old_runs() -> None:
    """Keep only last _INGEST_RUNS_LIMIT run ids; delete older run and failed keys."""
    try:
        r = get_redis()
        run_ids = r.lrange(_INGEST_RUNS_LIST, 0, -1)
        if len(run_ids) <= _INGEST_RUNS_LIMIT:
            return
        to_del = run_ids[_INGEST_RUNS_LIMIT:]
        for rid in to_del:
            r.delete(f"{_INGEST_RUN_PREFIX}{rid}", f"{_INGEST_FAILED_PREFIX}{rid}")
        r.ltrim(_INGEST_RUNS_LIST, 0, _INGEST_RUNS_LIMIT - 1)
    except Exception as e:
        _LOG.debug("ingest_trim_old_runs: %s", e)


# --- Snippets cache ---


def snippets_cache_get_all() -> dict[str, dict[str, Any]]:
    """Dict source_key -> {signature, loaded_at, items_count}."""
    out: dict[str, dict[str, Any]] = {}
    try:
        r = get_redis()
        raw = r.hgetall(_SNIPPETS_CACHE) or {}
        for k, v in raw.items():
            try:
                obj = json.loads(v)
                out[k] = {
                    "signature": obj.get("signature", ""),
                    "loaded_at": obj.get("loaded_at", 0),
                    "items_count": obj.get("items_count", 0),
                }
            except (TypeError, ValueError):
                pass
    except Exception as e:
        _LOG.debug("snippets_cache_get_all: %s", e)
    return out


def snippets_cache_set(source_key: str, signature: str, items_count: int) -> None:
    """Record successful load of a source."""
    try:
        r = get_redis()
        val = json.dumps(
            {"signature": signature, "loaded_at": time.time(), "items_count": items_count}
        )
        r.hset(_SNIPPETS_CACHE, source_key, val)
    except Exception as e:
        _LOG.debug("snippets_cache_set: %s", e)


def snippets_run_record(
    files_processed: int,
    files_skipped: int,
    items_loaded: int,
    started_at: float,
) -> None:
    """Record last snippets run (single key, overwrite)."""
    try:
        r = get_redis()
        row = {
            "started_at": started_at,
            "finished_at": time.time(),
            "files_processed": files_processed,
            "files_skipped": files_skipped,
            "items_loaded": items_loaded,
        }
        r.set(_SNIPPETS_LAST_RUN, json.dumps(row))
    except Exception as e:
        _LOG.debug("snippets_run_record: %s", e)


def snippets_last_run() -> dict[str, Any] | None:
    """Last snippets run for dashboard."""
    try:
        r = get_redis()
        raw = r.get(_SNIPPETS_LAST_RUN)
        if not raw:
            return None
        row = json.loads(raw)
        return {
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "files_processed": row.get("files_processed", 0),
            "files_skipped": row.get("files_skipped", 0),
            "items_loaded": row.get("items_loaded", 0),
            "total_elapsed_sec": (row.get("finished_at") or 0) - (row.get("started_at") or 0)
            if row.get("finished_at") and row.get("started_at")
            else None,
        }
    except Exception as e:
        _LOG.debug("snippets_last_run: %s", e)
        return None


def snippets_cache_entries(limit: int = 50) -> list[dict[str, Any]]:
    """Cached sources for display. Each item: {path, source, loaded_at, items_count, status}."""
    entries: list[dict[str, Any]] = []
    try:
        r = get_redis()
        raw = r.hgetall(_SNIPPETS_CACHE) or {}
        for source_key, v in raw.items():
            if len(entries) >= limit:
                break
            try:
                obj = json.loads(v)
                name = source_key.split("/")[-1] if "/" in source_key else source_key
                entries.append(
                    {
                        "path": name,
                        "source": source_key,
                        "loaded_at": obj.get("loaded_at", 0),
                        "items_count": obj.get("items_count", 0),
                        "status": "cached",
                    }
                )
            except (TypeError, ValueError):
                pass
        entries.sort(key=lambda x: x.get("loaded_at", 0), reverse=True)
    except Exception as e:
        _LOG.debug("snippets_cache_entries: %s", e)
    return entries[:limit]


def watchdog_state_get(kind: str) -> dict[str, float]:
    """Load state dict path -> value for given kind (hbk, standards, snippets)."""
    out: dict[str, float] = {}
    try:
        r = get_redis()
        key = f"watchdog:state:{kind}"
        raw = r.hgetall(key) or {}
        for k, v in raw.items():
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                pass
    except Exception as e:
        _LOG.debug("watchdog_state_get: %s", e)
    return out


def watchdog_state_set(kind: str, data: dict[str, float]) -> None:
    """Save state dict for kind. Replaces previous."""
    try:
        r = get_redis()
        key = f"watchdog:state:{kind}"
        r.delete(key)
        if data:
            mapping = {k: str(float(v)) for k, v in data.items()}
            r.hset(key, mapping=mapping)
    except Exception as e:
        _LOG.debug("watchdog_state_set: %s", e)


def snippets_items_total() -> int:
    """Sum of items_count from snippets cache hash."""
    try:
        r = get_redis()
        total = 0
        raw = r.hgetall(_SNIPPETS_CACHE) or {}
        for v in raw.values():
            try:
                obj = json.loads(v)
                total += int(obj.get("items_count", 0))
            except (TypeError, ValueError):
                pass
        return total
    except Exception as e:
        _LOG.debug("snippets_items_total: %s", e)
        return 0
