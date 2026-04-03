"""
Watchdog: monitor new .hbk files, incremental ingest; process pending memory embeddings.
Also monitors STANDARDS_DIR and SNIPPETS_DIR: on change runs load-standards / load-snippets.
State for hbk/standards/snippets is stored in Redis (same as ingest cache).
"""

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..knowledge.kd2_metadata import find_kd2_xml_exports, is_kd2_snapshot_dir, is_kd2_snapshot_root
from ..shared import env_config
from ..shared._utils import safe_error_message
from . import redis_cache
from .ingest import _ingest_cache_path, collect_hbk_tasks, discover_version_dirs

_STANDARDS_EXT = frozenset({".md"})
_SNIPPETS_EXT = frozenset({".json", ".bsl", ".1c", ".md"})
_CONFIG_EXT = frozenset({".xml", ".bsl"})
_KD2_SNAPSHOT_EXT = frozenset({".json", ".jsonl"})
_INGEST_STDERR_LOG = "ingest_stderr.log"
_INGEST_STDERR_LOG_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB; rotate to .old when exceeded


def _get_collection_points(collection_name: str) -> int:
    """Return points count for a Qdrant collection, 0 if missing, -1 on error."""
    try:
        from ..search_store import indexer

        status = indexer.get_index_status(collection=collection_name)
        if "error" in status and not status.get("exists", True):
            return -1  # Qdrant unreachable
        count = status.get("points_count")
        if count is None:
            return -1
        return int(count)
    except Exception:
        return -1


def _parse_languages() -> list[str] | None:
    raw = env_config.get_help_languages()
    if not raw or raw.lower() == "all":
        return None
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def _load_watchdog_state(kind: str) -> dict[str, float]:
    """Load state dict (path -> value) for given kind from Redis. kind: hbk, standards, snippets."""
    try:
        return redis_cache.watchdog_state_get(kind)
    except Exception:
        return {}


def _save_watchdog_state(kind: str, data: dict[str, float]) -> None:
    """Save state dict for kind to Redis."""
    try:
        redis_cache.watchdog_state_set(kind, data)
    except Exception:
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


def _scan_config_dir_stable(config_dir: Path) -> dict[str, int]:
    """Scan exported 1C configuration dir; return path -> size for relevant files.

    Uses a limited set of extensions (.xml, .bsl) to approximate changes while
    keeping the scan reasonably cheap.
    """

    return _scan_dir_by_ext_sizes(config_dir, _CONFIG_EXT)


def _scan_metadata_source_stable(source_path: Path) -> dict[str, int]:
    """Scan metadata source path for watchdog state.

    Supports:
    - KD2 XML file: single file path -> size
    - KD2 working dir: KD2 XML + in-place snapshot files
    - KD2 snapshot dir: manifest.json + *.jsonl files
    - deprecated config export dir: .xml/.bsl files
    """
    if not source_path.exists():
        return {}
    if source_path.is_file():
        try:
            return {str(source_path.resolve()): source_path.stat().st_size}
        except OSError:
            return {}
    if source_path.is_dir():
        kd2_xml = find_kd2_xml_exports(source_path)
        if kd2_xml or is_kd2_snapshot_dir(source_path) or is_kd2_snapshot_root(source_path):
            return _scan_dir_by_ext_sizes(source_path, _KD2_SNAPSHOT_EXT | frozenset({".xml"}))
    return _scan_config_dir_stable(source_path)


