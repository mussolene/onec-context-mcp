"""CLI: unpack, build-docs, build-index, mcp."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def _make_args(**kwargs: Any) -> argparse.Namespace:
    """Build argparse-like namespace for cmd_* calls."""
    return argparse.Namespace(**kwargs)


def _env_path(name: str, default=None):
    v = os.environ.get(name)
    if v:
        return v
    return default


def cmd_unpack(args: argparse.Namespace) -> int:
    """Unpack .hbk with 7z."""
    from .unpack import unpack_hbk

    try:
        unpack_hbk(args.archive, args.output_dir)
        print(f"Unpacked to {args.output_dir}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Run: python -m onec_help unpack-diag <file> -o /tmp/out", file=sys.stderr)
        return 1


def cmd_unpack_diag(args: argparse.Namespace) -> int:
    """Diagnose unpack failure: try each method and print results."""
    from .unpack import unpack_diag

    try:
        unpack_diag(args.archive, args.output_dir or "/tmp/unpack_diag")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_build_docs(args: argparse.Namespace) -> int:
    """Generate Markdown from HTML in project dir."""
    from .html2md import build_docs

    out = args.output or Path(args.project_dir) / "docs_md"
    out = Path(out)
    try:
        created = build_docs(args.project_dir, out)
        print(f"Created {len(created)} .md files in {out}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_build_index(args: argparse.Namespace) -> int:
    """Build Qdrant index from Markdown (or HTML) in directory."""
    from .indexer import build_index

    docs_dir = args.docs_dir or args.directory
    try:
        count = build_index(
            docs_dir=Path(docs_dir),
            qdrant_host=os.environ.get("QDRANT_HOST", "localhost"),
            qdrant_port=int(os.environ.get("QDRANT_PORT", "6333")),
            collection=os.environ.get("QDRANT_COLLECTION", "onec_help"),
            incremental=getattr(args, "incremental", False),
            embedding_batch_size=getattr(args, "embedding_batch_size", None),
            embedding_workers=getattr(args, "embedding_workers", None),
            bm25=not getattr(args, "no_bm25", False),
        )
        print(f"Indexed {count} chunks")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_add_bm25(args: argparse.Namespace) -> int:
    """Add BM25 sparse vectors to existing collection without re-ingest."""
    from .indexer import add_bm25_to_collection

    try:
        count = add_bm25_to_collection(
            qdrant_host=os.environ.get("QDRANT_HOST", "localhost"),
            qdrant_port=int(os.environ.get("QDRANT_PORT", "6333")),
            collection=args.collection or os.environ.get("QDRANT_COLLECTION", "onec_help"),
            batch_size=getattr(args, "batch_size", 200),
            verbose=not getattr(args, "quiet", False),
        )
        print(f"Migrated {count} points with BM25")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _categorize_error(err: str) -> str:
    """Categorize error: unpack|embed|index|build|other."""
    e = (err or "").lower()
    if any(x in e for x in ["unpack", "7z", "unzip", "all unpack methods failed", "no such file"]):
        return "unpack"
    if any(x in e for x in ["embed", "api", "429", "timeout", "connection", "placeholder"]):
        return "embed"
    if any(x in e for x in ["qdrant", "upsert", "collection", "vector"]):
        return "index"
    if any(x in e for x in ["build", "html", "markdown", "parse"]):
        return "build"
    return "other"


def _short_error(err: str, max_len: int = 40) -> str:
    """Compact error message for display."""
    e = (err or "").strip().split("\n")[0]
    if "All unpack methods failed" in e:
        return "unpack failed"
    if "No such file" in e and "unzip" in e:
        return "unzip not found"
    if "7z" in e or "invalid archive" in e:
        return "7z/invalid archive"
    if "timeout" in e.lower():
        return "timeout"
    if "429" in e or "rate limit" in e.lower():
        return "rate limit"
    if len(e) > max_len:
        return e[: max_len - 2] + "…"
    return e


def _render_index_status_compact(
    s, collections, ingest, snippets, spinner, format_duration
) -> tuple[str, int]:
    """Single-line compact output (for piping/scripts)."""
    prefix = f"{spinner} index-status".strip() if spinner else "index-status"
    parts: list[str] = []
    if collections:
        total_pts = sum(
            p
            for c in collections
            if (p := c.get("points_count")) is not None and isinstance(p, int)
        )
        col_strs = [f"{c.get('name', '?')}:{c.get('points_count', '—')} pts" for c in collections]
        parts.extend(col_strs)
        if total_pts > 0 and len(collections) > 1:
            parts.append(f"total:{total_pts}")
        storage_path = os.environ.get("QDRANT_STORAGE_PATH")
        if storage_path and os.path.isdir(storage_path):
            try:
                from ._utils import dir_size_on_disk

                total = dir_size_on_disk(storage_path)
                parts.append(f"DB:{total / (1024 * 1024):.1f}MB")
            except OSError:
                parts.append("DB:—")
    if s.get("exists") and (s.get("versions") or s.get("languages")):
        if s.get("versions"):
            vv = s["versions"][:4]
            parts.append(f"ver:{','.join(vv)}{'…' if len(s.get('versions', [])) > 4 else ''}")
        if s.get("languages"):
            parts.append(f"lang:{','.join(s['languages'])}")
    if ingest:
        backend = ingest.get("embedding_backend") or "none"
        status = ingest.get("status", "")
        elapsed = ingest.get("elapsed_sec")
        if status == "completed":
            total_sec = ingest.get("total_elapsed_sec")
            parts.append(f"Ingest ✓ {format_duration(total_sec)}" if total_sec else "Ingest ✓ done")
        else:
            done_t = ingest.get("done_tasks", 0)
            total_t = ingest.get("total_tasks", 0)
            pts_i = ingest.get("total_points", 0) + (ingest.get("current_task_points") or 0)
            est_pts = ingest.get("estimated_total_points") or 0
            cte = ingest.get("current_task_estimated_total") or 0
            if est_pts > 0:
                ing = [f"Ingest ⟳ {pts_i}/{est_pts} pts"]
            elif cte > 0 and pts_i > 0:
                ing = [f"Ingest ⟳ {pts_i} pts"]
            elif total_t > 0:
                ing = [f"Ingest ⟳ {done_t}/{total_t} tasks"]
            else:
                ing = ["Ingest ⟳ in progress"]
            if elapsed is not None:
                ing.append(f"elapsed {format_duration(elapsed)}")
            eta = ingest.get("eta_sec")
            eta_finish = ingest.get("eta_finish_at")
            if eta is not None and eta >= 0:
                ing.append(f"ETA {format_duration(eta)}")
            if eta_finish is not None:
                import time as _t

                lt = _t.localtime(eta_finish)
                ing.append(f"finish ~{_t.strftime('%H:%M', lt)}")
            parts.append(" ".join(ing))
        parts.append(f"embed: {backend}")
        mw = ingest.get("max_workers")
        if mw is not None:
            parts.append(f"workers:{mw}")
        ctp = ingest.get("current_task_points") or 0
        cte = ingest.get("current_task_estimated_total") or 0
        if ctp > 0:
            parts.append(f"{ctp}/{cte} pts" if cte > 0 else f"{ctp} pts")
        current = ingest.get("current") or []
        if current:
            _sp = {"embedding": 0, "writing": 1, "indexing": 2, "build_docs": 3, "unpack": 4}
            c0 = min(current, key=lambda c: (_sp.get(c.get("stage", ""), 99), c.get("path", "")))
            st = (c0.get("stage") or "").replace("build_docs", "build")
            cur = f"{c0.get('version', '')}/{c0.get('language', '')} {c0.get('path', '')} {st}"
            if len(current) > 1:
                cur += f" +{len(current) - 1}"
            parts.append(f"cur:{cur.strip()}")
        completed = ingest.get("completed_files") or []
        if completed:
            ok_c = sum(1 for f in completed if f.get("status") == "ok")
            skip_c = sum(1 for f in completed if f.get("status") in ("skip", "cached"))
            fail_c = sum(1 for f in completed if f.get("status") == "fail")
            parts.append(f"done:{ok_c}ok/{skip_c}skip/{fail_c}fail")
        folders = ingest.get("folders") or []
        total_err = sum(fo.get("err_count", 0) for fo in folders)
        if total_err > 0:
            failed_tasks = ingest.get("failed_tasks") or []
            if not failed_tasks:
                from .ingest import read_ingest_failed_log

                failed_tasks = read_ingest_failed_log(limit=3)
            err = f"Failed: {total_err}"
            if failed_tasks:
                ft = failed_tasks[0]
                short = (ft.get("path") or "").replace(".hbk", "") or ft.get("error", "")[:20]
                err += f" {short}:{_short_error(ft.get('error', ''))}"
            parts.append(err)
    if snippets:
        fp = snippets.get("files_processed", 0)
        fs = snippets.get("files_skipped", 0)
        il = snippets.get("items_loaded", 0)
        elapsed = snippets.get("total_elapsed_sec")
        snip_str = f"Snippets ✓ {fp} files, {il} items"
        if fs > 0:
            snip_str += f" ({fs} cached)"
            if fp == 0 and il == 0:
                from .snippets_cache import get_cached_items_total

                cached_total = get_cached_items_total()
                if cached_total > 0:
                    snip_str += f" {cached_total} in index"
        if elapsed is not None and elapsed > 0:
            snip_str += f" {format_duration(elapsed)}"
        parts.append(snip_str)
    return f"{prefix} │ {' │ '.join(parts)}\n", 0


def _render_index_status_rich(
    s, collections, ingest, snippets, spinner, format_duration, host, port
) -> tuple[str, int]:
    """Rich multi-line status: collections, operations, current files, elapsed, ETA, errors."""
    lines: list[str] = []
    try:
        cols = os.get_terminal_size().columns
    except OSError:
        cols = 80
    w = min(cols - 4, 76)
    bar_w = max(10, w - 30)
    sep = "─" * (w - 2)

    def line(txt: str) -> None:
        lines.append(txt[: cols - 1] if len(txt) > cols else txt)

    header = " index-status " if not spinner else f" {spinner} index-status "
    line(f"┌{header.center(w - 2, '─')}┐")

    # 1. Collections (all Qdrant)
    line(f"│ Collections (Qdrant) {''.rjust(w - 24)}│")
    if collections:
        total_pts = sum(
            p
            for c in collections
            if (p := c.get("points_count")) is not None and isinstance(p, int)
        )
        for c in collections:
            n = c.get("name", "?")
            pts = c.get("points_count", "—")
            vecs = c.get("indexed_vectors_count", pts)
            segs = c.get("segments_count", "—")
            line(f"│   {n}: {pts} pts, {vecs} vecs, {segs} segs".ljust(w - 1) + "│")
        if total_pts > 0:
            line(f"│   total: {total_pts} pts".ljust(w - 1) + "│")
        storage_path = os.environ.get("QDRANT_STORAGE_PATH")
        if storage_path:
            if os.path.isdir(storage_path):
                try:
                    from ._utils import dir_size_on_disk

                    sz = dir_size_on_disk(storage_path)
                    line(f"│   DB: {sz / (1024 * 1024):.1f} MB".ljust(w - 1) + "│")
                except OSError:
                    line("│   DB: —".ljust(w - 1) + "│")
            else:
                line("│   DB: —".ljust(w - 1) + "│")
        if s.get("versions"):
            vv = ", ".join(s["versions"][:5])
            if len(s.get("versions", [])) > 5:
                vv += "…"
            line(f"│   versions: {vv}".ljust(w - 1) + "│")
        if s.get("languages"):
            line(f"│   lang: {', '.join(s['languages'])}".ljust(w - 1) + "│")
    else:
        line("│   (no collections)".ljust(w - 1) + "│")
    line(f"├{sep}┤")

    # 2. Operations + 3. Current files + 4. Elapsed + 5. ETA
    if ingest:
        backend = ingest.get("embedding_backend") or "none"
        status = ingest.get("status", "")
        done = ingest.get("done_tasks", 0)
        total = ingest.get("total_tasks", 0)
        pts = ingest.get("total_points", 0)
        speed = ingest.get("embedding_speed_pts_per_sec")
        current_task_pts = ingest.get("current_task_points", 0) or 0
        current_list = ingest.get("current") or []

        max_workers = ingest.get("max_workers")
        embedding_workers = ingest.get("embedding_workers")
        workers_str = ""
        if max_workers is not None:
            workers_str = f"workers: {max_workers}"
            if embedding_workers is not None:
                workers_str += f", embed_w: {embedding_workers}"

        line(f"│ Operations {''.rjust(w - 14)}│")
        if status == "completed":
            line(f"│   ✓ done │ embed: {backend}".ljust(w - 1) + "│")
            total_sec = ingest.get("total_elapsed_sec")
            pts = ingest.get("total_points", 0)
            fail_cnt = ingest.get("failed_count", 0) or len(ingest.get("failed_tasks") or [])
            last_run_str = f"Last run: {format_duration(total_sec)}" if total_sec else "Last run"
            last_run_str += f", {pts} pts"
            if fail_cnt > 0:
                last_run_str += f", {fail_cnt} failed"
            if workers_str:
                last_run_str += f" │ {workers_str}"
            line(f"│   {last_run_str}".ljust(w - 1) + "│")
        else:
            # Dynamic stages — embedding/writing first (main work), then preparing
            _stage_order = ("embedding", "writing", "indexing", "build_docs", "unpack")
            by_stage: dict[str, int] = {}
            for c in current_list:
                st = c.get("stage") or "?"
                by_stage[st] = by_stage.get(st, 0) + 1

            def _stage_sort_key(item: tuple[str, int]) -> tuple[int, str]:
                stage_name, _ = item
                display = stage_name.replace("build_docs", "build")
                try:
                    return (_stage_order.index(stage_name), display)
                except ValueError:
                    return (99, display)

            parts = [
                f"{k.replace('build_docs', 'build')} ({v})"
                for k, v in sorted(by_stage.items(), key=_stage_sort_key)
            ]
            stages_str = ", ".join(parts) if parts else "in progress"
            line_str = f"│   {stages_str} │ embed: {backend}"
            if workers_str:
                line_str += f" │ {workers_str}"
            line(f"{line_str}".ljust(w - 1) + "│")

        # Progress bar: use pts when we have estimate; else tasks
        effective_pts = pts + current_task_pts
        current_task_est = ingest.get("current_task_estimated_total") or 0
        est_total_pts = ingest.get("estimated_total_points") or 0
        if est_total_pts > 0:
            # Overall pts estimate (from completed tasks)
            done_pts, total_pts = effective_pts, est_total_pts
            pct = min(100, int(100 * done_pts / total_pts))
            filled = min(bar_w, int(bar_w * done_pts / total_pts))
            bar = "█" * filled + "░" * (bar_w - filled)
            line(f"│   [{bar}] {done_pts}/{total_pts} pts ({pct}%)".ljust(w - 1) + "│")
        elif current_task_est > 0:
            # First file: pts for current file only (no completed tasks yet)
            done_pts = current_task_pts
            total_pts = current_task_est
            pct = min(100, int(100 * done_pts / total_pts)) if total_pts else 0
            filled = min(bar_w, int(bar_w * done_pts / total_pts)) if total_pts else 0
            bar = "█" * filled + "░" * (bar_w - filled)
            line(f"│   [{bar}] {done_pts}/{total_pts} pts ({pct}%)".ljust(w - 1) + "│")
        elif total > 0:
            pct = int(100 * done / total)
            filled = int(bar_w * done / total)
            bar = "█" * filled + "░" * (bar_w - filled)
            line(f"│   [{bar}] {done}/{total} tasks ({pct}%)".ljust(w - 1) + "│")
        if effective_pts > 0:
            pts_str = f"{effective_pts} pts indexed"
            if speed:
                pts_str += f", {speed} pts/s"
            line(f"│   {pts_str}".ljust(w - 1) + "│")

        elapsed = ingest.get("elapsed_sec")
        if elapsed is not None:
            line(f"│   elapsed: {format_duration(elapsed)}".ljust(w - 1) + "│")
        eta = ingest.get("eta_sec")
        eta_finish = ingest.get("eta_finish_at")
        if eta is not None and eta >= 0:
            line(f"│   ETA: {format_duration(eta)}".ljust(w - 1) + "│")
        if eta_finish is not None:
            import time as _t

            finish_str = _t.strftime("%H:%M", _t.localtime(eta_finish))
            line(f"│   ≈ finish: ~{finish_str}".ljust(w - 1) + "│")

        # Summary: tasks, done, ok/skip/fail, workers, pts
        completed = ingest.get("completed_files") or []
        ok_c = sum(1 for f in completed if f.get("status") == "ok")
        skip_c = sum(1 for f in completed if f.get("status") in ("skip", "cached"))
        fail_c = sum(1 for f in completed if f.get("status") == "fail")
        summary_parts = [f"{total} tasks", f"{done} done"]
        if ok_c or skip_c or fail_c:
            summary_parts.append(f"{ok_c} ok, {skip_c} skip, {fail_c} fail")
        if effective_pts > 0:
            summary_parts.append(f"{effective_pts} pts")
        if workers_str:
            summary_parts.append(workers_str)
        line(f"│   Summary: {' │ '.join(summary_parts)}".ljust(w - 1) + "│")

        # Errors first when present (priority over file list)
        folders = ingest.get("folders") or []
        total_err = sum(fo.get("err_count", 0) for fo in folders)
        failed_tasks = ingest.get("failed_tasks") or []
        if not failed_tasks and total_err > 0:
            from .ingest import read_ingest_failed_log, read_last_ingest_failed

            failed_tasks = read_last_ingest_failed(limit=20) or read_ingest_failed_log(limit=20)
        if failed_tasks:
            total_err = total_err or len(failed_tasks)
            line(f"├{sep}┤")
            line(
                f"│ Failed ({total_err})  ver = метка каталога (HELP_SOURCE_BASE или path:ver)".ljust(
                    w - 1
                )
                + "│"
            )
            for ft in failed_tasks[:10]:
                path_raw = ft.get("path") or "?"
                path = path_raw.replace(".hbk", "")
                err = (ft.get("error") or "").strip()
                ver = ft.get("version", "") or "?"
                lang = ft.get("language", "") or "?"
                if len(path) > w - 10:
                    path = "…" + path[-(w - 11) :]
                line(f"│   {ver}/{lang} {path}".ljust(w - 1) + "│")
                if err:
                    err_short = err[: (w - 8)] + ("…" if len(err) > w - 8 else "")
                    line(f"│     → {err_short}".ljust(w - 1) + "│")
            if len(failed_tasks) > 10:
                line(f"│   ... +{len(failed_tasks) - 10} more".ljust(w - 1) + "│")
        elif completed:
            line(f"├{sep}┤")
            line(f"│ Files (per file) {''.rjust(w - 18)}│")
            for f in completed[-12:]:
                path_s = (f.get("path") or "?").replace(".hbk", "")
                ver = f.get("version", "")
                lang = f.get("language", "")
                pts = f.get("points", 0)
                st = f.get("status", "?")
                line(f"│   {ver}/{lang} {path_s} {pts} pts [{st}]".ljust(w - 1) + "│")
            if len(completed) > 12:
                line(f"│   ... +{len(completed) - 12} more".ljust(w - 1) + "│")

        current = ingest.get("current") or []
        if current:
            line(f"├{sep}┤")
            line(f"│ Current files {''.rjust(w - 16)}│")
            _stage_priority = {
                "embedding": 0,
                "writing": 1,
                "indexing": 2,
                "build_docs": 3,
                "unpack": 4,
            }
            current_sorted = sorted(
                current,
                key=lambda c: (_stage_priority.get(c.get("stage", ""), 99), c.get("path", "")),
            )
            for i, c in enumerate(current_sorted[:5], 1):
                v = c.get("version", "")
                lang = c.get("language", "")
                path = (c.get("path") or "").replace(".hbk", "")
                stage = (c.get("stage") or "").replace("build_docs", "build")
                pts_info = ""
                if c.get("points") is not None and c.get("estimated_total") is not None:
                    pts_info = f" {c['points']}/{c['estimated_total']} pts"
                elif c.get("points") is not None:
                    pts_info = f" {c['points']} pts"
                line(f"│   [W{i}] {v}/{lang} {path} [{stage}]{pts_info}".ljust(w - 1) + "│")
            if len(current) > 5:
                line(f"│   ... +{len(current) - 5} more".ljust(w - 1) + "│")
    else:
        line(f"│ No ingest in progress {''.rjust(w - 24)}│")

    if snippets:
        line(f"├{sep}┤")
        fp = snippets.get("files_processed", 0)
        fs = snippets.get("files_skipped", 0)
        il = snippets.get("items_loaded", 0)
        elapsed = snippets.get("total_elapsed_sec")
        snip_line = f"Snippets: {fp} files loaded, {il} items"
        if fs > 0:
            snip_line += f" ({fs} cached)"
            if fp == 0 and il == 0:
                from .snippets_cache import get_cached_items_total

                cached_total = get_cached_items_total()
                if cached_total > 0:
                    snip_line += f" — {cached_total} in index"
        if elapsed is not None and elapsed > 0:
            snip_line += f" in {format_duration(elapsed)}"
        line(f"│ {snip_line}".ljust(w - 1) + "│")

    line(f"└{sep}┘")
    return "\n".join(lines) + "\n", 0


def _render_index_status(*, spinner: str = "", compact: bool = False) -> tuple[str, int]:
    """Build index status. compact=False: rich multi-line; compact=True: single line.
    Returns (output_string, exit_code)."""
    from ._utils import format_duration
    from .indexer import get_all_collections_status, get_index_status
    from .ingest import read_ingest_status, read_last_ingest_run
    from .snippets_cache import read_last_snippets_run

    host = os.environ.get("QDRANT_HOST", "localhost")
    port = int(os.environ.get("QDRANT_PORT", "6333"))
    collection = os.environ.get("QDRANT_COLLECTION", "onec_help")
    s = get_index_status(qdrant_host=host, qdrant_port=port, collection=collection)
    if s.get("error"):
        return f"Error: {s['error']}\n", 1
    ingest = read_ingest_status()
    if not ingest:
        last_run = read_last_ingest_run()
        if last_run:
            from .ingest import (
                read_ingest_cache_entries,
                read_ingest_failed_log,
                read_last_ingest_failed,
            )

            failed_count = last_run.get("failed_count", 0)
            failed_tasks = (
                read_last_ingest_failed(limit=20) or read_ingest_failed_log(limit=20)
                if failed_count > 0
                else []
            )
            if failed_count > 0 and not failed_tasks:
                failed_tasks = [
                    {
                        "path": "?",
                        "error": "Details not stored (re-run ingest to capture errors)",
                    }
                ]
            ingest = {
                "status": "completed",
                "embedding_backend": last_run.get("embedding_backend", "none"),
                "total_points": last_run.get("total_points", 0),
                "done_tasks": last_run.get("done_tasks", 0),
                "total_tasks": last_run.get("total_tasks", 0),
                "total_elapsed_sec": last_run.get("total_elapsed_sec"),
                "failed_count": failed_count,
                "current": [],
                "folders": [],
                "failed_tasks": failed_tasks,
                "completed_files": read_ingest_cache_entries(limit=50),
            }
    collections = get_all_collections_status(qdrant_host=host, qdrant_port=port)
    if not collections and s.get("exists"):
        collections = [
            {
                "name": s.get("collection", collection),
                "points_count": s.get("points_count"),
                "indexed_vectors_count": s.get("points_count"),
                "segments_count": None,
            }
        ]
    if not collections and not ingest:
        return "Index does not exist. Run: python -m onec_help ingest\n", 0

    snippets = read_last_snippets_run()

    # --- Compact (single line) ---
    if compact:
        return _render_index_status_compact(
            s, collections, ingest, snippets, spinner, format_duration
        )

    # --- Rich multi-line ---
    return _render_index_status_rich(
        s, collections, ingest, snippets, spinner, format_duration, host, port
    )


def cmd_index_status(args: argparse.Namespace) -> int:
    """Print index status: rich multi-line or compact. Watch mode: live refresh."""
    import time

    from ._utils import progress_done, progress_line

    watch = getattr(args, "watch", False)
    interval = float(getattr(args, "interval", 2))
    compact = getattr(args, "compact", False)
    tick = [0]

    def _print_update() -> int:
        spinner = ("◐", "◓", "◑", "◒")[tick[0] % 4] if watch else ""
        out, code = _render_index_status(spinner=spinner, compact=compact)
        if code != 0:
            print(out, file=sys.stderr)
            return code
        if compact:
            line = out.rstrip("\n")
            if watch:
                progress_line(line)
            else:
                print(line)
        else:
            if watch:
                sys.stdout.write("\033[H\033[J")  # clear screen, cursor home
                try:
                    intv = int(interval)
                    sys.stdout.write(f"\033[1;1H\033[K⟳ refresh {intv}s  Ctrl+C to stop\n")
                except (ValueError, OSError):
                    pass
            print(out, end="")
            sys.stdout.flush()
        tick[0] += 1
        return 0

    if not watch:
        tick[0] = 0
        return _print_update()

    try:
        while True:
            _print_update()
            time.sleep(interval)
    except KeyboardInterrupt:
        progress_done("")
        return 0


def cmd_unpack_dir(args: argparse.Namespace) -> int:
    """Unpack all .hbk from source dir(s) into output_dir (no indexing)."""
    import os
    from pathlib import Path

    from .ingest import (
        discover_version_dirs,
        parse_languages_env,
        parse_source_dirs_env,
        run_unpack_only,
    )

    sources: list[tuple[str, str]] = []
    if getattr(args, "sources", None):
        for s in args.sources:
            s = s.strip()
            if ":" in s:
                p, v = s.split(":", 1)
                sources.append((p.strip(), v.strip()))
            else:
                sources.append((s, Path(s).name or "default"))
    if not sources:
        base = os.environ.get("HELP_SOURCE_BASE") or os.environ.get("HELP_SOURCES_DIR")
        if base and base.strip():
            discovered = discover_version_dirs(base.strip())
            sources = [(str(p), v) for p, v in discovered]
        if not sources:
            sources = parse_source_dirs_env(os.environ.get("HELP_SOURCE_DIRS"))
    if not sources:
        # Single directory as version
        src = getattr(args, "source_dir", None) or ""
        if src and Path(src).is_dir():
            sources = [(src, Path(src).name or "default")]
    if not sources:
        print(
            "Error: no source directories. Set HELP_SOURCE_BASE or use --sources or pass source_dir",
            file=sys.stderr,
        )
        return 1
    raw_lang = getattr(args, "languages", None)
    languages = parse_languages_env(
        raw_lang if raw_lang is not None and raw_lang.strip() else os.environ.get("HELP_LANGUAGES")
    )
    out = Path(args.output_dir or "./unpacked").resolve()
    try:
        n = run_unpack_only(
            source_dirs_with_versions=sources,
            output_dir=out,
            languages=languages,
            max_workers=getattr(args, "workers", 4),
            verbose=not getattr(args, "quiet", False),
        )
        print(f"Unpacked {n} archive(s) to {out}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_unpack_sync(args: argparse.Namespace) -> int:
    """Unpack .hbk to data/unpacked with .hbk_info.json, skip unchanged by hash."""
    import os
    from pathlib import Path

    from .ingest import (
        discover_version_dirs,
        parse_languages_env,
        parse_source_dirs_env,
        run_unpack_sync,
    )

    sources: list[tuple[str, str]] = []
    if getattr(args, "sources", None):
        for s in args.sources:
            s = s.strip()
            if ":" in s:
                p, v = s.split(":", 1)
                sources.append((p.strip(), v.strip()))
            else:
                sources.append((s, Path(s).name or "default"))
    if not sources:
        base = os.environ.get("HELP_SOURCE_BASE") or os.environ.get("HELP_SOURCES_DIR")
        if base and base.strip():
            discovered = discover_version_dirs(base.strip())
            sources = [(str(p), v) for p, v in discovered]
        if not sources:
            sources = parse_source_dirs_env(os.environ.get("HELP_SOURCE_DIRS"))
    if not sources:
        src = getattr(args, "source_dir", None) or ""
        if src and Path(src).is_dir():
            discovered = discover_version_dirs(src)
            sources = (
                [(str(p), v) for p, v in discovered]
                if discovered
                else [(src, Path(src).name or "default")]
            )
    if not sources:
        print(
            "Error: no source directories. Set HELP_SOURCE_BASE or use --sources",
            file=sys.stderr,
        )
        return 1
    raw_lang = getattr(args, "languages", None)
    languages = parse_languages_env(
        raw_lang if raw_lang is not None and raw_lang.strip() else os.environ.get("HELP_LANGUAGES")
    )
    out = getattr(args, "output_dir", None) or os.environ.get("DATA_UNPACKED_DIR", "data/unpacked")
    out = Path(out).resolve()
    try:
        n = run_unpack_sync(
            source_dirs_with_versions=sources,
            output_dir=out,
            languages=languages,
            max_workers=getattr(args, "workers", 4),
            verbose=not getattr(args, "quiet", False),
        )
        print(f"Unpacked {n} archive(s) to {out}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_read_hbk_container(args: argparse.Namespace) -> int:
    """Read HBK binary container (source: alkoleft/hbk-viewer); list entities or extract to dir."""
    from pathlib import Path

    from .hbk_container import (
        extract_filestorage_bytes,
        extract_packblock_toc_bytes,
        read_container_from_path,
    )

    hbk_path = Path(getattr(args, "file", None) or "").resolve()
    if not hbk_path.is_file():
        print(f"Error: not a file: {hbk_path}", file=sys.stderr)
        return 1
    try:
        entities = read_container_from_path(hbk_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: invalid HBK container: {e}", file=sys.stderr)
        return 1

    out_dir = getattr(args, "out_dir", None)
    toc_json = getattr(args, "toc_json", None)
    if not out_dir and not toc_json:
        print("Entities:", ", ".join(sorted(entities.keys())))
        for name, body in sorted(entities.items()):
            print(f"  {name}: {len(body)} bytes")
        return 0

    if toc_json:
        toc_bytes = extract_packblock_toc_bytes(entities)
        if toc_bytes:
            Path(toc_json).parent.mkdir(parents=True, exist_ok=True)
            Path(toc_json).write_bytes(toc_bytes)
            print(f"TOC written to {toc_json} ({len(toc_bytes)} bytes)")
        else:
            print("No PackBlock TOC in container", file=sys.stderr)

    if out_dir:
        out_path = Path(out_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)
        fs = extract_filestorage_bytes(entities)
        if fs:
            import io
            import zipfile

            z = zipfile.ZipFile(io.BytesIO(fs), "r")
            z.extractall(out_path)
            print(f"FileStorage extracted to {out_path}")
        else:
            print("No FileStorage in container", file=sys.stderr)
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest .hbk from multiple read-only source dirs: unpack to temp, build docs, index, cleanup."""
    from pathlib import Path

    from .ingest import (
        discover_version_dirs,
        parse_languages_env,
        parse_source_dirs_env,
        run_ingest,
    )

    sources: list[tuple[str, str]] = []
    if getattr(args, "sources", None):
        for s in args.sources:
            s = s.strip()
            if ":" in s:
                p, v = s.split(":", 1)
                sources.append((p.strip(), v.strip()))
            else:
                sources.append((s, Path(s).name or "default"))
    if not sources and getattr(args, "sources_file", None):
        # sources_file path is from CLI args; CLI is intended for trusted operator use only
        for line in Path(args.sources_file).read_text(encoding="utf-8").strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                p, v = line.split(":", 1)
                sources.append((p.strip(), v.strip()))
            else:
                sources.append((line, Path(line).name or "default"))
    if not sources:
        base = os.environ.get("HELP_SOURCE_BASE") or os.environ.get("HELP_SOURCES_DIR")
        if base and base.strip():
            discovered = discover_version_dirs(base.strip())
            sources = [(str(p), v) for p, v in discovered]
        if not sources:
            sources = parse_source_dirs_env(os.environ.get("HELP_SOURCE_DIRS"))
    if not sources:
        print(
            "Error: no source directories. Set HELP_SOURCE_BASE (path to folder with version subdirs) or use --sources / --sources-file",
            file=sys.stderr,
        )
        return 1
    raw_lang = getattr(args, "languages", None)
    if raw_lang is not None:
        languages = parse_languages_env(raw_lang if raw_lang.strip() else "all")
    else:
        languages = parse_languages_env(os.environ.get("HELP_LANGUAGES"))
    if getattr(args, "no_cache", False):
        os.environ["INGEST_SKIP_CACHE"] = "1"
    try:
        if os.environ.get("INGEST_USE_UNPACKED", "").strip() == "1" and not getattr(
            args, "dry_run", False
        ):
            from .ingest import run_ingest_from_unpacked, run_unpack_sync

            unpacked_dir = os.environ.get("DATA_UNPACKED_DIR", "data/unpacked")
            unpacked_base = Path(unpacked_dir).resolve()
            unpacked_base.mkdir(parents=True, exist_ok=True)
            run_unpack_sync(
                source_dirs_with_versions=sources,
                output_dir=unpacked_base,
                languages=languages,
                max_workers=getattr(args, "workers", None) or 4,
                verbose=not getattr(args, "quiet", False),
            )
            n = run_ingest_from_unpacked(
                unpacked_base=unpacked_base,
                qdrant_host=os.environ.get("QDRANT_HOST", "localhost"),
                qdrant_port=int(os.environ.get("QDRANT_PORT", "6333")),
                collection=os.environ.get("QDRANT_COLLECTION", "onec_help"),
                incremental=not getattr(args, "recreate", False),
                verbose=not getattr(args, "quiet", False),
                embedding_batch_size=getattr(args, "embedding_batch_size", None),
                embedding_workers=getattr(args, "embedding_workers", None),
            )
        else:
            _default_temp = os.path.join(tempfile.gettempdir(), "help_ingest")
            n = run_ingest(
                source_dirs_with_versions=sources,
                languages=languages,
                temp_base=args.temp_base or os.environ.get("HELP_INGEST_TEMP") or _default_temp,
                qdrant_host=os.environ.get("QDRANT_HOST", "localhost"),
                qdrant_port=int(os.environ.get("QDRANT_PORT", "6333")),
                collection=os.environ.get("QDRANT_COLLECTION", "onec_help"),
                incremental=not getattr(args, "recreate", False),
                max_workers=getattr(args, "workers", None),
                max_tasks=getattr(args, "max_tasks", None),
                verbose=not getattr(args, "quiet", False),
                dry_run=getattr(args, "dry_run", False),
                index_batch_size=getattr(args, "index_batch_size", 500),
                embedding_batch_size=getattr(args, "embedding_batch_size", None),
                embedding_workers=getattr(args, "embedding_workers", None),
            )
        print(f"Ingested and indexed {n} chunks")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_ingest_from_unpacked(args: argparse.Namespace) -> int:
    """Index help from unpacked dir (data/unpacked structure: version/stem)."""
    from pathlib import Path

    from .ingest import run_ingest_from_unpacked

    unpacked_dir = getattr(args, "dir", None) or os.environ.get(
        "DATA_UNPACKED_DIR", "data/unpacked"
    )
    base = Path(unpacked_dir).resolve()
    if not base.is_dir():
        print(f"Error: unpacked dir not found: {base}", file=sys.stderr)
        return 1
    bm25_val = None
    if getattr(args, "bm25", False):
        bm25_val = True
    elif getattr(args, "no_bm25", False):
        bm25_val = False
    try:
        n = run_ingest_from_unpacked(
            unpacked_base=base,
            qdrant_host=os.environ.get("QDRANT_HOST", "localhost"),
            qdrant_port=int(os.environ.get("QDRANT_PORT", "6333")),
            collection=os.environ.get("QDRANT_COLLECTION", "onec_help"),
            incremental=not getattr(args, "recreate", False),
            verbose=not getattr(args, "quiet", False),
            embedding_batch_size=getattr(args, "embedding_batch_size", None),
            embedding_workers=getattr(args, "embedding_workers", None),
            bm25=bm25_val,
        )
        print(f"Ingested from unpacked: {n} points")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _build_snippets_sources(args: argparse.Namespace) -> list[tuple[Path, str]]:
    """Build list of (path, type) for snippets sources. type: 'json' | 'folder'."""
    path_arg = getattr(args, "snippets_file", None) or os.environ.get("SNIPPETS_JSON_PATH", "")
    snippets_dir = os.environ.get("SNIPPETS_DIR", "")
    from_project = getattr(args, "from_project", None)
    sources: list[tuple[Path, str]] = []

    if from_project:
        d = Path(from_project.strip()).resolve()
        if d.exists() and d.is_dir():
            sources.append((d, "folder"))
    elif path_arg and path_arg.strip():
        p = Path(path_arg.strip()).resolve()
        if not p.exists():
            return []
        if p.is_dir():
            for j in sorted(p.glob("*.json")):
                sources.append((j, "json"))
            sources.append((p, "folder"))
        else:
            sources.append((p, "json"))
    elif snippets_dir:
        d = Path(snippets_dir).resolve()
        if d.exists():
            for j in sorted(d.glob("*.json")):
                sources.append((j, "json"))
            sources.append((d, "folder"))
    return sources


