"""Tests for CLI."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from onec_help.cli import (
    _build_snippets_sources,
    _categorize_error,
    _env_path,
    _render_index_status,
    _render_index_status_compact,
    _render_index_status_rich,
    _short_error,
    cmd_add_bm25,
    cmd_build_docs,
    cmd_build_index,
    cmd_index_status,
    cmd_ingest,
    cmd_ingest_from_unpacked,
    cmd_load_snippets,
    cmd_load_standards,
    cmd_mcp,
    cmd_parse_fastcode,
    cmd_parse_helpf,
    cmd_qdrant_backup,
    cmd_qdrant_restore,
    cmd_read_hbk_container,
    cmd_reinit,
    cmd_unpack,
    cmd_unpack_diag,
    cmd_unpack_dir,
    cmd_unpack_sync,
    cmd_watchdog,
    main,
)


def make_args(**kwargs) -> SimpleNamespace:
    """Create argparse.Namespace-like object for cmd_* tests."""
    return SimpleNamespace(**kwargs)


def test_cmd_build_docs(help_sample_dir: Path, tmp_path: Path) -> None:
    args = make_args(project_dir=str(help_sample_dir), output=str(tmp_path / "out_md"))
    assert cmd_build_docs(args) == 0
    assert (tmp_path / "out_md").exists()


@patch("onec_help.html2md.build_docs")
def test_cmd_build_docs_error(mock_build_docs, tmp_path: Path) -> None:
    mock_build_docs.side_effect = RuntimeError("disk full")
    tmp_path.mkdir(exist_ok=True)
    args = make_args(project_dir=str(tmp_path), output=str(tmp_path / "out_md"))
    assert cmd_build_docs(args) == 1


def test_cmd_read_hbk_container_not_file() -> None:
    """read-hbk-container returns 1 when path is not a file."""
    args = make_args(file="/nonexistent.hbk", out_dir=None, toc_json=None)
    assert cmd_read_hbk_container(args) == 1


def test_cmd_read_hbk_container_empty_toc(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """read-hbk-container on minimal container (empty TOC) lists entities."""
    import struct

    header = struct.pack("<iiii", 0, 256, 0, 0)
    toc_header = b"\x0d\x0a00000000 00000000 FFFFFFFF \x0d\x0a"
    hbk = tmp_path / "empty.hbk"
    hbk.write_bytes(header + toc_header)
    args = make_args(file=str(hbk), out_dir=None, toc_json=None)
    assert cmd_read_hbk_container(args) == 0
    out = capsys.readouterr().out
    assert "Entities:" in out


def test_cmd_unpack_diag_success(tmp_path: Path) -> None:
    out = tmp_path / "diag_out"
    with patch("onec_help.unpack.unpack_diag"):
        args = make_args(archive="/nonexistent.hbk", output_dir=str(out))
        assert cmd_unpack_diag(args) == 0


def test_cmd_unpack_diag_error(tmp_path: Path) -> None:
    with patch("onec_help.unpack.unpack_diag", side_effect=RuntimeError("diag failed")):
        args = make_args(archive="/nonexistent.hbk", output_dir=str(tmp_path))
        assert cmd_unpack_diag(args) == 1


def test_cmd_add_bm25_success() -> None:
    with patch("onec_help.indexer.add_bm25_to_collection", return_value=100):
        args = make_args(collection="onec_help", batch_size=200, quiet=False)
        with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
            assert cmd_add_bm25(args) == 0


def test_cmd_add_bm25_error() -> None:
    with patch(
        "onec_help.indexer.add_bm25_to_collection",
        side_effect=RuntimeError("Qdrant unavailable"),
    ):
        args = make_args(collection="onec_help")
        with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
            assert cmd_add_bm25(args) == 1


def test_categorize_error() -> None:
    assert _categorize_error("All unpack methods failed") == "unpack"
    assert _categorize_error("connection timeout") == "embed"
    assert _categorize_error("qdrant upsert failed") == "index"
    assert _categorize_error("html parse error") == "build"
    assert _categorize_error("something else") == "other"


def test_short_error() -> None:
    assert _short_error("All unpack methods failed") == "unpack failed"
    assert _short_error("unzip: No such file or directory") == "unzip not found"
    assert _short_error("invalid archive") == "7z/invalid archive"
    assert _short_error("Connection timeout") == "timeout"
    assert _short_error("429 rate limit") == "rate limit"
    assert _short_error("x" * 50) == "x" * 38 + "…"
    assert _short_error("short") == "short"


def test_cmd_unpack_fail() -> None:
    args = make_args(archive="/nonexistent.hbk", output_dir="/tmp/out")
    assert cmd_unpack(args) == 1


@patch("onec_help.unpack.unpack_hbk")
def test_cmd_unpack_success(mock_unpack, tmp_path: Path) -> None:
    (tmp_path / "fake.hbk").write_bytes(b"x")
    args = make_args(archive=str(tmp_path / "fake.hbk"), output_dir=str(tmp_path / "out"))
    assert cmd_unpack(args) == 0
    mock_unpack.assert_called_once()


@patch("onec_help.indexer.build_index")
def test_cmd_build_index(mock_build, help_sample_dir: Path) -> None:
    mock_build.return_value = 5
    args = make_args(directory=str(help_sample_dir), docs_dir=None)
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_build_index(args) == 0


@patch("onec_help.indexer.build_index")
def test_cmd_build_index_error(mock_build, help_sample_dir: Path) -> None:
    mock_build.side_effect = RuntimeError("Qdrant unavailable")
    args = make_args(directory=str(help_sample_dir), docs_dir=None)
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_build_index(args) == 1


def test_main_help() -> None:
    with patch("sys.argv", ["onec_help", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0


def test_main_unpack_usage() -> None:
    with patch("sys.argv", ["onec_help", "unpack", "--help"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0


@patch("onec_help.ingest.read_ingest_status")
@patch("onec_help.indexer.get_index_status")
def test_cmd_index_status_ingest_backend_none(
    mock_status, mock_ingest, capsys: pytest.CaptureFixture[str]
) -> None:
    """index-status with ingest backend 'none' prints embed: none."""
    mock_status.return_value = {"exists": True, "points_count": 10}
    mock_ingest.return_value = {
        "embedding_backend": "none",
        "status": "completed",
    }
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_index_status(make_args()) == 0
    out = capsys.readouterr().out
    assert "embed: none" in out


@patch("onec_help.ingest.read_ingest_status")
@patch("onec_help.indexer.get_index_status")
def test_cmd_index_status_ingest_speed_none(
    mock_status, mock_ingest, capsys: pytest.CaptureFixture[str]
) -> None:
    """index-status with ingest in progress shows elapsed."""
    mock_status.return_value = {"exists": True, "points_count": 10}
    mock_ingest.return_value = {
        "embedding_backend": "openai_api",
        "elapsed_sec": 5.0,
        "status": "in progress",
    }
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_index_status(make_args()) == 0
    out = capsys.readouterr().out
    assert "embed: openai_api" in out and "in progress" in out


@patch("onec_help.ingest.read_ingest_status")
@patch("onec_help.indexer.get_index_status")
def test_cmd_index_status_storage_path_not_dir(
    mock_status, mock_ingest, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When QDRANT_STORAGE_PATH exists but is not a directory, DB shows dash."""
    mock_ingest.return_value = None
    mock_status.return_value = {"exists": True, "points_count": 10}
    f = tmp_path / "file"
    f.write_text("x")
    with patch.dict(
        "os.environ",
        {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333", "QDRANT_STORAGE_PATH": str(f)},
    ):
        assert cmd_index_status(make_args()) == 0
    out = capsys.readouterr().out
    assert "DB:" in out


@patch("onec_help.ingest.read_ingest_status")
@patch("onec_help.indexer.get_index_status")
@patch("os.walk")
def test_cmd_index_status_storage_path_oserror(
    mock_walk, mock_status, mock_ingest, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When os.walk raises OSError, DB shows dash."""
    mock_ingest.return_value = None
    mock_status.return_value = {"exists": True, "points_count": 10}
    mock_walk.side_effect = OSError("permission denied")
    with patch.dict(
        "os.environ",
        {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333", "QDRANT_STORAGE_PATH": str(tmp_path)},
    ):
        assert cmd_index_status(make_args()) == 0
    out = capsys.readouterr().out
    assert "DB:" in out


@patch("onec_help.ingest.read_ingest_status")
@patch("onec_help.indexer.get_index_status")
def test_cmd_index_status_ingest_with_eta(
    mock_status, mock_ingest, capsys: pytest.CaptureFixture[str]
) -> None:
    """index-status with ingest ETA prints ETA seconds."""
    mock_status.return_value = {"exists": True, "points_count": 10}
    mock_ingest.return_value = {
        "embedding_backend": "openai_api",
        "status": "in progress",
        "eta_sec": 120,
        "elapsed_sec": 10.0,
    }
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_index_status(make_args()) == 0
    out = capsys.readouterr().out
    assert "ETA" in out or "120" in out


@patch("onec_help.ingest.read_ingest_status")
@patch("onec_help.indexer.get_index_status")
def test_cmd_index_status_ingest_with_current_workers(
    mock_status, mock_ingest, capsys: pytest.CaptureFixture[str]
) -> None:
    """index-status with ingest current workers shows current file and stage."""
    mock_status.return_value = {"exists": True, "points_count": 10}
    mock_ingest.return_value = {
        "embedding_backend": "openai_api",
        "status": "in progress",
        "current": [{"path": "x", "version": "8.3", "language": "ru", "stage": "embed"}],
    }
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_index_status(make_args()) == 0
    out = capsys.readouterr().out
    assert "8.3/ru" in out and "embed" in out


@patch("onec_help.indexer.get_index_status")
def test_cmd_index_status_exists(mock_status) -> None:
    mock_status.return_value = {
        "exists": True,
        "collection": "onec_help",
        "points_count": 42,
        "versions": ["8.3.27"],
        "languages": ["ru"],
    }

    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_index_status(make_args()) == 0


@patch("onec_help.indexer.get_all_collections_status")
@patch("onec_help.ingest.read_ingest_status")
@patch("onec_help.indexer.get_index_status")
def test_cmd_index_status_shows_embeddings_and_db_size(
    mock_status, mock_ingest, mock_collections, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """index-status shows Collections (points, vectors, segments), total points, DB size."""
    mock_ingest.return_value = None
    mock_status.return_value = {
        "exists": True,
        "collection": "onec_help",
        "points_count": 100,
    }
    mock_collections.return_value = [
        {
            "name": "onec_help",
            "points_count": 100,
            "indexed_vectors_count": 100,
            "segments_count": 1,
        },
    ]
    (tmp_path / "some_file").write_bytes(b"x" * 500)  # ~0.5 KB

    with patch.dict(
        "os.environ",
        {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333", "QDRANT_STORAGE_PATH": str(tmp_path)},
    ):
        assert cmd_index_status(make_args()) == 0
    out = capsys.readouterr().out
    assert "index-status" in out
    assert "onec_help" in out
    assert "100" in out
    assert "total:" in out or "pts" in out
    assert "DB:" in out
    assert "MB" in out


@patch("onec_help.indexer.get_index_status")
def test_cmd_index_status_not_exists(mock_status) -> None:
    mock_status.return_value = {"exists": False}

    assert cmd_index_status(make_args()) == 0


@patch("onec_help.indexer.get_index_status")
def test_cmd_index_status_error(mock_status) -> None:
    mock_status.return_value = {"error": "connection refused"}
    assert cmd_index_status(make_args()) == 1


@patch("onec_help.ingest.read_ingest_status")
@patch("onec_help.indexer.get_index_status")
def test_cmd_index_status_with_ingest(
    mock_status, mock_ingest, capsys: pytest.CaptureFixture[str]
) -> None:
    """index-status shows embedding speed, per-folder, total time when ingest status exists.
    When status is completed, current is empty so no stale workers are shown."""
    mock_status.return_value = {
        "exists": True,
        "collection": "onec_help",
        "points_count": 100,
        "versions": ["8.3"],
        "languages": ["ru"],
    }
    mock_ingest.return_value = {
        "embedding_backend": "openai_api",
        "embedding_speed_pts_per_sec": 12.5,
        "elapsed_sec": 8.0,
        "status": "completed",
        "total_elapsed_sec": 8.2,
        "current": [],  # cleared when ingest completes
        "folders": [
            {
                "version": "8.3",
                "language": "ru",
                "hbk_count": 1,
                "html_count": 50,
                "md_count": 100,
                "err_count": 0,
                "points": 100,
                "status": "done",
            },
        ],
    }

    assert cmd_index_status(make_args()) == 0
    out = capsys.readouterr().out
    assert "Current (per thread):" not in out  # completed => no worker list


@patch("onec_help.indexer.get_all_collections_status")
@patch("onec_help.ingest.read_ingest_status")
@patch("onec_help.indexer.get_index_status")
def test_cmd_index_status_shows_failed_task_details(
    mock_status, mock_ingest, mock_collections, capsys: pytest.CaptureFixture[str]
) -> None:
    """index-status shows failed task error details when failed_tasks in ingest status."""
    mock_status.return_value = {"exists": True, "collection": "onec_help", "points_count": 100}
    mock_collections.return_value = [
        {
            "name": "onec_help",
            "points_count": 100,
            "indexed_vectors_count": 100,
            "segments_count": 1,
        },
    ]
    mock_ingest.return_value = {
        "status": "completed",
        "folders": [
            {"version": "8.3", "language": "ru", "err_count": 1, "hbk_count": 2},
        ],
        "failed_tasks": [
            {
                "version": "8.3",
                "language": "ru",
                "path": "shcntx_ru.hbk",
                "error": "7z failed: invalid archive",
            },
        ],
    }
    assert cmd_index_status(make_args()) == 0
    out = capsys.readouterr().out
    assert "1 failed" in out or "Failed: 1" in out
    assert "shcntx_ru" in out


@patch("onec_help.indexer.get_all_collections_status")
@patch("onec_help.ingest.read_last_ingest_run")
@patch("onec_help.ingest.read_ingest_status")
@patch("onec_help.indexer.get_index_status")
def test_cmd_index_status_shows_last_run_when_no_active_ingest(
    mock_status: MagicMock,
    mock_ingest: MagicMock,
    mock_last_run: MagicMock,
    mock_collections: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """index-status shows Last run from ingest_runs when no active ingest."""
    mock_status.return_value = {"exists": True, "collection": "onec_help", "points_count": 5000}
    mock_collections.return_value = [
        {
            "name": "onec_help",
            "points_count": 5000,
            "indexed_vectors_count": 5000,
            "segments_count": 2,
        },
    ]
    mock_ingest.return_value = None
    mock_last_run.return_value = {
        "status": "completed",
        "total_points": 5000,
        "total_elapsed_sec": 120.5,
        "failed_count": 0,
    }
    assert cmd_index_status(make_args()) == 0
    out = capsys.readouterr().out
    assert "Last run" in out
    assert "5000" in out and "pts" in out


@patch("onec_help.indexer.get_all_collections_status")
@patch("onec_help.ingest.read_ingest_cache_entries")
@patch("onec_help.ingest.read_ingest_failed_log")
@patch("onec_help.ingest.read_last_ingest_failed")
@patch("onec_help.ingest.read_last_ingest_run")
@patch("onec_help.ingest.read_ingest_status")
@patch("onec_help.indexer.get_index_status")
def test_cmd_index_status_shows_failed_placeholder_when_no_details(
    mock_status: MagicMock,
    mock_ingest: MagicMock,
    mock_last_run: MagicMock,
    mock_failed: MagicMock,
    mock_failed_log: MagicMock,
    mock_cache: MagicMock,
    mock_collections: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """index-status shows placeholder when failed_count > 0 but DB/log have no details."""
    mock_status.return_value = {"exists": True, "collection": "onec_help", "points_count": 100}
    mock_collections.return_value = [
        {
            "name": "onec_help",
            "points_count": 100,
            "indexed_vectors_count": 100,
            "segments_count": 1,
        },
    ]
    mock_ingest.return_value = None
    mock_last_run.return_value = {
        "status": "completed",
        "total_points": 100,
        "total_elapsed_sec": 10.0,
        "failed_count": 1,
    }
    mock_failed.return_value = []
    mock_failed_log.return_value = []
    mock_cache.return_value = []
    assert cmd_index_status(make_args()) == 0
    out = capsys.readouterr().out
    assert "1 failed" in out or "Failed" in out
    assert "Details not stored" in out or "re-run ingest" in out


@patch("onec_help.ingest.run_ingest")
def test_cmd_ingest_with_sources_env(mock_run_ingest, tmp_path: Path) -> None:
    mock_run_ingest.return_value = 10
    (tmp_path / "ver").mkdir()
    args = make_args(
        sources=None,
        sources_file=None,
        languages=None,
        temp_base=None,
        workers=2,
        max_tasks=None,
        quiet=False,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {
            "HELP_SOURCE_BASE": str(tmp_path),
            "QDRANT_HOST": "localhost",
            "QDRANT_PORT": "6333",
            "INGEST_USE_TEMP": "1",
        },
    ):
        with patch("onec_help.ingest.discover_version_dirs") as mock_disc:
            mock_disc.return_value = [(tmp_path / "ver", "ver")]
            assert cmd_ingest(args) == 0
    mock_run_ingest.assert_called_once()


@patch("onec_help.ingest.run_ingest")
def test_cmd_ingest_sources_arg(mock_run_ingest) -> None:
    mock_run_ingest.return_value = 5
    args = make_args(
        sources=["/path/to/1cv8:8.3"],
        sources_file=None,
        languages=None,
        temp_base="/tmp/t",
        workers=1,
        max_tasks=None,
        quiet=True,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333", "INGEST_USE_TEMP": "1"},
        clear=False,
    ):
        assert cmd_ingest(args) == 0
    mock_run_ingest.assert_called_once()
    call_kw = mock_run_ingest.call_args[1]
    assert call_kw["source_dirs_with_versions"] == [("/path/to/1cv8", "8.3")]


def test_env_path() -> None:
    assert _env_path("NONEXISTENT_VAR") is None
    with patch.dict("os.environ", {"TEST_VAR": "/path"}):
        assert _env_path("TEST_VAR") == "/path"
    with patch.dict("os.environ", {"PORT": "8080"}):
        assert _env_path("PORT", "5000") == "8080"
    assert _env_path("MISSING", "default") == "default"


def test_cmd_ingest_no_sources_returns_error() -> None:
    args = make_args(
        sources=None,
        sources_file=None,
        languages=None,
        temp_base=None,
        workers=1,
        max_tasks=None,
        quiet=False,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict("os.environ", {}, clear=True):
        assert cmd_ingest(args) == 1


@patch("onec_help.ingest.run_unpack_only")
def test_cmd_unpack_dir_sources_path_version(mock_run, tmp_path: Path) -> None:
    """cmd_unpack_dir parses sources as path:version."""
    mock_run.return_value = 1
    out = tmp_path / "out"
    out.mkdir()
    args = make_args(
        source_dir="",
        output_dir=str(out),
        sources=["/path/to/1cv8:8.3"],
        languages=None,
        workers=1,
    )
    assert cmd_unpack_dir(args) == 0
    call_kw = mock_run.call_args[1]
    assert call_kw["source_dirs_with_versions"] == [("/path/to/1cv8", "8.3")]


@patch("onec_help.ingest.run_unpack_only")
def test_cmd_unpack_dir_sources_path_only(mock_run, tmp_path: Path) -> None:
    """cmd_unpack_dir with single path (no colon) uses path name as version."""
    mock_run.return_value = 1
    out = tmp_path / "out"
    out.mkdir()
    args = make_args(
        source_dir="",
        output_dir=str(out),
        sources=["/single/path"],
        languages=None,
        workers=1,
    )
    assert cmd_unpack_dir(args) == 0
    call_kw = mock_run.call_args[1]
    assert len(call_kw["source_dirs_with_versions"]) == 1
    assert call_kw["source_dirs_with_versions"][0][0] == "/single/path"


def test_cmd_unpack_dir_no_sources_error(tmp_path: Path) -> None:
    """When no sources and no HELP_SOURCE_BASE, cmd_unpack_dir returns 1."""
    args = make_args(
        source_dir="",
        output_dir=str(tmp_path / "out"),
        sources=None,
        languages=None,
        workers=1,
    )
    with patch.dict("os.environ", {}, clear=True):
        assert cmd_unpack_dir(args) == 1


@patch("onec_help.ingest.run_unpack_only")
def test_cmd_unpack_dir_success(mock_run, tmp_path: Path) -> None:
    mock_run.return_value = 2
    args = make_args(
        source_dir=str(tmp_path),
        output_dir=str(tmp_path / "out"),
        sources=None,
        languages="ru",
        workers=1,
        quiet=True,
    )
    assert cmd_unpack_dir(args) == 0
    mock_run.assert_called_once()


@patch("onec_help.ingest.run_unpack_sync")
def test_cmd_unpack_sync_success(mock_run, tmp_path: Path) -> None:
    """cmd_unpack_sync calls run_unpack_sync with correct output dir."""
    mock_run.return_value = 1
    out = tmp_path / "unpacked"
    args = make_args(
        source_dir=str(tmp_path),
        output_dir=str(out),
        sources=None,
        languages="ru",
        workers=1,
        quiet=True,
    )
    assert cmd_unpack_sync(args) == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["output_dir"] == out


@patch("onec_help.ingest.run_unpack_sync")
def test_cmd_unpack_sync_no_sources_error(mock_run) -> None:
    """cmd_unpack_sync returns 1 when no sources."""
    args = make_args(
        source_dir="",
        output_dir=None,
        sources=None,
        languages=None,
        workers=1,
        quiet=True,
    )
    with patch.dict("os.environ", {}, clear=True):
        assert cmd_unpack_sync(args) == 1
    mock_run.assert_not_called()


@patch("onec_help.ingest.read_ingest_status", return_value=None)
@patch("onec_help.indexer.get_index_status", return_value={"error": "Connection refused"})
def test_render_index_status_returns_error_when_index_status_has_error(
    mock_status, mock_ingest
) -> None:
    """_render_index_status returns error string and code 1 when get_index_status has error."""
    out, code = _render_index_status()
    assert code == 1
    assert "Error:" in out and "Connection refused" in out


@patch("onec_help.indexer.build_index")
def test_cmd_build_index_incremental_no_bm25(mock_build, help_sample_dir: Path) -> None:
    """cmd_build_index passes incremental and no_bm25 to build_index."""
    mock_build.return_value = 3
    args = make_args(
        directory=str(help_sample_dir),
        docs_dir=None,
        incremental=True,
        no_bm25=True,
    )
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_build_index(args) == 0
    call_kw = mock_build.call_args[1]
    assert call_kw["incremental"] is True
    assert call_kw["bm25"] is False


def test_cmd_load_snippets_path_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    """cmd_load_snippets returns 1 when snippets_file path does not exist."""
    args = make_args(snippets_file="/nonexistent/snippets.json", from_project=False)
    with patch.dict("os.environ", {}, clear=True):
        assert cmd_load_snippets(args) == 1
    assert "not found" in capsys.readouterr().err


@patch("onec_help.cli._build_snippets_sources", return_value=[])
def test_cmd_load_snippets_no_source_returns_zero(
    mock_build, capsys: pytest.CaptureFixture[str]
) -> None:
    """cmd_load_snippets returns 0 when no source and SNIPPETS_DIR not set."""
    args = make_args(snippets_file=None, from_project=False)
    with patch.dict("os.environ", {"SNIPPETS_DIR": "", "SNIPPETS_JSON_PATH": ""}, clear=False):
        assert cmd_load_snippets(args) == 0
    err = capsys.readouterr().err
    assert "SNIPPETS_DIR" in err or "No source" in err or "not found" in err


def test_cmd_load_standards_path_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    """cmd_load_standards returns 1 when standards_path does not exist."""
    args = make_args(standards_path="/nonexistent/standards")
    with patch.dict("os.environ", {"STANDARDS_REPOS": "", "STANDARDS_REPO": ""}, clear=False):
        assert cmd_load_standards(args) == 1
    err = capsys.readouterr().err
    assert "not found" in err or "path" in err.lower() or "Error:" in err


@patch("onec_help.parse_fastcode.run_parse", return_value=0)
def test_cmd_parse_fastcode_pages_range(mock_run, tmp_path: Path) -> None:
    """cmd_parse_fastcode parses pages '1-3' as range."""
    args = make_args(pages="1-3", out=str(tmp_path / "out.json"), delay=0)
    assert cmd_parse_fastcode(args) == 0
    call_kw = mock_run.call_args[1]
    assert call_kw["pages"] == [1, 2, 3]


@patch("onec_help.parse_helpf.run_parse", return_value=0)
def test_cmd_parse_helpf_pages_list(mock_run, tmp_path: Path) -> None:
    """cmd_parse_helpf parses pages '1,2,5' as list."""
    args = make_args(
        pages="1,2,5",
        out=str(tmp_path / "helpf.json"),
        source="faq",
        delay=0,
        max_items=0,
    )
    assert cmd_parse_helpf(args) == 0
    call_kw = mock_run.call_args[1]
    assert call_kw["pages"] == [1, 2, 5]


@patch("urllib.request.urlopen")
def test_cmd_qdrant_backup_fails(
    mock_urlopen, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """cmd_qdrant_backup returns 1 when API raises."""
    mock_urlopen.side_effect = OSError("Connection refused")
    args = make_args(output_dir=str(tmp_path))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_backup(args) == 1
    assert "Error:" in capsys.readouterr().err


def test_cmd_qdrant_restore_file_not_found(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """cmd_qdrant_restore returns 1 when file path does not exist."""
    args = make_args(file=str(tmp_path / "missing.snapshot"), backup_dir=str(tmp_path))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_restore(args) == 1
    assert "not found" in capsys.readouterr().err or "Error:" in capsys.readouterr().err


@patch("onec_help.cli.cmd_load_standards", return_value=0)
@patch("onec_help.cli.cmd_load_snippets", return_value=0)
@patch("onec_help.cli.cmd_ingest", return_value=0)
@patch("onec_help.ingest.clear_ingest_cache")
def test_cmd_reinit_force(
    mock_clear_cache, mock_ingest, mock_snippets, mock_standards, tmp_path: Path
) -> None:
    """cmd_reinit with force clears cache and runs init."""
    args = make_args(force=True)
    with patch.dict(
        "os.environ",
        {"HELP_SOURCE_BASE": str(tmp_path), "QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"},
        clear=False,
    ):
        rc = cmd_reinit(args)
    assert rc == 0
    mock_clear_cache.assert_called()
    mock_ingest.assert_called()
    mock_snippets.assert_called()
    mock_standards.assert_called()


@patch("onec_help.mcp_server.run_mcp")
def test_cmd_mcp_runtime_error_fastmcp(mock_run_mcp, capsys: pytest.CaptureFixture[str]) -> None:
    """cmd_mcp returns 1 when run_mcp raises RuntimeError mentioning fastmcp."""
    mock_run_mcp.side_effect = RuntimeError("fastmcp not installed")
    args = make_args(directory="data", transport="stdio")
    assert cmd_mcp(args) == 1
    assert "fastmcp" in capsys.readouterr().err.lower()


@patch("onec_help.ingest.run_ingest_from_unpacked")
def test_cmd_ingest_from_unpacked_success(mock_run, tmp_path: Path) -> None:
    """cmd_ingest_from_unpacked calls run_ingest_from_unpacked with correct dir."""
    mock_run.return_value = 10
    (tmp_path / "8.3").mkdir()
    (tmp_path / "8.3" / "1cv8_ru").mkdir()
    (tmp_path / "8.3" / "1cv8_ru" / "a.html").write_text("<html>")
    args = make_args(
        dir=str(tmp_path),
        recreate=False,
        quiet=True,
        embedding_batch_size=None,
        embedding_workers=None,
        bm25=False,
        no_bm25=False,
    )
    assert cmd_ingest_from_unpacked(args) == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["unpacked_base"] == tmp_path.resolve()


@patch("onec_help.ingest.run_ingest_from_unpacked")
def test_cmd_ingest_from_unpacked_dir_missing(mock_run) -> None:
    """cmd_ingest_from_unpacked returns 1 when unpacked dir does not exist."""
    args = make_args(dir="/nonexistent/unpacked", recreate=False, quiet=True)
    with patch.dict("os.environ", {}, clear=True):
        assert cmd_ingest_from_unpacked(args) == 1
    mock_run.assert_not_called()


@patch("onec_help.ingest.run_ingest")
def test_cmd_ingest_sources_file(mock_run, tmp_path: Path) -> None:
    mock_run.return_value = 3
    sf = tmp_path / "sources.txt"
    sf.write_text("/path/1:ver1\n/path/2:ver2\n", encoding="utf-8")
    args = make_args(
        sources=None,
        sources_file=str(sf),
        languages=None,
        temp_base=None,
        workers=1,
        max_tasks=None,
        quiet=True,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333", "INGEST_USE_TEMP": "1"},
        clear=False,
    ):
        assert cmd_ingest(args) == 0
    call_kw = mock_run.call_args[1]
    assert len(call_kw["source_dirs_with_versions"]) == 2


@patch("onec_help.ingest.run_ingest")
def test_cmd_ingest_sources_file_path_only(mock_run, tmp_path: Path) -> None:
    """sources_file with lines without colon uses path name as version."""
    mock_run.return_value = 1
    sf = tmp_path / "list.txt"
    sf.write_text("/only/path\n", encoding="utf-8")
    args = make_args(
        sources=None,
        sources_file=str(sf),
        languages=None,
        temp_base=None,
        workers=1,
        max_tasks=None,
        quiet=True,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333", "INGEST_USE_TEMP": "1"},
        clear=False,
    ):
        assert cmd_ingest(args) == 0
    call_kw = mock_run.call_args[1]
    assert len(call_kw["source_dirs_with_versions"]) == 1
    assert call_kw["source_dirs_with_versions"][0][0] == "/only/path"


@patch("onec_help.ingest.run_ingest_from_unpacked")
@patch("onec_help.ingest.run_unpack_sync")
def test_cmd_ingest_default_unpacked(mock_unpack, mock_from_unpacked, tmp_path: Path) -> None:
    """By default cmd_ingest runs unpack-sync to data/unpacked + ingest-from-unpacked."""
    mock_unpack.return_value = 1
    mock_from_unpacked.return_value = 10
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "1cv8_ru.hbk").write_bytes(b"x")
    args = make_args(
        sources=[str(tmp_path) + ":v"],
        sources_file=None,
        languages="ru",
        temp_base=None,
        workers=1,
        max_tasks=None,
        quiet=True,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {
            "QDRANT_HOST": "localhost",
            "QDRANT_PORT": "6333",
            "DATA_UNPACKED_DIR": str(tmp_path / "unpacked"),
        },
        clear=False,
    ):
        assert cmd_ingest(args) == 0
    mock_unpack.assert_called_once()
    mock_from_unpacked.assert_called_once()
    assert mock_from_unpacked.call_args[1]["unpacked_base"] == (tmp_path / "unpacked").resolve()


@patch("onec_help.ingest.run_ingest")
def test_cmd_ingest_use_temp(mock_run_ingest, tmp_path: Path) -> None:
    """When INGEST_USE_TEMP=1, cmd_ingest uses temp dir and run_ingest (no unpack_sync)."""
    mock_run_ingest.return_value = 5
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "1cv8_ru.hbk").write_bytes(b"x")
    args = make_args(
        sources=[str(tmp_path) + ":v"],
        sources_file=None,
        languages="ru",
        temp_base=None,
        workers=1,
        max_tasks=None,
        quiet=True,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {
            "QDRANT_HOST": "localhost",
            "QDRANT_PORT": "6333",
            "INGEST_USE_TEMP": "1",
        },
        clear=False,
    ):
        assert cmd_ingest(args) == 0
    mock_run_ingest.assert_called_once()


@patch("onec_help.ingest.run_ingest")
def test_cmd_ingest_exception(mock_run) -> None:
    mock_run.side_effect = RuntimeError("Qdrant down")
    args = make_args(
        sources=["/x:v"],
        sources_file=None,
        languages=None,
        temp_base=None,
        workers=1,
        max_tasks=None,
        quiet=True,
        dry_run=False,
        index_batch_size=500,
    )
    with patch.dict(
        "os.environ",
        {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333", "INGEST_USE_TEMP": "1"},
        clear=False,
    ):
        assert cmd_ingest(args) == 1


@patch("onec_help.watchdog.run_watchdog")
def test_cmd_watchdog_success(mock_run_watchdog) -> None:
    """cmd_watchdog calls run_watchdog with poll/pending intervals and returns 0."""
    args = make_args(poll_interval=120, pending_interval=300)
    assert cmd_watchdog(args) == 0
    mock_run_watchdog.assert_called_once_with(
        poll_interval_sec=120,
        pending_interval_sec=300,
    )


@patch("onec_help.watchdog.run_watchdog")
def test_cmd_watchdog_exception(mock_run_watchdog) -> None:
    """cmd_watchdog returns 1 when run_watchdog raises."""
    mock_run_watchdog.side_effect = RuntimeError("watchdog error")
    args = make_args(poll_interval=60, pending_interval=60)
    assert cmd_watchdog(args) == 1


@patch("onec_help.watchdog.run_watchdog")
def test_cmd_watchdog_keyboard_interrupt(mock_run_watchdog) -> None:
    """cmd_watchdog returns 0 on KeyboardInterrupt (graceful exit)."""
    mock_run_watchdog.side_effect = KeyboardInterrupt
    args = make_args(poll_interval=60, pending_interval=60)
    assert cmd_watchdog(args) == 0


@patch("onec_help.mcp_server.run_mcp")
def test_cmd_mcp_run_raises(mock_run_mcp) -> None:
    """When run_mcp raises (e.g. fastmcp required), cmd_mcp returns 1."""
    mock_run_mcp.side_effect = RuntimeError("fastmcp required: pip install fastmcp")
    args = make_args(directory="/tmp", transport=None, host=None, port=None, path=None)
    assert cmd_mcp(args) == 1


def test_cmd_load_snippets_file_not_found() -> None:
    """cmd_load_snippets returns 1 when path does not exist."""
    args = make_args(snippets_file="/nonexistent/snippets.json")
    assert cmd_load_snippets(args) == 1


def test_cmd_load_snippets_no_source(capsys) -> None:
    """cmd_load_snippets returns 0 with message when no path and no SNIPPETS_DIR."""
    with patch.dict("os.environ", {"SNIPPETS_JSON_PATH": "", "SNIPPETS_DIR": ""}, clear=False):
        args = make_args(snippets_file=None)
        assert cmd_load_snippets(args) == 0
    out = capsys.readouterr().err
    assert "No source" in out or "examples only" in out


def test_cmd_load_snippets_invalid_json(tmp_path: Path) -> None:
    """cmd_load_snippets returns 1 when JSON is invalid."""
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    args = make_args(snippets_file=str(bad))
    assert cmd_load_snippets(args) == 1


def test_cmd_load_snippets_not_array(tmp_path: Path) -> None:
    """cmd_load_snippets returns 1 when JSON is not an array."""
    bad = tmp_path / "bad.json"
    bad.write_text('{"title": "x"}')
    args = make_args(snippets_file=str(bad))
    assert cmd_load_snippets(args) == 1


@patch("onec_help.memory.get_memory_store")
def test_cmd_load_snippets_success(mock_get_store, tmp_path: Path) -> None:
    """cmd_load_snippets loads snippets and prints count."""
    snippet_file = tmp_path / "snippets.json"
    snippet_file.write_text(
        '[{"title": "Test", "description": "desc", "code_snippet": "Сообщить(1);"}]',
        encoding="utf-8",
    )
    mock_store = MagicMock()
    mock_store.upsert_curated_snippets.return_value = 1
    mock_get_store.return_value = mock_store
    args = make_args(snippets_file=str(snippet_file))
    assert cmd_load_snippets(args) == 0
    mock_store.upsert_curated_snippets.assert_called_once()
    call_args = mock_store.upsert_curated_snippets.call_args[0][0]
    assert len(call_args) == 1
    assert call_args[0]["title"] == "Test"


def test_main_load_snippets(tmp_path: Path) -> None:
    """main() parses load-snippets and invokes cmd_load_snippets."""
    snippet_file = tmp_path / "snippets.json"
    snippet_file.write_text('[{"title": "X", "code_snippet": "x"}]', encoding="utf-8")
    with patch("onec_help.memory.get_memory_store") as mock_get:
        mock_store = MagicMock()
        mock_store.upsert_curated_snippets.return_value = 1
        mock_get.return_value = mock_store
        with patch("sys.argv", ["onec_help", "load-snippets", str(snippet_file)]):
            assert main() == 0
        mock_store.upsert_curated_snippets.assert_called_once()


def test_cmd_load_snippets_exception(tmp_path: Path) -> None:
    """cmd_load_snippets returns 1 when get_memory_store raises."""
    snippet_file = tmp_path / "snippets.json"
    snippet_file.write_text('[{"title": "X", "code_snippet": "x"}]', encoding="utf-8")
    with patch("onec_help.memory.get_memory_store", side_effect=RuntimeError("no qdrant")):
        args = make_args(snippets_file=str(snippet_file))
        assert cmd_load_snippets(args) == 1


@patch("onec_help.memory.get_memory_store")
def test_cmd_load_snippets_from_folder(mock_get_store, tmp_path: Path) -> None:
    """cmd_load_snippets loads from folder (*.bsl, *.1c, *.json) when path is directory."""
    (tmp_path / "example.bsl").write_text("Сообщить(1);", encoding="utf-8")
    (tmp_path / "other.1c").write_text("Возврат Истина;", encoding="utf-8")
    (tmp_path / "extra.json").write_text(
        '[{"title":"FromJSON","description":"","code_snippet":"Возврат;"}]', encoding="utf-8"
    )
    mock_store = MagicMock()
    mock_store.upsert_curated_snippets.return_value = 3
    mock_get_store.return_value = mock_store
    args = make_args(snippets_file=str(tmp_path))
    assert cmd_load_snippets(args) == 0
    mock_store.upsert_curated_snippets.assert_called_once()
    items = mock_store.upsert_curated_snippets.call_args[0][0]
    assert len(items) == 3
    titles = {it["title"] for it in items}
    assert titles == {"example", "other", "FromJSON"}


@patch("onec_help.memory.get_memory_store")
def test_cmd_load_snippets_type_split(mock_get_store, tmp_path: Path) -> None:
    """cmd_load_snippets splits items by type into snippets and community_help domains."""
    mixed = tmp_path / "mixed.json"
    mixed.write_text(
        json.dumps(
            [
                {
                    "title": "Snippet1",
                    "code_snippet": "Процедура Х()\nКонецПроцедуры",
                    "type": "snippet",
                },
                {
                    "title": "Ref1",
                    "description": "Long text " * 50,
                    "code_snippet": "x",
                    "type": "reference",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    mock_store = MagicMock()
    mock_store.upsert_curated_snippets.return_value = 1
    mock_get_store.return_value = mock_store
    args = make_args(snippets_file=str(mixed))
    assert cmd_load_snippets(args) == 0
    assert mock_store.upsert_curated_snippets.call_count == 2
    calls = mock_store.upsert_curated_snippets.call_args_list
    domains = [c[1]["domain"] for c in calls]
    assert "snippets" in domains
    assert "community_help" in domains


@patch("urllib.request.urlopen")
def test_cmd_qdrant_backup_success(mock_urlopen, tmp_path: Path) -> None:
    """cmd_qdrant_backup creates snapshot and saves to output dir."""
    create_resp = MagicMock()
    create_resp.read.return_value = b'{"result":{"name":"abc-123.snapshot"}}'
    create_resp.__enter__ = lambda self: self
    create_resp.__exit__ = lambda *a: None
    download_resp = MagicMock()
    download_resp.read.return_value = b"snapshot-data"
    download_resp.__enter__ = lambda self: self
    download_resp.__exit__ = lambda *a: None
    mock_urlopen.side_effect = [create_resp, download_resp]

    out_dir = tmp_path / "backup"
    args = make_args(output_dir=str(out_dir))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_backup(args) == 0

    assert mock_urlopen.call_count == 2
    snaps = list(out_dir.glob("onec_help-*.snapshot"))
    assert len(snaps) == 1
    assert snaps[0].read_bytes() == b"snapshot-data"


@patch("urllib.request.urlopen")
def test_cmd_qdrant_backup_no_name_in_response(mock_urlopen, tmp_path: Path) -> None:
    """cmd_qdrant_backup returns 1 when response has no snapshot name."""
    create_resp = MagicMock()
    create_resp.read.return_value = b'{"result":{}}'
    mock_urlopen.return_value = create_resp

    args = make_args(output_dir=str(tmp_path / "backup"))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_backup(args) == 1


@patch("urllib.request.urlopen")
def test_cmd_qdrant_backup_http_error(mock_urlopen, tmp_path: Path) -> None:
    """cmd_qdrant_backup returns 1 on HTTP/network error."""
    import urllib.error

    mock_urlopen.side_effect = urllib.error.URLError("connection refused")

    args = make_args(output_dir=str(tmp_path / "backup"))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_backup(args) == 1


@patch("urllib.request.urlopen")
def test_cmd_qdrant_restore_success(mock_urlopen, tmp_path: Path) -> None:
    """cmd_qdrant_restore restores from snapshot file."""
    snap = tmp_path / "onec_help-20260302-120000.snapshot"
    snap.write_bytes(b"snapshot-content")

    resp = MagicMock()
    resp.read.return_value = b'{"status":"ok"}'
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: None
    mock_urlopen.return_value = resp

    args = make_args(backup_dir=str(tmp_path), file=str(snap))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_restore(args) == 0

    mock_urlopen.assert_called_once()


@patch("urllib.request.urlopen")
def test_cmd_qdrant_restore_latest_from_dir(mock_urlopen, tmp_path: Path) -> None:
    """cmd_qdrant_restore uses latest snapshot when file not specified."""
    (tmp_path / "onec_help-20260301-100000.snapshot").write_bytes(b"old")
    (tmp_path / "onec_help-20260302-120000.snapshot").write_bytes(b"new")

    resp = MagicMock()
    resp.read.return_value = b'{"status":"ok"}'
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: None
    mock_urlopen.return_value = resp

    args = make_args(backup_dir=str(tmp_path), file=None)
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_restore(args) == 0

    # Should use latest (20260302)
    call_data = mock_urlopen.call_args[0][0].data
    assert b"new" in call_data
    assert b"old" not in call_data


def test_cmd_qdrant_restore_no_snapshots(tmp_path: Path) -> None:
    """cmd_qdrant_restore returns 1 when backup dir has no snapshots."""
    args = make_args(backup_dir=str(tmp_path), file=None)
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_restore(args) == 1


@patch("urllib.request.urlopen")
def test_cmd_qdrant_restore_http_error(mock_urlopen, tmp_path: Path) -> None:
    """cmd_qdrant_restore returns 1 on HTTP/network error."""
    import urllib.error

    snap = tmp_path / "onec_help-20260302.snapshot"
    snap.write_bytes(b"data")
    mock_urlopen.side_effect = urllib.error.URLError("connection refused")

    args = make_args(backup_dir=str(tmp_path), file=str(snap))
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        assert cmd_qdrant_restore(args) == 1


@patch("onec_help.parse_fastcode.run_parse")
def test_cmd_parse_fastcode(mock_run, tmp_path: Path) -> None:
    """cmd_parse_fastcode delegates to run_parse with correct args."""
    mock_run.return_value = 0
    args = SimpleNamespace(
        out=str(tmp_path / "out.json"), pages="1-3", delay=0.5, no_fetch_detail=False
    )
    assert cmd_parse_fastcode(args) == 0
    mock_run.assert_called_once()
    call_kw = mock_run.call_args[1]
    assert list(call_kw["out"].parts)[-1] == "out.json"
    assert call_kw["pages"] == [1, 2, 3]
    assert call_kw["fetch_detail"] is True


@patch("onec_help.parse_fastcode.run_parse")
def test_cmd_parse_fastcode_auto_pages(mock_run, tmp_path: Path) -> None:
    """cmd_parse_fastcode with pages=auto passes None."""
    mock_run.return_value = 0
    args = SimpleNamespace(
        out=str(tmp_path / "out.json"), pages="auto", delay=1.0, no_fetch_detail=True
    )
    assert cmd_parse_fastcode(args) == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["pages"] is None


@patch("onec_help.parse_helpf.run_parse")
def test_cmd_parse_helpf(mock_run, tmp_path: Path) -> None:
    """cmd_parse_helpf delegates to run_parse."""
    mock_run.return_value = 0
    args = SimpleNamespace(
        out=str(tmp_path / "helpf.json"),
        pages="1",
        source="faq",
        max_items=10,
        delay=1.0,
        no_fetch_detail=True,
    )
    assert cmd_parse_helpf(args) == 0
    mock_run.assert_called_once()
    call_kw = mock_run.call_args[1]
    assert call_kw["source"] == "faq"
    assert call_kw["max_items"] == 10


def test_cmd_load_standards_no_source(capsys) -> None:
    """cmd_load_standards returns 0 when no path and no STANDARDS_* (default disabled)."""
    import onec_help.cli as cli_mod

    args = make_args(standards_path=None)
    with (
        patch.dict(
            "os.environ",
            {"STANDARDS_DIR": "", "STANDARDS_REPO": "", "STANDARDS_REPOS": ""},
            clear=False,
        ),
        patch.object(cli_mod, "_DEFAULT_STANDARDS_REPOS", ""),
    ):
        assert cmd_load_standards(args) == 0
    err = capsys.readouterr().err
    assert "No source" in err and (
        "STANDARDS_REPO" in err or "STANDARDS_REPOS" in err or "STANDARDS_DIR" in err
    )


@patch("onec_help.memory.get_memory_store")
def test_cmd_load_standards_success(mock_get_store, tmp_path: Path) -> None:
    """cmd_load_standards loads markdown and upserts with domain=standards."""
    (tmp_path / "rule.md").write_text("# Проверка\n\nОписание правила.", encoding="utf-8")
    mock_store = MagicMock()
    mock_store.upsert_curated_snippets.return_value = 1
    mock_get_store.return_value = mock_store
    args = make_args(standards_path=str(tmp_path))
    assert cmd_load_standards(args) == 0
    mock_store.upsert_curated_snippets.assert_called_once()
    call_kw = mock_store.upsert_curated_snippets.call_args[1]
    assert call_kw.get("domain") == "standards"


@patch("onec_help.memory.get_memory_store")
@patch("onec_help.standards_loader.fetch_repo_archive")
def test_cmd_load_standards_from_repo(mock_fetch, mock_get_store, tmp_path: Path) -> None:
    """cmd_load_standards fetches from STANDARDS_REPO when no path given.
    Redirect copy destination to tmp_path to avoid writing to data/standards (pytest-* pollution)."""
    fetch_dir = tmp_path / "fetched"
    fetch_dir.mkdir()
    (fetch_dir / "fetched.md").write_text("# Fetched rule\n\nContent.", encoding="utf-8")
    mock_fetch.return_value = (fetch_dir, Path("/tmp/nonexistent_standards_xxx"))
    mock_store = MagicMock()
    mock_store.upsert_curated_snippets.return_value = 1
    mock_get_store.return_value = mock_store
    standards_out = tmp_path / "standards_out"
    standards_out.mkdir()
    args = make_args(standards_path=None)
    original_resolve = Path.resolve

    def resolve_redirect(self: Path) -> Path:
        # Redirect data/standards to tmp to avoid polluting repo (pytest-* dirs)
        if len(self.parts) == 2 and self.parts[0] == "data" and self.parts[1] == "standards":
            return standards_out.resolve()
        return original_resolve(self)

    with (
        patch.dict(
            "os.environ",
            {
                "STANDARDS_DIR": "",
                "STANDARDS_REPOS": "",
                "STANDARDS_REPO": "https://github.com/1C-Company/v8-code-style",
            },
        ),
        patch.object(Path, "resolve", resolve_redirect),
    ):
        assert cmd_load_standards(args) == 0
    mock_fetch.assert_called_once()
    mock_store.upsert_curated_snippets.assert_called_once()


@patch("onec_help.memory.get_memory_store")
@patch("onec_help.standards_loader.fetch_repo_archive")
def test_cmd_load_standards_from_repos(mock_fetch, mock_get_store, tmp_path: Path) -> None:
    """cmd_load_standards fetches from STANDARDS_REPOS (multiple repos) when set.
    Redirect copy destination to tmp_path to avoid writing to data/standards."""
    fetch1 = tmp_path / "repo1"
    fetch2 = tmp_path / "repo2"
    fetch1.mkdir()
    fetch2.mkdir()
    (fetch1 / "a.md").write_text("# A\n\nFrom first.", encoding="utf-8")
    (fetch2 / "b.md").write_text("# B\n\nFrom second.", encoding="utf-8")
    mock_fetch.side_effect = [
        (fetch1, Path("/tmp/tmp1")),
        (fetch2, Path("/tmp/tmp2")),
    ]
    mock_store = MagicMock()
    mock_store.upsert_curated_snippets.return_value = 2
    mock_get_store.return_value = mock_store
    standards_out = tmp_path / "standards_out"
    standards_out.mkdir()
    args = make_args(standards_path=None)
    original_resolve = Path.resolve

    def resolve_redirect(self: Path) -> Path:
        if len(self.parts) == 2 and self.parts[0] == "data" and self.parts[1] == "standards":
            return standards_out.resolve()
        return original_resolve(self)

    with (
        patch.dict(
            "os.environ",
            {
                "STANDARDS_DIR": "",
                "STANDARDS_REPOS": "1C-Company/v8-code-style:master,zeegin/v8std:main",
                "STANDARDS_REPO": "",
            },
        ),
        patch.object(Path, "resolve", resolve_redirect),
    ):
        assert cmd_load_standards(args) == 0
    assert mock_fetch.call_count == 2
    mock_store.upsert_curated_snippets.assert_called_once()


@patch("onec_help.indexer.get_index_status")
def test_main_index_status(mock_status) -> None:
    """main() parses argv and invokes cmd_index_status."""
    mock_status.return_value = {"exists": True, "points_count": 10, "collection": "onec_help"}
    with patch("sys.argv", ["onec_help", "index-status"]):
        from onec_help.cli import main

        assert main() == 0
    mock_status.assert_called_once()


@patch("onec_help.parse_fastcode.run_parse")
def test_main_parse_fastcode(mock_run, tmp_path: Path) -> None:
    """main() with parse-fastcode invokes run_parse."""
    mock_run.return_value = 0
    out = tmp_path / "fc.json"
    with patch("sys.argv", ["onec_help", "parse-fastcode", "--out", str(out), "--pages", "1"]):
        assert main() == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["out"] == out


@patch("onec_help.parse_helpf.run_parse")
def test_main_parse_helpf(mock_run, tmp_path: Path) -> None:
    """main() with parse-helpf invokes run_parse."""
    mock_run.return_value = 0
    out = tmp_path / "helpf.json"
    with patch(
        "sys.argv",
        ["onec_help", "parse-helpf", "--out", str(out), "--source", "faq", "--pages", "1"],
    ):
        assert main() == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[1]["source"] == "faq"


# --- _render_index_status_compact / _render_index_status_rich branches ---


def _format_duration(sec: float | None) -> str:
    if sec is None:
        return "—"
    if sec < 60:
        return f"{sec:.0f}s"
    return f"{sec / 60:.1f}m"


def test_render_index_status_rich_ingest_in_progress() -> None:
    """_render_index_status_rich: ingest in progress, progress bar, current, completed, failed."""
    s = {"exists": True, "versions": ["8.3"], "languages": ["ru"]}
    collections = [{"name": "onec_help", "points_count": 100}]
    ingest = {
        "status": "in_progress",
        "embedding_backend": "local",
        "done_tasks": 2,
        "total_tasks": 5,
        "total_points": 50,
        "current_task_points": 20,
        "current_task_estimated_total": 100,
        "estimated_total_points": 200,
        "max_workers": 2,
        "current": [
            {"stage": "embedding", "version": "8.3", "language": "ru", "path": "a.hbk"},
            {"stage": "build_docs", "version": "8.3", "language": "ru", "path": "b.hbk"},
        ],
        "completed_files": [
            {"path": "c.hbk", "status": "ok", "version": "8.3", "language": "ru", "points": 10},
        ],
        "folders": [{"err_count": 1}],
        "failed_tasks": [{"path": "x.hbk", "error": "err", "version": "8.3", "language": "ru"}],
    }
    snippets = None
    with patch("onec_help.cli.os.get_terminal_size", side_effect=OSError):
        out, code = _render_index_status_rich(
            s, collections, ingest, snippets, "", _format_duration, "localhost", 6333
        )
    assert code == 0
    assert "index-status" in out
    assert "Ingest" in out or "embed" in out
    assert "Failed" in out or "err" in out


def test_render_index_status_compact_with_ingest_in_progress(tmp_path: Path) -> None:
    """_render_index_status_compact: ingest in progress, current, completed, eta, snippets."""
    s = {"exists": True, "versions": ["8.3"], "languages": ["ru"]}
    collections = [
        {"name": "onec_help", "points_count": 50},
        {"name": "other", "points_count": 30},
    ]
    ingest = {
        "status": "in_progress",
        "embedding_backend": "openai_api",
        "elapsed_sec": 10.0,
        "eta_sec": 5.0,
        "eta_finish_at": 1234567890.0,
        "done_tasks": 2,
        "total_tasks": 5,
        "total_points": 50,
        "current_task_points": 10,
        "current_task_estimated_total": 100,
        "estimated_total_points": 200,
        "max_workers": 2,
        "current": [
            {"stage": "embedding", "version": "8.3", "language": "ru", "path": "a.hbk"},
        ],
        "completed_files": [
            {"path": "b.hbk", "status": "ok", "version": "8.3", "language": "ru", "points": 10},
            {"path": "c.hbk", "status": "skip", "version": "8.3", "language": "ru"},
        ],
        "folders": [],
    }
    snippets = {
        "files_processed": 1,
        "files_skipped": 0,
        "items_loaded": 5,
        "total_elapsed_sec": 1.0,
    }
    with patch.dict("os.environ", {}, clear=False):
        out, code = _render_index_status_compact(
            s, collections, ingest, snippets, "", _format_duration
        )
    assert code == 0
    assert "Ingest" in out and "embed:" in out
    assert "Snippets" in out


def test_render_index_status_compact_with_failed_and_snippets_cached(tmp_path: Path) -> None:
    """_render_index_status_compact: failed_tasks and snippets with cached_total."""
    s = {"exists": True}
    collections = [{"name": "onec_help", "points_count": 10}]
    ingest = {
        "status": "completed",
        "embedding_backend": "none",
        "folders": [{"err_count": 1}],
        "failed_tasks": [
            {"path": "x.hbk", "error": "7z failed", "version": "8.3", "language": "ru"}
        ],
    }
    snippets = {"files_processed": 0, "files_skipped": 2, "items_loaded": 0}
    with patch("onec_help.snippets_cache.get_cached_items_total", return_value=42):
        with patch.dict("os.environ", {}, clear=False):
            out, code = _render_index_status_compact(
                s, collections, ingest, snippets, "", _format_duration
            )
    assert code == 0
    assert "Failed" in out or "failed" in out


@patch("onec_help.snippets_cache.get_cached_items_total", return_value=10)
def test_render_index_status_compact_snippets_cached(mock_cached) -> None:
    """_render_index_status_compact: snippets with fp=0, il=0, fs>0 triggers get_cached_items_total."""
    s = {"exists": True}
    collections = [{"name": "c", "points_count": 0}]
    ingest = None
    snippets = {"files_processed": 0, "files_skipped": 1, "items_loaded": 0}
    out, code = _render_index_status_compact(s, collections, ingest, snippets, "", _format_duration)
    assert code == 0
    mock_cached.assert_called_once()


@patch("onec_help.ingest.read_ingest_failed_log")
def test_render_index_status_compact_failed_log_fallback(mock_read_failed) -> None:
    """_render_index_status_compact: total_err>0 and no failed_tasks -> read_ingest_failed_log."""
    mock_read_failed.return_value = [{"path": "a.hbk", "error": "err"}]
    s = {"exists": True}
    collections = [{"name": "c", "points_count": 0}]
    ingest = {
        "status": "in_progress",
        "embedding_backend": "none",
        "folders": [{"err_count": 1}],
        "failed_tasks": [],
    }
    snippets = None
    out, code = _render_index_status_compact(s, collections, ingest, snippets, "", _format_duration)
    assert code == 0
    mock_read_failed.assert_called_once()


@patch("onec_help.indexer.get_all_collections_status")
@patch("onec_help.ingest.read_ingest_status")
@patch("onec_help.indexer.get_index_status")
def test_render_index_status_compact_via_cmd(
    mock_status, mock_ingest, mock_collections, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """cmd_index_status(compact=True) uses _render_index_status_compact."""
    mock_status.return_value = {
        "exists": True,
        "collection": "onec_help",
        "points_count": 100,
        "versions": ["8.3"],
        "languages": ["ru"],
    }
    mock_collections.return_value = [
        {
            "name": "onec_help",
            "points_count": 100,
            "indexed_vectors_count": 100,
            "segments_count": 1,
        },
    ]
    mock_ingest.return_value = {
        "status": "completed",
        "embedding_backend": "local",
        "total_elapsed_sec": 5.0,
    }
    with patch("onec_help.snippets_cache.read_last_snippets_run", return_value={"items_loaded": 0}):
        with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
            assert cmd_index_status(make_args(compact=True)) == 0
    out = capsys.readouterr().out
    assert "index-status" in out
    assert "100" in out


@patch("onec_help.snippets_cache.read_last_snippets_run", return_value=None)
@patch("onec_help.indexer.get_all_collections_status", return_value=[])
@patch("onec_help.ingest.read_last_ingest_run", return_value=None)
@patch("onec_help.ingest.read_ingest_status", return_value=None)
@patch("onec_help.indexer.get_index_status", return_value={"exists": False})
def test_render_index_status_no_collections_no_ingest(
    mock_status, mock_ingest, mock_last_run, mock_collections, mock_snippets
) -> None:
    """_render_index_status returns 'Index does not exist' when no collections and no ingest."""
    with patch.dict("os.environ", {"QDRANT_HOST": "localhost", "QDRANT_PORT": "6333"}):
        out, code = _render_index_status(compact=True)
    assert code == 0
    assert "Index does not exist" in out


def test_build_snippets_sources_from_project(tmp_path: Path) -> None:
    """_build_snippets_sources with from_project adds folder."""
    (tmp_path / "a").mkdir()
    args = make_args(from_project=str(tmp_path), snippets_file=None)
    with patch.dict("os.environ", {"SNIPPETS_DIR": "", "SNIPPETS_JSON_PATH": ""}, clear=False):
        sources = _build_snippets_sources(args)
    assert len(sources) == 1
    assert sources[0][1] == "folder"


def test_build_snippets_sources_json_file(tmp_path: Path) -> None:
    """_build_snippets_sources with snippets_file path to file adds json."""
    j = tmp_path / "s.json"
    j.write_text("[]")
    args = make_args(snippets_file=str(j), from_project=None)
    with patch.dict("os.environ", {"SNIPPETS_DIR": "", "SNIPPETS_JSON_PATH": ""}, clear=False):
        sources = _build_snippets_sources(args)
    assert len(sources) >= 1
    assert any(s[1] == "json" for s in sources)


def test_build_snippets_sources_snippets_dir(tmp_path: Path) -> None:
    """_build_snippets_sources with SNIPPETS_DIR adds dir and jsons."""
    (tmp_path / "x.json").write_text("[]")
    args = make_args(snippets_file=None, from_project=None)
    with patch.dict(
        "os.environ", {"SNIPPETS_DIR": str(tmp_path), "SNIPPETS_JSON_PATH": ""}, clear=False
    ):
        sources = _build_snippets_sources(args)
    assert any(s[1] == "folder" for s in sources)
    assert any(s[1] == "json" for s in sources)


def test_render_index_status_rich_ingest_completed_with_elapsed_and_failed() -> None:
    """_render_index_status_rich: status completed shows total_elapsed_sec and failed_count."""
    from onec_help._utils import format_duration

    s = {"exists": True, "points_count": 100}
    collections = [{"name": "onec_help", "points_count": 100}]
    ingest = {
        "status": "completed",
        "embedding_backend": "openai_api",
        "total_elapsed_sec": 120.5,
        "total_points": 500,
        "failed_count": 2,
        "failed_tasks": [{"path": "a.hbk", "error": "e1"}, {"path": "b.hbk", "error": "e2"}],
        "max_workers": 4,
    }
    with patch("onec_help.cli.os.get_terminal_size", side_effect=OSError):
        out, code = _render_index_status_rich(
            s, collections, ingest, None, "", format_duration, "localhost", 6333
        )
    assert code == 0
    assert "✓ done" in out
    assert "2m" in out or "120" in out or "2 min" in out or "500 pts" in out
    assert "2 failed" in out or "failed" in out


def test_render_index_status_rich_ingest_completed_files_only_no_failed() -> None:
    """_render_index_status_rich: in progress with many completed_files, no failed_tasks."""
    from onec_help._utils import format_duration

    s = {"exists": True}
    collections = [{"name": "onec_help", "points_count": 50}]
    completed = [
        {"path": f"f{i}.hbk", "status": "ok", "version": "8.3", "language": "ru", "points": 5}
        for i in range(15)
    ]
    ingest = {
        "status": "in progress",
        "embedding_backend": "none",
        "done_tasks": 15,
        "total_tasks": 20,
        "current": [],
        "completed_files": completed,
        "failed_tasks": [],
        "folders": [],
    }
    with patch("onec_help.cli.os.get_terminal_size", side_effect=OSError):
        out, code = _render_index_status_rich(
            s, collections, ingest, None, "", format_duration, "localhost", 6333
        )
    assert code == 0
    assert "Files (per file)" in out or "pts [" in out
    assert "+3 more" in out or "+" in out


@patch("onec_help.ingest.read_last_ingest_run")
@patch("onec_help.ingest.read_ingest_status")
@patch("onec_help.indexer.get_index_status")
def test_render_index_status_uses_last_run_when_no_ingest(
    mock_get_status: MagicMock,
    mock_read_ingest: MagicMock,
    mock_last_run: MagicMock,
) -> None:
    """_render_index_status with no ingest uses read_last_ingest_run and builds ingest block."""
    mock_get_status.return_value = {"exists": True, "points_count": 10}
    mock_read_ingest.return_value = None
    mock_last_run.return_value = {
        "total_elapsed_sec": 60,
        "total_points": 100,
        "done_tasks": 5,
        "total_tasks": 5,
        "failed_count": 1,
        "embedding_backend": "openai_api",
    }
    with patch("onec_help.indexer.get_all_collections_status", return_value=[]):
        with patch("onec_help.ingest.read_last_ingest_failed", return_value=[]):
            with patch("onec_help.ingest.read_ingest_failed_log", return_value=[]):
                with patch("onec_help.ingest.read_ingest_cache_entries", return_value=[]):
                    with patch(
                        "onec_help.snippets_cache.read_last_snippets_run", return_value=None
                    ):
                        out, code = _render_index_status()
    assert code == 0
    assert "Details not stored" in out or "failed" in out.lower()


def test_cmd_index_status_watch_interrupt() -> None:
    """cmd_index_status with watch=True exits on KeyboardInterrupt."""
    with patch("onec_help.cli._render_index_status", return_value=("ok\n", 0)):
        with patch("time.sleep", side_effect=KeyboardInterrupt):
            args = make_args(watch=True, interval=1)
            assert cmd_index_status(args) == 0