def _scan_hbk_like_ingest(base: Path | None = None) -> dict[str, float]:
    """Scan .hbk files using same logic as ingest (version dirs + languages filter)."""
    if base is None:
        base_str = env_config.get_help_source_base()
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
    once: bool = False,
) -> None:
    """
    Check hbk/standards/snippets/config and run ingest/load-standards/load-snippets/metadata-graph-build
    when changed; process pending memory. If once=True, run one cycle and exit; else infinite loop.
    """
    if help_source_base is not None:
        base = Path(help_source_base).resolve()
    else:
        base_str = env_config.get_help_source_base()
        if not base_str:
            print("[watchdog] HELP_SOURCE_BASE not set", file=sys.stderr, flush=True)
            return
        base = Path(base_str).resolve()
    if not base.exists() or not base.is_dir():
        print(f"[watchdog] HELP_SOURCE_BASE not a directory: {base}", file=sys.stderr, flush=True)
        return
    last_hbk = _load_watchdog_state("hbk")
    standards_dir_str = env_config.get_standards_dir()
    standards_dir = Path(standards_dir_str).resolve()
    last_standards = _load_watchdog_state("standards")
    snippets_dir_str = env_config.get_snippets_dir()
    snippets_dir = Path(snippets_dir_str).resolve()
    last_snippets = _load_watchdog_state("snippets")
    config_dir_str = env_config.get_config_source_dir()
    config_dir = Path(config_dir_str).resolve() if config_dir_str else None
    last_metadata = _load_watchdog_state("metadata")

    last_pending = 0.0
    last_ingest_failed = False
    poll = max(30, poll_interval_sec)
    pending_int = max(30, pending_interval_sec)

    # Показать, какие папки отслеживаются (чтобы было видно, что config в списке).
    print(
        "[watchdog] watching: HELP_SOURCE_BASE, STANDARDS_DIR, SNIPPETS_DIR, ONEC_CONFIG_SOURCE_DIR",
        file=sys.stderr,
        flush=True,
    )
    if config_dir and config_dir_str:
        exists = config_dir.exists()
        kind = "file" if config_dir.is_file() else "dir"
        print(
            f"[watchdog] metadata source: {config_dir_str} (exists={exists}, kind={kind})",
            file=sys.stderr,
            flush=True,
        )
    else:
        print(
            "[watchdog] metadata source: not set (ONEC_CONFIG_SOURCE_DIR)",
            file=sys.stderr,
            flush=True,
        )

    def _one_cycle() -> None:
        nonlocal \
            last_hbk, \
            last_standards, \
            last_snippets, \
            last_metadata, \
            last_pending, \
            last_ingest_failed
        now = time.time()
        current = _scan_hbk_like_ingest(base)
        current_std = _scan_standards_dir_stable(standards_dir) if standards_dir.exists() else {}
        current_snip = _scan_snippets_dir_stable(snippets_dir) if snippets_dir.exists() else {}
        current_meta = (
            _scan_metadata_source_stable(config_dir) if config_dir and config_dir.exists() else {}
        )

        run_ingest = False
        run_standards = False
        run_snippets = False
        run_metadata = False
        force_ingest_skip_cache = False
        metadata_ok: bool | None = None

        if last_ingest_failed and current:
            print("[watchdog] retrying ingest after previous failure", file=sys.stderr, flush=True)
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

        if current_meta != last_metadata and (last_metadata or current_meta):
            print(
                f"[watchdog] config dir changed ({len(current_meta)} files), running metadata-graph-build",
                file=sys.stderr,
                flush=True,
            )
            # Состояние в Redis пишем только после успешного прогона (иначе при падении не перезапустим).
            run_metadata = True

        # Force ingest/metadata-build when collections are empty but source files exist.
        # This handles fresh installs, Qdrant volume wipes, and first starts where the
        # watchdog state in Redis already matches the filesystem (no change detected).
        if not run_ingest and current:
            # Check primary structured collection; fall back to legacy onec_help for old installs.
            pts = _get_collection_points("onec_help_api_objects")
            if pts < 0:
                pts = _get_collection_points("onec_help")
            if pts == 0:
                print(
                    "[watchdog] help collection empty — forcing ingest with INGEST_SKIP_CACHE=1",
                    file=sys.stderr,
                    flush=True,
                )
                run_ingest = True
                force_ingest_skip_cache = True

        if not run_metadata and current_meta and config_dir_str:
            pts = _get_collection_points("onec_config_metadata")
            if pts == 0:
                print(
                    "[watchdog] onec_config_metadata collection empty — forcing metadata-graph-build",
                    file=sys.stderr,
                    flush=True,
                )
                run_metadata = True

        if run_ingest or run_standards or run_snippets or run_metadata:
            tasks = []
            if run_ingest:
                _fsc = force_ingest_skip_cache
                tasks.append(("ingest", lambda _fsc=_fsc: _run_ingest(_fsc)))
            if run_standards:
                tasks.append(("standards", lambda: _run_load_standards(standards_dir_str)))
            if run_snippets:
                tasks.append(("snippets", lambda: _run_load_snippets(snippets_dir_str)))
            if run_metadata and config_dir_str:

                def _run_metadata_task() -> bool:
                    print(
                        f"[watchdog] running metadata-graph-build for {config_dir_str}",
                        file=sys.stderr,
                        flush=True,
                    )
                    return _run_build_metadata_graph(config_dir_str)

                tasks.append(("metadata", _run_metadata_task))
            if len(tasks) == 1:
                name, fn = tasks[0]
                if name == "ingest":
                    last_ingest_failed = not fn()
                elif name == "metadata":
                    metadata_ok = fn()
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
                            elif name == "metadata":
                                metadata_ok = result
                        except Exception as e:
                            print(
                                f"[watchdog] {name} failed: {safe_error_message(e)}",
                                file=sys.stderr,
                                flush=True,
                            )
                            if name == "ingest":
                                last_ingest_failed = True
            if metadata_ok is True:
                last_metadata = current_meta
                _save_watchdog_state("metadata", {k: float(v) for k, v in current_meta.items()})

        # Краткий итог цикла (как для справки/стандартов/сниппетов): видно, что папки сканируются.
        n_hbk = len(current)
        n_std = len(current_std)
        n_snip = len(current_snip)
        n_meta = len(current_meta)
        print(
            f"[watchdog] cycle: hbk={n_hbk} standards={n_std} snippets={n_snip} metadata={n_meta}",
            file=sys.stderr,
            flush=True,
        )

        if now - last_pending >= pending_int:
            last_pending = now
            _process_pending_memory()

    # Один цикл сразу (при --once выходим после него).
    try:
        _one_cycle()
    except Exception as e:
        print(f"[watchdog] error: {safe_error_message(e)}", file=sys.stderr, flush=True)
    if once:
        return

    while True:
        try:
            _one_cycle()
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


