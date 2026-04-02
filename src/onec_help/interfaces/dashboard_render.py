"""Render dashboard data as Rich panels (Tasks, Errors, Database)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..shared._utils import format_duration

if TYPE_CHECKING:
    from rich.text import Text


def _dim(text: str) -> Text:
    """Dimmed text via style (avoids raw [dim] tags when Console markup is disabled, e.g. non-TTY)."""
    from rich.text import Text

    return Text(text, style="dim")


def _format_loader_summary(
    title: str,
    *,
    loading: bool,
    pts: dict[str, Any] | None,
    last_run: dict[str, Any] | None,
    count_key: str,
    count_label: str,
    no_data: str,
) -> str:
    """Render a single status line for a background loader."""
    if loading:
        if pts:
            phase = str(pts.get("phase") or "embedding")
            loaded = int(pts.get("loaded") or 0)
            total = int(pts.get("total") or 0)
            if phase == "parsing":
                return f"{title}: loading (parsing)"
            if total > 0:
                return f"{title}: loading ({phase} → Qdrant, {loaded}/{total})"
            return f"{title}: loading ({phase})"
        return f"{title}: loading"
    if last_run:
        count = last_run.get(count_key)
        elapsed = last_run.get("total_elapsed_sec")
        parts = [f"{title}: last run"]
        if count is not None:
            if isinstance(count, int):
                parts.append(f", {count:,} {count_label}")
            else:
                parts.append(f", {count} {count_label}")
        if elapsed is not None:
            parts.append(f", {format_duration(elapsed)}")
        return "".join(parts)
    return f"{title}: {no_data}"


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
    active_workers: list[dict[str, Any]] = []
    ingest = data.get("ingest")
    ingest_last = data.get("ingest_last_run")
    ingest_last_stale = bool(data.get("ingest_last_run_stale"))
    standards_loading = bool(data.get("standards_loading"))
    standards_pts = data.get("standards_loading_pts")
    snippets_loading = bool(data.get("snippets_loading"))
    snippets_pts = data.get("snippets_loading_pts")
    metadata_loading = bool(data.get("metadata_loading"))
    metadata_pts = data.get("metadata_loading_pts")
    snippets = data.get("snippets")
    standards_last = data.get("standards_last_run")
    metadata_last = data.get("metadata_last_run")
    if ingest and ingest.get("status") == "in_progress":
        total = ingest.get("total_tasks") or 0
        done = ingest.get("done_tasks") or 0
        elapsed = ingest.get("elapsed_sec") or 0
        total_pts = ingest.get("total_points") or 0
        current_tasks = ingest.get("current") or []
        in_progress_pts = sum(int(c.get("points") or 0) for c in current_tasks)
        pts_so_far = total_pts + in_progress_pts
        est_pts = ingest.get("estimated_total_points")
        eta = ""
        eta_sec_from_ingest = ingest.get("eta_sec")
        if (
            eta_sec_from_ingest is not None
            and isinstance(eta_sec_from_ingest, (int, float))
            and eta_sec_from_ingest >= 0
        ):
            eta = f", ETA {format_duration(eta_sec_from_ingest)}"
        elif done and total and done < total and elapsed:
            try:
                rate = elapsed / done
                eta_sec = rate * (total - done)
                eta = f", ETA {format_duration(eta_sec)}"
            except (ZeroDivisionError, TypeError):
                pass
        pts_str = ""
        if pts_so_far > 0 or est_pts:
            pts_str = f", {pts_so_far} pts" if pts_so_far > 0 else ""
            if est_pts is not None and est_pts > 0:
                pts_str += f" (est. ~{est_pts})"
        ingest_line = (
            f"Ingest: in progress {done}/{total}{pts_str}{eta} ({format_duration(elapsed)} elapsed)"
        )
        last_batch = ingest.get("last_batch_sec")
        if last_batch is not None and isinstance(last_batch, (int, float)) and last_batch > 0:
            ingest_line += f"  │  Last batch: {last_batch}s"
        tasks_parts.append(Text(ingest_line + "\n"))
        mw = ingest.get("max_workers")
        ew = ingest.get("embedding_workers")
        if mw is not None or ew is not None:
            parts = []
            if mw is not None:
                parts.append(f"Ingest slots: {mw}")
            if ew is not None:
                parts.append(f"Embedding workers: {ew}")
            tasks_parts.append(Text("  " + "  │  ".join(parts) + "\n"))
        for cur in (current_tasks or [])[:10]:
            version = (cur.get("version") or "—")[:12]
            lang = (cur.get("language") or "—")[:8]
            path = (cur.get("path") or "—")[:28]
            stage = cur.get("stage") or "—"
            pts = cur.get("points")
            est = cur.get("estimated_total")
            stage_label = (
                "embed"
                if stage == "embedding"
                else "Qdrant"
                if stage == "writing"
                else "index"
                if stage == "indexing"
                else (stage or "indexing")[:8]
            )
            label = f"{version}/{lang} — {path} — {stage_label}"
            # Avoid "8.2.19.130/8.2.19.130/1cv": use stem (part after last /) when path looks like version/stem
            path_str = cur.get("path") or "—"
            stem = path_str.split("/")[-1][:14] if "/" in path_str else path_str[:14]
            short = f"{version[:10]}/{stem} {stage_label}"
            active_workers.append({"label": label, "short": short, "pts": pts, "total": est})
        if not active_workers:
            pts = ingest.get("current_task_points")
            est = ingest.get("current_task_estimated_total")
            if pts is not None and est is not None and est > 0:
                active_workers.append(
                    {
                        "label": "Ingest (current)",
                        "short": "Ingest (current)",
                        "pts": pts,
                        "total": est,
                    }
                )
        if standards_loading and standards_pts and standards_pts.get("phase") != "parsing":
            tot_s = standards_pts.get("total") or 0
            if tot_s > 0:
                active_workers.append(
                    {
                        "label": "Standards — embed → Qdrant",
                        "short": "Standards → Qdrant",
                        "pts": standards_pts.get("loaded", 0),
                        "total": tot_s,
                    }
                )
        if snippets_loading and snippets_pts and snippets_pts.get("phase") != "parsing":
            tot_sn = snippets_pts.get("total") or 0
            if tot_sn > 0:
                active_workers.append(
                    {
                        "label": "Snippets — embed → Qdrant",
                        "short": "Snippets → Qdrant",
                        "pts": snippets_pts.get("loaded", 0),
                        "total": tot_sn,
                    }
                )
        metadata_loading_w = metadata_loading
        metadata_pts_w = metadata_pts
        if metadata_loading_w and metadata_pts_w and metadata_pts_w.get("phase") not in ("parsing", None):
            tot_m = metadata_pts_w.get("total") or 0
            if tot_m > 0:
                phase_m = metadata_pts_w.get("phase") or "embedding"
                active_workers.append(
                    {
                        "label": f"Config metadata — {phase_m} → Qdrant",
                        "short": "Metadata → Qdrant",
                        "pts": metadata_pts_w.get("loaded", 0),
                        "total": tot_m,
                    }
                )
        elif metadata_loading_w:
            active_workers.append(
                {
                    "label": "Config metadata — parsing",
                    "short": "Metadata parsing",
                    "pts": None,
                    "total": None,
                }
            )
    elif ingest_last and not ingest_last_stale:
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
    elif ingest_last_stale and ingest_last:
        total = ingest_last.get("total_tasks") or 0
        done = ingest_last.get("done_tasks") or 0
        tasks_parts.append(
            Text(
                f"Ingest: no active run (stale persisted state {done}/{total}, not completed)",
                style="yellow",
            )
        )
    else:
        tasks_parts.append(Text("Ingest: no data"))

    if not (ingest and ingest.get("status") == "in_progress") and (
        standards_loading or snippets_loading or metadata_loading
    ):
        if standards_loading and standards_pts and standards_pts.get("phase") != "parsing":
            tot_s = standards_pts.get("total") or 0
            if tot_s > 0:
                active_workers.append(
                    {
                        "label": "Standards — embed → Qdrant",
                        "short": "Standards → Qdrant",
                        "pts": standards_pts.get("loaded", 0),
                        "total": tot_s,
                    }
                )
        elif standards_loading:
            active_workers.append(
                {
                    "label": "Standards — parsing",
                    "short": "Standards parsing",
                    "pts": None,
                    "total": None,
                }
            )
        if snippets_loading and snippets_pts and snippets_pts.get("phase") != "parsing":
            tot_sn = snippets_pts.get("total") or 0
            if tot_sn > 0:
                active_workers.append(
                    {
                        "label": "Snippets — embed → Qdrant",
                        "short": "Snippets → Qdrant",
                        "pts": snippets_pts.get("loaded", 0),
                        "total": tot_sn,
                    }
                )
        elif snippets_loading:
            active_workers.append(
                {
                    "label": "Snippets — parsing",
                    "short": "Snippets parsing",
                    "pts": None,
                    "total": None,
                }
            )
        if metadata_loading and metadata_pts and metadata_pts.get("phase") not in ("parsing", None):
            tot_m = metadata_pts.get("total") or 0
            if tot_m > 0:
                phase = metadata_pts.get("phase") or "embedding"
                active_workers.append(
                    {
                        "label": f"Config metadata — {phase} → Qdrant",
                        "short": "Metadata → Qdrant",
                        "pts": metadata_pts.get("loaded", 0),
                        "total": tot_m,
                    }
                )
        elif metadata_loading:
            active_workers.append(
                {
                    "label": "Config metadata — parsing",
                    "short": "Metadata parsing",
                    "pts": None,
                    "total": None,
                }
            )

    tasks_parts.append(
        Text(
            "\n"
            + _format_loader_summary(
                "Standards",
                loading=standards_loading,
                pts=standards_pts,
                last_run=standards_last,
                count_key="items_loaded",
                count_label="items",
                no_data="no data (watchdog or load-standards)",
            )
        )
    )
    tasks_parts.append(
        Text(
            "\n"
            + _format_loader_summary(
                "Snippets",
                loading=snippets_loading,
                pts=snippets_pts,
                last_run=snippets,
                count_key="items_loaded",
                count_label="items",
                no_data="no data (watchdog or load-snippets)",
            )
        )
    )
    if metadata_loading or metadata_last:
        metadata_summary = _format_loader_summary(
            "Config metadata",
            loading=metadata_loading,
            pts=metadata_pts,
            last_run=metadata_last,
            count_key="objects_indexed",
            count_label="objects",
            no_data="no data",
        )
    else:
        meta_coll = next(
            (
                c
                for c in (data.get("collections") or [])
                if (c.get("name") or "").strip() == "onec_config_metadata"
            ),
            None,
        )
        meta_pts = (meta_coll.get("points_count") or 0) if meta_coll else 0
        if meta_pts > 0:
            metadata_summary = f"Config metadata: {meta_pts:,} objects (onec_config_metadata)"
        else:
            metadata_summary = (
                "Config metadata: no data (put KD2 XML in data/kd2, then run "
                "metadata-graph-build or watchdog)"
            )
    tasks_parts.append(Text("\n" + metadata_summary))

    if active_workers:
        workers_table = Table(show_header=False, box=None, padding=(0, 1))
        workers_table.add_column(style="dim", width=4)
        workers_table.add_column(max_width=38)
        workers_table.add_column(min_width=20, max_width=28)
        for idx, w in enumerate(active_workers):
            i = idx + 1
            pts_val = w.get("pts")
            total_val = w.get("total")
            short = w.get("short") or w["label"]
            short = short if len(short) <= 38 else (short[:35] + "…")
            if total_val is not None and total_val > 0:
                workers_table.add_row(
                    Text(f"[{i}]"),
                    Text(f"{short} {(pts_val or 0)}/{total_val}"),
                    ProgressBar(total=float(total_val), completed=float(pts_val or 0), width=22),
                )
            else:
                workers_table.add_row(Text(f"[{i}]"), Text(short), Text("—"))
        tasks_parts.append(Text(f"\n  Active tasks: {len(active_workers)}\n"))
        tasks_parts.append(workers_table)
        current_tasks = (ingest or {}).get("current") or []
        if ingest and ingest.get("status") == "in_progress" and current_tasks and len(current_tasks) > 10:
            tasks_parts.append(Text(f"  … +{len(current_tasks) - 10} more\n"))

    tasks_content: Any = Group(*tasks_parts)
    panels.append(Panel(tasks_content, title="[bold]Tasks[/bold]", border_style="blue"))

    # --- Panel 2: Errors (ingest only; MCP errors are in panel "MCP requests") ---
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
            _dim("Ingest errors (Redis). MCP errors → see panel «MCP requests»."),
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
            panels.append(
                Panel(
                    Group(
                        Text("—\n"),
                        _dim(
                            "Ingest only. MCP errors → «MCP requests» or docker compose logs mcp."
                        ),
                    ),
                    title="[bold]Errors[/bold]",
                    border_style="dim",
                )
            )

    # --- Panel 3: Database (Qdrant actual data only; not mixed with loading progress) ---
    index_status = data.get("index_status") or {}
    collections = data.get("collections") or []
    standards_loading_db = data.get("standards_loading")
    snippets_loading_db = data.get("snippets_loading")
    metadata_loading_db = data.get("metadata_loading")
    if index_status.get("error"):
        db_content = f"Qdrant: [red]{index_status.get('error', 'error')}[/red]"
    elif collections:
        db_table = Table(show_header=True, header_style="bold")
        db_table.add_column("Collection")
        db_table.add_column("Points")
        db_table.add_column("Indexed vectors")
        db_table.add_column("Segments")
        db_table.add_column("BM25")
        db_table.add_column("Status")
        for c in collections:
            name = c.get("name") or "—"
            pts = c.get("points_count")
            vecs = c.get("indexed_vectors_count")
            segs = c.get("segments_count")
            bm25 = c.get("bm25")
            status = c.get("status") or "—"
            bm25_str = "yes" if bm25 else "no"
            db_table.add_row(
                name,
                str(pts) if pts is not None else "—",
                str(vecs) if vecs is not None else "—",
                str(segs) if segs is not None else "—",
                bm25_str,
                str(status),
            )
        db_parts = [
            db_table,
            _dim(
                "Points ≈ stored count (Qdrant API); Indexed vectors = in search index; can differ. BM25 = sparse vector text-bm25."
            ),
        ]
        # When BM25 is present, indexed_vectors_count often stays = points until optimizer builds sparse index (then ~2×)
        if any(
            c.get("bm25")
            and c.get("indexed_vectors_count") is not None
            and c.get("points_count")
            and c.get("indexed_vectors_count") == c.get("points_count")
            for c in collections
        ):
            db_parts.append(
                _dim(
                    "Indexed = Points for BM25 collection: sparse index may not be built yet (optimizer async). Status yellow = optimizing; grey = trigger in Qdrant Web UI. Expect ~2× when done."
                )
            )
        bm25_vocab = data.get("bm25_vocab") or {}
        if bm25_vocab:
            vocab_lines = [
                f"BM25 vocab: {name} — {st.get('terms', 0):,} terms, {st.get('documents', 0):,} docs"
                for name, st in bm25_vocab.items()
            ]
            db_parts.append(Text("\n".join(vocab_lines)))
        if standards_loading_db or snippets_loading_db:
            db_parts.append(
                _dim("Updating: standards/snippets → onec_help_memory (progress in Tasks)")
            )
        if metadata_loading_db:
            db_parts.append(_dim("Updating: config metadata graph (progress in Tasks)"))
        # onec_help_memory = standards + snippets + save_1c_snippet; pts may be less than sum of sources until load completes
        for c in collections or []:
            if (c.get("name") or "").strip() == "onec_help_memory":
                db_parts.append(_dim("onec_help_memory: standards + snippets + save_1c_snippet"))
                break
        for c in collections or []:
            if (c.get("name") or "").strip() == "onec_config_metadata":
                db_parts.append(
                    _dim(
                        "onec_config_metadata: config objects from data/kd2 (metadata-graph-build)"
                    )
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
    max_sec = mcp.get("max_response_sec")
    errors_total = mcp.get("errors_total", 0) or 0
    errors_recent = mcp.get("errors_recent") or []
    per_tool: dict[str, int] = mcp.get("per_tool") or {}
    mcp_line = f"Total: {total}  │  Last hour: {last_hour}"
    if max_sec is not None and isinstance(max_sec, (int, float)) and max_sec > 0:
        mcp_line += f"  │  Max response: {format_duration(max_sec)}"
    if errors_total > 0:
        mcp_line += f"  │  Errors: {errors_total}"
    mcp_parts: list[Any] = [Text(mcp_line)]
    if per_tool:
        tool_table = Table(show_header=False, box=None, padding=(0, 1))
        tool_table.add_column(style="dim", min_width=36)
        tool_table.add_column(justify="right")
        for tool, count in list(per_tool.items())[:15]:
            tool_table.add_row(tool, str(count))
        mcp_parts += [Text(""), _dim("Calls by tool:"), tool_table]
    if errors_recent:
        mcp_parts += [
            Text(""),
            _dim("Last errors:"),
            *[
                Text(f"  {e.get('tool', '?')}: {(e.get('error') or '')[:80]}")
                for e in errors_recent[:5]
            ],
        ]
    mcp_parts += [Text(""), _dim("Full MCP logs: docker compose logs mcp.")]
    if total == 0 and last_hour == 0:
        mcp_parts += [
            _dim(
                "0 requests — call an MCP tool from Cursor (e.g. get_1c_help_index_status). Same REDIS_URL for MCP and dashboard (Docker: redis://redis:6379/0)."
            ),
            _dim("MCP errors (tools + protocol) appear here; full logs: docker compose logs mcp."),
        ]
    mcp_content = Group(*mcp_parts)
    panels.append(Panel(mcp_content, title="[bold]MCP requests[/bold]", border_style="cyan"))

    return Group(*panels)
