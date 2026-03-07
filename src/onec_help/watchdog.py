"""
Watchdog: monitor new .hbk files, incremental ingest; process pending memory embeddings.
Also monitors STANDARDS_DIR and SNIPPETS_DIR: on change runs load-standards / load-snippets
(so standards and snippets from disk are reloaded automatically like ingest for .hbk).
Uses same discovery as ingest (discover_version_dirs + collect_hbk_tasks) for .hbk.
State for hbk/standards/snippets is stored in the same SQLite DB as ingest (one place).
"""

import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ._utils import safe_error_message
from .ingest import _ingest_cache_path, _sqlite_timeout, collect_hbk_tasks, discover_version_dirs

_WATCHDOG_STATE_TABLE = "watchdog_state"
_STANDARDS_EXT = frozenset({".md"})
_SNIPPETS_EXT = frozenset({".json", ".bsl", ".1c", ".md"})
_INGEST_STDERR_LOG = "ingest_stderr.log"
_INGEST_STDERR_LOG_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB; rotate to .old when exceeded


def _parse_languages() -> list[str] | None:
    raw = os.environ.get("HELP_LANGUAGES", "").strip()
    if not raw or raw.lower() == "all":
        return None
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def _load_watchdog_state(kind: str) -> dict[str, float]:
    """Load state dict (path -> value) for given kind from ingest SQLite DB. kind: hbk, standards, snippets."""
    out: dict[str, float] = {}
    db_path = _ingest_cache_path()
    try:
        parent = Path(db_path).parent
        if parent:
            parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=_sqlite_timeout())
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {_WATCHDOG_STATE_TABLE} "
            "(kind TEXT NOT NULL, path TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (kind, path))"
        )
        for row in conn.execute(
            f"SELECT path, value FROM {_WATCHDOG_STATE_TABLE} WHERE kind = ?", (kind,)
        ):
            out[row[0]] = row[1]
        conn.close()
    except (OSError, sqlite3.Error):
        pass
    return out


def _save_watchdog_state(kind: str, data: dict[str, float]) -> None:
    """Save state dict (path -> value) for given kind into ingest SQLite DB."""
    db_path = _ingest_cache_path()
    try:
        parent = Path(db_path).parent
        if parent:
            parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=_sqlite_timeout())
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {_WATCHDOG_STATE_TABLE} "
            "(kind TEXT NOT NULL, path TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (kind, path))"
        )
        conn.execute(f"DELETE FROM {_WATCHDOG_STATE_TABLE} WHERE kind = ?", (kind,))
        for path, value in data.items():
            conn.execute(
                f"INSERT INTO {_WATCHDOG_STATE_TABLE} (kind, path, value) VALUES (?, ?, ?)",
                (kind, path, float(value)),
            )
        conn.commit()
        conn.close()
    except (OSError, sqlite3.Error):
        pass


def _scan_dir_by_ext(dir_path: Path, exts: frozenset[str]) -> dict[str, float]:
    """Scan directory recursively for files with given extensions; return path -> mtime."""
    out: dict[str, float] = {}
    if not dir_path.exists() or not dir_path.is_dir():
        return out
    for f in dir_path.rglob("*"):
        if f.is_file() and f.suffix.lower() in exts:
            try:
                out[str(f.resolve())] = f.stat().st_mtime
            except OSError:
                pass
    return out


def _scan_dir_by_ext_sizes(dir_path: Path, exts: frozenset[str]) -> dict[str, int]:
    """Scan directory; return path -> size. Stable across restarts (no mtime)."""
    out: dict[str, int] = {}
    if not dir_path.exists() or not dir_path.is_dir():
        return out
    for f in dir_path.rglob("*"):
        if f.is_file() and f.suffix.lower() in exts:
            try:
                out[str(f.resolve())] = f.stat().st_size
            except OSError:
                pass
    return out


def _scan_standards_dir(standards_dir: Path) -> dict[str, float]:
    """Scan STANDARDS_DIR for .md files (same as load-standards / collect_from_folder)."""
    return _scan_dir_by_ext(standards_dir, _STANDARDS_EXT)


def _scan_snippets_dir(snippets_dir: Path) -> dict[str, float]:
    """Scan SNIPPETS_DIR for .json, .bsl, .1c, .md (sources used by load-snippets)."""
    return _scan_dir_by_ext(snippets_dir, _SNIPPETS_EXT)


def _scan_standards_dir_stable(standards_dir: Path) -> dict[str, int]:
    """Scan STANDARDS_DIR; return path -> size. For watchdog state (stable across restarts)."""
    return _scan_dir_by_ext_sizes(standards_dir, _STANDARDS_EXT)


def _scan_snippets_dir_stable(snippets_dir: Path) -> dict[str, int]:
    """Scan SNIPPETS_DIR; return path -> size. For watchdog state (stable across restarts)."""
    return _scan_dir_by_ext_sizes(snippets_dir, _SNIPPETS_EXT)


