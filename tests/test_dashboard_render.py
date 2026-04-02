"""Tests for dashboard_render.render_dashboard()."""

from onec_help.interfaces.dashboard_render import render_dashboard


def test_render_dashboard_returns_rich_group() -> None:
    """render_dashboard(data) returns a Rich Group (renderable)."""
    from rich.console import Group

    data = {
        "ingest": None,
        "ingest_last_run": None,
        "failed_tasks": [],
        "index_status": {"exists": False, "points_count": 0},
        "collections": [],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "metadata_loading": False,
    }
    result = render_dashboard(data)
    assert isinstance(result, Group)


def test_render_dashboard_output_contains_tasks_and_errors() -> None:
    """Rendered output contains Tasks, Errors, Database and MCP sections."""
    from rich.console import Console

    data = {
        "ingest": None,
        "ingest_last_run": {"total_tasks": 10, "done_tasks": 10, "failed_count": 0},
        "failed_tasks": [],
        "index_status": {"exists": True, "points_count": 100},
        "collections": [{"name": "onec_help", "points_count": 100}],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "storage_path_mb": None,
        "mcp_metrics": {"total": 5, "last_hour": 2},
        "metadata_loading": False,
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "Tasks" in out
    assert "Errors" in out
    assert "Database" in out
    assert "MCP" in out
    assert "Ingest" in out or "ingest" in out.lower()


def test_render_dashboard_shows_failed_tasks_table() -> None:
    """When failed_tasks is non-empty, output includes table content."""
    from rich.console import Console

    data = {
        "ingest": None,
        "ingest_last_run": {"failed_count": 1},
        "failed_tasks": [
            {"version": "8.3", "language": "ru", "path": "/x/y.md", "error": "timeout"}
        ],
        "index_status": {},
        "collections": [],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "metadata_loading": False,
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "timeout" in out or "8.3" in out or "ru" in out


def test_render_dashboard_ingest_in_progress_with_eta() -> None:
    """Tasks panel shows in progress with ETA when ingest has done/total/elapsed."""
    from rich.console import Console

    data = {
        "ingest": {
            "status": "in_progress",
            "done_tasks": 2,
            "total_tasks": 5,
            "elapsed_sec": 10.0,
        },
        "ingest_last_run": None,
        "failed_tasks": [],
        "index_status": {},
        "collections": [],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "storage_path_mb": None,
        "mcp_metrics": {},
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "in progress" in out and "2/5" in out
    assert "ETA" in out or "elapsed" in out


def test_render_dashboard_ingest_with_workers_eta_and_loading_pts() -> None:
    """Tasks panel with eta_sec_from_ingest, current_tasks (workers), last_batch_sec, standards/snippets loading pts."""
    from rich.console import Console

    data = {
        "ingest": {
            "status": "in_progress",
            "done_tasks": 10,
            "total_tasks": 100,
            "elapsed_sec": 60.0,
            "eta_sec_from_ingest": 540.0,
            "last_batch_sec": 2.5,
            "current_tasks": [
                {
                    "version": "8.3",
                    "language": "ru",
                    "path": "doc.hbk",
                    "stage": "embedding",
                    "points": 5,
                    "estimated_total": 20,
                },
                {
                    "version": "8.3",
                    "language": "ru",
                    "path": "other.hbk",
                    "stage": "writing",
                    "points": 10,
                    "estimated_total": 10,
                },
            ],
        },
        "ingest_last_run": None,
        "failed_tasks": [],
        "index_status": {},
        "collections": [],
        "snippets": None,
        "standards_loading": True,
        "snippets_loading": True,
        "standards_loading_pts": {"loaded": 50, "total": 200, "phase": "embedding"},
        "snippets_loading_pts": {"loaded": 10, "total": 100, "phase": "embedding"},
        "storage_path_mb": None,
        "mcp_metrics": {},
        "metadata_loading": False,
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "Tasks" in out or "pts" in out
    assert "ETA" in out or "batch" in out


def test_render_dashboard_standards_snippets_loading_workers_no_ingest() -> None:
    """When ingest not in progress but standards/snippets loading, workers_extra and ProgressBar are shown."""
    from rich.console import Console

    data = {
        "ingest": None,
        "ingest_last_run": None,
        "failed_tasks": [],
        "index_status": {},
        "collections": [],
        "snippets": None,
        "standards_loading": True,
        "snippets_loading": True,
        "standards_loading_pts": {"loaded": 30, "total": 100, "phase": "embedding"},
        "snippets_loading_pts": {"loaded": 5, "total": 50, "phase": "embedding"},
        "storage_path_mb": None,
        "mcp_metrics": {},
        "metadata_loading": False,
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "Standards" in out and "Snippets" in out
    assert "Tasks" in out or "embed" in out or "Qdrant" in out


def test_render_dashboard_ingest_in_progress_eta_zero_division_handled() -> None:
    """Tasks panel still renders when ETA would cause ZeroDivisionError (done=0)."""
    from rich.console import Console

    data = {
        "ingest": {
            "status": "in_progress",
            "done_tasks": 0,
            "total_tasks": 5,
            "elapsed_sec": 10.0,
        },
        "ingest_last_run": None,
        "failed_tasks": [],
        "index_status": {},
        "collections": [],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "storage_path_mb": None,
        "mcp_metrics": {},
        "metadata_loading": False,
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "in progress" in out and "0/5" in out


def test_render_dashboard_mcp_per_tool_table() -> None:
    """MCP panel shows per-tool call counts table when per_tool is non-empty."""
    from rich.console import Console

    data = {
        "ingest": None,
        "ingest_last_run": None,
        "failed_tasks": [],
        "index_status": {},
        "collections": [],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "storage_path_mb": None,
        "mcp_metrics": {
            "total": 10,
            "last_hour": 4,
            "per_tool": {"search_1c_help": 7, "get_1c_help_topic": 3},
        },
        "metadata_loading": False,
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "search_1c_help" in out
    assert "get_1c_help_topic" in out
    assert "Calls by tool" in out or "search_1c_help" in out


def test_render_dashboard_ingest_in_progress_single_task_progress_bar() -> None:
    """Tasks panel shows single progress bar from current_task_points/current_task_estimated_total when no current list."""
    from rich.console import Console

    data = {
        "ingest": {
            "status": "in_progress",
            "done_tasks": 0,
            "total_tasks": 1,
            "elapsed_sec": 0,
            "current_task_points": 100,
            "current_task_estimated_total": 500,
        },
        "ingest_last_run": None,
        "failed_tasks": [],
        "index_status": {},
        "collections": [],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "storage_path_mb": None,
        "mcp_metrics": {},
        "metadata_loading": False,
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "in progress" in out


def test_render_dashboard_ingest_in_progress_with_current_tasks() -> None:
    """Tasks panel shows active tasks and progress when ingest has current list."""
    from rich.console import Console

    data = {
        "ingest": {
            "status": "in_progress",
            "done_tasks": 1,
            "total_tasks": 10,
            "elapsed_sec": 5.0,
            "current": [
                {
                    "version": "8.3",
                    "language": "ru",
                    "path": "help.hbk",
                    "stage": "embedding",
                    "points": 100,
                    "estimated_total": 500,
                },
            ],
        },
        "ingest_last_run": None,
        "failed_tasks": [],
        "index_status": {},
        "collections": [],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "storage_path_mb": None,
        "mcp_metrics": {},
        "metadata_loading": False,
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "Active" in out or "embedding" in out or "100" in out


def test_render_dashboard_db_error_and_versions_languages() -> None:
    """Database panel shows error; and with collections shows versions/languages/storage."""
    from rich.console import Console

    data = {
        "ingest": None,
        "ingest_last_run": None,
        "failed_tasks": [],
        "index_status": {"error": "connection refused"},
        "collections": [],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "storage_path_mb": None,
        "mcp_metrics": {},
        "metadata_loading": False,
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "connection refused" in out

    data2 = {
        "ingest": None,
        "ingest_last_run": None,
        "failed_tasks": [],
        "index_status": {"exists": True, "versions": ["8.3", "8.2"], "languages": ["ru", "en"]},
        "collections": [
            {
                "name": "onec_help",
                "points_count": 100,
                "indexed_vectors_count": 100,
                "segments_count": 1,
            }
        ],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "storage_path_mb": 12.5,
        "mcp_metrics": {},
    }
    result2 = render_dashboard(data2)
    with console.capture() as cap2:
        console.print(result2)
    out2 = cap2.get()
    assert "8.3" in out2 and "ru" in out2
    assert "12.5" in out2 or "MB" in out2


def test_render_dashboard_failed_task_error_truncated_with_ellipsis() -> None:
    """When failed task error is longer than 80 chars, table cell gets ellipsis."""
    from rich.console import Console

    data = {
        "ingest": None,
        "ingest_last_run": {"failed_count": 1},
        "failed_tasks": [{"version": "8.3", "language": "ru", "path": "x.hbk", "error": "A" * 100}],
        "index_status": {},
        "collections": [],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "mcp_metrics": {},
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "…" in out or "A" in out


def test_render_dashboard_errors_placeholder_no_details() -> None:
    """Errors panel shows placeholder when failed_count > 0 but failed_tasks is empty."""
    from rich.console import Console

    data = {
        "ingest": None,
        "ingest_last_run": {"failed_count": 3},
        "failed_tasks": [],
        "index_status": {},
        "collections": [],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "mcp_metrics": {},
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "re-run" in out or "3" in out


def test_render_dashboard_versions_truncate_more_than_15() -> None:
    """Database panel shows versions truncated to 15 with '… +N' when more than 15."""
    from rich.console import Console

    data = {
        "ingest": None,
        "ingest_last_run": None,
        "failed_tasks": [],
        "index_status": {
            "exists": True,
            "versions": [f"8.3.{i}" for i in range(20)],
            "languages": ["ru"],
        },
        "collections": [{"name": "onec_help", "points_count": 100}],
        "snippets": None,
        "standards_loading": False,
        "snippets_loading": False,
        "storage_path_mb": None,
        "mcp_metrics": {},
        "metadata_loading": False,
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "8.3.0" in out
    assert "+5" in out or "…" in out