def _load_json_items(p: Path) -> list[dict]:
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("JSON must be an array of {title, description, code_snippet}")
    return data


def _load_folder_items(d: Path, per_func: bool = False) -> list[dict]:
    from .snippets_loader import collect_from_folder

    return collect_from_folder(d, per_function=per_func)


def cmd_load_snippets(args: argparse.Namespace) -> int:
    """Load curated snippets from JSON and/or folder into onec_help_memory (domain=snippets).
    Uses cache: only loads sources that changed. --no-cache or SNIPPETS_SKIP_CACHE=1 to force reload."""
    import time

    from ._utils import progress_done, progress_line
    from .memory import get_memory_store
    from .snippets_cache import (
        _file_signature,
        _folder_signature,
        get_snippets_sources_to_load,
        record_snippets_run,
        update_snippets_cache,
    )

    skip_cache = getattr(args, "no_cache", False) or (
        os.environ.get("SNIPPETS_SKIP_CACHE") or ""
    ).strip().lower() in ("1", "true", "yes")

    try:
        sources = _build_snippets_sources(args)
        if not sources:
            path_arg = getattr(args, "snippets_file", None) or os.environ.get(
                "SNIPPETS_JSON_PATH", ""
            )
            if path_arg:
                p = Path(path_arg.strip())
                if not p.exists():
                    print(f"Error: path not found: {p}", file=sys.stderr)
                    return 1
            elif not os.environ.get("SNIPPETS_DIR") and not getattr(args, "from_project", None):
                print(
                    "No source: set SNIPPETS_DIR, pass path, or use --from-project.",
                    file=sys.stderr,
                )
                return 0
            print("SNIPPETS_DIR not found or empty.", file=sys.stderr)
            return 0

        to_load = sources if skip_cache else get_snippets_sources_to_load(sources)[0]
        files_skipped = len(sources) - len(to_load)

        started_at = time.time()

        if not to_load:
            print(
                f"load-snippets │ All {len(sources)} source(s) unchanged (cache); nothing to do.",
                file=sys.stderr,
            )
            record_snippets_run(0, len(sources), 0, started_at)
            return 0

        if files_skipped > 0:
            print(
                f"load-snippets │ Cache hit: skip {files_skipped} unchanged; loading {len(to_load)}",
                file=sys.stderr,
            )

        items: list[dict] = []
        folder_ext = frozenset({".bsl", ".1c", ".md"})
        per_func = getattr(args, "per_function", False)

        for path, stype in to_load:
            path = Path(path).resolve()
            src_items = (
                _load_json_items(path)
                if stype == "json"
                else _load_folder_items(path, per_func=per_func)
            )
            items.extend(src_items)
            # Update cache per source
            key = str(path)
            sig = _file_signature(path) if stype == "json" else _folder_signature(path, folder_ext)
            if sig:
                update_snippets_cache(key, sig, len(src_items))

        if not items:
            print("No snippets to load.", file=sys.stderr)
            return 0

        by_domain: dict[str, list[dict]] = {"snippets": [], "community_help": []}
        for it in items:
            t = (it.get("type") or "snippet").lower()
            domain = "community_help" if t == "reference" else "snippets"
            by_domain[domain].append(it)

        def _progress(loaded: int, tot: int, skipped: int) -> None:
            progress_line(
                f"load-snippets │ {loaded + skipped}/{tot} │ {loaded} loaded │ {skipped} skip"
            )

        store = get_memory_store()
        total_loaded = 0
        domain_counts: list[str] = []
        for domain, domain_items in by_domain.items():
            if not domain_items:
                continue
            n = store.upsert_curated_snippets(
                domain_items, progress_callback=_progress, domain=domain
            )
            total_loaded += n
            domain_counts.append(f"{domain}={n}")

        record_snippets_run(len(to_load), files_skipped, total_loaded, started_at)
        progress_done(
            f"load-snippets │ ✓ {total_loaded} loaded ({', '.join(domain_counts)}) → onec_help_memory"
        )
        return 0
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _parse_standards_repo_spec(spec: str, default_branch: str = "master") -> tuple[str, str]:
    """Parse 'owner/repo' or 'owner/repo:branch'. Returns (repo_url, branch)."""
    spec = spec.strip()
    if ":" in spec:
        repo, branch = spec.rsplit(":", 1)
        return repo.strip(), (branch.strip() or default_branch)
    return spec, default_branch