def _scan_hbk_like_ingest(base: Path | None = None) -> dict[str, float]:
    """Scan .hbk files using same logic as ingest (version dirs + languages filter)."""
    if base is None:
        base_str = os.environ.get("HELP_SOURCE_BASE", "").strip()
        if not base_str:
            return {}
        base = Path(base_str).resolve()
    if not base.exists() or not base.is_dir():
        return {}
    version_dirs = discover_version_dirs(base)
    if not version_dirs:
        return {}
    source_pairs = [(p, v) for p, v in version_dirs]
    languages = _parse_languages()
    tasks = collect_hbk_tasks(source_pairs, languages)
    current: dict[str, float] = {}
    for path, _version, _lang in tasks:
        if path.is_file():
            try:
                current[str(path.resolve())] = path.stat().st_mtime
            except OSError:
                pass
    return current


def run_watchdog(
    help_source_base: Path | None = None,
    poll_interval_sec: int = 600,
    pending_interval_sec: int = 600,
) -> None:
    """
    Infinite loop: (1) check for new/changed .hbk (same discovery as ingest), trigger ingest;
    (2) check STANDARDS_DIR and SNIPPETS_DIR, on change run load-standards / load-snippets;
    (3) process pending memory embeddings periodically.
    """
    if help_source_base is not None:
        base = Path(help_source_base).resolve()
    else:
        base_str = os.environ.get("HELP_SOURCE_BASE", "").strip()
        if not base_str:
            print("[watchdog] HELP_SOURCE_BASE not set", file=sys.stderr, flush=True)
            return
        base = Path(base_str).resolve()
    if not base.exists() or not base.is_dir():
        print(f"[watchdog] HELP_SOURCE_BASE not a directory: {base}", file=sys.stderr, flush=True)
        return
    last_hbk = _load_watchdog_state("hbk")
    standards_dir_str = (os.environ.get("STANDARDS_DIR") or "data/standards").strip()
    standards_dir = Path(standards_dir_str).resolve()
    last_standards = _load_watchdog_state("standards")
    snippets_dir_str = (os.environ.get("SNIPPETS_DIR") or "data/snippets").strip()
    snippets_dir = Path(snippets_dir_str).resolve()
    last_snippets = _load_watchdog_state("snippets")

    last_pending = 0.0
    last_ingest_failed = False
    poll = max(60, poll_interval_sec)
    pending_int = max(60, pending_interval_sec)
    while True:
        try:
            now = time.time()
            current = _scan_hbk_like_ingest(base)
            current_std = (
                _scan_standards_dir_stable(standards_dir) if standards_dir.exists() else {}
            )
            current_snip = _scan_snippets_dir_stable(snippets_dir) if snippets_dir.exists() else {}

            run_ingest = False
            run_standards = False
            run_snippets = False

            # Retry ingest on next poll if previous run failed (recovery after crash/OOM)
            if last_ingest_failed and current:
                print(
                    "[watchdog] retrying ingest after previous failure", file=sys.stderr, flush=True
                )
                run_ingest = True
            if current != last_hbk:
                prev_keys = set(last_hbk)
                curr_keys = set(current)
                added = len(curr_keys - prev_keys)
                removed = len(prev_keys - curr_keys)
                changed = sum(1 for k in curr_keys & prev_keys if last_hbk.get(k) != current.get(k))
                if added or removed or changed:
                    print(
                        f"[watchdog] .hbk changed: +{added} new, -{removed} removed, ~{changed} modified",
                        file=sys.stderr,
                        flush=True,
                    )
                last_hbk = current
                _save_watchdog_state("hbk", current)
                if current:
                    run_ingest = True

            if current_std != last_standards and (last_standards or current_std):
                print(
                    "[watchdog] standards dir changed, running load-standards",
                    file=sys.stderr,
                    flush=True,
                )
                last_standards = current_std
                _save_watchdog_state("standards", {k: float(v) for k, v in current_std.items()})
                run_standards = True

            if current_snip != last_snippets and (last_snippets or current_snip):
                print(
                    "[watchdog] snippets dir changed, running load-snippets",
                    file=sys.stderr,
                    flush=True,
                )
                last_snippets = current_snip
                _save_watchdog_state("snippets", {k: float(v) for k, v in current_snip.items()})
                run_snippets = True

            # Run needed tasks in parallel (async)
            if run_ingest or run_standards or run_snippets:
                tasks = []
                if run_ingest:
                    tasks.append(("ingest", _run_ingest))
                if run_standards:
                    tasks.append(("standards", lambda: _run_load_standards(standards_dir_str)))
                if run_snippets:
                    tasks.append(("snippets", lambda: _run_load_snippets(snippets_dir_str)))
                if len(tasks) == 1:
                    name, fn = tasks[0]
                    if name == "ingest":
                        last_ingest_failed = not fn()
                    else:
                        fn()
                else:
                    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
                        futures = {executor.submit(fn): name for name, fn in tasks}
                        for future in as_completed(futures):
                            name = futures[future]
                            try:
                                result = future.result()
                                if name == "ingest":
                                    last_ingest_failed = not result
                            except Exception as e:
                                print(
                                    f"[watchdog] {name} failed: {safe_error_message(e)}",
                                    file=sys.stderr,
                                    flush=True,
                                )
                                if name == "ingest":
                                    last_ingest_failed = True

            if now - last_pending >= pending_int:
                last_pending = now
                _process_pending_memory()
        except Exception as e:
            print(f"[watchdog] error: {safe_error_message(e)}", file=sys.stderr, flush=True)
        time.sleep(poll)


