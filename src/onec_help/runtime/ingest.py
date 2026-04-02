"""Ingest .hbk from multiple read-only source directories.

Pipeline: HBK -> unpacked HTML (temporary) -> structured JSONL -> Qdrant structured collections.
Markdown/topic indexing is no longer part of the runtime ingest path.
Cache and status: Redis (REDIS_URL or REDIS_HOST required). Runs with ingest-worker and mcp.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from ..shared import env_config
from ..shared._utils import mask_path_for_log, safe_error_message
from . import redis_cache

# How often to write status to Redis while ingest runs (seconds); env INDEX_STATUS_INTERVAL_SEC
STATUS_UPDATE_INTERVAL_SEC = 2.0


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


def _safe_stem(path: Path) -> str:
    """Safe directory name from path stem (alphanumeric, underscore, hyphen only)."""
    return re.sub(r"[^\w\-]", "_", path.stem)


def _ingest_cache_key(version: str, lang: str, path: Path) -> str:
    """Unique cache key: version/lang/filename + short path hash so same name from different dirs don't collide."""
    path_id = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
    return f"{version}/{lang}/{path.name}|{path_id}"


def _ingest_cache_path() -> str:
    """Return path whose parent is used for markers (load_*.running, load_*.status.json). Redis holds cache."""
    path = env_config.get_ingest_cache_file()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


def clear_ingest_cache() -> bool:
    """Clear ingest and snippets cache in Redis. Returns True on success."""
    try:
        return redis_cache.clear_all()
    except Exception:
        return False


def read_ingest_cache_entries(limit: int = 100) -> list[dict[str, Any]]:
    """Return list of cached indexed files for display. Each item: {path, version, language, points, status}."""
    return redis_cache.ingest_cache_entries(limit=limit)


def _load_ingest_cache() -> dict[str, dict[str, Any]]:
    """Load cache from Redis. Returns dict key -> {hash, indexed, points}."""
    try:
        return redis_cache.ingest_cache_get_all()
    except Exception:
        return {}


def _load_ingest_cache_indexed_set() -> set[tuple[str, str, str]]:
    """Set of (version, language, hash) for indexed entries."""
    return redis_cache.ingest_cache_get_indexed_set()


def _update_ingest_cache_entry(key: str, file_hash: str, points: int) -> None:
    """Persist one cache entry to Redis."""
    try:
        redis_cache.ingest_cache_set_entry(key, file_hash, points)
    except Exception:
        pass


def _log_status_error(op: str, err: Exception) -> None:
    """Log ingest status error once per run."""
    if not hasattr(_log_status_error, "_warned"):
        _log_status_error._warned = set()  # type: ignore[attr-defined]
    if op not in _log_status_error._warned:  # type: ignore[attr-defined]
        _log_status_error._warned.add(op)  # type: ignore[attr-defined]
        _log(
            f"[ingest] WARN: ingest status {op} failed: {safe_error_message(err)}. "
            "dashboard may show incomplete data."
        )


def _error_category_and_stored_message(err: str) -> tuple[str, str]:
    """Return (error_category, error_message) for storing in ingest_failed."""
    err = (err or "")[:500]
    if "unpack" in err.lower() or "7z" in err:
        cat = "unpack"
        return cat, err
    if "embed" in err.lower() or "429" in err or "timeout" in err.lower():
        hint = (
            " Рекомендация: проверьте EMBEDDING_API_URL, EMBEDDING_TIMEOUT; перезапустите ingest."
        )
        stored = (err[:450] + hint) if len(err) + len(hint) > 500 else err + hint
        return "embed", stored[:500]
    if "qdrant" in err.lower() or "upsert" in err.lower():
        return "index", err
    if "build" in err.lower() or "html" in err.lower():
        return "build", err
    return "other", err