def _ingest_subprocess_timeout() -> int:
    """Timeout in seconds for one ingest run. 0 = no timeout. From env_config."""
    return env_config.get_watchdog_ingest_timeout()


def _run_ingest(force_skip_cache: bool = False) -> bool:
    """Run full ingest (python -m onec_help ingest). Returns True if exit code was 0, False otherwise.

    force_skip_cache: if True, sets INGEST_SKIP_CACHE=1 in the subprocess env so the ingest
    ignores the SQLite cache and re-processes all files. Used when the Qdrant collection is
    empty but the cache thinks everything is already indexed.
    """
    timeout_sec = _ingest_subprocess_timeout()
    try:
        env = os.environ.copy()
        if force_skip_cache:
            env["INGEST_SKIP_CACHE"] = "1"
        result = subprocess.run(
            [sys.executable, "-m", "onec_help", "ingest"],
            capture_output=True,
            timeout=timeout_sec if timeout_sec > 0 else None,
            env=env,
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
            f"[watchdog] ingest timeout ({timeout_sec}s)\n".encode(),
        )
        print(
            f"[watchdog] ingest failed: timeout ({timeout_sec}s), will retry on next poll",
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
        result = subprocess.run(
            [sys.executable, "-m", "onec_help", "load-standards", standards_dir],
            capture_output=True,
            timeout=1800,
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            tail = (
                (result.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()[-15:]
            )
            print(
                f"[watchdog] load-standards exited {result.returncode}: "
                + ("; ".join(tail) if tail else "no stderr"),
                file=sys.stderr,
                flush=True,
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
        result = subprocess.run(
            [sys.executable, "-m", "onec_help", "load-snippets", snippets_dir],
            capture_output=True,
            timeout=1800,
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            tail = (
                (result.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()[-15:]
            )
            print(
                f"[watchdog] load-snippets exited {result.returncode}: "
                + ("; ".join(tail) if tail else "no stderr"),
                file=sys.stderr,
                flush=True,
            )
    except (subprocess.TimeoutExpired, OSError) as e:
        print(
            f"[watchdog] load-snippets failed: {safe_error_message(e)}",
            file=sys.stderr,
            flush=True,
        )


def _run_build_metadata_graph(config_dir: str) -> bool:
    """Run metadata-graph-build for exported configuration in config_dir. Returns True on success.

    Skips if a fresh load_metadata.running marker exists (another process already running).
    """
    if not config_dir:
        return False
    # Не запускаем повторно если операция уже идёт (маркер свежий — обновлялся heartbeat-ом).
    try:
        import time as _time

        from .ingest import _ingest_cache_path
        marker = Path(_ingest_cache_path()).parent / "load_metadata.running"
        if marker.exists():
            age = _time.time() - marker.stat().st_mtime
            if age < 600:
                print(
                    f"[watchdog] metadata-graph-build already running (marker age {int(age)}s), skipping",
                    file=sys.stderr,
                    flush=True,
                )
                return True  # Считаем это не-ошибкой: процесс уже работает
    except OSError:
        pass
    try:
        result = subprocess.run(
            [sys.executable, "-m", "onec_help", "metadata-graph-build", config_dir],
            capture_output=True,
            timeout=1800,
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            tail = (
                (result.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()[-15:]
            )
            print(
                f"[watchdog] metadata-graph-build exited {result.returncode}: "
                + ("; ".join(tail) if tail else "no stderr"),
                file=sys.stderr,
                flush=True,
            )
            return False
        return True
    except (subprocess.TimeoutExpired, OSError) as e:
        print(
            f"[watchdog] metadata-graph-build failed: {safe_error_message(e)}",
            file=sys.stderr,
            flush=True,
        )
        return False


def _process_pending_memory() -> None:
    """Process pending memory embeddings via MemoryStore."""
    try:
        from ..knowledge.memory import get_memory_store

        n = get_memory_store().process_pending()
        if n > 0:
            print(f"[watchdog] processed {n} pending memory entries", file=sys.stderr, flush=True)
    except Exception as e:
        print(
            f"[watchdog] process_pending failed: {safe_error_message(e)}",
            file=sys.stderr,
            flush=True,
        )
