"""Snippets load cache: track source files, skip unchanged (like ingest for .hbk)."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from .ingest import _ingest_cache_path, _sqlite_timeout

_SNIPPETS_CACHE_TABLE = "snippets_cache"
_SNIPPETS_RUNS_TABLE = "snippets_runs"


def _conn() -> sqlite3.Connection:
    path = _ingest_cache_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return sqlite3.connect(path, timeout=_sqlite_timeout())


def _init_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {_SNIPPETS_CACHE_TABLE} (
            source_key TEXT PRIMARY KEY,
            signature TEXT NOT NULL,
            loaded_at REAL NOT NULL,
            items_count INTEGER NOT NULL
        )"""
    )
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {_SNIPPETS_RUNS_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at REAL NOT NULL,
            finished_at REAL NOT NULL,
            files_processed INTEGER NOT NULL,
            files_skipped INTEGER NOT NULL,
            items_loaded INTEGER NOT NULL,
            status TEXT NOT NULL
        )"""
    )
    conn.commit()


def _file_signature(path: Path) -> str | None:
    """Signature for a file: mtime:size. None if unreadable."""
    try:
        st = path.stat()
        return f"{st.st_mtime}:{st.st_size}"
    except OSError:
        return None


def _folder_signature(folder: Path, extensions: frozenset[str] | None = None) -> str | None:
    """Signature for folder: hash of sorted (relpath, size). Uses size (not mtime) so it is stable across container restarts and volume remounts."""
    exts = extensions or {".bsl", ".1c", ".md"}
    try:
        parts: list[tuple[str, int]] = []
        for f in folder.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() not in exts:
                continue
            try:
                st = f.stat()
                rel = str(f.relative_to(folder))
                parts.append((rel, st.st_size))
            except (ValueError, OSError):
                continue
        if not parts:
            try:
                return f"empty:{folder.stat().st_size}"
            except OSError:
                return None
        parts.sort(key=lambda x: x[0])
        raw = json.dumps(parts, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()
    except OSError:
        return None


def get_snippets_sources_to_load(
    sources: list[tuple[Path, str]],
) -> tuple[list[tuple[Path, str]], dict[str, dict[str, Any]]]:
    """
    sources: [(path, type), ...] where type is 'json' or 'folder'.
    Returns (to_load, cache_entries) — to_load = sources that changed or are new.
    """
    to_load: list[tuple[Path, str]] = []
    cache_entries: dict[str, dict[str, Any]] = {}
    try:
        conn = _conn()
        _init_tables(conn)
        for row in conn.execute(
            f"SELECT source_key, signature, loaded_at, items_count FROM {_SNIPPETS_CACHE_TABLE}"
        ):
            cache_entries[row[0]] = {
                "signature": row[1],
                "loaded_at": row[2],
                "items_count": row[3],
            }
        conn.close()
    except (OSError, sqlite3.Error):
        pass

    folder_extensions: frozenset[str] = frozenset({".bsl", ".1c", ".md"})
    for path, stype in sources:
        path = Path(path).resolve()
        key = str(path)
        if stype == "json":
            sig = _file_signature(path)
        else:
            sig = _folder_signature(path, folder_extensions)
        if sig is None:
            to_load.append((path, stype))
            continue
        ent = cache_entries.get(key)
        if ent is None or ent.get("signature") != sig:
            to_load.append((path, stype))

    return (to_load, cache_entries)


def update_snippets_cache(
    source_key: str,
    signature: str,
    items_count: int,
) -> None:
    """Record successful load of a source."""
    try:
        conn = _conn()
        _init_tables(conn)
        now = time.time()
        conn.execute(
            f"""INSERT OR REPLACE INTO {_SNIPPETS_CACHE_TABLE}
                (source_key, signature, loaded_at, items_count) VALUES (?, ?, ?, ?)""",
            (source_key, signature, now, items_count),
        )
        conn.commit()
        conn.close()
    except (OSError, sqlite3.Error):
        pass


def record_snippets_run(
    files_processed: int,
    files_skipped: int,
    items_loaded: int,
    started_at: float,
) -> None:
    """Record snippets load run for index-status."""
    try:
        conn = _conn()
        _init_tables(conn)
        now = time.time()
        conn.execute(
            f"""INSERT INTO {_SNIPPETS_RUNS_TABLE}
                (started_at, finished_at, files_processed, files_skipped, items_loaded, status)
                VALUES (?, ?, ?, ?, ?, ?)""",
            (started_at, now, files_processed, files_skipped, items_loaded, "completed"),
        )
        conn.commit()
        conn.close()
    except (OSError, sqlite3.Error):
        pass


def read_last_snippets_run() -> dict[str, Any] | None:
    """Last snippets load run for index-status. Same shape as read_last_ingest_run."""
    try:
        conn = _conn()
        row = conn.execute(
            f"""SELECT started_at, finished_at, files_processed, files_skipped, items_loaded
                FROM {_SNIPPETS_RUNS_TABLE} ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "started_at": row[0],
            "finished_at": row[1],
            "files_processed": row[2],
            "files_skipped": row[3],
            "items_loaded": row[4],
            "total_elapsed_sec": row[1] - row[0] if row[1] and row[0] else None,
        }
    except (OSError, sqlite3.Error):
        return None


def get_cached_items_total() -> int:
    """Sum of items_count from cache (items loaded in previous runs, now in index)."""
    try:
        conn = _conn()
        row = conn.execute(
            f"SELECT COALESCE(SUM(items_count), 0) FROM {_SNIPPETS_CACHE_TABLE}"
        ).fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except (OSError, sqlite3.Error):
        return 0


def read_snippets_cache_entries(limit: int = 50) -> list[dict[str, Any]]:
    """Cached sources for display in index-status."""
    entries: list[dict[str, Any]] = []
    try:
        conn = _conn()
        for row in conn.execute(
            f"""SELECT source_key, loaded_at, items_count
                FROM {_SNIPPETS_CACHE_TABLE} ORDER BY loaded_at DESC LIMIT ?""",
            (limit,),
        ):
            path = row[0]
            name = Path(path).name if path else "?"
            entries.append(
                {
                    "path": name,
                    "source": path,
                    "loaded_at": row[1],
                    "items_count": row[2],
                    "status": "cached",
                }
            )
        conn.close()
    except (OSError, sqlite3.Error):
        pass
    return entries
