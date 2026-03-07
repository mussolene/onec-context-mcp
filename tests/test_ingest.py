"""Tests for ingest module: collect tasks, discover versions, parse env, run_ingest (dry_run / empty)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from onec_help.ingest import (
    _append_failed_to_cache,
    _collect_unpacked_tasks,
    _create_ingest_run,
    _default_workers,
    _file_sha256,
    _hbk_label_from_stem,
    _ingest_cache_key,
    _language_from_filename,
    _load_ingest_cache,
    _load_ingest_cache_indexed_set,
    _persist_ingest_status_sqlite,
    _read_unpacked_hash,
    _safe_stem,
    _sqlite_timeout,
    _update_ingest_cache_entry,
    _vacuum_cache_db,
    _write_hbk_info,
    _write_ingest_status,
    clear_ingest_cache,
    collect_hbk_tasks,
    discover_version_dirs,
    parse_languages_env,
    parse_source_dirs_env,
    read_ingest_cache_entries,
    read_ingest_failed_log,
    read_ingest_status,
    read_last_ingest_failed,
    read_last_ingest_run,
    run_ingest,
    run_ingest_from_unpacked,
    run_unpack_only,
    run_unpack_sync,
)


def test_language_from_filename() -> None:
    assert _language_from_filename("1cv8_ru.hbk") == "ru"
    assert _language_from_filename("shcntx_en.HBK") == "en"
    assert _language_from_filename("other.hbk") is None
    assert _language_from_filename("no_ext") is None


def test_collect_hbk_tasks_empty_sources() -> None:
    assert collect_hbk_tasks([], None) == []
    assert collect_hbk_tasks([], ["ru"]) == []


def test_collect_hbk_tasks_no_dir(tmp_path: Path) -> None:
    assert collect_hbk_tasks([(tmp_path / "missing", "v1")], None) == []


def test_collect_hbk_tasks_filters_language(tmp_path: Path) -> None:
    sub = tmp_path / "8.3"
    sub.mkdir()
    (sub / "1cv8_ru.hbk").write_bytes(b"x")
    (sub / "1cv8_en.hbk").write_bytes(b"y")
    tasks = collect_hbk_tasks([(tmp_path, "8.3")], ["ru"])
    paths = [t[0] for t in tasks]
    assert len(paths) == 1
    assert paths[0].name == "1cv8_ru.hbk"


def test_collect_hbk_tasks_all_languages(tmp_path: Path) -> None:
    sub = tmp_path / "v"
    sub.mkdir()
    (sub / "1cv8_ru.hbk").write_bytes(b"x")
    (sub / "1cv8_en.hbk").write_bytes(b"y")
    tasks = collect_hbk_tasks([(tmp_path, "v")], None)
    assert len(tasks) == 2
    names = {t[0].name for t in tasks}
    assert names == {"1cv8_ru.hbk", "1cv8_en.hbk"}


def test_collect_hbk_tasks_skips_no_lang(tmp_path: Path) -> None:
    sub = tmp_path / "v"
    sub.mkdir()
    (sub / "plain.hbk").write_bytes(b"x")
    tasks = collect_hbk_tasks([(tmp_path, "v")], None)
    assert len(tasks) == 0


def test_discover_version_dirs_empty(tmp_path: Path) -> None:
    assert discover_version_dirs(tmp_path) == []


def test_discover_version_dirs_ignores_files(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("x")
    assert discover_version_dirs(tmp_path) == []


def test_discover_version_dirs_ignores_hidden(tmp_path: Path) -> None:
    (tmp_path / ".hidden").mkdir()
    assert discover_version_dirs(tmp_path) == []


def test_discover_version_dirs_returns_subdirs(tmp_path: Path) -> None:
    (tmp_path / "8.3.27").mkdir()
    (tmp_path / "8.3.26").mkdir()
    result = discover_version_dirs(tmp_path)
    assert len(result) == 2
    names = {r[1] for r in result}
    assert names == {"8.3.27", "8.3.26"}


def test_file_sha256(tmp_path: Path) -> None:
    """_file_sha256 returns hex digest of file contents; same content => same hash."""
    f = tmp_path / "a.hbk"
    f.write_bytes(b"hello")
    h1 = _file_sha256(f)
    assert h1 is not None
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)
    f.write_bytes(b"hello")
    assert _file_sha256(f) == h1
    f.write_bytes(b"world")
    assert _file_sha256(f) != h1


def test_file_sha256_missing() -> None:
    """_file_sha256 returns None for non-existent file."""
    assert _file_sha256(Path("/nonexistent/file.hbk")) is None


def test_sqlite_timeout() -> None:
    """_sqlite_timeout reads env and clamps; invalid value falls back to 15."""
    with patch.dict("os.environ", {"SQLITE_BUSY_TIMEOUT": "30"}, clear=False):
        assert _sqlite_timeout() == 30.0
    with patch.dict("os.environ", {"SQLITE_BUSY_TIMEOUT": "invalid"}, clear=False):
        assert _sqlite_timeout() == 15.0


def test_default_workers() -> None:
    """_default_workers returns at least 1 (half of cpu_count or 4)."""
    w = _default_workers()
    assert w >= 1


def test_safe_stem() -> None:
    """_safe_stem replaces non-alphanumeric with underscore."""
    assert _safe_stem(Path("1cv8_ru.hbk")) == "1cv8_ru"
    assert _safe_stem(Path("path with spaces.txt")) == "path_with_spaces"


def test_clear_ingest_cache_remove_raises(tmp_path: Path) -> None:
    """clear_ingest_cache returns False when os.remove raises OSError."""
    cache_file = tmp_path / "cache.db"
    cache_file.write_bytes(b"x")
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_file)}, clear=False):
        with patch("os.remove", side_effect=OSError("Permission denied")):
            assert clear_ingest_cache() is False
    assert cache_file.exists()


def test_clear_ingest_cache(tmp_path: Path) -> None:
    """clear_ingest_cache removes cache file when present; returns True when absent."""
    cache_file = tmp_path / "cache.db"
    cache_file.write_bytes(b"x")
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_file)}, clear=False):
        assert clear_ingest_cache() is True
        assert not cache_file.exists()
        assert clear_ingest_cache() is True


def test_load_ingest_cache_error_returns_empty(tmp_path: Path) -> None:
    """When cache read raises, _load_ingest_cache returns empty dict."""
    cache_file = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_file)}, clear=False):
        with patch("onec_help.ingest.sqlite3.connect", side_effect=OSError("read-only")):
            c = _load_ingest_cache()
    assert c == {}


def test_update_ingest_cache_entry_write_error(tmp_path: Path) -> None:
    """When cache write raises, _update_ingest_cache_entry calls _log_cache_error and does not raise."""
    cache_file = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_file)}, clear=False):
        with patch("onec_help.ingest.sqlite3.connect", side_effect=OSError("read-only")):
            _update_ingest_cache_entry("v/ru/file.hbk", "hash123", 1)


def test_read_ingest_cache_entries_key_fewer_than_three_parts(tmp_path: Path) -> None:
    """read_ingest_cache_entries handles cache keys with fewer than 3 parts (version/lang/path)."""
    import sqlite3

    cache_file = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_file)}, clear=False):
        conn = sqlite3.connect(str(cache_file))
        conn.execute(
            "CREATE TABLE ingest_cache (key TEXT PRIMARY KEY, hash TEXT NOT NULL, indexed INTEGER NOT NULL, points INTEGER)"
        )
        conn.execute(
            "INSERT INTO ingest_cache (key, hash, indexed, points) VALUES (?, ?, 1, 5)",
            ("8.3/ru", "abc"),
        )
        conn.execute(
            "INSERT INTO ingest_cache (key, hash, indexed, points) VALUES (?, ?, 1, 10)",
            ("only", "def"),
        )
        conn.commit()
        conn.close()
        entries = read_ingest_cache_entries(limit=10)
    assert len(entries) == 2
    paths = [e.get("path") or e.get("language") or e.get("version") for e in entries]
    assert "8.3/ru" in paths or "only" in paths


def test_load_ingest_cache_connect_raises_returns_empty(tmp_path: Path) -> None:
    """_load_ingest_cache returns {} and logs when sqlite3.connect raises."""
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(tmp_path / "cache.db")}, clear=False):
        with patch("onec_help.ingest.sqlite3.connect", side_effect=OSError("read only")):
            entries = _load_ingest_cache()
    assert entries == {}


def test_load_save_ingest_cache(tmp_path: Path) -> None:
    """_load_ingest_cache returns entries from SQLite; _update_ingest_cache_entry persists one row."""
    cache_file = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_file)}, clear=False):
        c = _load_ingest_cache()
        assert c == {}
        _update_ingest_cache_entry("v/ru/1cv8.hbk", "abc", 10)
        c2 = _load_ingest_cache()
        assert c2["v/ru/1cv8.hbk"] == {"hash": "abc", "indexed": True, "points": 10}


def test_load_ingest_cache_indexed_set(tmp_path: Path) -> None:
    """_load_ingest_cache_indexed_set returns (version, lang, hash) for indexed entries; parses key with or without |path_id."""
    cache_db = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        _load_ingest_cache()  # create table
        _update_ingest_cache_entry("8.3/ru/1cv8_ru.hbk|abc123", "h1", 10)
        _update_ingest_cache_entry("8.5/en/1cv8_en", "h2", 5)
        idx = _load_ingest_cache_indexed_set()
    assert idx == {("8.3", "ru", "h1"), ("8.5", "en", "h2")}


def test_read_unpacked_hash(tmp_path: Path) -> None:
    """_read_unpacked_hash returns hash from .hbk_info.json or empty string."""
    (tmp_path / ".hbk_info.json").write_text(
        '{"hash": "abc123", "language": "ru"}', encoding="utf-8"
    )
    assert _read_unpacked_hash(tmp_path) == "abc123"
    (tmp_path / "no_hash").mkdir(parents=True, exist_ok=True)
    (tmp_path / "no_hash" / ".hbk_info.json").write_text("{}", encoding="utf-8")
    assert _read_unpacked_hash(tmp_path / "no_hash") == ""
    assert _read_unpacked_hash(tmp_path / "missing") == ""


def test_run_ingest_skips_cached(tmp_path: Path) -> None:
    """When cache has same-hash entry with indexed=true, task is skipped (no unpack/index)."""
    hbk_path = tmp_path / "v" / "1cv8_ru.hbk"
    hbk_path.parent.mkdir(parents=True, exist_ok=True)
    hbk_path.write_bytes(b"x")
    cache_file = tmp_path / "cache.db"
    key = _ingest_cache_key("v", "ru", hbk_path)
    h = _file_sha256(hbk_path)
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_file)}, clear=False):
        _update_ingest_cache_entry(key, h, 5)
        with patch("onec_help.indexer.build_index") as mock_idx:
            with patch("onec_help.html2md.build_docs") as mock_docs:
                with patch("onec_help.unpack.unpack_hbk") as mock_unpack:
                    n = run_ingest(
                        source_dirs_with_versions=[(tmp_path, "v")],
                        languages=["ru"],
                        temp_base=tmp_path / "temp",
                        max_workers=1,
                        verbose=False,
                    )
    assert n == 0
    mock_unpack.assert_not_called()
    mock_docs.assert_not_called()
    mock_idx.assert_not_called()


def test_write_ingest_status_completed_clears_current(tmp_path: Path) -> None:
    """When status is completed, ingest_current is cleared and run is in ingest_runs."""
    cache_db = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        _write_ingest_status(
            started_at=0.0,
            embedding_backend="local",
            total_tasks=2,
            done_tasks=2,
            total_points=100,
            folders=[],
            status="completed",
            finished_at=1.0,
        )
        last = read_last_ingest_run()
        assert last is not None
        assert last["status"] == "completed"
        assert last["total_points"] == 100
        assert read_ingest_status() is None  # ingest_current cleared


def test_read_ingest_status_missing(tmp_path: Path) -> None:
    """read_ingest_status returns None when SQLite ingest_current has no row."""
    cache_db = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        assert read_ingest_status() is None


def test_read_ingest_status_exists(tmp_path: Path) -> None:
    """read_ingest_status returns data from SQLite ingest_current when present."""
    cache_db = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        _persist_ingest_status_sqlite(
            started_at=1000.0,
            embedding_backend="local",
            total_tasks=1,
            done_tasks=1,
            total_points=10,
            folders=[],
            status="in_progress",
        )
        out = read_ingest_status()
    assert out is not None
    assert out["status"] == "in_progress"
    assert out["embedding_backend"] == "local"
    assert out["total_points"] == 10


def test_read_ingest_status_from_sqlite(tmp_path: Path) -> None:
    """read_ingest_status returns data from SQLite ingest_current when present."""
    cache_db = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        _persist_ingest_status_sqlite(
            started_at=1000.0,
            embedding_backend="local",
            total_tasks=5,
            done_tasks=2,
            total_points=100,
            folders=[],
            status="in_progress",
        )
        out = read_ingest_status()
    assert out is not None
    assert out["status"] == "in_progress"
    assert out["embedding_backend"] == "local"
    assert out["total_points"] == 100
    assert out["done_tasks"] == 2
    assert out["total_tasks"] == 5


def test_read_last_ingest_run(tmp_path: Path) -> None:
    """read_last_ingest_run returns last row from ingest_runs when present."""
    cache_db = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        _persist_ingest_status_sqlite(
            started_at=1000.0,
            embedding_backend="openai_api",
            total_tasks=10,
            done_tasks=10,
            total_points=5000,
            folders=[],
            status="completed",
            finished_at=1100.0,
            failed_tasks=[{"path": "a.hbk", "version": "8.3", "language": "ru", "error": "err"}],
        )
        out = read_last_ingest_run()
    assert out is not None
    assert out["status"] == "completed"
    assert out["total_points"] == 5000
    assert out["total_elapsed_sec"] == 100.0
    assert out["failed_count"] == 1


def test_read_last_ingest_failed(tmp_path: Path) -> None:
    """read_last_ingest_failed returns failed tasks from ingest_failed for latest run."""
    cache_db = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        _persist_ingest_status_sqlite(
            started_at=1000.0,
            embedding_backend="local",
            total_tasks=2,
            done_tasks=2,
            total_points=100,
            folders=[],
            status="completed",
            finished_at=1100.0,
            failed_tasks=[
                {"path": "a.hbk", "version": "8.3", "language": "ru", "error": "unpack failed"},
            ],
        )
        out = read_last_ingest_failed(limit=10)
    assert len(out) == 1
    assert out[0]["path"] == "a.hbk"
    assert out[0]["error"] == "unpack failed"
    assert out[0]["version"] == "8.3"


def test_failed_tasks_written_to_cache_before_run_completes(tmp_path: Path) -> None:
    """Errors are written to ingest_failed as they occur; read_last_ingest_failed returns them even for in_progress run."""
    cache_db = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        run_id = _create_ingest_run(
            started_at=1000.0, embedding_backend="openai_api", total_tasks=5
        )
        assert run_id is not None
        _append_failed_to_cache(
            run_id,
            {
                "path": "shcntx_ru.hbk",
                "path_full": "/sources/8.2/shcntx_ru.hbk",
                "version": "8.2.19.130",
                "language": "ru",
                "error": "TimeoutError: embedding API slot not available within 300s",
            },
        )
        out = read_last_ingest_failed(limit=10)
    assert len(out) == 1
    assert "shcntx_ru" in out[0]["path"]
    assert "embedding" in out[0]["error"].lower() or "timeout" in out[0]["error"].lower()


def test_read_last_ingest_failed_empty(tmp_path: Path) -> None:
    """read_last_ingest_failed returns [] when no runs or no failures."""
    cache_db = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        assert read_last_ingest_failed() == []


def test_read_last_ingest_run_empty(tmp_path: Path) -> None:
    """read_last_ingest_run returns None when ingest_runs is empty."""
    cache_db = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        assert read_last_ingest_run() is None


def test_vacuum_cache_db_no_error(tmp_path: Path) -> None:
    """_vacuum_cache_db runs without error on valid DB."""
    cache_db = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        _load_ingest_cache()  # creates DB
        _vacuum_cache_db()  # should not raise


def test_read_ingest_failed_log(tmp_path: Path) -> None:
    """read_ingest_failed_log parses INGEST_FAILED_LOG format."""
    log_file = tmp_path / "failed.log"
    log_file.write_text(
        "# Ingest failed .hbk (2)\n"
        "8.3\tru\t/path/to/shcntx_ru.hbk\t7z failed: invalid archive\n"
        "8.2\ten\t/path/to/1cv8_en.hbk\tBuildError: parse failed\n",
        encoding="utf-8",
    )
    with patch.dict("os.environ", {"INGEST_FAILED_LOG": str(log_file)}):
        out = read_ingest_failed_log(limit=10)
    assert len(out) == 2
    assert out[0]["version"] == "8.3"
    assert out[0]["language"] == "ru"
    assert "shcntx_ru" in out[0]["path"]
    assert "invalid archive" in out[0]["error"]
    assert out[1]["version"] == "8.2"
    assert out[1]["error"] == "BuildError: parse failed"


def test_read_ingest_failed_log_empty_env() -> None:
    """read_ingest_failed_log returns [] when INGEST_FAILED_LOG not set."""
    with patch.dict("os.environ", {"INGEST_FAILED_LOG": ""}, clear=False):
        out = read_ingest_failed_log()
    assert out == []


def test_parse_source_dirs_env_empty() -> None:
    assert parse_source_dirs_env("") == []
    assert parse_source_dirs_env(None) == []


def test_parse_source_dirs_env_path_only() -> None:
    out = parse_source_dirs_env("/opt/1cv8")
    assert out == [("/opt/1cv8", "1cv8")]


def test_parse_source_dirs_env_path_version() -> None:
    out = parse_source_dirs_env("/opt/1cv8:8.3.27")
    assert out == [("/opt/1cv8", "8.3.27")]


def test_parse_source_dirs_env_multiple() -> None:
    out = parse_source_dirs_env("/a:va,/b:vb")
    assert out == [("/a", "va"), ("/b", "vb")]


def test_parse_languages_env_empty() -> None:
    assert parse_languages_env("") is None
    assert parse_languages_env(None) is None


def test_parse_languages_env_all() -> None:
    assert parse_languages_env("all") is None


def test_parse_languages_env_single() -> None:
    assert parse_languages_env("ru") == ["ru"]


def test_parse_languages_env_multi() -> None:
    assert parse_languages_env("ru,en") == ["ru", "en"]


def test_run_ingest_dry_run(tmp_path: Path) -> None:
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "1cv8_ru.hbk").write_bytes(b"x")
    n = run_ingest(
        source_dirs_with_versions=[(tmp_path, "v")],
        languages=["ru"],
        temp_base=tmp_path / "temp",
        dry_run=True,
        verbose=True,
    )
    assert n == 0


def test_run_ingest_dry_run_many_tasks(tmp_path: Path) -> None:
    """Dry run with >25 tasks hits the '... and N more' log branch."""
    (tmp_path / "v").mkdir()
    for i in range(30):
        (tmp_path / "v" / f"1cv8_ru_{i}.hbk").write_bytes(b"x")
    n = run_ingest(
        source_dirs_with_versions=[(tmp_path, "v")],
        languages=["ru"],
        temp_base=tmp_path / "temp",
        dry_run=True,
        verbose=True,
    )
    assert n == 0


@patch("onec_help.ingest._unpack_and_build_docs")
@patch("qdrant_client.QdrantClient")
def test_run_ingest_max_tasks(mock_qdrant: MagicMock, mock_task: MagicMock, tmp_path: Path) -> None:
    """max_tasks limits how many .hbk are processed."""
    (tmp_path / "v").mkdir()
    # Names must match LANG_PATTERN (*_ru.hbk) so collect_hbk_tasks returns them
    for name in ("a_ru.hbk", "b_ru.hbk", "c_ru.hbk", "d_ru.hbk", "e_ru.hbk"):
        (tmp_path / "v" / name).write_bytes(b"x")
    mock_task.return_value = (None, None, "v", "ru", "skip")
    mock_qdrant.return_value.collection_exists.return_value = True
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(tmp_path / "cache.db")}, clear=False):
        n = run_ingest(
            source_dirs_with_versions=[(tmp_path, "v")],
            languages=["ru"],
            temp_base=tmp_path / "temp",
            max_tasks=2,
            max_workers=1,
            verbose=False,
        )
    assert mock_task.call_count == 2, "_unpack_and_build_docs should be called max_tasks=2 times"
    assert n == 0


def test_discover_version_dirs_not_dir(tmp_path: Path) -> None:
    """When base is a file or missing, returns []."""
    assert discover_version_dirs(tmp_path / "missing") == []
    (tmp_path / "file").write_text("x")
    assert discover_version_dirs(tmp_path / "file") == []


def test_parse_source_dirs_env_blank_parts() -> None:
    """Blank and comma-only parts are skipped."""
    assert parse_source_dirs_env("  ,  /a:v1  ,  ") == [("/a", "v1")]


def test_run_ingest_empty_sources() -> None:
    n = run_ingest(
        source_dirs_with_versions=[],
        temp_base="/tmp/help_ingest",
    )
    assert n == 0


def test_run_ingest_no_tasks(tmp_path: Path) -> None:
    (tmp_path / "v").mkdir()
    # no .hbk files
    n = run_ingest(
        source_dirs_with_versions=[(tmp_path, "v")],
        languages=["ru"],
        temp_base=tmp_path / "temp",
    )
    assert n == 0


def test_run_unpack_only_empty(tmp_path: Path) -> None:
    n = run_unpack_only(
        source_dirs_with_versions=[],
        output_dir=tmp_path,
        verbose=False,
    )
    assert n == 0


def test_run_unpack_only_no_tasks(tmp_path: Path) -> None:
    (tmp_path / "v").mkdir()
    n = run_unpack_only(
        source_dirs_with_versions=[(tmp_path, "v")],
        output_dir=tmp_path / "out",
        languages=["ru"],
        verbose=False,
    )
    assert n == 0


@patch("onec_help.unpack.unpack_hbk")
def test_run_unpack_only_one_archive(mock_unpack: MagicMock, tmp_path: Path) -> None:
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "1cv8_ru.hbk").write_bytes(b"x")
    out = tmp_path / "output"
    n = run_unpack_only(
        source_dirs_with_versions=[(tmp_path, "v")],
        output_dir=out,
        languages=["ru"],
        max_workers=1,
        verbose=False,
    )
    assert n == 1
    mock_unpack.assert_called_once()
    call_args = mock_unpack.call_args[0]
    assert call_args[0].name == "1cv8_ru.hbk"
    assert (out / "v" / "ru" / "1cv8_ru").exists()


@patch("onec_help.indexer.build_index")
@patch("onec_help.html2md.build_docs")
@patch("onec_help.unpack.unpack_hbk")
@patch("qdrant_client.QdrantClient")
def test_run_ingest_unpack_fails_one_task(
    mock_qdrant: MagicMock,
    mock_unpack: MagicMock,
    mock_build_docs: MagicMock,
    mock_build_index: MagicMock,
    tmp_path: Path,
) -> None:
    """When unpack raises, task is skipped and no index call for that task."""
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "1cv8_ru.hbk").write_bytes(b"x")
    mock_unpack.side_effect = RuntimeError("7z failed")
    mock_qdrant.return_value.collection_exists.return_value = True
    cache_db = tmp_path / "cache.db"
    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        n = run_ingest(
            source_dirs_with_versions=[(tmp_path, "v")],
            languages=["ru"],
            temp_base=tmp_path / "temp",
            max_workers=1,
            verbose=False,
        )
    assert n == 0
    mock_build_index.assert_not_called()


@patch("onec_help.indexer.build_index")
@patch("onec_help.html2md.build_docs")
@patch("onec_help.unpack.unpack_hbk")
@patch("qdrant_client.QdrantClient")
def test_run_ingest_integration_mock(
    mock_qdrant: MagicMock,
    mock_unpack: MagicMock,
    mock_build_docs: MagicMock,
    mock_build_index: MagicMock,
    tmp_path: Path,
) -> None:
    """Run ingest with one .hbk; unpack and build_docs succeed; index is called."""
    (tmp_path / "v").mkdir()
    hbk = tmp_path / "v" / "1cv8_ru.hbk"
    hbk.write_bytes(b"x")
    md_dir = tmp_path / "temp" / "v" / "ru" / "1cv8_ru" / "md"
    md_dir.mkdir(parents=True)
    (md_dir / "one.md").write_text("# One\n\nBody.", encoding="utf-8")
    mock_build_docs.side_effect = lambda src, out: (out / "one.md").write_text(
        "# One\n\nBody.", encoding="utf-8"
    )

    mock_build_index.return_value = 1
    mock_qdrant.return_value.collection_exists.return_value = False

    with patch.dict("os.environ", {"INGEST_CACHE_FILE": str(tmp_path / "cache.json")}, clear=False):
        n = run_ingest(
            source_dirs_with_versions=[(tmp_path, "v")],
            languages=["ru"],
            temp_base=tmp_path / "temp",
            qdrant_host="localhost",
            qdrant_port=6333,
            max_workers=1,
            verbose=False,
        )
    assert mock_unpack.called
    assert mock_build_index.return_value == 1
    assert n >= 1


def test_hbk_label_from_stem() -> None:
    """_hbk_label_from_stem returns built-in or env labels."""
    assert _hbk_label_from_stem("1cv8_ru") == "Справка 1С:Предприятие 8"
    assert _hbk_label_from_stem("shcntx_en") == "Синтаксис"
    assert _hbk_label_from_stem("unknown_ru") == "unknown_ru"


def test_hbk_label_from_stem_env(tmp_path: Path) -> None:
    """_hbk_label_from_stem uses HBK_LABELS env when set."""
    with patch.dict("os.environ", {"HBK_LABELS": "custom:My Custom Help"}):
        assert _hbk_label_from_stem("custom_ru") == "My Custom Help"


def test_write_hbk_info(tmp_path: Path) -> None:
    """_write_hbk_info creates .hbk_info.json with metadata."""
    _write_hbk_info(tmp_path, "1cv8_ru.hbk", "Справка 1С", "8.3", "ru", "abc123")
    info_path = tmp_path / ".hbk_info.json"
    assert info_path.exists()
    import json

    info = json.loads(info_path.read_text(encoding="utf-8"))
    assert info["source_file"] == "1cv8_ru.hbk"
    assert info["label"] == "Справка 1С"
    assert info["version"] == "8.3"
    assert info["language"] == "ru"
    assert info["hash"] == "abc123"


@patch("onec_help.unpack.unpack_hbk")
def test_run_unpack_sync_one_archive(mock_unpack: MagicMock, tmp_path: Path) -> None:
    """run_unpack_sync unpacks to version/stem and writes .hbk_info.json."""
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "1cv8_ru.hbk").write_bytes(b"x")
    out = tmp_path / "output"
    n = run_unpack_sync(
        source_dirs_with_versions=[(tmp_path, "v")],
        output_dir=out,
        languages=["ru"],
        max_workers=1,
        verbose=False,
    )
    assert n == 1
    mock_unpack.assert_called_once()
    out_sub = out / "v" / "1cv8_ru"
    assert out_sub.exists()
    info_path = out_sub / ".hbk_info.json"
    assert info_path.exists()
    import json

    info = json.loads(info_path.read_text(encoding="utf-8"))
    assert info["source_file"] == "1cv8_ru.hbk"
    assert info["version"] == "v"
    assert info["language"] == "ru"


@patch("onec_help.unpack.unpack_hbk")
def test_run_unpack_sync_skip_unchanged(mock_unpack: MagicMock, tmp_path: Path) -> None:
    """run_unpack_sync skips when .hbk_info.json hash matches."""
    (tmp_path / "v").mkdir()
    hbk = tmp_path / "v" / "1cv8_ru.hbk"
    hbk.write_bytes(b"same")
    out = tmp_path / "output"
    h = _file_sha256(hbk)
    out_sub = out / "v" / "1cv8_ru"
    out_sub.mkdir(parents=True)
    _write_hbk_info(out_sub, "1cv8_ru.hbk", "Label", "v", "ru", file_hash=h or "")
    n = run_unpack_sync(
        source_dirs_with_versions=[(tmp_path, "v")],
        output_dir=out,
        languages=["ru"],
        max_workers=1,
        verbose=False,
    )
    assert n == 0
    mock_unpack.assert_not_called()


@patch("onec_help.unpack.unpack_hbk")
def test_run_unpack_only_two_workers(mock_unpack: MagicMock, tmp_path: Path) -> None:
    """run_unpack_only with max_workers=2 uses thread pool."""
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "1cv8_ru.hbk").write_bytes(b"x")
    (tmp_path / "v" / "1cv8_en.hbk").write_bytes(b"y")
    out = tmp_path / "out"
    n = run_unpack_only(
        source_dirs_with_versions=[(tmp_path, "v")],
        output_dir=out,
        languages=None,
        max_workers=2,
        verbose=False,
    )
    assert n == 2
    assert mock_unpack.call_count == 2


def test_run_ingest_temp_base_creation_fails(tmp_path: Path) -> None:
    """When temp_base cannot be created, run_ingest raises RuntimeError."""
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "1cv8_ru.hbk").write_bytes(b"x")
    real_mkdir = Path.mkdir
    first_call = [True]

    def mkdir_raise_first(self, *args, **kwargs):
        if first_call[0]:
            first_call[0] = False
            raise OSError(13, "Permission denied")
        return real_mkdir(self, *args, **kwargs)

    with patch.object(Path, "mkdir", mkdir_raise_first):
        with pytest.raises(RuntimeError, match="Cannot create temp dir"):
            run_ingest(
                source_dirs_with_versions=[(tmp_path, "v")],
                languages=["ru"],
                temp_base=tmp_path / "temp",
                max_workers=1,
            )


@patch("onec_help.indexer.build_index")
@patch("onec_help.html2md.build_docs")
@patch("onec_help.unpack.unpack_hbk")
@patch("qdrant_client.QdrantClient")
def test_run_ingest_failed_log(
    mock_qdrant: MagicMock,
    mock_unpack: MagicMock,
    mock_build_docs: MagicMock,
    mock_build_index: MagicMock,
    tmp_path: Path,
) -> None:
    """When some tasks fail, INGEST_FAILED_LOG is written if set."""
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "1cv8_ru.hbk").write_bytes(b"x")
    mock_unpack.side_effect = RuntimeError("7z failed")
    mock_qdrant.return_value.collection_exists.return_value = True
    fail_log = tmp_path / "failed.txt"
    with patch.dict(
        "os.environ",
        {"INGEST_FAILED_LOG": str(fail_log), "INGEST_CACHE_FILE": str(tmp_path / "cache.json")},
        clear=False,
    ):
        n = run_ingest(
            source_dirs_with_versions=[(tmp_path, "v")],
            languages=["ru"],
            temp_base=tmp_path / "temp",
            max_workers=1,
            verbose=True,
        )
    assert n == 0
    assert fail_log.exists()
    assert "1cv8_ru" in fail_log.read_text()


@patch("onec_help.indexer.build_index")
@patch("onec_help.html2md.build_docs")
@patch("onec_help.unpack.unpack_hbk")
@patch("qdrant_client.QdrantClient")
def test_run_ingest_failed_log_write_raises(
    mock_qdrant: MagicMock,
    mock_unpack: MagicMock,
    mock_build_docs: MagicMock,
    mock_build_index: MagicMock,
    tmp_path: Path,
) -> None:
    """When writing INGEST_FAILED_LOG raises OSError, ingest still completes and logs the error."""
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "1cv8_ru.hbk").write_bytes(b"x")
    mock_unpack.side_effect = RuntimeError("7z failed")
    mock_qdrant.return_value.collection_exists.return_value = True
    fail_log = tmp_path / "failed.txt"
    real_open = open

    def open_raise_for_fail_log(path, mode="r", *args, **kwargs):
        if path == str(fail_log) and "w" in mode:
            raise OSError(13, "Permission denied")
        return real_open(path, mode, *args, **kwargs)

    with patch.dict(
        "os.environ",
        {"INGEST_FAILED_LOG": str(fail_log), "INGEST_CACHE_FILE": str(tmp_path / "cache2.json")},
        clear=False,
    ):
        with patch("builtins.open", open_raise_for_fail_log):
            n = run_ingest(
                source_dirs_with_versions=[(tmp_path, "v")],
                languages=["ru"],
                temp_base=tmp_path / "temp",
                max_workers=1,
                verbose=True,
            )
    assert n == 0


def test_collect_unpacked_tasks_empty(tmp_path: Path) -> None:
    """_collect_unpacked_tasks returns [] for empty or missing dir."""
    assert _collect_unpacked_tasks(tmp_path) == []
    assert _collect_unpacked_tasks(tmp_path / "missing") == []


def test_collect_unpacked_tasks_one_version_stem(tmp_path: Path) -> None:
    """_collect_unpacked_tasks finds version/stem with HTML."""
    v_dir = tmp_path / "8.3.27"
    v_dir.mkdir()
    stem_dir = v_dir / "1cv8_ru"
    stem_dir.mkdir()
    (stem_dir / "one.html").write_text("<html>")
    tasks = _collect_unpacked_tasks(tmp_path)
    assert len(tasks) == 1
    docs_dir, version, stem, language = tasks[0]
    assert docs_dir == stem_dir
    assert version == "8.3.27"
    assert stem == "1cv8_ru"
    assert language == "ru"


def test_collect_unpacked_tasks_with_hbk_info(tmp_path: Path) -> None:
    """_collect_unpacked_tasks uses .hbk_info.json for version/language."""
    import json

    v_dir = tmp_path / "8.3"
    v_dir.mkdir()
    stem_dir = v_dir / "custom_en"
    stem_dir.mkdir()
    (stem_dir / "a.html").write_text("<html>")
    (stem_dir / ".hbk_info.json").write_text(
        json.dumps({"version": "8.3.26", "language": "en", "source_file": "custom_en.hbk"}),
        encoding="utf-8",
    )
    tasks = _collect_unpacked_tasks(tmp_path)
    assert len(tasks) == 1
    _, version, stem, language = tasks[0]
    assert version == "8.3.26"
    assert stem == "custom_en"
    assert language == "en"


@patch("onec_help.indexer.build_index")
@patch("qdrant_client.QdrantClient")
def test_run_ingest_from_unpacked_one(
    mock_qdrant: MagicMock, mock_build_index: MagicMock, tmp_path: Path
) -> None:
    """run_ingest_from_unpacked indexes version/stem dirs with path_prefix."""
    mock_qdrant.return_value.collection_exists.return_value = True
    mock_build_index.return_value = 5

    v_dir = tmp_path / "8.3"
    v_dir.mkdir()
    stem_dir = v_dir / "1cv8_ru"
    stem_dir.mkdir()
    (stem_dir / "Query.html").write_text("<html><body>Query</body></html>")

    n = run_ingest_from_unpacked(
        unpacked_base=tmp_path,
        qdrant_host="localhost",
        qdrant_port=6333,
        verbose=False,
    )
    assert n == 5
    mock_build_index.assert_called_once()
    call_kw = mock_build_index.call_args[1]
    assert call_kw["path_prefix"] == "8.3/1cv8_ru"
    assert call_kw["extra_payload"]["version"] == "8.3"
    assert call_kw["extra_payload"]["language"] == "ru"
    assert call_kw["extra_payload"]["hbk_slug"] == "1cv8_ru"
