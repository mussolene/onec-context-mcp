"""Tests for watchdog module."""

from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from onec_help.watchdog import (
    _process_pending_memory,
    _run_build_metadata_graph,
    _run_ingest,
    _run_load_snippets,
    _run_load_standards,
    _scan_config_dir_stable,
    _scan_snippets_dir,
    _scan_standards_dir,
    run_watchdog,
)


@contextmanager
def _watchdog_loop_mocks(
    *,
    sleep_raises_after: int = 1,
    raise_exc: type[BaseException] = StopIteration,
    run_ingest: Callable | None = None,
    run_load_standards: Callable | None = None,
):
    """Общие моки для тестов run_watchdog: состояние Redis, time, все run_* (no-op). sleep после N вызовов бросает raise_exc."""
    count = [0]

    def sleep(_sec: float) -> None:
        count[0] += 1
        if count[0] >= sleep_raises_after:
            raise raise_exc("stop")

    with (
        patch("onec_help.watchdog._load_watchdog_state", return_value={}),
        patch("onec_help.watchdog._save_watchdog_state"),
        patch("onec_help.watchdog.time.sleep", side_effect=sleep),
        patch("onec_help.watchdog.time.time", return_value=0.0),
        patch("onec_help.watchdog._run_ingest", side_effect=run_ingest),
        patch("onec_help.watchdog._run_load_standards", side_effect=run_load_standards),
        patch("onec_help.watchdog._run_load_snippets"),
        patch("onec_help.watchdog._run_build_metadata_graph"),
        patch("onec_help.watchdog._process_pending_memory"),
    ):
        yield


def test_run_watchdog_no_help_source_base(capsys: pytest.CaptureFixture[str]) -> None:
    """When HELP_SOURCE_BASE is not set, run_watchdog prints message and returns."""
    with patch.dict("os.environ", {}, clear=True):
        run_watchdog()
    err = capsys.readouterr().err
    assert "HELP_SOURCE_BASE not set" in err


