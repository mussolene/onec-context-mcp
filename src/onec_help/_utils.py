"""Shared utilities for onec_help package."""

import os
import sys
from pathlib import Path


def safe_error_message(e: BaseException, *, production: bool | None = None) -> str:
    """Return error message safe for API/logs: no stack trace or sensitive detail in production."""
    if production is None:
        from . import env_config

        production = env_config.get_production()
    return type(e).__name__ if production else f"{type(e).__name__}: {e}"


def mask_path_for_log(path: str | Path) -> str:
    """Return path safe for logging: filename only to avoid leaking full paths."""
    try:
        p = Path(path)
        return p.name if p.name else str(p)[-50:]  # fallback: last 50 chars
    except Exception:
        return "<path>"


def _is_tty() -> bool:
    """True if stderr is a TTY (for progress overwrite)."""
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


def _rich_console():
    """Return Rich Console for stderr, or None if rich not available."""
    try:
        from rich.console import Console

        return Console(stderr=True, force_terminal=_is_tty())
    except ImportError:
        return None


def progress_line(msg: str, *, overwrite: bool = True) -> None:
    """Print compact progress line. Uses Rich when available and TTY; else stderr."""
    console = _rich_console() if _is_tty() else None
    if console is not None:
        try:
            if overwrite:
                console.print(msg, end="\r")
            else:
                console.print(msg)
            return
        except Exception:
            pass
    pad = msg.ljust(78) if overwrite and _is_tty() else msg
    term = "\r" if (overwrite and _is_tty()) else "\n"
    sys.stderr.write(pad + term)
    sys.stderr.flush()


def progress_done(msg: str) -> None:
    """Print final progress line (newline, no overwrite). Uses Rich when available and TTY."""
    console = _rich_console() if _is_tty() else None
    if console is not None:
        try:
            console.print(msg)
            return
        except Exception:
            pass
    sys.stderr.write(f"{msg}\n")
    sys.stderr.flush()


def format_duration(sec: float) -> str:
    """Human-readable duration: 5m 30s, 2h 15m, 1d 3h. Rounds to nearest unit."""
    if sec < 0 or not (sec == sec):  # NaN
        return "—"
    s = int(round(sec))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        parts = [f"{h}h"]
        if m:
            parts.append(f"{m}m")
        if s and not m:
            parts.append(f"{s}s")
        return " ".join(parts)
    d, h = divmod(h, 24)
    parts = [f"{d}d"]
    if h:
        parts.append(f"{h}h")
    if m and not h:
        parts.append(f"{m}m")
    return " ".join(parts)


def dir_size_on_disk(path: str | Path) -> int:
    """Return actual disk usage in bytes (matches du). Deduplicates hard links via inode."""
    root = Path(path)
    if not root.exists() or not root.is_dir():
        return 0
    seen: set[tuple[int, int]] = set()
    total_blocks = 0
    fallback_bytes = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for f in filenames:
            try:
                fp = Path(dirpath) / f
                st = fp.stat()
                key = (st.st_ino, st.st_dev)
                if key not in seen:
                    seen.add(key)
                    if hasattr(st, "st_blocks") and st.st_blocks:
                        total_blocks += st.st_blocks
                    fallback_bytes += st.st_size
            except OSError:
                pass
    return (total_blocks * 512) if total_blocks > 0 else fallback_bytes


def path_inside_base(path: Path, base: Path) -> bool:
    """Return True if path resolves to a location under base (prevents path traversal)."""
    try:
        resolved = path.resolve()
        base_resolved = base.resolve()
        return resolved.is_relative_to(base_resolved) or resolved == base_resolved
    except (ValueError, OSError):
        return False
