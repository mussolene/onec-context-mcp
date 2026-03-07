"""MCP request metrics: SQLite store for dashboard (total and per-hour counts)."""

import os
import sqlite3
import time
from typing import Any

_TABLE = "requests"
_DEFAULT_DB = "mcp_metrics.db"


def _metrics_db_path() -> str:
    """Path to SQLite DB. MCP_METRICS_DB or next to ingest cache."""
    path = os.environ.get("MCP_METRICS_DB", "").strip()
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


def record_request(tool_name: str, success: bool) -> None:
    """Append one MCP tool call. Safe to call from any thread."""
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
    """Return total count and count in last hour. For dashboard."""
    path = _metrics_db_path()
    out: dict[str, Any] = {"total": 0, "last_hour": 0}
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