def test_run_watchdog_base_not_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When HELP_SOURCE_BASE is not a directory, run_watchdog prints message and returns."""
    missing_dir = tmp_path / "nonexistent"
    run_watchdog(help_source_base=missing_dir)
    err = capsys.readouterr().err
    assert "not a directory" in err


def test_run_watchdog_base_is_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """When help_source_base is a file, run_watchdog prints message and returns."""
    f = tmp_path / "file.txt"
    f.write_text("x")
    run_watchdog(help_source_base=f)
    err = capsys.readouterr().err
    assert "not a directory" in err


def test_run_watchdog_help_source_base_from_env(tmp_path: Path) -> None:
    """When help_source_base is None, run_watchdog uses HELP_SOURCE_BASE from env."""
    with patch.dict("os.environ", {"HELP_SOURCE_BASE": str(tmp_path)}, clear=False):
        with _watchdog_loop_mocks():
            try:
                run_watchdog(help_source_base=None, poll_interval_sec=60, pending_interval_sec=60)
            except StopIteration:
                pass


def test_run_watchdog_one_iteration_then_stop(tmp_path: Path) -> None:
    """run_watchdog runs one iteration then exits when sleep raises (simulates KeyboardInterrupt)."""

    class StopAfterOne(Exception):
        pass

    with _watchdog_loop_mocks(raise_exc=StopAfterOne):
        with pytest.raises(StopAfterOne):
            run_watchdog(
                help_source_base=tmp_path,
                poll_interval_sec=60,
                pending_interval_sec=60,
            )


def test_run_watchdog_triggers_ingest_on_hbk_change(tmp_path: Path) -> None:
    """When .hbk files exist and differ from cache, _run_ingest is called."""
    (tmp_path / "8.3.27").mkdir()
    (tmp_path / "8.3.27" / "1cv8_ru.hbk").write_bytes(b"x")
    ingest_called: list[int] = []

    with _watchdog_loop_mocks(run_ingest=lambda: ingest_called.append(1)):
        try:
            run_watchdog(
                help_source_base=tmp_path,
                poll_interval_sec=60,
                pending_interval_sec=60,
            )
        except StopIteration:
            pass
    assert len(ingest_called) >= 1


def test_run_ingest_success() -> None:
    """_run_ingest runs subprocess without error when ingest succeeds."""
    with patch("onec_help.watchdog.subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"returncode": 0, "stdout": b"", "stderr": b""})()
        _run_ingest()
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert "onec_help" in call_args
    assert "ingest" in call_args


def test_run_ingest_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """_run_ingest logs when subprocess fails."""
    with patch("onec_help.watchdog.subprocess.run") as mock_run:
        mock_run.side_effect = OSError("7z not found")
        _run_ingest()
    err = capsys.readouterr().err
    assert "ingest failed" in err


def test_process_pending_memory_success(capsys: pytest.CaptureFixture[str]) -> None:
    """_process_pending_memory logs when entries are processed."""
    with patch("onec_help.memory.get_memory_store") as mock_get:
        mock_store = type("Store", (), {"process_pending": lambda self: 3})()
        mock_get.return_value = mock_store
        _process_pending_memory()
    err = capsys.readouterr().err
    assert "processed 3 pending" in err


def test_process_pending_memory_no_entries() -> None:
    """_process_pending_memory does not log when 0 entries processed."""
    with patch("onec_help.memory.get_memory_store") as mock_get:
        mock_store = type("Store", (), {"process_pending": lambda self: 0})()
        mock_get.return_value = mock_store
        _process_pending_memory()
    # No exception, no log for 0


def test_process_pending_memory_import_from_memory() -> None:
    """_process_pending_memory imports get_memory_store from memory module."""
    with patch("onec_help.memory.get_memory_store") as mock_get:
        mock_store = type("Store", (), {"process_pending": lambda self: 0})()
        mock_get.return_value = mock_store
        _process_pending_memory()
    mock_get.assert_called_once()


def test_scan_standards_dir_collects_md(tmp_path: Path) -> None:
    """_scan_standards_dir returns path->mtime for .md files only."""
    (tmp_path / "a.md").write_text("# One")
    (tmp_path / "b.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.md").write_text("# Two")
    out = _scan_standards_dir(tmp_path)
    assert len(out) == 2
    assert any("a.md" in p for p in out)
    assert any("c.md" in p for p in out)


def test_scan_snippets_dir_collects_json_bsl(tmp_path: Path) -> None:
    """_scan_snippets_dir returns path->mtime for .json, .bsl, .1c, .md."""
    (tmp_path / "x.json").write_text("[]")
    (tmp_path / "y.bsl").write_text("// code")
    (tmp_path / "z.1c").write_text("")
    out = _scan_snippets_dir(tmp_path)
    assert len(out) == 3


def test_scan_config_dir_stable_collects_xml_bsl(tmp_path: Path) -> None:
    """_scan_config_dir_stable returns path->size for .xml and .bsl only."""
    (tmp_path / "x.xml").write_text("<root/>")
    (tmp_path / "y.bsl").write_text("// code")
    (tmp_path / "z.txt").write_text("ignore")
    out = _scan_config_dir_stable(tmp_path)
    assert len(out) == 2
    assert any("x.xml" in p for p in out)
    assert any("y.bsl" in p for p in out)


def test_run_watchdog_triggers_load_standards_when_dir_changes(tmp_path: Path) -> None:
    """When STANDARDS_DIR exists and has .md files, first run calls _run_load_standards."""
    standards_dir = tmp_path / "st"
    standards_dir.mkdir()
    (standards_dir / "doc.md").write_text("# Doc")
    load_standards_called: list[str] = []

    with patch.dict("os.environ", {"STANDARDS_DIR": str(standards_dir)}, clear=False):
        with _watchdog_loop_mocks(
            run_load_standards=lambda path: load_standards_called.append(path)
        ):
            try:
                run_watchdog(
                    help_source_base=tmp_path,
                    poll_interval_sec=60,
                    pending_interval_sec=60,
                )
            except StopIteration:
                pass
    assert len(load_standards_called) >= 1
    assert load_standards_called[0] == str(standards_dir)


def test_run_load_standards_success() -> None:
    """_run_load_standards runs subprocess with path."""
    with patch("onec_help.watchdog.subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"returncode": 0})()
        _run_load_standards("/data/standards")
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert "load-standards" in call_args
    assert "/data/standards" in call_args


def test_run_load_snippets_success() -> None:
    """_run_load_snippets runs subprocess with path."""
    with patch("onec_help.watchdog.subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"returncode": 0})()
        _run_load_snippets("/data/snippets")
    mock_run.assert_called_once()
    assert "load-snippets" in mock_run.call_args[0][0]


def test_run_build_metadata_graph_success() -> None:
    """_run_build_metadata_graph runs subprocess with path."""
    with patch("onec_help.watchdog.subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"returncode": 0})()
        _run_build_metadata_graph("/data/config")
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert "metadata-graph-build" in call_args
    assert "/data/config" in call_args
