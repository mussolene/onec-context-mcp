"""Ingest .hbk from multiple read-only source directories.

Unpacks to a temp dir in the container, builds docs, indexes with version/language, then cleans up.
Supports language filter (e.g. only *_ru.hbk) and concurrent processing.
Progress is printed to stderr so long runs are not killed by "no output" timeouts.
Writes ingest status to SQLite cache DB (ingest_current, ingest_runs) for index-status command.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from ._utils import mask_path_for_log, safe_error_message

# How often to write status to SQLite while ingest runs (seconds); env INDEX_STATUS_INTERVAL_SEC
STATUS_UPDATE_INTERVAL_SEC = 2.0
# Path for ingest cache (SQLite). data/ingest_cache — общий каталог для ingest и index-status.
DEFAULT_INGEST_CACHE_FILE = str(Path("data/ingest_cache/ingest_cache.db").resolve())
_CACHE_TABLE = "ingest_cache"
_STATUS_TABLE_RUNS = "ingest_runs"
_STATUS_TABLE_CURRENT = "ingest_current"
_STATUS_TABLE_FAILED = "ingest_failed"
_INGEST_RUNS_LIMIT = 20


def _sqlite_timeout() -> float:
    """Seconds to wait for SQLite lock (env SQLITE_BUSY_TIMEOUT). Helps on Docker Mac bind mounts."""
    try:
        return max(5.0, float(os.environ.get("SQLITE_BUSY_TIMEOUT", "15")))
    except (TypeError, ValueError):
        return 15.0


def _default_workers() -> int:
    """Default workers = half of available CPUs, at least 1 (do not exceed half of resources)."""
    return max(1, (os.cpu_count() or 4) // 2)


def _file_sha256(path: Path) -> str | None:
    """SHA256 of file contents (for .hbk). Returns None on read error."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _ingest_cache_path() -> str:
    path = os.environ.get("INGEST_CACHE_FILE", DEFAULT_INGEST_CACHE_FILE)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


def clear_ingest_cache() -> bool:
    """Delete ingest cache DB file (cache + status). Returns True if removed or absent."""
    path = _ingest_cache_path()
    try:
        if os.path.exists(path):
            os.remove(path)
        return True
    except OSError:
        return False


def _log_cache_error(op: str, path: str, err: Exception) -> None:
    """Log cache I/O error once per run to avoid spam."""
    if not hasattr(_log_cache_error, "_warned"):
        _log_cache_error._warned = set()  # type: ignore[attr-defined]
    key = (op, path)
    if key not in _log_cache_error._warned:  # type: ignore[attr-defined]
        _log_cache_error._warned.add(key)  # type: ignore[attr-defined]
        env_hint = ""
        if "INGEST_CACHE_FILE" not in os.environ:
            env_hint = " Set INGEST_CACHE_FILE to a persistent path (e.g. in Docker: /app/var/ingest_cache/ingest_cache.db)."
        _log(
            f"[ingest] WARN: ingest cache {op} failed for {mask_path_for_log(path)}: {safe_error_message(err)}. "
            f"Re-indexing will not be skipped.{env_hint} Check path exists, permissions, and disk space."
        )


def read_ingest_cache_entries(limit: int = 100) -> list[dict[str, Any]]:
    """Return list of cached indexed files from ingest_cache for display.
    Each item: {path, version, language, points, status: 'cached'}."""
    entries: list[dict[str, Any]] = []
    path = _ingest_cache_path()
    try:
        conn = sqlite3.connect(path, timeout=_sqlite_timeout())
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {_CACHE_TABLE} "
            "(key TEXT PRIMARY KEY, hash TEXT NOT NULL, indexed INTEGER NOT NULL, points INTEGER)"
        )
        for row in conn.execute(
            f"SELECT key, hash, indexed, points FROM {_CACHE_TABLE} WHERE indexed = 1 ORDER BY key LIMIT ?",
            (limit,),
        ):
            key = row[0]
            parts = key.split("/", 2)
            version = parts[0] if len(parts) > 0 else ""
            language = parts[1] if len(parts) > 1 else ""
            path_name = parts[2] if len(parts) > 2 else key
            entries.append(
                {
                    "path": path_name,
                    "version": version,
                    "language": language,
                    "points": row[3] or 0,
                    "status": "cached",
                }
            )
        conn.close()
    except (OSError, sqlite3.Error):
        pass
    return entries


def _load_ingest_cache() -> dict[str, dict[str, Any]]:
    """Load cache from SQLite. Returns dict key -> {hash, indexed, points}."""
    path = _ingest_cache_path()
    entries: dict[str, dict[str, Any]] = {}
    try:
        conn = sqlite3.connect(path, timeout=_sqlite_timeout())
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {_CACHE_TABLE} "
            "(key TEXT PRIMARY KEY, hash TEXT NOT NULL, indexed INTEGER NOT NULL, points INTEGER)"
        )
        for row in conn.execute(f"SELECT key, hash, indexed, points FROM {_CACHE_TABLE}"):
            entries[row[0]] = {
                "hash": row[1],
                "indexed": bool(row[2]),
                "points": row[3],
            }
        conn.close()
    except (OSError, sqlite3.Error) as e:
        _log_cache_error("read", path, e)
    return entries


def _update_ingest_cache_entry(key: str, file_hash: str, points: int) -> None:
    """Persist one cache entry (SQLite INSERT OR REPLACE). No full rewrite."""
    path = _ingest_cache_path()
    try:
        conn = sqlite3.connect(path, timeout=_sqlite_timeout())
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {_CACHE_TABLE} "
            "(key TEXT PRIMARY KEY, hash TEXT NOT NULL, indexed INTEGER NOT NULL, points INTEGER)"
        )
        conn.execute(
            f"INSERT OR REPLACE INTO {_CACHE_TABLE} (key, hash, indexed, points) VALUES (?, ?, 1, ?)",
            (key, file_hash, points),
        )
        conn.commit()
        conn.close()
    except (OSError, sqlite3.Error) as e:
        _log_cache_error("write", path, e)


def _log_status_error(op: str, err: Exception) -> None:
    """Log ingest status SQLite error once per run to avoid spam."""
    if not hasattr(_log_status_error, "_warned"):
        _log_status_error._warned = set()  # type: ignore[attr-defined]
    key = op
    if key not in _log_status_error._warned:  # type: ignore[attr-defined]
        _log_status_error._warned.add(key)  # type: ignore[attr-defined]
        _log(
            f"[ingest] WARN: ingest status {op} failed: {safe_error_message(err)}. "
            "index-status may show incomplete data."
        )


