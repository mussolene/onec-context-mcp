"""Redis backend for ingest cache and status. Replaces SQLite when running with ingest-worker and mcp.

Keys: ingest:cache (hash), ingest:current, ingest:run:next_id, ingest:runs (list), ingest:run:{id}, ingest:failed:{id};
      snippets:cache (hash), snippets:last_run.
When Redis is unavailable, get_redis() returns a no-op client: no writes, no errors, reads return empty/None until process restart.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

from .. import env_config

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
_STANDARDS_LAST_RUN = "standards:last_run"
_METADATA_LAST_RUN = "metadata:last_run"

_client: Any = None


class _NoOpRedis:
    """No-op Redis client when Redis is unavailable. All reads return empty/None, writes do nothing. No exceptions."""

    def ping(self) -> None:
        pass

    def get(self, key: str) -> None:
        return None

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        pass

    def incr(self, key: str) -> int:
        return 0

    def hgetall(self, name: str) -> dict[str, str]:
        return {}

    def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        mapping: dict | None = None,
    ) -> None:
        pass

    def delete(self, *keys: str) -> None:
        pass

    def lpush(self, key: str, *values: str) -> int:
        return 0

    def ltrim(self, key: str, start: int, end: int) -> None:
        pass

    def lrange(self, key: str, start: int, end: int) -> list:
        return []

    def rpush(self, key: str, *values: str) -> int:
        return 0

    def zadd(self, name: str, mapping: dict[str, float]) -> int:
        return 0

    def zremrangebyscore(self, name: str, min_: float | str, max_: float | str) -> int:
        return 0

    def zcount(self, name: str, min_: float | str, max_: float | str) -> int:
        return 0

    def scan_iter(self, match: str) -> Iterator[str]:
        return iter([])


def get_redis():
    """Return Redis client or no-op if unavailable. Uses REDIS_URL / REDIS_HOST / default localhost:6379. Cached; on first failure switches to no-op until process restart."""
    global _client
    if _client is not None:
        return _client
    try:
        import redis as redis_mod
    except ImportError as e:
        _LOG.warning("redis_cache: redis not installed, using no-op: %s", e)
        _client = _NoOpRedis()
        return _client
    url = env_config.get_redis_url()
    if url:
        try:
            _client = redis_mod.from_url(url, decode_responses=True)
            _client.ping()
        except Exception as e:
            _LOG.warning("redis_cache: Redis unavailable (%s), no writes until restart", e)
            _client = _NoOpRedis()
    else:
        host = env_config.get_redis_host()
        if host:
            port = env_config.get_redis_port()
            try:
                _client = redis_mod.Redis(host=host, port=port, decode_responses=True)
                _client.ping()
            except Exception as e:
                _LOG.warning("redis_cache: Redis unavailable (%s), no writes until restart", e)
                _client = _NoOpRedis()
        else:
            try:
                _client = redis_mod.from_url(
                    env_config.get_redis_url_fallback(), decode_responses=True
                )
                _client.ping()
            except Exception as e:
                _LOG.warning("redis_cache: Redis unavailable (%s), no writes until restart", e)
                _client = _NoOpRedis()
    return _client


def clear_all() -> bool:
    """Delete all ingest, snippets, standards, metadata, watchdog and MCP metrics keys. Returns True on success."""
    try:
        r = get_redis()
        keys = (
            list(r.scan_iter(match="ingest:*"))
            + list(r.scan_iter(match="snippets:*"))
            + list(r.scan_iter(match="standards:*"))
            + list(r.scan_iter(match="metadata:*"))
            + list(r.scan_iter(match="watchdog:*"))
            + list(r.scan_iter(match="mcp:*"))
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
        item = json.dumps(
            {"version": version, "language": language, "path": path, "error": error[:500]}
        )
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


def standards_run_record(items_loaded: int, started_at: float) -> None:
    """Record last standards load run (for dashboard)."""
    try:
        r = get_redis()
        row = {
            "started_at": started_at,
            "finished_at": time.time(),
            "items_loaded": items_loaded,
        }
        r.set(_STANDARDS_LAST_RUN, json.dumps(row))
    except Exception as e:
        _LOG.debug("standards_run_record: %s", e)


def standards_last_run() -> dict[str, Any] | None:
    """Last standards load run for dashboard."""
    try:
        r = get_redis()
        raw = r.get(_STANDARDS_LAST_RUN)
        if not raw:
            return None
        row = json.loads(raw)
        return {
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "items_loaded": row.get("items_loaded", 0),
            "total_elapsed_sec": (row.get("finished_at") or 0) - (row.get("started_at") or 0)
            if row.get("finished_at") and row.get("started_at")
            else None,
        }
    except Exception as e:
        _LOG.debug("standards_last_run: %s", e)
        return None


def metadata_run_record(objects_indexed: int, started_at: float) -> None:
    """Record last metadata-graph-build run (for dashboard)."""
    try:
        r = get_redis()
        row = {
            "started_at": started_at,
            "finished_at": time.time(),
            "objects_indexed": objects_indexed,
        }
        r.set(_METADATA_LAST_RUN, json.dumps(row))
    except Exception as e:
        _LOG.debug("metadata_run_record: %s", e)


def metadata_last_run() -> dict[str, Any] | None:
    """Last metadata-graph-build run for dashboard."""
    try:
        r = get_redis()
        raw = r.get(_METADATA_LAST_RUN)
        if not raw:
            return None
        row = json.loads(raw)
        return {
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "objects_indexed": row.get("objects_indexed", 0),
            "total_elapsed_sec": (row.get("finished_at") or 0) - (row.get("started_at") or 0)
            if row.get("finished_at") and row.get("started_at")
            else None,
        }
    except Exception as e:
        _LOG.debug("metadata_last_run: %s", e)
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


# --- MCP request metrics (dashboard: total, last hour, max response time, errors) ---

_MCP_TOTAL = "mcp:total"
_MCP_TS_ZSET = "mcp:requests_ts"
_MCP_LAST_HOUR = 3600
_MCP_MAX_RESPONSE_SEC = "mcp:max_response_sec"
_MCP_ERRORS_TOTAL = "mcp:errors_total"
_MCP_ERRORS_RECENT = "mcp:errors_recent"
_MCP_ERRORS_RECENT_MAX = 20
_MCP_TOOL_COUNTS = "mcp:tool_counts"  # hash: tool_name -> call count


def mcp_request_record(
    tool_name: str = "",
    success: bool = True,
    duration_sec: float | None = None,
    error_msg: str | None = None,
) -> None:
    """Record one MCP tool call. Dashboard reads via mcp_metrics_get."""
    try:
        r = get_redis()
        now = time.time()
        r.incr(_MCP_TOTAL)
        r.zadd(_MCP_TS_ZSET, {str(now): now})
        r.zremrangebyscore(_MCP_TS_ZSET, "-inf", now - _MCP_LAST_HOUR)
        if tool_name:
            r.hincrby(_MCP_TOOL_COUNTS, tool_name, 1)
        if duration_sec is not None and duration_sec > 0:
            cur = r.get(_MCP_MAX_RESPONSE_SEC)
            if cur is None or float(cur) < duration_sec:
                r.set(_MCP_MAX_RESPONSE_SEC, str(round(duration_sec, 3)))
        if not success:
            r.incr(_MCP_ERRORS_TOTAL)
            item = json.dumps(
                {
                    "ts": now,
                    "tool": (tool_name or "?")[:64],
                    "error": (error_msg or "error")[:200],
                },
                ensure_ascii=False,
            )
            r.lpush(_MCP_ERRORS_RECENT, item)
            r.ltrim(_MCP_ERRORS_RECENT, 0, _MCP_ERRORS_RECENT_MAX - 1)
    except Exception as e:
        _LOG.debug("mcp_request_record: %s", e)


def mcp_metrics_get() -> dict[str, Any]:
    """Return total, last_hour, max_response_sec, errors_total, errors_recent, per_tool for dashboard."""
    out: dict[str, Any] = {
        "total": 0,
        "last_hour": 0,
        "max_response_sec": None,
        "errors_total": 0,
        "errors_recent": [],
        "per_tool": {},
    }
    try:
        r = get_redis()
        total = r.get(_MCP_TOTAL)
        out["total"] = int(total) if total else 0
        now = time.time()
        out["last_hour"] = r.zcount(_MCP_TS_ZSET, now - _MCP_LAST_HOUR, "+inf")
        max_sec = r.get(_MCP_MAX_RESPONSE_SEC)
        if max_sec is not None:
            try:
                out["max_response_sec"] = round(float(max_sec), 2)
            except (TypeError, ValueError):
                pass
        err_total = r.get(_MCP_ERRORS_TOTAL)
        out["errors_total"] = int(err_total) if err_total else 0
        raw_list = r.lrange(_MCP_ERRORS_RECENT, 0, 9) or []
        for raw in raw_list:
            try:
                obj = json.loads(raw)
                out["errors_recent"].append(
                    {
                        "tool": obj.get("tool", "?"),
                        "error": (obj.get("error") or "")[:100],
                        "ts": obj.get("ts"),
                    }
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        raw_counts = r.hgetall(_MCP_TOOL_COUNTS) or {}
        per_tool: dict[str, int] = {}
        for k, v in raw_counts.items():
            try:
                key = k.decode() if isinstance(k, bytes) else str(k)
                per_tool[key] = int(v)
            except (ValueError, AttributeError):
                pass
        out["per_tool"] = dict(sorted(per_tool.items(), key=lambda x: x[1], reverse=True))
    except Exception as e:
        _LOG.debug("mcp_metrics_get: %s", e)
    return out
