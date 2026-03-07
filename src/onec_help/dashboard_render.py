"""Render dashboard data as Rich panels (Tasks, Errors, Database)."""

from typing import Any

from ._utils import format_duration


def render_dashboard(data: dict[str, Any]) -> Any:
    """Build Rich renderable from get_dashboard_data() result. Returns Group of Panels."""
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table

    panels = []

    # --- Panel 1: Tasks ---
    tasks_lines: list[str] = []
    ingest = data.get("ingest")
    ingest_last = data.get("ingest_last_run")
    if ingest and ingest.get("status") == "in_progress":
        total = ingest.get("total_tasks") or 0
        done = ingest.get("done_tasks") or 0
        elapsed = ingest.get("elapsed_sec") or 0
        eta = ""
        if done and total and done < total and elapsed:
            try:
                rate = elapsed / done
                eta_sec = rate * (total - done)
                eta = f", ETA {format_duration(eta_sec)}"
            except (ZeroDivisionError, TypeError):
                pass
        tasks_lines.append(
            f"Ingest: in progress {done}/{total}{eta} ({format_duration(elapsed)} elapsed)"
        )
    elif ingest_last:
        total = ingest_last.get("total_tasks") or 0
        done = ingest_last.get("done_tasks") or 0
        failed = ingest_last.get("failed_count") or 0
        elapsed = ingest_last.get("total_elapsed_sec")
        tasks_lines.append(
            f"Ingest: last run {done}/{total} done"
            + (f", {failed} failed" if failed else "")
            + (f", {format_duration(elapsed)}" if elapsed is not None else "")
        )
    else:
        tasks_lines.append("Ingest: —")

    standards_loading = data.get("standards_loading")
    tasks_lines.append("Standards: loading…" if standards_loading else "Standards: —")

    snippets_loading = data.get("snippets_loading")
    snippets = data.get("snippets")
    if snippets_loading:
        tasks_lines.append("Snippets: loading…")
    elif snippets:
        items = snippets.get("items_loaded")
        tasks_lines.append(
            f"Snippets: last run, {items} items" if items is not None else "Snippets: last run"
        )
    else:
        tasks_lines.append("Snippets: —")

    panels.append(Panel("\n".join(tasks_lines), title="[bold]Tasks[/bold]", border_style="blue"))

    # --- Panel 2: Errors ---
    failed = data.get("failed_tasks") or []
    err_max_len = 80
    if failed:
        err_table = Table(show_header=True, header_style="bold")
        err_table.add_column("Version", style="dim")
        err_table.add_column("Language", style="dim")
        err_table.add_column("Path", max_width=40, overflow="ellipsis")
        err_table.add_column("Error", max_width=err_max_len, overflow="ellipsis")
        for t in failed[:20]:
            err = (t.get("error") or "")[:err_max_len]
            if len(t.get("error") or "") > err_max_len:
                err = err + "…"
            err_table.add_row(
                (t.get("version") or "—")[:12],
                (t.get("language") or "—")[:8],
                (t.get("path") or "—"),
                err,
            )
        panels.append(
            Panel(
                err_table, title=f"[bold]Errors[/bold] ({len(failed)} failed)", border_style="red"
            )
        )
    else:
        total_err = (data.get("ingest_last_run") or {}).get("failed_count") or 0
        if total_err > 0:
            panels.append(
                Panel(
                    f"{total_err} failed (re-run ingest to see details)",
                    title="[bold]Errors[/bold]",
                    border_style="red",
                )
            )
        else:
            panels.append(Panel("—", title="[bold]Errors[/bold]", border_style="dim"))

    # --- Panel 3: Database ---
    index_status = data.get("index_status") or {}
    collections = data.get("collections") or []
    if index_status.get("error"):
        db_content = f"Qdrant: [red]{index_status.get('error', 'error')}[/red]"
    elif collections:
        db_table = Table(show_header=True, header_style="bold")
        db_table.add_column("Collection")
        db_table.add_column("Points")
        db_table.add_column("Indexed vectors")
        db_table.add_column("Segments")
        for c in collections:
            pts = c.get("points_count")
            vecs = c.get("indexed_vectors_count")
            segs = c.get("segments_count")
            db_table.add_row(
                c.get("name") or "—",
                str(pts) if pts is not None else "—",
                str(vecs) if vecs is not None else "—",
                str(segs) if segs is not None else "—",
            )
        db_content = db_table
        storage_mb = data.get("storage_path_mb")
        if storage_mb is not None:
            db_content = Group(db_content, f"DB on disk: {storage_mb} MB")
    else:
        db_content = "No collections"
    panels.append(Panel(db_content, title="[bold]Database[/bold] (Qdrant)", border_style="green"))

    # --- Panel 4: MCP requests ---
    mcp = data.get("mcp_metrics") or {}
    total = mcp.get("total", 0) or 0
    last_hour = mcp.get("last_hour", 0) or 0
    mcp_text = f"Total: {total}  │  Last hour: {last_hour}"
    panels.append(Panel(mcp_text, title="[bold]MCP requests[/bold]", border_style="cyan"))

    return Group(*panels)


def render_dashboard_compact(data: dict[str, Any], *, spinner: str = "") -> str:
    """Single-line summary from dashboard data (for index-status --compact). Caller checks index_status.error first."""
    parts: list[str] = []
    prefix = f"{spinner} index-status".strip() if spinner else "index-status"

    collections = data.get("collections") or []
    if collections:
        total_pts = sum(
            p
            for c in collections
            if (p := c.get("points_count")) is not None and isinstance(p, int)
        )
        for c in collections:
            parts.append(f"{c.get('name', '?')}:{c.get('points_count', '—')} pts")
        if total_pts > 0 and len(collections) > 1:
            parts.append(f"total:{total_pts}")
        storage_mb = data.get("storage_path_mb")
        if storage_mb is not None:
            parts.append(f"DB:{storage_mb}MB")

    ingest = data.get("ingest")
    ingest_last = data.get("ingest_last_run")
    if ingest and ingest.get("status") == "in_progress":
        done = ingest.get("done_tasks") or 0
        total = ingest.get("total_tasks") or 0
        elapsed = ingest.get("elapsed_sec")
        ing = f"Ingest ⟳ {done}/{total} tasks"
        if elapsed is not None:
            ing += f" elapsed {format_duration(elapsed)}"
        parts.append(ing)
    elif ingest_last:
        done = ingest_last.get("done_tasks") or 0
        total = ingest_last.get("total_tasks") or 0
        failed = ingest_last.get("failed_count") or 0
        elapsed = ingest_last.get("total_elapsed_sec")
        parts.append(f"Ingest ✓ {format_duration(elapsed)}" if elapsed else "Ingest ✓ done")
        if failed:
            parts.append(f"{failed} failed")
    else:
        parts.append("Ingest: —")

    failed_tasks = data.get("failed_tasks") or []
    total_err = (data.get("ingest_last_run") or {}).get("failed_count") or len(failed_tasks)
    if total_err > 0 and failed_tasks:
        err0 = (failed_tasks[0].get("error") or "")[:80]
        if len(failed_tasks[0].get("error") or "") > 80:
            err0 += "…"
        parts.append(f"Failed: {total_err} {err0}")

    if data.get("standards_loading"):
        parts.append("Standards: loading…")
    if data.get("snippets_loading"):
        parts.append("Snippets: loading…")

    snippets = data.get("snippets")
    if snippets:
        items = snippets.get("items_loaded")
        parts.append(f"Snippets ✓ {items} items" if items is not None else "Snippets ✓")

    return f"{prefix} │ {' │ '.join(parts)}\n"
