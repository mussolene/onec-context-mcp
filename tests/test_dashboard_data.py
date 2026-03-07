"""Tests for dashboard_data.get_dashboard_data()."""

import os
import time
from pathlib import Path
from unittest.mock import patch

from onec_help.dashboard_data import get_dashboard_data


@patch("onec_help.dashboard_data.get_all_collections_status", return_value=[])
@patch(
    "onec_help.dashboard_data.get_index_status", return_value={"exists": True, "points_count": 0}
)
def test_get_dashboard_data_returns_expected_keys(
    mock_index: object, mock_collections: object
) -> None:
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
        "mcp_metrics",
    ):
        assert key in data, f"missing key: {key}"
    assert isinstance(data["failed_tasks"], list)
    assert isinstance(data["standards_loading"], bool)
    assert isinstance(data["snippets_loading"], bool)


@patch("onec_help.dashboard_data.get_index_status")
def test_get_dashboard_data_index_status_error(mock_get_index_status) -> None:
    """When get_index_status returns error, data contains index_status with error key."""
    mock_get_index_status.return_value = {
        "error": "connection refused",
        "exists": False,
        "points_count": 0,
    }
    data = get_dashboard_data()
    assert data["index_status"].get("error") == "connection refused"


@patch("onec_help.dashboard_data.get_all_collections_status", return_value=[])
@patch("onec_help.dashboard_data.get_index_status", return_value={"exists": True})
@patch("onec_help.dashboard_data.read_ingest_errors_log")
def test_get_dashboard_data_respects_failed_tasks_limit(
    mock_errors_log: object, _mock_index: object, _mock_collections: object
) -> None:
    """failed_tasks_limit is passed to read_ingest_errors_log (primary source for errors)."""
    mock_errors_log.return_value = []
    get_dashboard_data(failed_tasks_limit=7)
    mock_errors_log.assert_called_once_with(limit=7)


def test_load_marker_stat_oserror_returns_false(tmp_path: Path) -> None:
    """When marker file exists but stat() raises OSError, _load_marker_exists returns False."""
    cache_dir = tmp_path / "var" / "ingest_cache"
    cache_dir.mkdir(parents=True)
    marker = cache_dir / "load_standards.running"
    marker.write_text("1", encoding="utf-8")
    original_stat = Path.stat

    def stat_raise_for_marker(self: Path):
        if self.name == "load_standards.running":
            raise OSError("Permission denied")
        return original_stat(self)

    with (
        patch(
            "onec_help.dashboard_data._ingest_cache_path",
            return_value=str(cache_dir / "ingest_cache.db"),
        ),
        patch.object(Path, "stat", stat_raise_for_marker),
        patch("onec_help.dashboard_data.get_index_status", return_value={"exists": True}),
        patch("onec_help.dashboard_data.get_all_collections_status", return_value=[]),
        patch("onec_help.dashboard_data.read_ingest_status", return_value=None),
        patch("onec_help.dashboard_data.read_last_ingest_run", return_value=None),
        patch("onec_help.dashboard_data.read_last_ingest_failed", return_value=[]),
        patch("onec_help.dashboard_data.read_last_snippets_run", return_value=None),
        patch(
            "onec_help.dashboard_data.get_mcp_metrics", return_value={"total": 0, "last_hour": 0}
        ),
    ):
        data = get_dashboard_data()
    assert data["standards_loading"] is False


def test_load_marker_stale_not_loading(tmp_path: Path) -> None:
    """When load_snippets.running exists but is older than 10 min, snippets_loading is False."""
    cache_dir = tmp_path / "var" / "ingest_cache"
    cache_dir.mkdir(parents=True)
    marker = cache_dir / "load_snippets.running"
    marker.write_text("1", encoding="utf-8")
    old_ts = time.time() - 700  # 700 s ago so past _LOAD_MARKER_STALE_SEC (600)
    os.utime(marker, (old_ts, old_ts))

    with (
        patch(
            "onec_help.dashboard_data._ingest_cache_path",
            return_value=str(cache_dir / "ingest_cache.db"),
        ),
        patch("onec_help.dashboard_data.get_index_status", return_value={"exists": True}),
        patch("onec_help.dashboard_data.get_all_collections_status", return_value=[]),
    ):
        data = get_dashboard_data()
    assert data["snippets_loading"] is False


