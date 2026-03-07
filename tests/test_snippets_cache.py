"""Tests for snippets_cache module."""

import os
from pathlib import Path
from unittest.mock import patch

from onec_help.snippets_cache import (
    _file_signature,
    _folder_signature,
    get_cached_items_total,
    get_snippets_sources_to_load,
    read_last_snippets_run,
    read_snippets_cache_entries,
    record_snippets_run,
    update_snippets_cache,
)


def test_file_signature(tmp_path: Path) -> None:
    """_file_signature returns mtime:size for readable file."""
    f = tmp_path / "a.json"
    f.write_text("[]")
    sig = _file_signature(f)
    assert sig is not None
    assert ":" in sig


def test_file_signature_nonexistent_returns_none() -> None:
    """_file_signature returns None when path does not exist (OSError on stat)."""
    assert _file_signature(Path("/nonexistent/file.json")) is None


def test_folder_signature(tmp_path: Path) -> None:
    """_folder_signature returns hash for folder with matching files."""
    (tmp_path / "a.bsl").write_text("x")
    sig = _folder_signature(tmp_path)
    assert sig is not None
    assert len(sig) == 64  # sha256 hex


def test_folder_signature_empty_returns_empty_marker(tmp_path: Path) -> None:
    """_folder_signature for empty folder returns empty:<size> (stable across restarts)."""
    sig = _folder_signature(tmp_path)
    assert sig is not None
    assert sig.startswith("empty:")


def test_folder_signature_skips_non_matching_ext(tmp_path: Path) -> None:
    """_folder_signature ignores files without .bsl, .1c, .md."""
    (tmp_path / "a.txt").write_text("x")
    sig = _folder_signature(tmp_path)
    assert sig is not None
    assert sig.startswith("empty:")


def test_get_snippets_sources_to_load(tmp_path: Path) -> None:
    """get_snippets_sources_to_load returns to_load and cache_entries."""
    cache_db = tmp_path / "cache.db"
    json_file = tmp_path / "snippets.json"
    json_file.write_text("[]")
    with patch.dict(os.environ, {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        to_load, entries = get_snippets_sources_to_load([(json_file, "json")])
    assert len(to_load) >= 1  # New source, needs load
    assert isinstance(entries, dict)


def test_update_snippets_cache(tmp_path: Path) -> None:
    """update_snippets_cache records load without error."""
    cache_db = tmp_path / "cache.db"
    with patch.dict(os.environ, {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        update_snippets_cache(str(tmp_path / "x.json"), "sig:123", 5)
        total = get_cached_items_total()
    assert total == 5


def test_get_cached_items_total(tmp_path: Path) -> None:
    """get_cached_items_total returns sum of items_count across all cache entries."""
    cache_db = tmp_path / "cache.db"
    with patch.dict(os.environ, {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        update_snippets_cache("key1", "s1", 3)
        update_snippets_cache("key2", "s2", 7)
        total = get_cached_items_total()
    assert total == 10  # 3 + 7 from two sources


def test_read_snippets_cache_entries(tmp_path: Path) -> None:
    """read_snippets_cache_entries returns list of cache entries."""
    cache_db = tmp_path / "cache.db"
    with patch.dict(os.environ, {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        update_snippets_cache(str(tmp_path / "a.json"), "sig", 2)
        entries = read_snippets_cache_entries(limit=10)
    assert len(entries) >= 1
    assert entries[0]["status"] == "cached"
    assert "items_count" in entries[0]


def test_record_and_read_last_snippets_run(tmp_path: Path) -> None:
    """record_snippets_run and read_last_snippets_run roundtrip."""
    import time

    cache_db = tmp_path / "cache.db"
    with patch.dict(os.environ, {"INGEST_CACHE_FILE": str(cache_db)}, clear=False):
        started = time.time()
        record_snippets_run(files_processed=2, files_skipped=0, items_loaded=5, started_at=started)
        run = read_last_snippets_run()
    assert run is not None
    assert run["files_processed"] == 2
    assert run["items_loaded"] == 5
