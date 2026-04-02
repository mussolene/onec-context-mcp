"""Tests for mcp_metrics: record_request and get_metrics (SQLite path)."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

from onec_help.runtime.mcp_metrics import get_metrics, record_request

# Force SQLite path so tests do not require Redis
_use_sqlite = patch("onec_help.runtime.mcp_metrics._use_redis", return_value=False)


def test_use_redis_true_when_mcp_metrics_db_unset() -> None:
    """_use_redis returns True when MCP_METRICS_DB is not set."""
    from onec_help.runtime.mcp_metrics import _use_redis

    with patch.dict("os.environ", {"MCP_METRICS_DB": ""}, clear=False):
        assert _use_redis() is True


def test_use_redis_false_when_mcp_metrics_db_set() -> None:
    """_use_redis returns False when MCP_METRICS_DB is set (force SQLite)."""
    from onec_help.runtime.mcp_metrics import _use_redis

    with patch.dict("os.environ", {"MCP_METRICS_DB": "/tmp/mcp.db"}, clear=False):
        assert _use_redis() is False


def test_record_request_redis_fails_fallback_sqlite(tmp_path: Path) -> None:
    """When Redis path is used but redis_cache raises, record_request falls back to SQLite."""
    db = str(tmp_path / "fallback.db")
    with (
        patch("onec_help.runtime.mcp_metrics._use_redis", return_value=True),
        patch("onec_help.runtime.redis_cache.mcp_request_record", side_effect=RuntimeError),
        patch("onec_help.runtime.mcp_metrics._metrics_db_path", return_value=db),
    ):
        record_request("test_tool", True)
    with (
        patch("onec_help.runtime.mcp_metrics._use_redis", return_value=False),
        patch("onec_help.runtime.mcp_metrics._metrics_db_path", return_value=db),
    ):
        m = get_metrics()
    assert m["total"] == 1


def test_get_metrics_redis_fails_fallback_sqlite(tmp_path: Path) -> None:
    """When Redis path is used but redis_cache.mcp_metrics_get raises, get_metrics falls back to SQLite."""
    db = str(tmp_path / "mcp_metrics.db")
    with _use_sqlite, patch("onec_help.runtime.mcp_metrics._metrics_db_path", return_value=db):
        record_request("x", True)
    with (
        patch("onec_help.runtime.mcp_metrics._use_redis", return_value=True),
        patch(
            "onec_help.runtime.redis_cache.mcp_metrics_get",
            side_effect=RuntimeError("redis down"),
        ),
        patch("onec_help.runtime.mcp_metrics._metrics_db_path", return_value=db),
    ):
        m = get_metrics()
    assert m["total"] == 1
    assert m["last_hour"] == 1


def test_get_metrics_empty_when_no_db() -> None:
    """get_metrics returns total=0, last_hour=0 when DB does not exist."""
    with (
        _use_sqlite,
        patch("onec_help.runtime.mcp_metrics._metrics_db_path", return_value="/nonexistent/mcp_metrics.db"),
    ):
        m = get_metrics()
    assert m["total"] == 0
    assert m["last_hour"] == 0


def test_record_request_and_get_metrics(tmp_path: Path) -> None:
    """record_request writes one row; get_metrics returns total=1 and last_hour=1."""
    db = str(tmp_path / "mcp_metrics.db")
    with _use_sqlite, patch("onec_help.runtime.mcp_metrics._metrics_db_path", return_value=db):
        record_request("search_1c_help", True)
        m = get_metrics()
    assert m["total"] == 1
    assert m["last_hour"] == 1


def test_record_request_failure_recorded(tmp_path: Path) -> None:
    """record_request(..., success=False) still writes a row."""
    db = str(tmp_path / "mcp_metrics.db")
    with _use_sqlite, patch("onec_help.runtime.mcp_metrics._metrics_db_path", return_value=db):
        record_request("get_1c_help_topic", False)
        m = get_metrics()
    assert m["total"] == 1


def test_metrics_db_path_returns_env_path_when_set() -> None:
    """_metrics_db_path returns MCP_METRICS_DB when set (line 51: if path return path)."""
    from onec_help.runtime.mcp_metrics import _metrics_db_path

    with patch.dict("os.environ", {"MCP_METRICS_DB": "/custom/mcp.db"}, clear=False):
        path = _metrics_db_path()
    assert path == "/custom/mcp.db"


def test_metrics_db_path_fallback_when_ingest_raises() -> None:
    """_metrics_db_path returns _DEFAULT_DB when ingest._ingest_cache_path raises (covers except at 56-58)."""
    import sys

    from onec_help.runtime.mcp_metrics import _metrics_db_path

    ingest_mod = sys.modules["onec_help.ingest"]
    with (
        patch("onec_help.shared.env_config.get_mcp_metrics_db", return_value=""),
        patch.object(ingest_mod, "_ingest_cache_path", side_effect=RuntimeError("no cache path")),
    ):
        path = _metrics_db_path()
    assert path == "mcp_metrics.db"


def test_record_request_sqlite_handles_connect_error() -> None:
    """When sqlite3.connect raises, record_request does not crash."""
    with (
        _use_sqlite,
        patch("onec_help.runtime.mcp_metrics._metrics_db_path", return_value="/nonexistent/dir/mcp.db"),
        patch("onec_help.runtime.mcp_metrics.sqlite3.connect", side_effect=OSError("readonly")),
    ):
        record_request("x", True)


def test_get_metrics_when_path_empty_returns_zeros() -> None:
    """get_metrics returns zeros when _metrics_db_path returns empty string."""
    with (
        patch("onec_help.runtime.mcp_metrics._use_redis", return_value=False),
        patch("onec_help.runtime.mcp_metrics._metrics_db_path", return_value=""),
    ):
        m = get_metrics()
    assert m["total"] == 0
    assert m["last_hour"] == 0


def test_get_metrics_handles_conn_error() -> None:
    """get_metrics returns zeros when DB file exists but connect fails."""
    with (
        patch("onec_help.runtime.mcp_metrics._use_redis", return_value=False),
        patch("onec_help.runtime.mcp_metrics._metrics_db_path", return_value="/tmp/mcp_metrics.db"),
        patch("onec_help.runtime.mcp_metrics.os.path.isfile", return_value=True),
        patch(
            "onec_help.runtime.mcp_metrics.sqlite3.connect", side_effect=sqlite3.OperationalError("locked")
        ),
    ):
        m = get_metrics()
    assert m["total"] == 0
    assert m["last_hour"] == 0