def _create_ingest_run(started_at: float, embedding_backend: str, total_tasks: int) -> int | None:
    """Create run in Redis; return run_id. Errors -> None."""
    try:
        run_id = redis_cache.ingest_run_create(started_at, embedding_backend or "none", total_tasks)
        return run_id
    except Exception as e:
        _log_status_error("create run", e)
        return None


def _append_failed_to_cache(run_id: int, task: dict[str, Any]) -> None:
    """Append one failed task to Redis (per-run and accumulated log for dashboard)."""
    _, err_stored = _error_category_and_stored_message((task.get("error") or "")[:500])
    path_for_db = task.get("path_full") or task.get("path", "")
    version = task.get("version", "")
    language = task.get("language", "")
    try:
        redis_cache.ingest_run_append_failed(
            run_id,
            version,
            language,
            path_for_db,
            err_stored[:500],
        )
        redis_cache.ingest_errors_append(version, language, path_for_db, err_stored[:500])
    except Exception as e:
        _log_status_error("append failed", e)


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
    run_id: int | None = None,
    last_batch_sec: float | None = None,
) -> None:
    """Persist ingest status to Redis (ingest:current). On completion update run and trim old runs."""
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
    if last_batch_sec is not None and last_batch_sec > 0:
        payload["last_batch_sec"] = round(last_batch_sec, 2)

    payload_with_ts = {**payload, "started_at_ts": started_at}
    try:
        redis_cache.ingest_current_set(payload_with_ts)
    except Exception as e:
        _log_status_error("write", e)
    if status == "completed" and run_id is not None and finished_at is not None:
        try:
            redis_cache.ingest_run_update(
                run_id,
                finished_at,
                status,
                done_tasks,
                total_points,
                failed_count,
                finished_at - started_at,
            )
            redis_cache.ingest_trim_old_runs()
        except Exception as e:
            _log_status_error("write run", e)


def _vacuum_cache_db() -> None:
    """No-op: cache is in Redis (no VACUUM). Kept for API compatibility."""


def _flush_ingest_status(state_lock: threading.Lock, state: dict[str, Any]) -> None:
    """Write current state to Redis immediately (e.g. after each embedding batch). No-op if completed."""
    with state_lock:
        if state.get("status") == "completed":
            return
        done_tasks = state["done_tasks"]
        total_points = state["total_points"]
        folders = copy.deepcopy(state["folders"])
        current = list(state["current_work"].values())
        failed_tasks = list(state.get("failed", []))
        completed_files = list(state.get("completed_files", []))
        current_task_points = state.get("current_task_points", 0) or 0
        current_task_estimated = state.get("current_task_estimated_total")
        last_batch_sec = state.get("last_batch_sec")
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
        last_batch_sec=last_batch_sec,
    )


def _status_writer_loop(
    stop_event: threading.Event,
    state_lock: threading.Lock,
    state: dict[str, Any],
    interval_sec: float,
) -> None:
    """Background thread: write status to Redis every interval_sec until stop_event is set."""
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
            last_batch_sec = state.get("last_batch_sec")
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
            last_batch_sec=last_batch_sec,
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
    run_id: int | None = None,
    last_batch_sec: float | None = None,
) -> None:
    """Write ingest status to Redis for dashboard."""
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
        run_id=run_id,
        last_batch_sec=last_batch_sec,
    )


def read_ingest_status() -> dict[str, Any] | None:
    """Read ingest status from Redis."""
    try:
        return redis_cache.ingest_current_get()
    except Exception:
        return None


def read_last_ingest_run() -> dict[str, Any] | None:
    """Read last ingest run from Redis. Returns None if none."""
    try:
        return redis_cache.ingest_last_run()
    except Exception:
        return None


def read_last_ingest_failed(limit: int = 20) -> list[dict[str, str]]:
    """Read failed tasks for the latest run from Redis."""
    try:
        return redis_cache.ingest_last_failed(limit=limit)
    except Exception:
        return []


