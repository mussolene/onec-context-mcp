"""Tests for dashboard_render.render_dashboard()."""

from onec_help.dashboard_render import render_dashboard


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
    }
    result = render_dashboard(data)
    console = Console(force_terminal=True, no_color=True)
    with console.capture() as cap:
        console.print(result)
    out = cap.get()
    assert "timeout" in out or "8.3" in out or "ru" in out
