"""Tests for mcp_metrics: record_request and get_metrics."""

from pathlib import Path
from unittest.mock import patch

from onec_help.mcp_metrics import get_metrics, record_request


def test_get_metrics_empty_when_no_db() -> None:
    """get_metrics returns total=0, last_hour=0 when DB does not exist."""
    with patch(
        "onec_help.mcp_metrics._metrics_db_path", return_value="/nonexistent/mcp_metrics.db"
    ):
        m = get_metrics()
    assert m["total"] == 0
    assert m["last_hour"] == 0


def test_record_request_and_get_metrics(tmp_path: Path) -> None:
    """record_request writes one row; get_metrics returns total=1 and last_hour=1."""
    db = str(tmp_path / "mcp_metrics.db")
    with patch("onec_help.mcp_metrics._metrics_db_path", return_value=db):
        record_request("search_1c_help", True)
        m = get_metrics()
    assert m["total"] == 1
    assert m["last_hour"] == 1


def test_record_request_failure_recorded(tmp_path: Path) -> None:
    """record_request(..., success=False) still writes a row."""
    db = str(tmp_path / "mcp_metrics.db")
    with patch("onec_help.mcp_metrics._metrics_db_path", return_value=db):
        record_request("get_1c_help_topic", False)
        m = get_metrics()
    assert m["total"] == 1