def read_ingest_errors_log(limit: int = 50) -> list[dict[str, str]]:
    """Read accumulated errors from Redis (ingest:errors). Always available for dashboard. Same shape as read_last_ingest_failed."""
    try:
        return redis_cache.ingest_errors_list(limit=limit)
    except Exception:
        return []


def read_ingest_failed_log(limit: int = 30) -> list[dict[str, str]]:
    """Read INGEST_FAILED_LOG if set and exists. Returns list of {version, language, path, error}."""
    path = env_config.get_ingest_failed_log()
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
    """Ingest .hbk from multiple source dirs into structured JSONL + structured Qdrant collections."""
    from ..help_core.unpack import unpack_hbk

    redis_cache.require_runtime_redis("ingest")

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

    skip_cache = env_config.get_ingest_skip_cache()
    cache_entries = _load_ingest_cache()
    changed_tasks: list[tuple[Path, str, str]] = []
    skipped_files: list[dict[str, Any]] = []
    for path, version, lang in all_tasks:
        key = _ingest_cache_key(version, lang, path)
        h = None if skip_cache else _file_sha256(path)
        if h is None:
            changed_tasks.append((path, version, lang))
            continue
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
        changed_tasks.append((path, version, lang))
    skipped = len(skipped_files)
    if verbose and skipped > 0:
        _log(f"[ingest] Cache hit: {skipped} unchanged .hbk")
    tasks = list(all_tasks)

    if dry_run:
        if verbose:
            _log(
                "[ingest] DRY RUN: "
                f"{len(changed_tasks)} changed of {len(tasks)} .hbk task(s); "
                "ingest rebuilds the structured snapshot from the selected source set"
            )
            for i, (path, version, lang) in enumerate(tasks[:25], 1):
                _log(f"  {i}. {version}/{lang}  {path.name}")
            if len(tasks) > 25:
                _log(f"  ... and {len(tasks) - 25} more")
        return 0

    if not changed_tasks and not skip_cache:
        if verbose:
            _log("[ingest] No changed .hbk files; structured snapshot is up to date.")
        return 0

    if max_tasks is not None and max_tasks > 0:
        tasks = tasks[:max_tasks]
        if verbose:
            _log(
                f"[ingest] Limiting source set to first {max_tasks} task(s); "
                "resulting structured snapshot will include only this subset."
            )

    if max_workers is None:
        max_workers = _default_workers()
    if verbose:
        _log(f"[ingest] Rebuilding structured help from {len(tasks)} .hbk task(s); workers={max_workers}")

    failed: list[tuple[Path, str, str, str]] = []
    unpacked_count = 0
    try:
        if max_workers <= 1:
            for path, version, lang in tasks:
                ok, msg = _unpack_one_sync(path, version, lang, base, unpack_hbk, verbose)
                if ok:
                    unpacked_count += 1
                elif msg != "cached":
                    failed.append((path, version, lang, msg))
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futs = {
                    executor.submit(_unpack_one_sync, path, version, lang, base, unpack_hbk, verbose): (path, version, lang)
                    for path, version, lang in tasks
                }
                for fut in as_completed(futs):
                    task = futs[fut]
                    ok, msg = fut.result()
                    if ok:
                        unpacked_count += 1
                    elif msg != "cached":
                        path, version, lang = task
                        failed.append((path, version, lang, msg))
        if failed and verbose:
            _log(f"[ingest] Failed to unpack {len(failed)} archive(s)")
            for path_hbk, version, language, err in failed[:20]:
                _log(f"[ingest]   — {version}/{language} {path_hbk.name}: {(err or '')[:150]}")
        if unpacked_count == 0:
            fail_log = env_config.get_ingest_failed_log() or None
            if fail_log:
                try:
                    with open(fail_log, "w", encoding="utf-8") as f:
                        f.write(f"# Ingest failed .hbk ({len(failed)})\n")
                        for path_hbk, version, language, err in failed:
                            f.write(f"{version}\t{language}\t{path_hbk}\t{err or ''}\n")
                except OSError as e:
                    if verbose:
                        _log(
                            f"[ingest] Could not write failure log {mask_path_for_log(fail_log)}: {safe_error_message(e)}"
                        )
            return 0
        if verbose:
            _log(f"[ingest] Unpacked source set: {unpacked_count}/{len(tasks)} archive(s)")
        total = run_ingest_from_unpacked(
            unpacked_base=base,
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
            collection=collection,
            incremental=False,
            verbose=verbose,
            embedding_batch_size=embedding_batch_size,
            embedding_workers=embedding_workers,
            bm25=True,
            max_workers=max_workers,
        )
        if failed:
            fail_log = env_config.get_ingest_failed_log() or None
            if fail_log:
                try:
                    with open(fail_log, "w", encoding="utf-8") as f:
                        f.write(f"# Ingest failed .hbk ({len(failed)})\n")
                        for path_hbk, version, language, err in failed:
                            f.write(f"{version}\t{language}\t{path_hbk}\t{err or ''}\n")
                except OSError as e:
                    if verbose:
                        _log(
                            f"[ingest] Could not write failure log {mask_path_for_log(fail_log)}: {safe_error_message(e)}"
                        )
        return total
    finally:
        try:
            shutil.rmtree(base)
        except OSError:
            pass


