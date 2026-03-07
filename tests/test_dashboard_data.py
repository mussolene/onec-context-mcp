"""Tests for dashboard_data.get_dashboard_data()."""

from unittest.mock import patch

import pytest

from onec_help.dashboard_data import get_dashboard_data


def test_get_dashboard_data_returns_expected_keys() -> None:
    """get_dashboard_data() returns dict with ingest, collections, index_status, snippets, loading flags, failed_tasks."""
    data = get_dashboard_data()
    assert isinstance(data, dict)
    for key in (
        "ingest",
        "ingest_last_run",
        "failed_tasks",
        "index_status",
        "collections",
        "snippets",
        "standards_loading",
        "snippets_loading",
        "storage_path_mb",
    ):
        assert key in data, f"missing key: {key}"
    assert isinstance(data["failed_tasks"], list)
    assert isinstance(data["standards_loading"], bool)
    assert isinstance(data["snippets_loading"], bool)


@patch("onec_help.dashboard_data.get_index_status")
def test_get_dashboard_data_index_status_error(mock_get_index_status) -> None:
    """When get_index_status returns error, data contains index_status with error key."""
    mock_get_index_status.return_value = {"error": "connection refused", "exists": False, "points_count": 0}
    data = get_dashboard_data()
    assert data["index_status"].get("error") == "connection refused"


@patch("onec_help.dashboard_data.read_last_ingest_failed")
def test_get_dashboard_data_respects_failed_tasks_limit(mock_failed) -> None:
    """failed_tasks_limit is passed to read_last_ingest_failed."""
    mock_failed.return_value = []
    get_dashboard_data(failed_tasks_limit=7)
    mock_failed.assert_called_once_with(limit=7)