_DEFAULT_STANDARDS_REPOS = "1C-Company/v8-code-style:master,zeegin/v8std:main"


def cmd_load_standards(args: argparse.Namespace) -> int:
    """Load standards (markdown) into onec_help_memory (domain=standards).
    Sources: path arg, STANDARDS_DIR, STANDARDS_REPOS (comma-separated, loaded jointly),
    or STANDARDS_REPO (single, legacy). By default loads both v8-code-style and v8std."""
    path_arg = getattr(args, "standards_path", None) or os.environ.get("STANDARDS_DIR", "")
    path_arg = (path_arg or "").strip()
    standards_repos = (os.environ.get("STANDARDS_REPOS") or "").strip()
    standards_repo = (os.environ.get("STANDARDS_REPO") or "").strip()
    standards_subpath = os.environ.get("STANDARDS_SUBPATH", "docs").strip() or "docs"
    default_branch = os.environ.get("STANDARDS_BRANCH", "master").strip() or "master"
    # Fallback: when no source is set, use default repos (both v8-code-style and v8std)
    if not path_arg and not standards_repos and not standards_repo:
        standards_repos = _DEFAULT_STANDARDS_REPOS
    temp_dirs: list[Path] = []
    dirs_to_load: list[Path] = []

    if path_arg:
        d = Path(path_arg)
        if not d.exists() or not d.is_dir():
            print(f"Error: path not found or not a directory: {d}", file=sys.stderr)
            return 1
        dirs_to_load.append(d)
    elif standards_repos:
        for spec in standards_repos.split(","):
            if not spec.strip():
                continue
            repo_url, branch = _parse_standards_repo_spec(spec, default_branch)
            if "github.com" not in repo_url:
                repo_url = f"https://github.com/{repo_url}"
            try:
                from .standards_loader import fetch_repo_archive

                d, tmp = fetch_repo_archive(repo_url, subpath=standards_subpath, branch=branch)
                dirs_to_load.append(d)
                temp_dirs.append(tmp)
            except Exception as e:
                print(f"Error fetching {repo_url}: {e}", file=sys.stderr)
                for t in temp_dirs:
                    import shutil

                    shutil.rmtree(t, ignore_errors=True)
                return 1
    elif standards_repo:
        try:
            from .standards_loader import fetch_repo_archive

            d, tmp = fetch_repo_archive(
                standards_repo, subpath=standards_subpath, branch=default_branch
            )
            dirs_to_load.append(d)
            temp_dirs.append(tmp)
        except Exception as e:
            print(f"Error fetching {standards_repo}: {e}", file=sys.stderr)
            return 1
    else:
        print(
            "No source: set STANDARDS_REPOS (e.g. 1C-Company/v8-code-style:master,zeegin/v8std:main) "
            "or STANDARDS_REPO or STANDARDS_DIR / pass path.",
            file=sys.stderr,
        )
        return 0

    try:
        import shutil as _shutil

        from ._utils import progress_done, progress_line
        from .memory import get_memory_store
        from .standards_loader import collect_from_folder

        # Копировать загруженные репо в папку standards (если загрузка из репо, а не из path)
        if temp_dirs:
            standards_out = Path(os.environ.get("STANDARDS_DIR") or "data/standards").resolve()
            standards_out.mkdir(parents=True, exist_ok=True)
            for d in dirs_to_load:
                subdir = d.parent.name
                dest = standards_out / subdir
                _shutil.copytree(d, dest, dirs_exist_ok=True)
            progress_done(f"load-standards │ copied to {standards_out}")

        items: list[dict[str, Any]] = []
        for d in dirs_to_load:
            items.extend(collect_from_folder(d))

        if not items:
            print("No .md files found.", file=sys.stderr)
            return 0

        def _progress(loaded: int, tot: int, skipped: int) -> None:
            progress_line(
                f"load-standards │ {loaded + skipped}/{tot} │ {loaded} loaded │ {skipped} skip"
            )

        store = get_memory_store()
        n = store.upsert_curated_snippets(items, progress_callback=_progress, domain="standards")
        progress_done(f"load-standards │ ✓ {n} loaded → onec_help_memory (domain=standards)")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        import shutil

        for tmp in temp_dirs:
            shutil.rmtree(tmp, ignore_errors=True)