def _hbk_label_from_stem(stem: str) -> str:
    """Human-readable label from stem (e.g. 1cv8_ru → 'Справка 1С:Предприятие 8')."""
    raw = env_config.get_hbk_labels()
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
    """Unpack one .hbk. Returns (success, message). Uses version/lang/stem structure."""
    return _unpack_one_impl(path, version, lang, output_base, unpack_fn, verbose, sync=False)


def _unpack_one_sync(
    path: Path,
    version: str,
    lang: str,
    output_base: Path,
    unpack_fn: Any,
    verbose: bool,
) -> tuple[bool, str]:
    """Unpack one .hbk for unpack-sync: version/stem structure, .hbk_info.json, hash skip."""
    return _unpack_one_impl(path, version, lang, output_base, unpack_fn, verbose, sync=True)


def _unpack_one_impl(
    path: Path,
    version: str,
    lang: str,
    output_base: Path,
    unpack_fn: Any,
    verbose: bool,
    sync: bool,
) -> tuple[bool, str]:
    """Shared unpack logic: sync=True => version/stem + .hbk_info.json + hash skip; sync=False => version/lang/stem."""
    safe_stem = _safe_stem(path)
    if sync:
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
    else:
        out_sub = output_base / version / lang / safe_stem
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
    from ..help_core.unpack import unpack_hbk

    out_raw = output_dir or env_config.get_data_unpacked_dir()
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
            if any(stem_dir.rglob("*.html")):
                tasks.append((stem_dir, version, stem, language))
    return tasks


def _status_writer_loop_from_unpacked(
    stop_event: threading.Event,
    state_lock: threading.Lock,
    state: dict[str, Any],
    interval_sec: float,
) -> None:
    """Background thread: write ingest status to SQLite every interval_sec for run_ingest_from_unpacked."""
    while not stop_event.wait(timeout=interval_sec):
        with state_lock:
            if state.get("status") == "completed":
                break
            # Prefer current_work (parallel) so dashboard shows all active workers
            current_work = state.get("current_work")
            if current_work:
                current = list(current_work.values())
            else:
                current = list(state.get("current") or [])
            done_tasks = state["done_tasks"]
            total_points = state["total_points"]
            current_task_points = state.get("current_task_points") or 0
            current_task_estimated = state.get("current_task_estimated_total")
            completed_files = list(state.get("completed_files") or [])
            folders = copy.deepcopy(state.get("folders") or [])
        _write_ingest_status(
            started_at=state["started_at"],
            embedding_backend=state["embedding_backend"],
            total_tasks=state["total_tasks"],
            done_tasks=done_tasks,
            total_points=total_points,
            folders=folders,
            status="in_progress",
            current=current if current else None,
            current_task_points=current_task_points if current_task_points > 0 else None,
            current_task_estimated_total=current_task_estimated,
            completed_files=completed_files,
        )


