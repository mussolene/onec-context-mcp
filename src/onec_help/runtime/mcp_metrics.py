"""MCP request metrics: Redis (preferred) or SQLite for dashboard (total and per-hour counts)."""

import os
import sqlite3
import time
from typing import Any

_TABLE = "requests"
_DEFAULT_DB = "mcp_metrics.db"


def _use_redis() -> bool:
    """True if Redis should be used for MCP metrics. False only when MCP_METRICS_DB is set (force SQLite)."""
    from ..shared import env_config

    if env_config.get_mcp_metrics_db():
        return False  # explicit SQLite path
    return True


def record_request(
    tool_name: str,
    success: bool,
    duration_sec: float | None = None,
    error_msg: str | None = None,
) -> None:
    """Append one MCP tool call. Writes to Redis (with duration/errors) or SQLite. Safe from any thread."""
    if _use_redis():
        try:
            from . import redis_cache

            redis_cache.mcp_request_record(
                tool_name=tool_name,
                success=success,
                duration_sec=duration_sec,
                error_msg=error_msg if not success else None,
            )
            return
        except Exception as e:
            _log = __import__("logging").getLogger(__name__)
            _log.debug("mcp_metrics Redis record_request failed: %s", e)
    _record_request_sqlite(tool_name, success)


def _metrics_db_path() -> str:
    """Path to SQLite DB. From env_config or next to ingest cache."""
    from ..shared import env_config

    path = env_config.get_mcp_metrics_db()
    if path:
        return path
    try:
        from .ingest import _ingest_cache_path

        parent = os.path.dirname(_ingest_cache_path())
        return os.path.join(parent, _DEFAULT_DB)
    except Exception:
        return _DEFAULT_DB


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {_TABLE}
        (ts REAL NOT NULL, tool_name TEXT NOT NULL, success INTEGER NOT NULL)"""
    )
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_ts ON {_TABLE}(ts)")
    conn.commit()


def _record_request_sqlite(tool_name: str, success: bool = True) -> None:
    path = _metrics_db_path()
    try:
        conn = sqlite3.connect(path, timeout=5)
        _init_db(conn)
        conn.execute(
            f"INSERT INTO {_TABLE} (ts, tool_name, success) VALUES (?, ?, ?)",
            (time.time(), tool_name, 1 if success else 0),
        )
        conn.commit()
        conn.close()
    except (OSError, sqlite3.Error) as e:
        logging = __import__("logging").getLogger(__name__)
        logging.debug("mcp_metrics record_request failed: %s", e)


def get_metrics() -> dict[str, Any]:
    """Return total count and count in last hour. For dashboard. Reads from Redis when available."""
    if _use_redis():
        try:
            from . import redis_cache

            return redis_cache.mcp_metrics_get()
        except Exception:
            pass
    path = _metrics_db_path()
    out: dict[str, Any] = {
        "total": 0,
        "last_hour": 0,
        "max_response_sec": None,
        "errors_total": 0,
        "errors_recent": [],
    }
    if not path or not os.path.isfile(path):
        return out
    try:
        conn = sqlite3.connect(path, timeout=2)
        _init_db(conn)
        now = time.time()
        hour_ago = now - 3600
        row = conn.execute(f"SELECT COUNT(*) FROM {_TABLE}").fetchone()
        out["total"] = row[0] if row else 0
        row = conn.execute(
            f"SELECT COUNT(*) FROM {_TABLE} WHERE ts >= ?",
            (hour_ago,),
        ).fetchone()
        out["last_hour"] = row[0] if row else 0
        conn.close()
    except (OSError, sqlite3.Error):
        pass
    return out