def _ingest_stderr_log_path() -> Path | None:
    """Path to ingest stderr log file in cache dir, or None if cache path unavailable."""
    try:
        cache_file = _ingest_cache_path()
        parent = Path(cache_file).parent
        if parent and parent != Path("."):
            return parent / _INGEST_STDERR_LOG
    except Exception:
        pass
    return None


def _append_ingest_run_log(returncode: int, stdout: bytes, stderr: bytes) -> None:
    """Append ingest run output to ingest_stderr.log in cache dir; rotate by size."""
    log_path = _ingest_stderr_log_path()
    if not log_path:
        return
    try:
        # Rotate if over size limit before appending
        if log_path.exists():
            try:
                if log_path.stat().st_size >= _INGEST_STDERR_LOG_MAX_BYTES:
                    old_path = log_path.with_suffix(log_path.suffix + ".old")
                    log_path.rename(old_path)
            except OSError:
                pass
        with open(log_path, "ab") as f:
            header = f"\n--- ingest exit {returncode} @ {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} ---\n"
            f.write(header.encode("utf-8", errors="replace"))
            if stderr:
                f.write(stderr)
                if not stderr.endswith(b"\n"):
                    f.write(b"\n")
            if stdout and stdout != stderr:
                f.write(b"[stdout]\n")
                f.write(stdout)
                if not stdout.endswith(b"\n"):
                    f.write(b"\n")
    except OSError:
        pass


def _run_ingest() -> bool:
    """Run full ingest (python -m onec_help ingest). Returns True if exit code was 0, False otherwise."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "onec_help", "ingest"],
            capture_output=True,
            timeout=3600,
            env=os.environ.copy(),
        )
        # Persist full stderr (and stdout) to cache dir for diagnostics (e.g. exit -7, OOM)
        _append_ingest_run_log(
            result.returncode,
            result.stdout or b"",
            result.stderr or b"",
        )
        if result.returncode != 0:
            print(
                f"[watchdog] ingest failed (exit {result.returncode}), will retry on next poll",
                file=sys.stderr,
                flush=True,
            )
            # Log last lines of stderr so OOM/SIGBUS and Python tracebacks are visible
            if result.stderr:
                try:
                    decoded = result.stderr.decode("utf-8", errors="replace").strip()
                    tail = "\n".join(decoded.splitlines()[-25:]) if decoded else ""
                    if tail:
                        print(
                            f"[watchdog] ingest stderr (last 25 lines):\n{tail}",
                            file=sys.stderr,
                            flush=True,
                        )
                except Exception:
                    pass
            return False
        return True
    except subprocess.TimeoutExpired:
        _append_ingest_run_log(
            -1,
            b"",
            b"[watchdog] ingest timeout (3600s)\n",
        )
        print(
            "[watchdog] ingest failed: timeout, will retry on next poll",
            file=sys.stderr,
            flush=True,
        )
        return False
    except OSError as e:
        print(
            f"[watchdog] ingest failed: {safe_error_message(e)}, will retry on next poll",
            file=sys.stderr,
            flush=True,
        )
        return False


def _run_load_standards(standards_dir: str) -> None:
    """Run load-standards from given path (loads from disk only, no GitHub fetch)."""
    try:
        subprocess.run(
            [sys.executable, "-m", "onec_help", "load-standards", standards_dir],
            capture_output=True,
            timeout=1800,
            env=os.environ.copy(),
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        print(
            f"[watchdog] load-standards failed: {safe_error_message(e)}",
            file=sys.stderr,
            flush=True,
        )


def _run_load_snippets(snippets_dir: str) -> None:
    """Run load-snippets from given path (folder with .json / .bsl / .1c / .md)."""
    try:
        subprocess.run(
            [sys.executable, "-m", "onec_help", "load-snippets", snippets_dir],
            capture_output=True,
            timeout=1800,
            env=os.environ.copy(),
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        print(
            f"[watchdog] load-snippets failed: {safe_error_message(e)}",
            file=sys.stderr,
            flush=True,
        )


def _process_pending_memory() -> None:
    """Process pending memory embeddings via MemoryStore."""
    try:
        from .memory import get_memory_store

        n = get_memory_store().process_pending()
        if n > 0:
            print(f"[watchdog] processed {n} pending memory entries", file=sys.stderr, flush=True)
    except Exception as e:
        print(
            f"[watchdog] process_pending failed: {safe_error_message(e)}",
            file=sys.stderr,
            flush=True,
        )