def _init_ingest_status_tables(conn: sqlite3.Connection) -> None:
    """Create ingest status tables if not exist. Enables WAL for read concurrency."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {_STATUS_TABLE_CURRENT} (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            started_at REAL NOT NULL,
            total_tasks INTEGER NOT NULL,
            done_tasks INTEGER NOT NULL,
            total_points INTEGER NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        )"""
    )
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {_STATUS_TABLE_RUNS} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at REAL NOT NULL,
            finished_at REAL NOT NULL,
            status TEXT NOT NULL,
            total_tasks INTEGER NOT NULL,
            done_tasks INTEGER NOT NULL,
            total_points INTEGER NOT NULL,
            failed_count INTEGER NOT NULL,
            embedding_backend TEXT,
            total_elapsed_sec REAL
        )"""
    )
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {_STATUS_TABLE_FAILED} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            version TEXT NOT NULL,
            language TEXT NOT NULL,
            path TEXT NOT NULL,
            error TEXT NOT NULL,
            error_category TEXT,
            FOREIGN KEY (run_id) REFERENCES {_STATUS_TABLE_RUNS}(id)
        )"""
    )
    conn.commit()


def _persist_ingest_status_sqlite(
    *,
    started_at: float,
    embedding_backend: str,
    total_tasks: int,
    done_tasks: int,
    total_points: int,
    folders: list[dict[str, Any]],
    status: str,
    finished_at: float | None = None,
    current: list[dict[str, Any]] | None = None,
    failed_tasks: list[dict[str, Any]] | None = None,
    current_task_points: int | None = None,
    current_task_estimated_total: int | None = None,
    completed_files: list[dict[str, Any]] | None = None,
    max_workers: int | None = None,
    embedding_workers: int | None = None,
) -> None:
    """Persist ingest status to SQLite (ingest_current). On completion, append to ingest_runs."""
    path = _ingest_cache_path()
    elapsed = time.time() - started_at
    payload: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at)),
        "embedding_backend": embedding_backend or "none",
        "total_tasks": total_tasks,
        "done_tasks": done_tasks,
        "total_points": total_points,
        "folders": folders,
        "status": status,
        "elapsed_sec": round(elapsed, 1),
    }
    if max_workers is not None:
        payload["max_workers"] = max_workers
    if embedding_workers is not None:
        payload["embedding_workers"] = embedding_workers
    if status == "completed":
        payload["current"] = []
    elif current is not None:
        payload["current"] = current
    if current_task_points is not None and current_task_points > 0:
        payload["current_task_points"] = current_task_points
    if current_task_estimated_total is not None and current_task_estimated_total > 0:
        payload["current_task_estimated_total"] = current_task_estimated_total
    if failed_tasks:
        payload["failed_tasks"] = failed_tasks[-50:]
    if completed_files is not None:
        payload["completed_files"] = completed_files
    if elapsed > 0 and total_points > 0:
        payload["embedding_speed_pts_per_sec"] = round(total_points / elapsed, 2)
    failed_count = len(failed_tasks) if failed_tasks else 0
    done_successful = max(0, done_tasks - failed_count)
    if done_successful > 0 and total_tasks > 0 and total_points > 0:
        avg_pts = total_points / done_successful
        payload["estimated_total_points"] = int(avg_pts * total_tasks)
    if done_successful > 0 and total_tasks > done_tasks and total_points > 0 and elapsed > 0:
        avg_pts = total_points / done_successful
        remaining_tasks = total_tasks - done_tasks
        eta_points = avg_pts * remaining_tasks
        rate = total_points / elapsed
        eta_sec = eta_points / rate if rate > 0 else None
        if eta_sec is not None and eta_sec >= 0:
            payload["eta_sec"] = round(eta_sec, 1)
            payload["eta_finish_at"] = round(time.time() + eta_sec, 0)
    if finished_at is not None:
        payload["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(finished_at))
        payload["total_elapsed_sec"] = round(finished_at - started_at, 1)

    try:
        conn = sqlite3.connect(path, timeout=_sqlite_timeout())
        _init_ingest_status_tables(conn)
        updated_at = time.time()
        payload_json = json.dumps(payload, ensure_ascii=False)

        if status == "completed":
            # Insert into ingest_runs and clear ingest_current
            run_id = conn.execute(
                f"""INSERT INTO {_STATUS_TABLE_RUNS}
                    (started_at, finished_at, status, total_tasks, done_tasks, total_points,
                     failed_count, embedding_backend, total_elapsed_sec)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    started_at,
                    finished_at,
                    status,
                    total_tasks,
                    done_tasks,
                    total_points,
                    failed_count,
                    embedding_backend or "none",
                    finished_at - started_at if finished_at else None,
                ),
            ).lastrowid
            if run_id and failed_tasks:
                for ft in failed_tasks:
                    err = ft.get("error", "") or ""
                    cat = "unpack" if "unpack" in err.lower() or "7z" in err else "other"
                    if "embed" in err.lower() or "429" in err or "timeout" in err.lower():
                        cat = "embed"
                        hint = " Рекомендация: проверьте EMBEDDING_API_URL, EMBEDDING_TIMEOUT; перезапустите ingest."
                        err_stored = (
                            (err[:450] + hint) if len(err) + len(hint) > 500 else err + hint
                        )
                    elif "qdrant" in err.lower() or "upsert" in err.lower():
                        cat = "index"
                        err_stored = err[:500]
                    elif "build" in err.lower() or "html" in err.lower():
                        cat = "build"
                        err_stored = err[:500]
                    else:
                        err_stored = err[:500]
                    path_for_db = ft.get("path_full") or ft.get("path", "")
                    conn.execute(
                        f"""INSERT INTO {_STATUS_TABLE_FAILED}
                            (run_id, version, language, path, error, error_category)
                            VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            run_id,
                            ft.get("version", ""),
                            ft.get("language", ""),
                            path_for_db,
                            err_stored[:500],
                            cat,
                        ),
                    )
            # Trim old runs
            cursor = conn.execute(
                f"SELECT id FROM {_STATUS_TABLE_RUNS} ORDER BY id DESC LIMIT 1 OFFSET {_INGEST_RUNS_LIMIT}"
            )
            row = cursor.fetchone()
            if row:
                conn.execute(f"DELETE FROM {_STATUS_TABLE_RUNS} WHERE id <= ?", (row[0],))
                conn.execute(f"DELETE FROM {_STATUS_TABLE_FAILED} WHERE run_id <= ?", (row[0],))
            conn.execute(f"DELETE FROM {_STATUS_TABLE_CURRENT} WHERE id = 1")
        else:
            conn.execute(
                f"""INSERT OR REPLACE INTO {_STATUS_TABLE_CURRENT}
                    (id, started_at, total_tasks, done_tasks, total_points, status, payload_json, updated_at)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    started_at,
                    total_tasks,
                    done_tasks,
                    total_points,
                    status,
                    payload_json,
                    updated_at,
                ),
            )
        conn.commit()
        conn.close()
    except (OSError, sqlite3.Error) as e:
        _log_status_error("write", e)


def _vacuum_cache_db() -> None:
    """VACUUM the ingest cache SQLite DB to reclaim space. Non-blocking; logs on error."""
    path = _ingest_cache_path()
    try:
        conn = sqlite3.connect(path, timeout=_sqlite_timeout())
        conn.execute("VACUUM")
        conn.close()
    except (OSError, sqlite3.Error) as e:
        _log(f"[ingest] WARN: VACUUM failed for {mask_path_for_log(path)}: {safe_error_message(e)}")


def _status_writer_loop(
    stop_event: threading.Event,
    state_lock: threading.Lock,
    state: dict[str, Any],
    interval_sec: float,
) -> None:
    """Background thread: write status to SQLite every interval_sec until stop_event is set."""
    while not stop_event.wait(timeout=interval_sec):
        with state_lock:
            if state.get("status") == "completed":
                break
            done_tasks = state["done_tasks"]
            total_points = state["total_points"]
            folders = copy.deepcopy(state["folders"])
            current = list(state["current_work"].values())
            failed_tasks = list(state.get("failed", []))
            completed_files = list(state.get("completed_files", []))
            current_task_points = state.get("current_task_points", 0) or 0
            current_task_estimated = state.get("current_task_estimated_total")
        _write_ingest_status(
            started_at=state["started_at"],
            embedding_backend=state["embedding_backend"],
            total_tasks=state["total_tasks"],
            done_tasks=done_tasks,
            total_points=total_points,
            folders=folders,
            status="in_progress",
            current=current,
            failed_tasks=failed_tasks,
            current_task_points=current_task_points if current_task_points > 0 else None,
            current_task_estimated_total=current_task_estimated,
            completed_files=completed_files,
            max_workers=state.get("max_workers"),
            embedding_workers=state.get("embedding_workers"),
        )


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _write_ingest_status(
    *,
    started_at: float,
    embedding_backend: str,
    total_tasks: int,
    done_tasks: int,
    total_points: int,
    folders: list[dict[str, Any]],
    status: str = "in_progress",
    finished_at: float | None = None,
    current: list[dict[str, Any]] | None = None,
    failed_tasks: list[dict[str, Any]] | None = None,
    current_task_points: int | None = None,
    current_task_estimated_total: int | None = None,
    completed_files: list[dict[str, Any]] | None = None,
    max_workers: int | None = None,
    embedding_workers: int | None = None,
) -> None:
    """Write ingest status to SQLite cache DB for index-status command."""
    _persist_ingest_status_sqlite(
        started_at=started_at,
        embedding_backend=embedding_backend,
        total_tasks=total_tasks,
        done_tasks=done_tasks,
        total_points=total_points,
        folders=folders,
        status=status,
        finished_at=finished_at,
        current=current,
        failed_tasks=failed_tasks,
        current_task_points=current_task_points,
        current_task_estimated_total=current_task_estimated_total,
        completed_files=completed_files,
        max_workers=max_workers,
        embedding_workers=embedding_workers,
    )


def read_ingest_status() -> dict[str, Any] | None:
    """Read ingest status from SQLite cache DB (ingest_current). Returns None if no active run."""
    db_path = _ingest_cache_path()
    try:
        conn = sqlite3.connect(db_path, timeout=_sqlite_timeout())
        _init_ingest_status_tables(conn)
        row = conn.execute(
            f"SELECT payload_json, started_at FROM {_STATUS_TABLE_CURRENT} WHERE id = 1"
        ).fetchone()
        conn.close()
        if row:
            data = json.loads(row[0])
            if data.get("status") == "in_progress" and row[1] is not None:
                data["elapsed_sec"] = round(time.time() - row[1], 1)
            return data
    except (OSError, sqlite3.Error, json.JSONDecodeError):
        pass
    return None


def read_last_ingest_run() -> dict[str, Any] | None:
    """Read last completed ingest run from SQLite ingest_runs. Returns None if none."""
    db_path = _ingest_cache_path()
    try:
        conn = sqlite3.connect(db_path, timeout=_sqlite_timeout())
        _init_ingest_status_tables(conn)
        row = conn.execute(
            f"""SELECT started_at, finished_at, status, total_tasks, done_tasks, total_points,
                       failed_count, embedding_backend, total_elapsed_sec
                FROM {_STATUS_TABLE_RUNS} ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        conn.close()
        if row:
            return {
                "started_at": row[0],
                "finished_at": row[1],
                "status": row[2],
                "total_tasks": row[3],
                "done_tasks": row[4],
                "total_points": row[5],
                "failed_count": row[6],
                "embedding_backend": row[7],
                "total_elapsed_sec": row[8],
                "finished_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(row[1]))
                if row[1]
                else None,
            }
    except (OSError, sqlite3.Error):
        pass
    return None


def read_last_ingest_failed(limit: int = 20) -> list[dict[str, str]]:
    """Read failed tasks from ingest_failed table for the latest run. For index-status."""
    db_path = _ingest_cache_path()
    try:
        conn = sqlite3.connect(db_path, timeout=_sqlite_timeout())
        _init_ingest_status_tables(conn)
        run_row = conn.execute(
            f"SELECT id FROM {_STATUS_TABLE_RUNS} ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not run_row:
            conn.close()
            return []
        run_id = run_row[0]
        rows = conn.execute(
            f"""SELECT version, language, path, error FROM {_STATUS_TABLE_FAILED}
                WHERE run_id = ? ORDER BY id LIMIT ?""",
            (run_id, limit),
        ).fetchall()
        conn.close()
        return [
            {"version": r[0], "language": r[1], "path": r[2], "error": (r[3] or "")[:500]}
            for r in rows
        ]
    except (OSError, sqlite3.Error):
        return []


def read_ingest_failed_log(limit: int = 30) -> list[dict[str, str]]:
    """Read INGEST_FAILED_LOG if set and exists. Returns list of {version, language, path, error}."""
    path = os.environ.get("INGEST_FAILED_LOG", "").strip()
    if not path:
        return []
    result: list[dict[str, str]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if len(result) >= limit:
                    break
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t", 3)
                if len(parts) >= 4:
                    result.append(
                        {
                            "version": parts[0],
                            "language": parts[1],
                            "path": parts[2].split("/")[-1] if "/" in parts[2] else parts[2],
                            "error": parts[3][:150],
                        }
                    )
    except OSError:
        pass
    return result


# Language: filename pattern like 1cv8_ru.hbk, shcntx_en.hbk
LANG_PATTERN = re.compile(r"_([a-z]{2})\.hbk$", re.IGNORECASE)


def _language_from_filename(name: str) -> str | None:
    m = LANG_PATTERN.search(name)
    return m.group(1).lower() if m else None


def _count_html_md(dir_path: Path) -> tuple[int, int]:
    """Return (html_count, md_count) for files under dir_path (recursive)."""
    html_c, md_c = 0, 0
    try:
        for p in dir_path.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() == ".html":
                html_c += 1
            elif p.suffix.lower() == ".md":
                md_c += 1
    except OSError:
        pass
    return (html_c, md_c)


def collect_hbk_tasks(
    source_dirs_with_versions: list[tuple[Path, str]],
    languages: list[str] | None,
) -> list[tuple[Path, str, str]]:
    """
    Scan source dirs (read-only) for .hbk files. Each item: (source_dir, version_label).
    Поиск рекурсивный (rglob), в т.ч. в подпапке bin/ (типично для Windows:
    C:\\Program Files\\1cv8\\8.3.27.1859\\bin).
    languages: e.g. ["ru"] for only *_ru.hbk; None or [] = all languages.
    Returns list of (hbk_path, version, language).
    """
    tasks: list[tuple[Path, str, str]] = []
    for source_dir, version in source_dirs_with_versions:
        source_dir = Path(source_dir).resolve()
        if not source_dir.is_dir():
            continue
        for path in source_dir.rglob("*.hbk"):
            if not path.is_file():
                continue
            lang = _language_from_filename(path.name)
            if lang is None:
                continue
            if languages and lang not in [x.lower() for x in languages]:
                continue
            tasks.append((path, version, lang))
    return tasks


def _unpack_and_build_docs(
    hbk_path: Path,
    version: str,
    language: str,
    temp_base: Path,
    unpack_fn: Any,
    build_docs_fn: Any,
    current_work: dict[int, dict[str, Any]] | None = None,
    state_lock: threading.Lock | None = None,
) -> tuple[Path | None, Path | None, str, str, str | None]:
    """Unpack one .hbk to temp, build .md there. Returns (md_dir, unpacked_dir, version, language, error_message) or (None, None, v, l, reason) on failure.
    If current_work and state_lock are set, updates current file/stage for this thread for status display."""
    ident = threading.get_ident()
    safe_name = re.sub(r"[^\w\-]", "_", hbk_path.stem)
    out_sub = temp_base / version / language / safe_name
    unpacked = out_sub / "unpacked"
    md_dir = out_sub / "md"
    err_msg: str | None = None
    try:
        if current_work is not None and state_lock is not None:
            with state_lock:
                current_work[ident] = {
                    "path": hbk_path.name,
                    "version": version,
                    "language": language,
                    "stage": "unpack",
                }
        unpacked.mkdir(parents=True, exist_ok=True)
        unpack_fn(hbk_path, unpacked)
        if current_work is not None and state_lock is not None:
            with state_lock:
                if ident in current_work:
                    current_work[ident]["stage"] = "build_docs"
        md_dir.mkdir(parents=True, exist_ok=True)
        build_docs_fn(unpacked, md_dir)
        if any(md_dir.rglob("*.md")) or any(md_dir.rglob("*")) and not list(md_dir.rglob("*.md")):
            # build_docs may create .md or we have extension-less HTML; indexer will use HTML fallback
            return (md_dir, unpacked, version, language, None)
        return (md_dir, unpacked, version, language, None)
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        return (None, None, version, language, err_msg)
    finally:
        if current_work is not None and state_lock is not None:
            with state_lock:
                current_work.pop(ident, None)


def run_ingest(
    source_dirs_with_versions: list[tuple[Path | str, str]],
    languages: list[str] | None = None,
    temp_base: Path | str | None = None,
    qdrant_host: str = "localhost",
    qdrant_port: int = 6333,
    collection: str = "onec_help",
    incremental: bool = True,
    max_workers: int | None = None,
    max_tasks: int | None = None,
    verbose: bool = True,
    dry_run: bool = False,
    index_batch_size: int = 500,
    embedding_batch_size: int | None = None,
    embedding_workers: int | None = None,
) -> int:
    """
    Ingest .hbk from multiple source dirs (read-only): unpack to temp, build docs, index in batches, cleanup.
    source_dirs_with_versions: [(path, version_label), ...].
    languages: e.g. ["ru"] for only *_ru.hbk; None or [] = all.
    temp_base: dir inside container for unpack (default /tmp/help_ingest). Removed at end.
    max_tasks: if set, process only first N .hbk files (for resumable runs or to avoid timeout).
    verbose: print progress to stderr (keeps long runs from being killed by "no output" timeouts).
    dry_run: if True, only report how many .hbk tasks would be processed and return 0.
    index_batch_size: number of files per index upsert (smaller = more progress, less memory per step).
    embedding_batch_size: texts per embedding batch (env EMBEDDING_BATCH_SIZE).
    embedding_workers: parallel API requests for openai_api (env EMBEDDING_WORKERS).
    Returns total points indexed (0 if dry_run).
    """
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams

    from .html2md import build_docs
    from .indexer import build_index, get_embedding_dimension
    from .unpack import unpack_hbk

    if not source_dirs_with_versions:
        return 0

    base = Path(temp_base or "/tmp/help_ingest").resolve()
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"Cannot create temp dir {base}: {e}") from e

    pairs = [(Path(p).resolve(), v) for p, v in source_dirs_with_versions]
    all_tasks = collect_hbk_tasks(pairs, languages)
    if not all_tasks:
        return 0

    skip_cache = (os.environ.get("INGEST_SKIP_CACHE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    cache_entries = _load_ingest_cache()
    to_process: list[tuple[Path, str, str]] = []
    task_hashes: dict[tuple[str, str, str], str] = {}
    skipped_files: list[dict[str, Any]] = []
    for path, version, lang in all_tasks:
        key = f"{version}/{lang}/{path.name}"
        h = None if skip_cache else _file_sha256(path)
        if h is None:
            to_process.append((path, version, lang))
            task_hashes[(version, lang, path.name)] = ""
            continue
        task_hashes[(version, lang, path.name)] = h
        ent = cache_entries.get(key)
        if ent and ent.get("hash") == h and ent.get("indexed"):
            skipped_files.append(
                {
                    "path": path.name,
                    "version": version,
                    "language": lang,
                    "points": ent.get("points") or 0,
                    "status": "skip",
                }
            )
            continue
        to_process.append((path, version, lang))
    tasks = to_process
    skipped = len(skipped_files)
    if verbose and skipped > 0:
        _log(f"[ingest] Cache hit: skip {skipped} already indexed .hbk (unchanged)")

    if dry_run:
        if verbose:
            _log(f"[ingest] DRY RUN: would process {len(tasks)} .hbk task(s)")
            for i, (path, version, lang) in enumerate(tasks[:25], 1):
                _log(f"  {i}. {version}/{lang}  {path.name}")
            if len(tasks) > 25:
                _log(f"  ... and {len(tasks) - 25} more")
        return 0

    if max_tasks is not None and max_tasks > 0:
        tasks = tasks[:max_tasks]
        if verbose:
            _log(f"[ingest] Limiting to first {max_tasks} task(s)")

    if not tasks:
        if verbose and skipped > 0:
            _log("[ingest] All tasks skipped (cache); nothing to do.")
        return 0

    if max_workers is None:
        max_workers = _default_workers()
    if verbose:
        _log(f"[ingest] Found {len(tasks)} .hbk task(s); workers={max_workers}")

    embedding_backend = (os.environ.get("EMBEDDING_BACKEND") or "local").strip().lower()
    if embedding_backend not in ("local", "openai_api", "deterministic"):
        embedding_backend = "none"
    started_at = time.time()
    # One entry per folder (version/language): hbk_count, html/md/err/points aggregated
    folder_hbk_count: dict[tuple[str, str], int] = Counter()
    for _, v, lang in tasks:
        folder_hbk_count[(v, lang)] += 1
    folders = [
        {
            "version": v,
            "language": lang,
            "hbk_count": folder_hbk_count[(v, lang)],
            "html_count": 0,
            "md_count": 0,
            "err_count": 0,
            "points": 0,
            "tasks_done": 0,
            "status": "pending",
        }
        for (v, lang) in sorted(folder_hbk_count.keys())
    ]
    _write_ingest_status(
        started_at=started_at,
        embedding_backend=embedding_backend,
        total_tasks=len(tasks),
        done_tasks=0,
        total_points=0,
        folders=folders,
        status="in_progress",
        completed_files=skipped_files,
        max_workers=max_workers,
        embedding_workers=embedding_workers,
    )

    state_lock = threading.Lock()
    current_work: dict[int, dict[str, Any]] = {}
    failed_tasks_list: list[dict[str, Any]] = []
    completed_files: list[dict[str, Any]] = list(skipped_files)
    state: dict[str, Any] = {
        "done_tasks": 0,
        "total_points": 0,
        "folders": folders,
        "current_work": current_work,
        "failed": failed_tasks_list,
        "completed_files": completed_files,
        "started_at": started_at,
        "embedding_backend": embedding_backend,
        "total_tasks": len(tasks),
        "status": "in_progress",
        "current_task_points": 0,
        "current_task_estimated_total": None,
        "max_workers": max_workers,
        "embedding_workers": embedding_workers,
    }
    interval_sec = float(
        os.environ.get("INDEX_STATUS_INTERVAL_SEC", str(STATUS_UPDATE_INTERVAL_SEC))
    )
    stop_event = threading.Event()
    writer = threading.Thread(
        target=_status_writer_loop,
        args=(stop_event, state_lock, state, interval_sec),
        daemon=True,
    )
    writer.start()

    # Ensure collection exists once (avoid race when multiple workers call build_index)
    if incremental:
        client = QdrantClient(host=qdrant_host, port=qdrant_port, check_compatibility=False)
        if not client.collection_exists(collection):
            client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(
                    size=get_embedding_dimension(), distance=Distance.COSINE
                ),
            )
            if verbose:
                _log("[ingest] Created Qdrant collection")

    total_indexed = 0
    done = 0
    failed: list[tuple[Path, str, str, str]] = []  # (path, version, language, error_message)
    main_ident = threading.get_ident()
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _unpack_and_build_docs,
                    path,
                    version,
                    lang,
                    base,
                    unpack_hbk,
                    build_docs,
                    current_work,
                    state_lock,
                ): (path, version, lang)
                for path, version, lang in tasks
            }
            for future in as_completed(futures):
                path_hbk, version, language = futures[future]
                done += 1
                md_dir, unpacked, _, _, err_msg = future.result()
                if md_dir is None or not md_dir.exists():
                    reason = (err_msg or "unknown").split("\n")[0].strip()[:200]
                    failed.append((path_hbk, version, language, err_msg or "unknown"))
                    with state_lock:
                        failed_tasks_list.append(
                            {
                                "path": path_hbk.name,
                                "path_full": str(path_hbk),
                                "version": version,
                                "language": language,
                                "error": (err_msg or "unknown").split("\n")[0].strip()[:200],
                            }
                        )
                        completed_files.append(
                            {
                                "path": path_hbk.name,
                                "version": version,
                                "language": language,
                                "points": 0,
                                "status": "fail",
                            }
                        )
                    for fo in folders:
                        if fo["version"] == version and fo["language"] == language:
                            fo["err_count"] = fo.get("err_count", 0) + 1
                            fo["tasks_done"] = fo.get("tasks_done", 0) + 1
                            if fo["tasks_done"] + fo["err_count"] >= fo["hbk_count"]:
                                fo["status"] = "done"
                            break
                    with state_lock:
                        state["done_tasks"] = done
                        state["total_points"] = total_indexed
                    _write_ingest_status(
                        started_at=started_at,
                        embedding_backend=embedding_backend,
                        total_tasks=len(tasks),
                        done_tasks=done,
                        total_points=total_indexed,
                        folders=folders,
                        status="in_progress",
                        failed_tasks=failed_tasks_list,
                        completed_files=completed_files,
                        max_workers=max_workers,
                        embedding_workers=embedding_workers,
                    )
                    if verbose:
                        _log(
                            f"[ingest] [{done}/{len(tasks)}] skip (unpack/build failed) {version}/{language} — {path_hbk}"
                        )
                        _log(f"[ingest]   reason: {reason}")
                    continue
                try:
                    if verbose:
                        _log(
                            f"[ingest] [{done}/{len(tasks)}] indexing {version}/{language} — {path_hbk}"
                        )
                    with state_lock:
                        state["current_task_points"] = 0
                        current_work[main_ident] = {
                            "path": path_hbk.name,
                            "version": version,
                            "language": language,
                            "stage": "indexing",
                        }

                    def _on_batch(
                        pts: int,
                        phase: str | None = None,
                        total_estimated: int | None = None,
                    ) -> None:
                        with state_lock:
                            state["current_task_points"] = pts
                            if total_estimated is not None:
                                state["current_task_estimated_total"] = total_estimated
                            if main_ident in current_work:
                                current_work[main_ident]["points"] = pts
                                if total_estimated is not None:
                                    current_work[main_ident]["estimated_total"] = total_estimated
                                if phase:
                                    current_work[main_ident]["stage"] = phase

                    try:
                        n = build_index(
                            docs_dir=md_dir,
                            qdrant_host=qdrant_host,
                            qdrant_port=qdrant_port,
                            collection=collection,
                            incremental=incremental,
                            extra_payload={"version": version, "language": language},
                            batch_size=index_batch_size,
                            embedding_batch_size=embedding_batch_size,
                            embedding_workers=embedding_workers,
                            source_dir=str(unpacked) if unpacked and unpacked.exists() else None,
                            progress_callback=_on_batch,
                        )
                        total_indexed += n
                        key = f"{version}/{language}/{path_hbk.name}"
                        h = task_hashes.get((version, language, path_hbk.name)) or _file_sha256(
                            path_hbk
                        )
                        if h:
                            cache_entries[key] = {"hash": h, "indexed": True, "points": n}
                            _update_ingest_cache_entry(key, h, n)
                        with state_lock:
                            completed_files.append(
                                {
                                    "path": path_hbk.name,
                                    "version": version,
                                    "language": language,
                                    "points": n,
                                    "status": "ok",
                                }
                            )
                        html_c, md_c = _count_html_md(md_dir)
                        for fo in folders:
                            if fo["version"] == version and fo["language"] == language:
                                fo["html_count"] = fo.get("html_count", 0) + html_c
                                fo["md_count"] = fo.get("md_count", 0) + md_c
                                fo["points"] = fo.get("points", 0) + n
                                fo["tasks_done"] = fo.get("tasks_done", 0) + 1
                                if fo["tasks_done"] + fo.get("err_count", 0) >= fo["hbk_count"]:
                                    fo["status"] = "done"
                                break
                        with state_lock:
                            state["done_tasks"] = done
                            state["total_points"] = total_indexed
                            current_snapshot = list(current_work.values())
                        _write_ingest_status(
                            started_at=started_at,
                            embedding_backend=embedding_backend,
                            total_tasks=len(tasks),
                            done_tasks=done,
                            total_points=total_indexed,
                            folders=folders,
                            status="in_progress",
                            current=current_snapshot,
                            failed_tasks=failed_tasks_list,
                            completed_files=completed_files,
                            max_workers=max_workers,
                            embedding_workers=embedding_workers,
                        )
                        if verbose:
                            _log(
                                f"[ingest] [{done}/{len(tasks)}] indexed {n} points ({version}/{language}) — {path_hbk}, total={total_indexed}"
                            )
                    finally:
                        with state_lock:
                            current_work.pop(main_ident, None)
                            state["current_task_points"] = 0
                            state["current_task_estimated_total"] = None
                        try:
                            shutil.rmtree(md_dir.parent)
                        except OSError:
                            pass
                except Exception as e:
                    err_msg = f"{type(e).__name__}: {e}"
                    err_str = str(e).lower()
                    if "500" in err_str or "unexpectedresponse" in type(e).__name__.lower():
                        err_msg += (
                            " [Qdrant 500: проверьте make qdrant-logs; "
                            "размерность векторов (EMBEDDING_DIMENSION); уменьшите index_batch_size]"
                        )
                    with state_lock:
                        failed_tasks_list.append(
                            {
                                "path": path_hbk.name,
                                "path_full": str(path_hbk),
                                "version": version,
                                "language": language,
                                "error": err_msg,
                            }
                        )
                        completed_files.append(
                            {
                                "path": path_hbk.name,
                                "version": version,
                                "language": language,
                                "points": 0,
                                "status": "fail",
                            }
                        )
                        failed.append((path_hbk, version, language, err_msg))
                        state["done_tasks"] = done
                        state["total_points"] = total_indexed
                    for fo in folders:
                        if fo["version"] == version and fo["language"] == language:
                            fo["err_count"] = fo.get("err_count", 0) + 1
                            fo["tasks_done"] = fo.get("tasks_done", 0) + 1
                            if fo["tasks_done"] + fo.get("err_count", 0) >= fo["hbk_count"]:
                                fo["status"] = "done"
                            break
                    _write_ingest_status(
                        started_at=started_at,
                        embedding_backend=embedding_backend,
                        total_tasks=len(tasks),
                        done_tasks=done,
                        total_points=total_indexed,
                        folders=folders,
                        status="in_progress",
                        failed_tasks=failed_tasks_list,
                        completed_files=completed_files,
                        max_workers=max_workers,
                        embedding_workers=embedding_workers,
                    )
                    if verbose:
                        _log(
                            f"[ingest] [{done}/{len(tasks)}] indexing failed {version}/{language} — {path_hbk}: {err_msg}"
                        )
                    try:
                        shutil.rmtree(md_dir.parent)
                    except OSError:
                        pass
                    raise
    finally:
        # Всегда пишем завершение в кэш — index-status читает реальный статус из той же БД
        with state_lock:
            state["status"] = "completed"
            current_work.clear()
            done_tasks = state["done_tasks"]
            total_points = state["total_points"]
        stop_event.set()
        writer.join(timeout=interval_sec * 2 + 1)
        _write_ingest_status(
            started_at=started_at,
            embedding_backend=embedding_backend,
            total_tasks=len(tasks),
            done_tasks=done_tasks,
            total_points=total_points,
            folders=folders,
            status="completed",
            finished_at=time.time(),
            current=[],
            failed_tasks=failed_tasks_list,
            completed_files=completed_files,
            max_workers=max_workers,
            embedding_workers=embedding_workers,
        )
        _vacuum_cache_db()
        try:
            shutil.rmtree(base)
        except OSError:
            pass
    if verbose:
        _log(f"[ingest] Done. Total points indexed: {total_indexed}")
    if failed and verbose:
        _log(f"[ingest] Failed {len(failed)} file(s) (unpack or build_docs error):")
        for path_hbk, version, language, err in failed:
            short_err = (err or "").split("\n")[0].strip()[:150]
            _log(f"[ingest]   — {version}/{language} {path_hbk.name}: {short_err}")
        fail_log = os.environ.get("INGEST_FAILED_LOG")
        if fail_log:
            try:
                with open(fail_log, "w", encoding="utf-8") as f:
                    f.write(f"# Ingest failed .hbk ({len(failed)})\n")
                    for path_hbk, version, language, err in failed:
                        f.write(f"{version}\t{language}\t{path_hbk}\t{err or ''}\n")
                _log(f"[ingest] Wrote failure list to {fail_log}")
            except OSError as e:
                _log(
                    f"[ingest] Could not write failure log {mask_path_for_log(fail_log)}: {safe_error_message(e)}"
                )
    return total_indexed


def _hbk_label_from_stem(stem: str) -> str:
    """Human-readable label from stem (e.g. 1cv8_ru → 'Справка 1С:Предприятие 8')."""
    raw = os.environ.get("HBK_LABELS", "").strip()
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if ":" in part:
                key, val = part.split(":", 1)
                if stem.lower().startswith(key.lower() + "_") or stem.lower() == key.lower():
                    return val.strip()
    # Built-in mapping
    s = stem.lower()
    if s.startswith("1cv8"):
        return "Справка 1С:Предприятие 8"
    if s.startswith("shcntx") or "syntax" in s:
        return "Синтаксис"
    if s.startswith("designer"):
        return "Конфигуратор"
    return stem


def _write_hbk_info(
    out_dir: Path,
    source_file: str,
    label: str,
    version: str,
    language: str,
    file_hash: str = "",
) -> None:
    """Write .hbk_info.json with metadata for unpacked help."""
    info = {
        "source_file": source_file,
        "label": label,
        "version": version,
        "language": language,
    }
    if file_hash:
        info["hash"] = file_hash
    path = out_dir / ".hbk_info.json"
    try:
        path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _unpack_one(
    path: Path,
    version: str,
    lang: str,
    output_base: Path,
    unpack_fn: Any,
    verbose: bool,
) -> tuple[bool, str]:
    """Unpack one .hbk. Returns (success, message)."""
    safe_name = re.sub(r"[^\w\-]", "_", path.stem)
    out_sub = output_base / version / lang / safe_name
    try:
        out_sub.mkdir(parents=True, exist_ok=True)
        unpack_fn(path, out_sub)
        msg = f"{version}/{lang} → {out_sub.relative_to(output_base)}"
        if verbose:
            _log(f"[unpack] {msg}")
        return (True, msg)
    except Exception as e:
        if verbose:
            _log(f"[unpack] skip {mask_path_for_log(str(path))}: {safe_error_message(e)}")
        return (False, str(e))


def _unpack_one_sync(
    path: Path,
    version: str,
    lang: str,
    output_base: Path,
    unpack_fn: Any,
    verbose: bool,
) -> tuple[bool, str]:
    """Unpack one .hbk for unpack-sync: version/stem structure, .hbk_info.json, hash skip."""
    safe_stem = re.sub(r"[^\w\-]", "_", path.stem)
    out_sub = output_base / version / safe_stem
    file_hash = _file_sha256(path)
    info_path = out_sub / ".hbk_info.json"
    if out_sub.exists() and info_path.exists() and file_hash:
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
            if info.get("hash") == file_hash:
                if verbose:
                    _log(f"[unpack-sync] skip (unchanged) {version}/{safe_stem}")
                return (False, "cached")
        except (json.JSONDecodeError, OSError):
            pass
    try:
        out_sub.mkdir(parents=True, exist_ok=True)
        unpack_fn(path, out_sub)
        label = _hbk_label_from_stem(safe_stem)
        _write_hbk_info(
            out_sub,
            source_file=path.name,
            label=label,
            version=version,
            language=lang,
            file_hash=file_hash or "",
        )
        msg = f"{version}/{safe_stem} → {out_sub.relative_to(output_base)}"
        if verbose:
            _log(f"[unpack-sync] {msg}")
        return (True, msg)
    except Exception as e:
        if verbose:
            _log(f"[unpack-sync] skip {mask_path_for_log(str(path))}: {safe_error_message(e)}")
        return (False, str(e))


def run_unpack_sync(
    source_dirs_with_versions: list[tuple[Path | str, str]],
    output_dir: Path | str | None = None,
    languages: list[str] | None = None,
    max_workers: int = 4,
    verbose: bool = True,
) -> int:
    """
    Unpack .hbk to data/unpacked with version/platform_lang structure and .hbk_info.json.
    Structure: output_dir / version / stem / (unpacked + .hbk_info.json). Skips if hash matches.
    Returns number of .hbk archives unpacked (excludes cached).
    """
    from .unpack import unpack_hbk

    out_raw = output_dir or os.environ.get("DATA_UNPACKED_DIR", "data/unpacked")
    output_base = Path(out_raw).resolve()
    pairs = [(Path(p).resolve(), v) for p, v in source_dirs_with_versions]
    tasks = collect_hbk_tasks(pairs, languages)
    if not tasks:
        return 0
    count = 0
    if max_workers <= 1:
        for path, version, lang in tasks:
            ok, _ = _unpack_one_sync(path, version, lang, output_base, unpack_hbk, verbose)
            if ok:
                count += 1
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futs = [
                executor.submit(
                    _unpack_one_sync, path, version, lang, output_base, unpack_hbk, verbose
                )
                for path, version, lang in tasks
            ]
            for fut in as_completed(futs):
                ok, _ = fut.result()
                if ok:
                    count += 1
    return count


def _collect_unpacked_tasks(unpacked_base: Path) -> list[tuple[Path, str, str, str]]:
    """Scan unpacked_base for version/stem dirs. Returns [(docs_dir, version, stem, language), ...]."""
    tasks: list[tuple[Path, str, str, str]] = []
    base = Path(unpacked_base).resolve()
    if not base.is_dir():
        return []
    for version_dir in sorted(base.iterdir()):
        if not version_dir.is_dir() or version_dir.name.startswith("."):
            continue
        version = version_dir.name
        for stem_dir in sorted(version_dir.iterdir()):
            if not stem_dir.is_dir() or stem_dir.name.startswith("."):
                continue
            stem = stem_dir.name
            info_path = stem_dir / ".hbk_info.json"
            language = ""
            if info_path.exists():
                try:
                    info = json.loads(info_path.read_text(encoding="utf-8"))
                    language = info.get("language", "")
                    if info.get("version"):
                        version = str(info["version"])
                except (json.JSONDecodeError, OSError):
                    pass
            if not language and "_" in stem:
                parts = stem.rsplit("_", 1)
                if len(parts[1]) == 2:
                    language = parts[1].lower()
            if not language:
                language = "ru"
            if any(stem_dir.rglob("*.html")) or any(stem_dir.rglob("*.md")):
                tasks.append((stem_dir, version, stem, language))
    return tasks


def run_ingest_from_unpacked(
    unpacked_base: Path | str,
    qdrant_host: str = "localhost",
    qdrant_port: int = 6333,
    collection: str = "onec_help",
    incremental: bool = True,
    verbose: bool = True,
    embedding_batch_size: int | None = None,
    embedding_workers: int | None = None,
    bm25: bool | None = None,
) -> int:
    """
    Index help from unpacked dir (data/unpacked structure).
    Scans version/stem dirs, uses path_prefix for payload path.
    Returns total points indexed.
    """
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams

    from .indexer import build_index, get_embedding_dimension

    base = Path(unpacked_base).resolve()
    if not base.is_dir():
        return 0
    tasks = _collect_unpacked_tasks(base)
    if not tasks:
        return 0
    if incremental:
        try:
            client = QdrantClient(host=qdrant_host, port=qdrant_port, check_compatibility=False)
            if not client.collection_exists(collection):
                client.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(
                        size=get_embedding_dimension(), distance=Distance.COSINE
                    ),
                )
                if verbose:
                    _log("[ingest-from-unpacked] Created Qdrant collection")
        except Exception as e:
            if verbose:
                _log(f"[ingest-from-unpacked] WARN: {safe_error_message(e)}")
    total = 0
    for docs_dir, version, stem, language in tasks:
        path_prefix = f"{version}/{stem}"
        try:
            n = build_index(
                docs_dir=docs_dir,
                qdrant_host=qdrant_host,
                qdrant_port=qdrant_port,
                collection=collection,
                incremental=incremental,
                extra_payload={"version": version, "language": language, "hbk_slug": stem},
                source_dir=str(docs_dir),
                path_prefix=path_prefix,
                embedding_batch_size=embedding_batch_size,
                embedding_workers=embedding_workers,
                bm25=bm25,
            )
            total += n
            if verbose:
                _log(f"[ingest-from-unpacked] {path_prefix}: {n} points")
        except Exception as e:
            if verbose:
                _log(f"[ingest-from-unpacked] skip {path_prefix}: {safe_error_message(e)}")
    return total