def cmd_parse_fastcode(args: argparse.Namespace) -> int:
    """Parse FastCode templates into snippets JSON."""
    from .parse_fastcode import run_parse

    pages = None
    if args.pages and args.pages.lower() != "auto":
        if "-" in args.pages:
            lo, hi = args.pages.split("-", 1)
            pages = list(range(int(lo), int(hi) + 1))
        else:
            pages = [int(p) for p in args.pages.split(",")]

    out_path = args.out
    if not out_path:
        snippets_dir = os.environ.get("SNIPPETS_DIR", "")
        if snippets_dir:
            out_path = str(Path(snippets_dir) / "fastcode_snippets.json")
        else:
            out_path = "data/snippets/fastcode_snippets.json"
    out = Path(out_path)
    fetch_detail = not getattr(args, "no_fetch_detail", False)
    return run_parse(out=out, pages=pages, delay=args.delay, fetch_detail=fetch_detail)


def cmd_parse_helpf(args: argparse.Namespace) -> int:
    """Parse HelpF.pro FAQ and Files into snippets JSON."""
    from .parse_helpf import run_parse

    pages = None
    if args.pages and args.pages.lower() != "auto":
        if "-" in args.pages:
            lo, hi = args.pages.split("-", 1)
            pages = list(range(int(lo), int(hi) + 1))
        else:
            pages = [int(p) for p in args.pages.split(",")]

    out_path = args.out
    if not out_path:
        snippets_dir = os.environ.get("SNIPPETS_DIR", "")
        if snippets_dir:
            out_path = str(Path(snippets_dir) / "helpf_snippets.json")
        else:
            out_path = "data/snippets/helpf_snippets.json"
    out = Path(out_path)
    fetch_detail = not getattr(args, "no_fetch_detail", False)
    return run_parse(
        out=out,
        source=args.source,
        pages=pages,
        max_items=getattr(args, "max_items", 0),
        delay=args.delay,
        fetch_detail=fetch_detail,
        skip_minimal=getattr(args, "skip_minimal", False),
    )