def test_load_marker_exists_not_stale_loading(tmp_path: Path) -> None:
    """When load_standards.running exists and is recent, standards_loading is True."""
    cache_dir = tmp_path / "var" / "ingest_cache"
    cache_dir.mkdir(parents=True)
    marker = cache_dir / "load_standards.running"
    marker.write_text("1", encoding="utf-8")

    with (
        patch(
            "onec_help.dashboard_data._ingest_cache_path",
            return_value=str(cache_dir / "ingest_cache.db"),
        ),
        patch("onec_help.dashboard_data.get_index_status", return_value={"exists": True}),
        patch("onec_help.dashboard_data.get_all_collections_status", return_value=[]),
        patch("onec_help.dashboard_data.read_ingest_status", return_value=None),
        patch("onec_help.dashboard_data.read_last_ingest_run", return_value=None),
        patch("onec_help.dashboard_data.read_last_ingest_failed", return_value=[]),
        patch("onec_help.dashboard_data.read_last_snippets_run", return_value=None),
        patch(
            "onec_help.dashboard_data.get_mcp_metrics", return_value={"total": 0, "last_hour": 0}
        ),
    ):
        data = get_dashboard_data()
    assert data["standards_loading"] is True


@patch("onec_help.dashboard_data.get_mcp_metrics", return_value={"total": 0, "last_hour": 0})
@patch("onec_help.dashboard_data.read_last_snippets_run", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_failed", return_value=[])
@patch("onec_help.dashboard_data.read_ingest_status", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_run", return_value={"failed_count": 2})
@patch("onec_help.dashboard_data.get_index_status", return_value={"exists": True})
@patch("onec_help.dashboard_data.get_all_collections_status", return_value=[])
def test_get_dashboard_data_fallback_ingest_failed_log(
    mock_collections,
    mock_index,
    mock_last_run,
    mock_status,
    mock_failed,
    mock_snippets,
    mock_mcp,
    tmp_path: Path,
) -> None:
    """When failed_tasks is empty but ingest_last_run has failed_count > 0, read_ingest_failed_log is called."""
    with (
        patch(
            "onec_help.dashboard_data._ingest_cache_path",
            return_value=str(tmp_path / "ingest_cache.db"),
        ),
        patch(
            "onec_help.dashboard_data.read_ingest_failed_log",
            return_value=[{"version": "8.3", "path": "x.hbk", "error": "7z failed"}],
        ) as mock_log,
    ):
        data = get_dashboard_data(failed_tasks_limit=5)
    mock_log.assert_called_once_with(limit=5)
    assert len(data["failed_tasks"]) == 1
    assert data["failed_tasks"][0]["error"] == "7z failed"


@patch("onec_help.dashboard_data.get_mcp_metrics", return_value={"total": 0, "last_hour": 0})
@patch("onec_help.dashboard_data.read_last_snippets_run", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_failed", return_value=[])
@patch("onec_help.dashboard_data.read_ingest_status", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_run", return_value=None)
@patch("onec_help.dashboard_data.get_index_status", return_value={"exists": True})
@patch("onec_help.dashboard_data.get_all_collections_status", return_value=[])
def test_load_marker_exists_returns_false_when_cache_path_raises(
    mock_collections,
    mock_index,
    mock_last_run,
    mock_status,
    mock_failed,
    mock_snippets,
    mock_mcp,
) -> None:
    """When _ingest_cache_path raises, _load_marker_exists returns False (standards_loading/snippets_loading False)."""
    with (
        patch(
            "onec_help.dashboard_data._ingest_cache_path",
            side_effect=RuntimeError("no cache"),
        ),
    ):
        data = get_dashboard_data()
    assert data["standards_loading"] is False
    assert data["snippets_loading"] is False


@patch("onec_help.dashboard_data.get_mcp_metrics", return_value={"total": 0, "last_hour": 0})
@patch("onec_help.dashboard_data.read_last_snippets_run", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_failed", return_value=[])
@patch("onec_help.dashboard_data.read_ingest_status", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_run", return_value=None)
@patch("onec_help.dashboard_data.get_index_status", return_value={"exists": True})
@patch("onec_help.dashboard_data.get_all_collections_status", return_value=[])
def test_read_load_status_none_when_status_file_not_dict_or_no_loaded_total(
    mock_collections,
    mock_index,
    mock_last_run,
    mock_status,
    mock_failed,
    mock_snippets,
    mock_mcp,
    tmp_path: Path,
) -> None:
    """standards_loading_pts is None when status file is not a dict or has no loaded/total."""
    cache_dir = tmp_path / "var" / "ingest_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "load_standards.running").write_text("1", encoding="utf-8")
    (cache_dir / "load_standards.status.json").write_text("[]", encoding="utf-8")
    with (
        patch(
            "onec_help.dashboard_data._ingest_cache_path",
            return_value=str(cache_dir / "ingest_cache.db"),
        ),
    ):
        data = get_dashboard_data()
    assert data["standards_loading"] is True
    assert data["standards_loading_pts"] is None


@patch("onec_help.dashboard_data.get_mcp_metrics", return_value={"total": 0, "last_hour": 0})
@patch("onec_help.dashboard_data.read_last_snippets_run", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_failed", return_value=[])
@patch("onec_help.dashboard_data.read_ingest_status", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_run", return_value=None)
@patch("onec_help.dashboard_data.get_index_status", return_value={"exists": True})
@patch("onec_help.dashboard_data.get_all_collections_status", return_value=[])
def test_storage_path_mb_from_env(
    mock_collections,
    mock_index,
    mock_last_run,
    mock_status,
    mock_failed,
    mock_snippets,
    mock_mcp,
    tmp_path: Path,
) -> None:
    """storage_path_mb is set when QDRANT_STORAGE_PATH is a valid dir and dir_size_on_disk works."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    with (
        patch(
            "onec_help.dashboard_data._ingest_cache_path",
            return_value=str(tmp_path / "ingest_cache.db"),
        ),
        patch.dict("os.environ", {"QDRANT_STORAGE_PATH": str(tmp_path)}, clear=False),
        patch(
            "onec_help._utils.dir_size_on_disk",
            return_value=2 * 1024 * 1024,
        ),
    ):
        data = get_dashboard_data()
    assert data["storage_path_mb"] == 2.0


@patch("onec_help.dashboard_data.get_mcp_metrics", return_value={"total": 0, "last_hour": 0})
@patch("onec_help.dashboard_data.read_last_snippets_run", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_failed", return_value=[])
@patch("onec_help.dashboard_data.read_ingest_status", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_run", return_value=None)
@patch("onec_help.dashboard_data.get_index_status", return_value={"exists": True})
@patch("onec_help.dashboard_data.get_all_collections_status", return_value=[])
def test_read_load_status_with_phase(
    mock_collections,
    mock_index,
    mock_last_run,
    mock_status,
    mock_failed,
    mock_snippets,
    mock_mcp,
    tmp_path: Path,
) -> None:
    """When load_standards.running exists and load_standards.status.json has phase, standards_loading_pts has phase."""
    cache_dir = tmp_path / "var" / "ingest_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "load_standards.running").write_text("1", encoding="utf-8")
    (cache_dir / "load_standards.status.json").write_text(
        '{"loaded": 10, "total": 100, "phase": "embedding"}', encoding="utf-8"
    )
    with (
        patch(
            "onec_help.dashboard_data._ingest_cache_path",
            return_value=str(cache_dir / "ingest_cache.db"),
        ),
        patch("onec_help.dashboard_data.get_index_status", return_value={"exists": True}),
        patch("onec_help.dashboard_data.get_all_collections_status", return_value=[]),
        patch("onec_help.dashboard_data.read_ingest_status", return_value=None),
        patch("onec_help.dashboard_data.read_last_ingest_run", return_value=None),
        patch("onec_help.dashboard_data.read_last_ingest_failed", return_value=[]),
        patch("onec_help.dashboard_data.read_last_snippets_run", return_value=None),
        patch(
            "onec_help.dashboard_data.get_mcp_metrics", return_value={"total": 0, "last_hour": 0}
        ),
    ):
        data = get_dashboard_data()
    assert data["standards_loading"] is True
    assert data["standards_loading_pts"] == {"loaded": 10, "total": 100, "phase": "embedding"}


@patch("onec_help.dashboard_data.get_mcp_metrics", return_value={"total": 0, "last_hour": 0})
@patch("onec_help.dashboard_data.read_last_snippets_run", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_failed", return_value=[])
@patch("onec_help.dashboard_data.read_ingest_status", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_run", return_value=None)
@patch("onec_help.dashboard_data.get_index_status", return_value={"exists": True})
@patch("onec_help.dashboard_data.get_all_collections_status", return_value=[{"name": "c1"}])
def test_bm25_vocab_stats_skips_bad_file(
    mock_collections,
    mock_index,
    mock_last_run,
    mock_status,
    mock_failed,
    mock_snippets,
    mock_mcp,
    tmp_path: Path,
) -> None:
    """When a BM25 vocab file exists but is invalid JSON, that collection is skipped (no crash)."""
    vocab_dir = tmp_path / "bm25_vocab"
    vocab_dir.mkdir(parents=True)
    (vocab_dir / "c1.json").write_text("not json", encoding="utf-8")
    with (
        patch(
            "onec_help.dashboard_data._ingest_cache_path",
            return_value=str(tmp_path / "ingest_cache.db"),
        ),
        patch(
            "onec_help.dashboard_data.bm25_vocab_path",
            side_effect=lambda name: vocab_dir / f"{name}.json",
        ),
    ):
        data = get_dashboard_data()
    assert "bm25_vocab" in data
    assert data["bm25_vocab"] == {}


@patch("onec_help.dashboard_data.get_mcp_metrics", return_value={"total": 0, "last_hour": 0})
@patch("onec_help.dashboard_data.read_last_snippets_run", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_failed", return_value=[])
@patch("onec_help.dashboard_data.read_ingest_status", return_value=None)
@patch("onec_help.dashboard_data.read_last_ingest_run", return_value=None)
@patch("onec_help.dashboard_data.get_index_status", return_value={"exists": True})
@patch("onec_help.dashboard_data.get_all_collections_status", return_value=[])
def test_storage_path_mb_oserror_returns_none(
    mock_collections,
    mock_index,
    mock_last_run,
    mock_status,
    mock_failed,
    mock_snippets,
    mock_mcp,
    tmp_path: Path,
) -> None:
    """storage_path_mb is None when dir_size_on_disk raises OSError."""
    (tmp_path / "qdrant").mkdir(parents=True, exist_ok=True)
    with (
        patch(
            "onec_help.dashboard_data._ingest_cache_path",
            return_value=str(tmp_path / "ingest_cache.db"),
        ),
        patch.dict("os.environ", {"QDRANT_STORAGE_PATH": str(tmp_path / "qdrant")}, clear=False),
        patch(
            "onec_help._utils.dir_size_on_disk",
            side_effect=OSError("Permission denied"),
        ),
    ):
        data = get_dashboard_data()
    assert data["storage_path_mb"] is None