def run_unpack_only(
    source_dirs_with_versions: list[tuple[Path | str, str]],
    output_dir: Path | str,
    languages: list[str] | None = None,
    max_workers: int = 4,
    verbose: bool = True,
) -> int:
    """
    Only unpack .hbk files into output_dir (no build-docs, no indexing).
    Structure: output_dir / version / language / safe_stem / (unpacked files).
    Returns number of .hbk archives unpacked.
    """
    from .unpack import unpack_hbk

    output_base = Path(output_dir).resolve()
    pairs = [(Path(p).resolve(), v) for p, v in source_dirs_with_versions]
    tasks = collect_hbk_tasks(pairs, languages)
    if not tasks:
        return 0
    count = 0
    if max_workers <= 1:
        for path, version, lang in tasks:
            ok, _ = _unpack_one(path, version, lang, output_base, unpack_hbk, verbose)
            if ok:
                count += 1
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futs = [
                executor.submit(_unpack_one, path, version, lang, output_base, unpack_hbk, verbose)
                for path, version, lang in tasks
            ]
            for fut in as_completed(futs):
                ok, _ = fut.result()
                if ok:
                    count += 1
    return count


def discover_version_dirs(base_path: Path | str) -> list[tuple[Path, str]]:
    """
    Сканировать базовый каталог: каждая прямая подпапка = версия 1С.
    Возвращает [(путь_к_подпапке, имя_подпапки), ...]. Скрытые и не-каталоги пропускаются.
    На Windows каталоги версий часто имеют вид ...\\8.3.27.1859\\bin — поиск .hbk идёт
    рекурсивно (rglob), так что файлы в bin/ находятся автоматически.
    """
    base = Path(base_path).resolve()
    if not base.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for child in sorted(base.iterdir()):
        if child.name.startswith(".") or not child.is_dir():
            continue
        out.append((child, child.name))
    return out


def parse_source_dirs_env(env_value: str | None) -> list[tuple[str, str]]:
    """
    Parse HELP_SOURCE_DIRS (legacy): "path1:version1,path2:version2" or "path1,path2".
    Returns [(path, version), ...]. Prefer HELP_SOURCE_BASE instead.
    """
    if not env_value or not env_value.strip():
        return []
    out = []
    for part in env_value.strip().split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            p, v = part.split(":", 1)
            out.append((p.strip(), v.strip()))
        else:
            p = part
            v = Path(p).name or "default"
            out.append((p, v))
    return out


def parse_languages_env(env_value: str | None) -> list[str] | None:
    """
    Parse HELP_LANGUAGES: "ru" => ["ru"], "ru,en" => ["ru","en"], empty or "all" => None (all languages).
    """
    if not env_value or not env_value.strip():
        return None
    raw = env_value.strip().lower()
    if raw == "all":
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]