def cmd_watchdog(args: argparse.Namespace) -> int:
    """Run watchdog: monitor .hbk, ingest on change; process pending memory."""
    from .watchdog import run_watchdog

    try:
        run_watchdog(
            poll_interval_sec=args.poll_interval,
            pending_interval_sec=args.pending_interval,
        )
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_mcp(args: argparse.Namespace) -> int:
    """Run MCP server (stdio, sse, http, streamable-http). Requires fastmcp (pip install fastmcp)."""
    try:
        from .mcp_server import run_mcp
    except ImportError:
        print("MCP requires fastmcp (Python 3.10+): pip install fastmcp", file=sys.stderr)
        return 1
    transport = getattr(args, "transport", None) or os.environ.get("MCP_TRANSPORT", "stdio")
    host = getattr(args, "host", None) or os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(getattr(args, "port", None) or os.environ.get("MCP_PORT", "8050"))
    path = getattr(args, "path", None) or os.environ.get("MCP_PATH", "/mcp")
    try:
        run_mcp(
            help_path=Path(args.directory),
            transport=transport,
            host=host,
            port=port,
            path=path,
        )
    except RuntimeError as e:
        if "fastmcp" in str(e).lower():
            print("MCP requires fastmcp (Python 3.10+): pip install fastmcp", file=sys.stderr)
            return 1
        raise
    return 0