def _read_unpacked_hash(docs_dir: Path) -> str:
    """Read hash from .hbk_info.json in unpacked stem dir. Returns empty string if missing or invalid."""
    info_path = docs_dir / ".hbk_info.json"
    if not info_path.exists():
        return ""
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
        return (info.get("hash") or "").strip()
    except (json.JSONDecodeError, OSError):
        return ""


def _index_one_unpacked_task(
    task_index: int,
    docs_dir: Path,
    version: str,
    stem: str,
    language: str,
    qdrant_host: str,
    qdrant_port: int,
    collection: str,
    incremental: bool,
    embedding_batch_size: int | None,
    embedding_workers: int | None,
    bm25: bool | None,
    current_work: dict[int, dict[str, Any]],
    state_lock: threading.Lock,
    state: dict[str, Any],
    build_index_fn: Any,
) -> dict[str, Any]:
    """Index one unpacked task (one version/stem). For parallel run_ingest_from_unpacked.
    Returns dict with task_index, path_prefix, version, language, points, error, file_hash."""
    ident = threading.get_ident()
    path_prefix = f"{version}/{stem}"
    result: dict[str, Any] = {
        "task_index": task_index,
        "path_prefix": path_prefix,
        "version": version,
        "language": language,
        "stem": stem,
        "points": 0,
        "error": None,
        "file_hash": _read_unpacked_hash(docs_dir),
    }
    with state_lock:
        current_work[ident] = {
            "path": path_prefix,
            "version": version,
            "language": language,
            "stage": "indexing",
        }
    try:

        def _on_batch(
            pts: int,
            phase: str | None = None,
            total_estimated: int | None = None,
            **kwargs: Any,
        ) -> None:
            with state_lock:
                state["current_task_points"] = pts
                if total_estimated is not None:
                    state["current_task_estimated_total"] = total_estimated
                if ident in current_work:
                    current_work[ident]["points"] = pts
                    if total_estimated is not None:
                        current_work[ident]["estimated_total"] = total_estimated
                    if phase:
                        current_work[ident]["stage"] = phase
                batch_sec = kwargs.get("batch_sec")
                if batch_sec is not None and isinstance(batch_sec, (int, float)):
                    state["last_batch_sec"] = round(float(batch_sec), 2)
            _flush_ingest_status(state_lock, state)

        n = build_index_fn(
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
            progress_callback=_on_batch,
        )
        result["points"] = n
        return result
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        return result
    finally:
        with state_lock:
            current_work.pop(ident, None)
            state["current_task_points"] = 0
            state["current_task_estimated_total"] = None


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
    max_workers: int | None = None,
) -> int:
    """Build structured JSONL from unpacked HTML and index structured help collections."""
    from ..knowledge.help_structured import (
        build_structured_api_snapshot,
        get_help_structured_dir,
        index_structured_help_snapshot,
    )

    redis_cache.require_runtime_redis("ingest-from-unpacked")

    base = Path(unpacked_base).resolve()
    if not base.is_dir():
        return 0
    tasks = _collect_unpacked_tasks(base)
    if not tasks:
        return 0

    embedding_backend = env_config.get_embedding_backend().strip().lower()
    if embedding_backend not in ("local", "openai_api", "deterministic"):
        embedding_backend = "none"
    started_at = time.time()
    run_id = _create_ingest_run(started_at, embedding_backend, len(tasks))
    folders = [
        {"version": v, "language": lang, "hbk_count": 1, "tasks_done": 0, "points": 0, "status": "pending"}
        for _, v, _, lang in tasks
    ]
    state_lock = threading.Lock()
    state: dict[str, Any] = {
        "started_at": started_at,
        "embedding_backend": embedding_backend,
        "total_tasks": len(tasks),
        "done_tasks": 0,
        "total_points": 0,
        "current": [{"path": str(base), "version": "", "language": "", "stage": "snapshot"}],
        "current_work": {},
        "current_task_points": 0,
        "current_task_estimated_total": None,
        "completed_files": [],
        "folders": folders,
        "status": "in_progress",
        "run_id": run_id,
        "failed": [],
    }
    interval_sec = float(env_config.get_index_status_interval_sec())
    stop_event = threading.Event()
    writer = threading.Thread(
        target=_status_writer_loop_from_unpacked,
        args=(stop_event, state_lock, state, interval_sec),
        daemon=True,
    )
    writer.start()
    _write_ingest_status(
        started_at=started_at,
        embedding_backend=embedding_backend,
        total_tasks=len(tasks),
        done_tasks=0,
        total_points=0,
        folders=folders,
        status="in_progress",
    )

    total = 0
    try:
        snapshot_dir = get_help_structured_dir()
        manifest = build_structured_api_snapshot(output_dir=Path(snapshot_dir), unpacked_dir=base)
        estimated_total = sum(int(manifest.get(name, 0) or 0) for name in ("objects", "members", "examples", "links"))
        with state_lock:
            state["current"] = [{"path": str(base), "version": "", "language": "", "stage": "index_structured"}]
            state["current_task_estimated_total"] = estimated_total
        _flush_ingest_status(state_lock, state)
        counts = index_structured_help_snapshot(
            Path(snapshot_dir),
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port,
            recreate=True,
            bm25_enabled=bm25,
        )
        total = sum(int(v or 0) for v in counts.values())
        completed_files: list[dict[str, Any]] = []
        for idx, (docs_dir, version, stem, language) in enumerate(tasks):
            file_hash = _read_unpacked_hash(docs_dir)
            if file_hash:
                _update_ingest_cache_entry(f"{version}/{language}/{stem}", file_hash, total)
            completed_files.append(
                {
                    "path": f"{version}/{stem}",
                    "version": version,
                    "language": language,
                    "points": 0,
                    "status": "ok",
                }
            )
            folders[idx]["tasks_done"] = 1
            folders[idx]["status"] = "done"
        with state_lock:
            state["done_tasks"] = len(tasks)
            state["total_points"] = total
            state["completed_files"] = completed_files
            state["status"] = "completed"
            state["current"] = []
            state["current_task_points"] = total
        _write_ingest_status(
            started_at=started_at,
            embedding_backend=embedding_backend,
            total_tasks=len(tasks),
            done_tasks=len(tasks),
            total_points=total,
            folders=folders,
            status="completed",
            finished_at=time.time(),
            completed_files=completed_files,
            failed_tasks=[],
            run_id=state.get("run_id"),
        )
        if verbose:
            _log(
                "[ingest-from-unpacked] Structured help indexed: "
                f"{counts['objects']} objects, {counts['members']} members, "
                f"{counts['examples']} examples, {counts['links']} links"
            )
        return total
    except Exception as e:
        failed_item = {
            "path": str(base),
            "version": "",
            "language": "",
            "error": f"{type(e).__name__}: {e}",
        }
        with state_lock:
            state["status"] = "failed"
            state["current"] = []
            state["failed"] = [failed_item]
            state["current_task_points"] = 0
            state["current_task_estimated_total"] = None
        _write_ingest_status(
            started_at=started_at,
            embedding_backend=embedding_backend,
            total_tasks=len(tasks),
            done_tasks=0,
            total_points=0,
            folders=folders,
            status="failed",
            finished_at=time.time(),
            current=[],
            failed_tasks=[failed_item],
            run_id=state.get("run_id"),
        )
        raise
    finally:
        stop_event.set()
        writer.join(timeout=interval_sec * 2)


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
    from ..help_core.unpack import unpack_hbk

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
