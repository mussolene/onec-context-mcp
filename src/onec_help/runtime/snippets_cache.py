"""Snippets load cache: track source files, skip unchanged (like ingest for .hbk). Backend: Redis."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import redis_cache


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
    try:
        cache_entries = redis_cache.snippets_cache_get_all()
    except Exception:
        cache_entries = {}

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
        redis_cache.snippets_cache_set(source_key, signature, items_count)
    except Exception:
        pass


def record_snippets_run(
    files_processed: int,
    files_skipped: int,
    items_loaded: int,
    started_at: float,
) -> None:
    """Record snippets load run for dashboard."""
    try:
        redis_cache.snippets_run_record(files_processed, files_skipped, items_loaded, started_at)
    except Exception:
        pass


def read_last_snippets_run() -> dict[str, Any] | None:
    """Last snippets load run for dashboard. Same shape as read_last_ingest_run."""
    try:
        return redis_cache.snippets_last_run()
    except Exception:
        return None


def get_cached_items_total() -> int:
    """Sum of items_count from cache (items loaded in previous runs, now in index)."""
    try:
        return redis_cache.snippets_items_total()
    except Exception:
        return 0


def read_snippets_cache_entries(limit: int = 50) -> list[dict[str, Any]]:
    """Cached sources for display in dashboard."""
    try:
        return redis_cache.snippets_cache_entries(limit=limit)
    except Exception:
        return []