def _collection_has_data(qdrant_host: str, qdrant_port: int, collection: str) -> bool:
    """Return True if collection exists and has points > 0."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(host=qdrant_host, port=qdrant_port, check_compatibility=False)
        if not client.collection_exists(collection):
            return False
        info = client.get_collection(collection)
        pts = getattr(info, "points_count", None) or getattr(info, "pointsCount", 0)
        return (pts or 0) > 0
    except Exception:
        return False


def _clear_before_reinit(
    qdrant_host: str = "localhost",
    qdrant_port: int = 6333,
    collection: str = "onec_help",
) -> bool:
    """Delete Qdrant collections (onec_help, onec_help_memory) and ingest cache. Returns True on success."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(host=qdrant_host, port=qdrant_port, check_compatibility=False)
        for coll in (collection, "onec_help_memory"):
            if client.collection_exists(coll):
                client.delete_collection(coll)
                print(f"Dropped Qdrant collection: {coll}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: could not drop Qdrant collections: {e}", file=sys.stderr)
    from .ingest import clear_ingest_cache

    if clear_ingest_cache():
        print("Cleared ingest cache.", file=sys.stderr)
    return True


def cmd_init(args: argparse.Namespace) -> int:
    """Initial load: ingest (help), load-snippets, load-standards. Does not erase existing data."""
    ingest_args = _make_args(
        sources=getattr(args, "sources", None),
        sources_file=getattr(args, "sources_file", None),
        languages=getattr(args, "languages", None) or os.environ.get("HELP_LANGUAGES"),
        temp_base=os.environ.get("HELP_INGEST_TEMP") or None,
        workers=None,
        max_tasks=None,
        quiet=getattr(args, "quiet", False),
        dry_run=False,
        recreate=False,
        no_cache=False,
        index_batch_size=500,
        embedding_batch_size=None,
        embedding_workers=None,
    )
    rc = cmd_ingest(ingest_args)
    if rc != 0:
        return rc
    snippets_args = _make_args(
        snippets_file=os.environ.get("SNIPPETS_JSON_PATH", ""),
        per_function=getattr(args, "per_function", False),
        from_project=getattr(args, "from_project", None),
    )
    rc = cmd_load_snippets(snippets_args)
    if rc != 0:
        return rc
    standards_args = _make_args(standards_path=os.environ.get("STANDARDS_DIR", ""))
    return cmd_load_standards(standards_args)


def cmd_reinit(args: argparse.Namespace) -> int:
    """Reinit: erase Qdrant + cache, then init. If DB exists with data, runs init (no wipe) unless --force."""
    qdrant_host = os.environ.get("QDRANT_HOST", "localhost")
    qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
    collection = os.environ.get("QDRANT_COLLECTION", "onec_help")
    force = getattr(args, "force", False)
    if not force and _collection_has_data(qdrant_host, qdrant_port, collection):
        if not getattr(args, "quiet", False):
            print(
                "Index exists with data; skipping wipe. Use --force to erase and reindex.",
                file=sys.stderr,
            )
        return cmd_init(args)
    _clear_before_reinit(qdrant_host=qdrant_host, qdrant_port=qdrant_port, collection=collection)
    reinit_args = _make_args(
        sources=getattr(args, "sources", None),
        sources_file=getattr(args, "sources_file", None),
        languages=getattr(args, "languages", None) or os.environ.get("HELP_LANGUAGES"),
        temp_base=os.environ.get("HELP_INGEST_TEMP") or None,
        workers=None,
        max_tasks=None,
        quiet=getattr(args, "quiet", False),
        dry_run=False,
        recreate=True,
        no_cache=True,
        index_batch_size=500,
        embedding_batch_size=None,
        embedding_workers=None,
    )
    rc = cmd_ingest(reinit_args)
    if rc != 0:
        return rc
    snippets_args = _make_args(
        snippets_file=os.environ.get("SNIPPETS_JSON_PATH", ""),
        per_function=getattr(args, "per_function", False),
        from_project=getattr(args, "from_project", None),
    )
    rc = cmd_load_snippets(snippets_args)
    if rc != 0:
        return rc
    standards_args = _make_args(standards_path=os.environ.get("STANDARDS_DIR", ""))
    return cmd_load_standards(standards_args)


