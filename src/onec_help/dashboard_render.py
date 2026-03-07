"""Render dashboard data as Rich panels (Tasks, Errors, Database)."""

from typing import Any

from ._utils import format_duration


def render_dashboard(data: dict[str, Any]) -> Any:
    """Build Rich renderable from get_dashboard_data() result. Returns Group of Panels."""
    from rich.console import Group
    from rich.panel import Panel
    from rich.progress_bar import ProgressBar
    from rich.table import Table
    from rich.text import Text

    panels = []

    # --- Panel 1: Tasks — summary lines + labeled progress bars stacked vertically ---
    tasks_parts: list[Any] = []
    ingest = data.get("ingest")
    ingest_last = data.get("ingest_last_run")
    if ingest and ingest.get("status") == "in_progress":
        total = ingest.get("total_tasks") or 0
        done = ingest.get("done_tasks") or 0
        elapsed = ingest.get("elapsed_sec") or 0
        total_pts = ingest.get("total_points") or 0
        est_pts = ingest.get("estimated_total_points")
        eta = ""
        if done and total and done < total and elapsed:
            try:
                rate = elapsed / done
                eta_sec = rate * (total - done)
                eta = f", ETA {format_duration(eta_sec)}"
            except (ZeroDivisionError, TypeError):
                pass
        pts_str = ""
        if total_pts > 0:
            pts_str = f", {total_pts} pts"
        if est_pts is not None and est_pts > 0:
            pts_str += f" (est. ~{est_pts})"
        tasks_parts.append(
            Text(
                f"Ingest: in progress {done}/{total}{pts_str}{eta} ({format_duration(elapsed)} elapsed)"
            )
        )
        current_tasks = ingest.get("current") or []
        if current_tasks:
            tasks_parts.append(
                Text(f"  Active: {len(current_tasks)} task{'s' if len(current_tasks) != 1 else ''}")
            )
            for i, cur in enumerate(current_tasks[:10]):
                version = (cur.get("version") or "—")[:12]
                lang = (cur.get("language") or "—")[:8]
                path = (cur.get("path") or "—")[:36]
                stage = cur.get("stage") or "—"
                pts = cur.get("points")
                est = cur.get("estimated_total")
                if pts is not None and est is not None and est > 0:
                    stage_label = (
                        "эмбеддинг"
                        if stage == "embedding"
                        else "запись в Qdrant"
                        if stage == "writing"
                        else "индексация"
                        if stage == "indexing"
                        else stage or "indexing"
                    )
                    label = (
                        f"  [{i + 1}] {version} / {lang} — {path} — {stage_label} {pts}/{est} pts"
                    )
                    tasks_parts.append(Text(label))
                    tasks_parts.append(
                        ProgressBar(total=float(est), completed=float(pts), width=50)
                    )
                    tasks_parts.append(Text("\n"))
                else:
                    stage_label = stage or "—"
                    tasks_parts.append(
                        Text(f"  [{i + 1}] {version} / {lang} — {path} — {stage_label}")
                    )
                    tasks_parts.append(Text("\n"))
            if len(current_tasks) > 10:
                tasks_parts.append(Text(f"  … and {len(current_tasks) - 10} more"))
        else:
            pts = ingest.get("current_task_points")
            est = ingest.get("current_task_estimated_total")
            if pts is not None and est is not None and est > 0:
                tasks_parts.append(
                    Text(f"  Ingest current task — {pts}/{est} pts (эмбеддинг / запись)")
                )
                tasks_parts.append(ProgressBar(total=float(est), completed=float(pts), width=50))
                tasks_parts.append(Text("\n"))
    elif ingest_last:
        total = ingest_last.get("total_tasks") or 0
        done = ingest_last.get("done_tasks") or 0
        failed = ingest_last.get("failed_count") or 0
        elapsed = ingest_last.get("total_elapsed_sec")
        total_pts = ingest_last.get("total_points")
        pts_str = f", {total_pts} pts" if total_pts is not None and total_pts > 0 else ""
        tasks_parts.append(
            Text(
                f"Ingest: last run {done}/{total} done"
                + pts_str
                + (f", {failed} failed" if failed else "")
                + (f", {format_duration(elapsed)}" if elapsed is not None else "")
            )
        )
    else:
        tasks_parts.append(Text("Ingest: нет данных"))

    tasks_parts.append(Text(""))  # spacer before Standards/Snippets
    standards_loading = data.get("standards_loading")
    standards_pts = data.get("standards_loading_pts")
    if standards_loading and standards_pts:
        phase = standards_pts.get("phase", "embedding")
        loaded = standards_pts.get("loaded", 0)
        tot_s = standards_pts.get("total", 0)
        if phase == "parsing":
            tasks_parts.append(Text("Standards: парсинг / подготовка (сбор .md)…"))
        else:
            tasks_parts.append(
                Text(f"Standards: эмбеддинг + запись в Qdrant — {loaded}/{tot_s} pts")
            )
            tasks_parts.append(ProgressBar(total=float(tot_s), completed=float(loaded), width=50))
            tasks_parts.append(Text("\n"))
    elif standards_loading:
        tasks_parts.append(Text("Standards: loading…"))
    else:
        tasks_parts.append(Text("Standards: нет данных (watchdog или load-standards)"))

    tasks_parts.append(Text(""))  # spacer before Snippets
    snippets_loading = data.get("snippets_loading")
    snippets_pts = data.get("snippets_loading_pts")
    snippets = data.get("snippets")
    if snippets_loading and snippets_pts:
        phase = snippets_pts.get("phase", "embedding")
        loaded = snippets_pts.get("loaded", 0)
        tot_sn = snippets_pts.get("total", 0)
        if phase == "parsing":
            tasks_parts.append(Text("Snippets: парсинг / подготовка (сбор источников)…"))
        else:
            tasks_parts.append(
                Text(f"Snippets: эмбеддинг + запись в Qdrant — {loaded}/{tot_sn} pts")
            )
            tasks_parts.append(ProgressBar(total=float(tot_sn), completed=float(loaded), width=50))
            tasks_parts.append(Text("\n"))
    elif snippets_loading:
        tasks_parts.append(Text("Snippets: loading…"))
    elif snippets:
        items = snippets.get("items_loaded")
        tasks_parts.append(
            Text(
                f"Snippets: last run, {items} items" if items is not None else "Snippets: last run"
            )
        )
    else:
        tasks_parts.append(Text("Snippets: нет данных (watchdog или load-snippets)"))

    tasks_content: Any = Group(*tasks_parts)
    panels.append(Panel(tasks_content, title="[bold]Tasks[/bold]", border_style="blue"))

    # --- Panel 2: Errors (из накопительного лога Redis, всегда доступны) ---
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
        err_content: Any = Group(
            err_table,
            Text("[dim]Ошибки накапливаются в Redis, доступны для просмотра.[/dim]"),
        )
        panels.append(
            Panel(
                err_content,
                title=f"[bold]Errors[/bold] ({len(failed)} failed)",
                border_style="red",
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

    # --- Panel 3: Database (только фактические данные Qdrant; не смешиваем с прогрессом загрузки) ---
    index_status = data.get("index_status") or {}
    collections = data.get("collections") or []
    standards_loading_db = data.get("standards_loading")
    snippets_loading_db = data.get("snippets_loading")
    if index_status.get("error"):
        db_content = f"Qdrant: [red]{index_status.get('error', 'error')}[/red]"
    elif collections:
        db_table = Table(show_header=True, header_style="bold")
        db_table.add_column("Collection")
        db_table.add_column("Points")
        db_table.add_column("Indexed vectors")
        db_table.add_column("Segments")
        for c in collections:
            name = c.get("name") or "—"
            pts = c.get("points_count")
            vecs = c.get("indexed_vectors_count")
            segs = c.get("segments_count")
            db_table.add_row(
                name,
                str(pts) if pts is not None else "—",
                str(vecs) if vecs is not None else "—",
                str(segs) if segs is not None else "—",
            )
        db_parts: list[Any] = [db_table]
        if standards_loading_db or snippets_loading_db:
            db_parts.append(Text("[dim]Обновление: standards/snippets → onec_help_memory (прогресс в Tasks)[/dim]"))
        # Пояснение: onec_help_memory = standards + snippets + сохранённые из MCP; число pts может быть меньше суммы источников до завершения загрузки
        for c in collections or []:
            if (c.get("name") or "").strip() == "onec_help_memory":
                db_parts.append(
                    Text("[dim]onec_help_memory: стандарты + сниппеты + save_1c_snippet[/dim]")
                )
                break
        versions = index_status.get("versions") or []
        languages = index_status.get("languages") or []
        if versions:
            max_show = 15
            if len(versions) <= max_show:
                ver_line = f"Versions 1C: {', '.join(versions)}"
            else:
                ver_line = (
                    f"Versions 1C: {', '.join(versions[:max_show])} … +{len(versions) - max_show}"
                )
            db_parts.append(ver_line)
        if languages:
            db_parts.append(f"Languages: {', '.join(languages)}")
        storage_mb = data.get("storage_path_mb")
        if storage_mb is not None:
            db_parts.append(f"DB on disk: {storage_mb} MB")
        db_content = Group(*db_parts)
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
    """Single-line summary from dashboard data. Caller checks index_status.error first."""
    parts: list[str] = []
    prefix = f"{spinner} dashboard".strip() if spinner else "dashboard"

    collections = data.get("collections") or []
    index_status = data.get("index_status") or {}
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
        versions = index_status.get("versions") or []
        if versions:
            ver_str = ",".join(versions[:5])
            if len(versions) > 5:
                ver_str += f"+{len(versions) - 5}"
            parts.append(f"1C: {ver_str}")
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
        parts.append("Ingest: нет данных")

    failed_tasks = data.get("failed_tasks") or []
    total_err = (data.get("ingest_last_run") or {}).get("failed_count") or len(failed_tasks)
    if total_err > 0 and failed_tasks:
        err0 = (failed_tasks[0].get("error") or "")[:80]
        if len(failed_tasks[0].get("error") or "") > 80:
            err0 += "…"
        parts.append(f"Failed: {total_err} {err0}")

    std_pts = data.get("standards_loading_pts")
    if data.get("standards_loading"):
        parts.append(
            f"Standards: loading {std_pts.get('loaded', 0)}/{std_pts.get('total', 0)} pts"
            if std_pts
            else "Standards: loading…"
        )
    snip_pts = data.get("snippets_loading_pts")
    if data.get("snippets_loading"):
        parts.append(
            f"Snippets: loading {snip_pts.get('loaded', 0)}/{snip_pts.get('total', 0)} pts"
            if snip_pts
            else "Snippets: loading…"
        )

    snippets = data.get("snippets")
    if snippets:
        items = snippets.get("items_loaded")
        parts.append(f"Snippets ✓ {items} items" if items is not None else "Snippets ✓")

    return f"{prefix} │ {' │ '.join(parts)}\n"