def cmd_qdrant_backup(args: argparse.Namespace) -> int:
    """Создать снапшот коллекции и сохранить в data/backup/."""
    import urllib.request
    from datetime import datetime

    host = os.environ.get("QDRANT_HOST", "localhost")
    port = int(os.environ.get("QDRANT_PORT", "6333"))
    collection = os.environ.get("QDRANT_COLLECTION", "onec_help")
    base = f"http://{host}:{port}"
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Create snapshot
        req = urllib.request.Request(
            f"{base}/collections/{collection}/snapshots",
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode())
        name = data.get("result", {}).get("name")
        if not name:
            print("Error: no snapshot name in response", file=sys.stderr)
            return 1

        # 2. Download snapshot
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = out_dir / f"onec_help-{ts}.snapshot"
        req = urllib.request.Request(f"{base}/collections/{collection}/snapshots/{name}")
        with urllib.request.urlopen(req, timeout=600) as resp:
            out_path.write_bytes(resp.read())

        print(f"Backup saved: {out_path}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_qdrant_restore(args: argparse.Namespace) -> int:
    """Восстановить коллекцию из снапшота."""
    import urllib.request

    host = os.environ.get("QDRANT_HOST", "localhost")
    port = int(os.environ.get("QDRANT_PORT", "6333"))
    collection = os.environ.get("QDRANT_COLLECTION", "onec_help")
    base = f"http://{host}:{port}"
    backup_dir = Path(args.backup_dir)

    if args.file:
        snap_path = Path(args.file)
        if not snap_path.is_file():
            print(f"Error: file not found: {snap_path}", file=sys.stderr)
            return 1
    else:
        snaps = sorted(backup_dir.glob("onec_help-*.snapshot"), reverse=True)
        if not snaps:
            print(f"Error: no snapshots in {backup_dir}", file=sys.stderr)
            return 1
        snap_path = snaps[0]
        print(f"Using latest: {snap_path}")

    try:
        boundary = "----WebKitFormBoundary7MA4YWxk"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="snapshot"; filename="snapshot.snapshot"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        body += snap_path.read_bytes()
        body += f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{base}/collections/{collection}/snapshots/upload?priority=snapshot",
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            json.loads(resp.read().decode())

        print(f"Restored from {snap_path}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="onec_help", description="1C Help: unpack, docs, index, MCP"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # unpack
    p_unpack = sub.add_parser("unpack", help="Unpack .hbk with 7z")
    p_unpack.add_argument("archive", type=str, help="Path to .hbk file")
    p_unpack.add_argument(
        "--output-dir", "-o", type=str, default="./unpacked", help="Output directory"
    )
    p_unpack.set_defaults(func=cmd_unpack)

    p_unpack_diag = sub.add_parser(
        "unpack-diag",
        help="Diagnose unpack failure (try each method, print 7z output)",
    )
    p_unpack_diag.add_argument("archive", type=str, help="Path to .hbk file")
    p_unpack_diag.add_argument(
        "--output-dir", "-o", type=str, default="/tmp/unpack_diag", help="Output dir"
    )
    p_unpack_diag.set_defaults(func=cmd_unpack_diag)

    # unpack-dir — only unpack all .hbk into a directory (no build-docs, no index)
    p_unpack_dir = sub.add_parser(
        "unpack-dir", help="Unpack all .hbk from source tree into output dir (no indexing)"
    )
    p_unpack_dir.add_argument(
        "source_dir",
        type=str,
        nargs="?",
        default="",
        help="Root dir with version subdirs (or set HELP_SOURCE_BASE)",
    )
    p_unpack_dir.add_argument(
        "--output-dir", "-o", type=str, default="./unpacked", help="Output directory"
    )
    p_unpack_dir.add_argument(
        "--sources",
        "-s",
        type=str,
        nargs="*",
        help="path:version pairs (overrides source_dir / HELP_SOURCE_BASE)",
    )
    p_unpack_dir.add_argument(
        "--languages",
        "-l",
        type=str,
        default=None,
        help="Comma-separated, e.g. ru (default: HELP_LANGUAGES or all)",
    )
    p_unpack_dir.add_argument("--workers", "-w", type=int, default=4, help="Parallel workers")
    p_unpack_dir.add_argument("--quiet", "-q", action="store_true", help="Less output")
    p_unpack_dir.set_defaults(func=cmd_unpack_dir)

    # unpack-sync — unpack to data/unpacked with .hbk_info.json, skip unchanged
    p_unpack_sync = sub.add_parser(
        "unpack-sync",
        help="Unpack .hbk to data/unpacked (version/stem), write .hbk_info.json, skip unchanged",
    )
    p_unpack_sync.add_argument(
        "source_dir",
        type=str,
        nargs="?",
        default="",
        help="Root dir with version subdirs (or set HELP_SOURCE_BASE)",
    )
    p_unpack_sync.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Output (default: DATA_UNPACKED_DIR or data/unpacked)",
    )
    p_unpack_sync.add_argument(
        "--sources",
        "-s",
        type=str,
        nargs="*",
        help="path:version pairs",
    )
    p_unpack_sync.add_argument(
        "--languages",
        "-l",
        type=str,
        default=None,
        help="Comma-separated, e.g. ru",
    )
    p_unpack_sync.add_argument("--workers", "-w", type=int, default=4, help="Parallel workers")
    p_unpack_sync.add_argument("--quiet", "-q", action="store_true", help="Less output")
    p_unpack_sync.set_defaults(func=cmd_unpack_sync)

    # read-hbk-container — read HBK binary container (source: alkoleft/hbk-viewer)
    p_read_hbk = sub.add_parser(
        "read-hbk-container",
        help="Read HBK binary container; list entities or extract FileStorage/TOC",
    )
    p_read_hbk.add_argument("file", type=str, help="Path to .hbk file")
    p_read_hbk.add_argument(
        "--out-dir", "-o", type=str, default=None, help="Extract FileStorage ZIP to this directory"
    )
    p_read_hbk.add_argument(
        "--toc-json", type=str, default=None, help="Write PackBlock TOC (UTF-8) to this file"
    )
    p_read_hbk.set_defaults(func=cmd_read_hbk_container)

    # build-docs
    p_docs = sub.add_parser("build-docs", help="Generate Markdown from HTML")
    p_docs.add_argument("project_dir", type=str, help="Directory with HTML files")
    p_docs.add_argument(
        "--output", "-o", type=str, help="Output directory (default: project_dir/docs_md)"
    )
    p_docs.set_defaults(func=cmd_build_docs)

    # build-index
    p_idx = sub.add_parser("build-index", help="Build Qdrant index from Markdown/docs (recursive)")
    p_idx.add_argument("directory", type=str, help="Directory with .md or HTML")
    p_idx.add_argument("--docs-dir", type=str, help="Alias for directory (optional)")
    p_idx.add_argument(
        "--incremental",
        action="store_true",
        help="Add/update only, do not recreate collection (new files in folder will be indexed)",
    )
    p_idx.add_argument(
        "--embedding-batch-size",
        type=int,
        default=None,
        metavar="N",
        help="Texts per embedding batch (default: env EMBEDDING_BATCH_SIZE or 64)",
    )
    p_idx.add_argument(
        "--embedding-workers",
        type=int,
        default=None,
        metavar="N",
        help="Parallel API requests for openai_api (default: env EMBEDDING_WORKERS or 4)",
    )
    p_idx.add_argument(
        "--no-bm25",
        action="store_true",
        help="Disable BM25 sparse vectors (default: BM25_ENABLED=1)",
    )
    p_idx.set_defaults(func=cmd_build_index)

    # add-bm25
    p_add_bm25 = sub.add_parser(
        "add-bm25",
        help="Add BM25 sparse vectors to existing collection (no re-ingest, no re-embedding)",
    )
    p_add_bm25.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Collection name (default: QDRANT_COLLECTION or onec_help)",
    )
    p_add_bm25.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Points per upsert batch (default 200)",
    )
    p_add_bm25.add_argument("--quiet", "-q", action="store_true", help="Less output")
    p_add_bm25.set_defaults(func=cmd_add_bm25)

    # ingest
    p_ingest = sub.add_parser(
        "ingest", help="Ingest .hbk from multiple read-only dirs (temp unpack, index, cleanup)"
    )
    p_ingest.add_argument(
        "--sources",
        "-s",
        type=str,
        nargs="*",
        help="Alternating path:version (or set HELP_SOURCE_BASE to scan a folder of version subdirs)",
    )
    p_ingest.add_argument("--sources-file", type=str, help="File with lines: path or path:version")
    p_ingest.add_argument(
        "--languages",
        "-l",
        type=str,
        default=None,
        help="Comma-separated, e.g. ru or ru,en; default from HELP_LANGUAGES; empty=all",
    )
    p_ingest.add_argument(
        "--temp-base",
        type=str,
        default=None,
        help="Temp dir in container (default HELP_INGEST_TEMP or /tmp/help_ingest)",
    )
    p_ingest.add_argument(
        "--workers",
        "-w",
        type=int,
        default=None,
        metavar="N",
        help="Parallel workers for unpack/build (default: half of CPUs)",
    )
    p_ingest.add_argument(
        "--max-tasks",
        "-n",
        type=int,
        default=None,
        help="Process only first N .hbk files (avoids timeout; run multiple times for full index)",
    )
    p_ingest.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="No progress output (default: print progress to stderr)",
    )
    p_ingest.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report how many .hbk tasks would be processed (no unpack/index)",
    )
    p_ingest.add_argument(
        "--index-batch-size",
        type=int,
        default=500,
        metavar="N",
        help="Index N files per upsert (default 500); smaller = more progress output, less memory",
    )
    p_ingest.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate Qdrant collection (e.g. after changing EMBEDDING_DIMENSION or model)",
    )
    p_ingest.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore ingest cache; re-parse and re-embed all .hbk (env INGEST_SKIP_CACHE=1)",
    )
    p_ingest.add_argument(
        "--embedding-batch-size",
        type=int,
        default=None,
        metavar="N",
        help="Texts per embedding batch (default: env EMBEDDING_BATCH_SIZE or 64)",
    )
    p_ingest.add_argument(
        "--embedding-workers",
        type=int,
        default=None,
        metavar="N",
        help="Parallel API requests for openai_api (default: env EMBEDDING_WORKERS or 4)",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    # ingest-from-unpacked — index from data/unpacked (version/stem structure)
    p_ingest_unpacked = sub.add_parser(
        "ingest-from-unpacked",
        help="Index from unpacked dir (version/stem, path_prefix in payload)",
    )
    p_ingest_unpacked.add_argument(
        "--dir",
        "-d",
        type=str,
        default=None,
        help="Unpacked base dir (default: DATA_UNPACKED_DIR or data/unpacked)",
    )
    p_ingest_unpacked.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate Qdrant collection before indexing",
    )
    p_ingest_unpacked.add_argument("--quiet", "-q", action="store_true", help="Less output")
    p_ingest_unpacked.add_argument(
        "--embedding-batch-size",
        type=int,
        default=None,
        metavar="N",
        help="Texts per embedding batch",
    )
    p_ingest_unpacked.add_argument(
        "--embedding-workers",
        type=int,
        default=None,
        metavar="N",
        help="Parallel embedding requests",
    )
    p_ingest_unpacked.add_argument(
        "--bm25",
        action="store_true",
        help="Enable BM25 sparse vectors",
    )
    p_ingest_unpacked.add_argument(
        "--no-bm25",
        action="store_true",
        dest="no_bm25",
        help="Disable BM25",
    )
    p_ingest_unpacked.set_defaults(func=cmd_ingest_from_unpacked)

    # init — ingest + load-snippets + load-standards (no erase)
    p_init = sub.add_parser(
        "init",
        help="Initial load: ingest help, load snippets, load standards (uses env; does not erase)",
    )
    p_init.add_argument(
        "--sources", "-s", type=str, nargs="*", help="path:version (or HELP_SOURCE_BASE)"
    )
    p_init.add_argument("--sources-file", type=str, help="File with path or path:version lines")
    p_init.add_argument("--languages", "-l", type=str, default=None, help="e.g. ru or ru,en")
    p_init.add_argument("--quiet", "-q", action="store_true", help="Less output")
    p_init.add_argument(
        "--per-function", action="store_true", help="Split .bsl by procedures for snippets"
    )
    p_init.add_argument("--from-project", type=str, help="Load snippets from 1C project path")
    p_init.set_defaults(func=cmd_init)

    # reinit — erase collections + cache, then init (skip wipe if DB exists, unless --force)
    p_reinit = sub.add_parser(
        "reinit",
        help="Init load. If index exists with data, runs init (no wipe). Use --force to erase and reindex.",
    )
    p_reinit.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Always erase collections and cache before init",
    )
    p_reinit.add_argument(
        "--sources", "-s", type=str, nargs="*", help="path:version (or HELP_SOURCE_BASE)"
    )
    p_reinit.add_argument("--sources-file", type=str, help="File with path or path:version lines")
    p_reinit.add_argument("--languages", "-l", type=str, default=None, help="e.g. ru or ru,en")
    p_reinit.add_argument("--quiet", "-q", action="store_true", help="Less output")
    p_reinit.add_argument(
        "--per-function", action="store_true", help="Split .bsl by procedures for snippets"
    )
    p_reinit.add_argument("--from-project", type=str, help="Load snippets from 1C project path")
    p_reinit.set_defaults(func=cmd_reinit)

    # load-snippets
    p_load_snippets = sub.add_parser(
        "load-snippets",
        help="Load curated snippets from JSON and/or folder into onec_help_memory (domain=snippets)",
    )
    p_load_snippets.add_argument(
        "snippets_file",
        type=str,
        nargs="?",
        default=None,
        help="Path to snippets.json or folder (default: SNIPPETS_DIR or SNIPPETS_JSON_PATH)",
    )
    p_load_snippets.add_argument(
        "--per-function",
        action="store_true",
        dest="per_function",
        help="Split large .bsl by procedures/functions (each as snippet, min 50 lines)",
    )
    p_load_snippets.add_argument(
        "--from-project",
        type=str,
        default=None,
        metavar="PATH",
        help="Load snippets from 1C project path (e.g. src). Uses collect_from_folder on **/*.bsl.",
    )
    p_load_snippets.add_argument(
        "--no-cache",
        action="store_true",
        dest="no_cache",
        help="Ignore cache; re-embed all sources (env SNIPPETS_SKIP_CACHE=1)",
    )
    p_load_snippets.set_defaults(func=cmd_load_snippets)

    # load-standards
    p_load_standards = sub.add_parser(
        "load-standards",
        help="Load v8-code-style docs (markdown) into onec_help_memory (domain=standards)",
    )
    p_load_standards.add_argument(
        "standards_path",
        type=str,
        nargs="?",
        default=None,
        help="Path to folder with .md (default: STANDARDS_DIR env)",
    )
    p_load_standards.set_defaults(func=cmd_load_standards)

    # parse-fastcode
    p_parse_fastcode = sub.add_parser(
        "parse-fastcode",
        help="Parse FastCode.im templates into snippets JSON",
    )
    p_parse_fastcode.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output path (default: SNIPPETS_DIR/fastcode_snippets.json or data/snippets/)",
    )
    p_parse_fastcode.add_argument(
        "--pages",
        type=str,
        default="auto",
        help="Page range: auto (detect from site), 1-51, or 1,2,3",
    )
    p_parse_fastcode.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between requests in seconds",
    )
    p_parse_fastcode.add_argument(
        "--no-fetch-detail",
        action="store_true",
        dest="no_fetch_detail",
        help="Do not fetch detail pages (faster, but code may be truncated)",
    )
    p_parse_fastcode.set_defaults(func=cmd_parse_fastcode)

    # parse-helpf
    p_parse_helpf = sub.add_parser(
        "parse-helpf",
        help="Parse HelpF.pro FAQ/Files into snippets JSON",
    )
    p_parse_helpf.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output path (default: SNIPPETS_DIR/helpf_snippets.json or data/snippets/)",
    )
    p_parse_helpf.add_argument(
        "--source",
        type=str,
        default="faq",
        choices=("faq", "file", "help", "freelance", "all"),
        help="Source: faq, file, help (forum), freelance, or all",
    )
    p_parse_helpf.add_argument(
        "--pages",
        type=str,
        default="auto",
        help="Page range: auto (detect from site), 1-10, or 1,2,3",
    )
    p_parse_helpf.add_argument(
        "--max-items",
        type=int,
        default=0,
        help="Max detail pages to fetch (0 = all)",
    )
    p_parse_helpf.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between requests in seconds",
    )
    p_parse_helpf.add_argument(
        "--no-fetch-detail",
        action="store_true",
        dest="no_fetch_detail",
        help="Do not fetch detail pages (listing only, no full content)",
    )
    p_parse_helpf.add_argument(
        "--skip-minimal",
        action="store_true",
        dest="skip_minimal",
        help="Exclude items with no real content (title-only, no code)",
    )
    p_parse_helpf.set_defaults(func=cmd_parse_helpf)

    # index-status (ingest: embedding speed, per-folder, ETA, total time)
    p_status = sub.add_parser(
        "index-status",
        help="Show index status (topics, versions, languages; ingest: embedding speed, per-folder, ETA)",
    )
    p_status.add_argument(
        "--watch",
        "-w",
        action="store_true",
        help="Refresh in-place every N seconds (progress-like display)",
    )
    p_status.add_argument(
        "--interval",
        "-n",
        type=float,
        default=2,
        metavar="SEC",
        help="Refresh interval for --watch (default: 2)",
    )
    p_status.add_argument(
        "--compact",
        "-c",
        action="store_true",
        help="Single-line output (for piping/scripts)",
    )
    p_status.set_defaults(func=cmd_index_status)

    # mcp
    p_mcp = sub.add_parser("mcp", help="Run MCP server (stdio, sse, http, streamable-http)")
    p_mcp.add_argument("directory", type=str, help="Directory with help (.md or HTML)")
    p_mcp.add_argument(
        "--transport",
        "-t",
        type=str,
        default=None,
        help="Transport: stdio (default), sse, http, streamable-http",
    )
    p_mcp.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host for sse/http (default: 127.0.0.1). Use 0.0.0.0 in Docker.",
    )
    p_mcp.add_argument(
        "--port", "-p", type=int, default=None, help="Port for sse/http (default: 8050)"
    )
    p_mcp.add_argument("--path", type=str, default=None, help="URL path (default: /mcp)")
    p_mcp.set_defaults(func=cmd_mcp)

    # watchdog
    p_watchdog = sub.add_parser(
        "watchdog",
        help="Monitor new .hbk files, run ingest on change; process pending memory embeddings",
    )
    p_watchdog.add_argument(
        "--poll-interval",
        type=int,
        default=int(os.environ.get("WATCHDOG_POLL_INTERVAL", "600")),
        help="Seconds between .hbk checks (default: 600)",
    )
    p_watchdog.add_argument(
        "--pending-interval",
        type=int,
        default=int(os.environ.get("WATCHDOG_PENDING_INTERVAL", "600")),
        help="Seconds between pending memory processing (default: 600)",
    )
    p_watchdog.set_defaults(func=cmd_watchdog)

    # qdrant-backup / qdrant-restore — снапшоты в data/backup/
    p_qdrant_backup = sub.add_parser(
        "qdrant-backup",
        help="Создать снапшот коллекции onec_help и сохранить в data/backup/",
    )
    p_qdrant_backup.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="data/backup",
        help="Каталог для снапшота (default: data/backup)",
    )
    p_qdrant_backup.set_defaults(func=cmd_qdrant_backup)

    p_qdrant_restore = sub.add_parser(
        "qdrant-restore",
        help="Восстановить коллекцию onec_help из снапшота в data/backup/",
    )
    p_qdrant_restore.add_argument(
        "--file",
        "-f",
        type=str,
        default=None,
        help="Путь к снапшоту (default: последний в data/backup/)",
    )
    p_qdrant_restore.add_argument(
        "--backup-dir",
        type=str,
        default="data/backup",
        help="Каталог со снапшотами (default: data/backup)",
    )
    p_qdrant_restore.set_defaults(func=cmd_qdrant_restore)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
