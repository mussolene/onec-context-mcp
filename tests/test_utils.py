"""Tests for _utils."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from onec_help._utils import (
    dir_size_on_disk,
    format_duration,
    mask_path_for_log,
    path_inside_base,
    progress_done,
    progress_line,
    safe_error_message,
)


def test_safe_error_message_production_hides_detail() -> None:
    """In production, only exception type is returned."""
    e = ValueError("sensitive path /home/secret")
    assert safe_error_message(e, production=True) == "ValueError"


def test_safe_error_message_non_production_shows_detail() -> None:
    """When not production, full message is included."""
    e = ValueError("disk full")
    assert "disk full" in safe_error_message(e, production=False)


def test_mask_path_for_log_exception_returns_placeholder() -> None:
    """When Path() raises, return safe placeholder."""
    with patch.object(Path, "__new__", side_effect=TypeError("bad")):
        assert mask_path_for_log("anything") == "<path>"


def test_mask_path_for_log_root_uses_fallback() -> None:
    """Path('/') has empty name; uses str(p)[-50:] fallback."""
    result = mask_path_for_log(Path("/"))
    assert result
    assert result != "<path>"


def test_progress_line_non_tty_no_overwrite() -> None:
    """When stderr is not TTY, use plain newline."""
    with patch("sys.stderr") as stderr:
        stderr.isatty.return_value = False
        progress_line("hello", overwrite=True)
        stderr.write.assert_called()
        call_args = "".join(c[0][0] for c in stderr.write.call_args_list)
        assert "\n" in call_args or "hello" in call_args


def test_progress_done_writes_newline() -> None:
    """progress_done writes message with newline (fallback path when Rich disabled)."""
    with patch("onec_help._utils._rich_console", return_value=None), patch("sys.stderr") as stderr:
        progress_done("done")
        stderr.write.assert_called_once()
        assert stderr.write.call_args[0][0].endswith("\n")
        assert "done" in stderr.write.call_args[0][0]


def test_progress_line_uses_rich_when_tty() -> None:
    """When TTY and Rich available, progress_line uses console.print."""
    fake_console = MagicMock()
    with patch("sys.stderr") as stderr:
        stderr.isatty.return_value = True
        with patch("onec_help._utils._rich_console", return_value=fake_console):
            progress_line("hello", overwrite=True)
    fake_console.print.assert_called_once()
    assert fake_console.print.call_args[0][0] == "hello"
    assert fake_console.print.call_args[1].get("end") == "\r"


def test_progress_done_uses_rich_when_tty() -> None:
    """When TTY and Rich available, progress_done uses console.print."""
    fake_console = MagicMock()
    with patch("sys.stderr") as stderr:
        stderr.isatty.return_value = True
        with patch("onec_help._utils._rich_console", return_value=fake_console):
            progress_done("done")
    fake_console.print.assert_called_once_with("done")


def test_rich_console_returns_none_when_import_error() -> None:
    """_rich_console returns None when rich.console is not available (line 36-37)."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "rich.console":
            raise ImportError("No module named 'rich.console'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        from onec_help._utils import _rich_console as _rc

        assert _rc() is None


def test_rich_console_returns_none_when_rich_not_available() -> None:
    """When rich.console cannot be imported, _rich_console returns None; progress_line uses stderr."""
    real_import = __import__

    def mock_import(name, *args, **kwargs):
        if name == "rich.console":
            raise ImportError("No module named 'rich'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import), patch("sys.stderr") as stderr:
        stderr.isatty.return_value = True
        progress_line("fallback")
    stderr.write.assert_called()
    assert "fallback" in "".join(c[0][0] for c in stderr.write.call_args_list)


def test_progress_line_overwrite_false_uses_print_no_carriage_return() -> None:
    """When overwrite=False, progress_line uses console.print without end='\\r'."""
    fake_console = MagicMock()
    with patch("sys.stderr") as stderr:
        stderr.isatty.return_value = True
        with patch("onec_help._utils._rich_console", return_value=fake_console):
            progress_line("msg", overwrite=False)
    fake_console.print.assert_called_once_with("msg")


def test_progress_line_console_raises_fallback_to_stderr() -> None:
    """When console.print raises, progress_line falls back to stderr."""
    fake_console = MagicMock()
    fake_console.print.side_effect = OSError("write failed")
    with patch("sys.stderr") as stderr:
        stderr.isatty.return_value = True
        with patch("onec_help._utils._rich_console", return_value=fake_console):
            progress_line("fallback")
    stderr.write.assert_called()
    assert "fallback" in "".join(c[0][0] for c in stderr.write.call_args_list)


def test_progress_done_console_raises_fallback_to_stderr() -> None:
    """When console.print raises in progress_done, fall back to stderr."""
    fake_console = MagicMock()
    fake_console.print.side_effect = RuntimeError("display error")
    with patch("sys.stderr") as stderr:
        stderr.isatty.return_value = True
        with patch("onec_help._utils._rich_console", return_value=fake_console):
            progress_done("fallback")
    stderr.write.assert_called_once()
    assert "fallback" in stderr.write.call_args[0][0]


def test_format_duration() -> None:
    """format_duration returns human-readable strings."""
    assert format_duration(0) == "0s"
    assert format_duration(45) == "45s"
    assert format_duration(90) == "1m 30s"
    assert format_duration(125) == "2m 5s"
    assert format_duration(3661) == "1h 1m"
    assert format_duration(7200) == "2h"
    assert format_duration(90061) == "1d 1h"
    assert format_duration(-1) == "—"
    assert format_duration(float("nan")) == "—"
    assert format_duration(3605) == "1h 5s"
    assert format_duration(86700) == "1d 5m"


def test_path_inside_base_valueerror_returns_false() -> None:
    """When resolve raises ValueError, return False."""
    base = Path("/base")
    path = base / "file"
    with patch.object(Path, "resolve", side_effect=ValueError("invalid")):
        assert path_inside_base(path, base) is False


def test_path_inside_base_path_equals_base() -> None:
    """When path resolves to base itself, return True."""
    base = Path(__file__).resolve().parent
    assert path_inside_base(base, base) is True


def test_dir_size_on_disk_nonexistent_returns_zero() -> None:
    """Non-existent path returns 0."""
    assert dir_size_on_disk(Path("/nonexistent/path/xyz")) == 0


def test_dir_size_on_disk_file_not_dir_returns_zero(tmp_path: Path) -> None:
    """Passing a file path (not dir) returns 0."""
    f = tmp_path / "file.txt"
    f.write_text("x")
    assert dir_size_on_disk(f) == 0


def test_dir_size_on_disk(tmp_path: Path) -> None:
    """dir_size_on_disk sums file sizes; deduplicates hard links."""
    (tmp_path / "a.txt").write_text("x" * 100)
    (tmp_path / "b.txt").write_text("y" * 200)
    sz = dir_size_on_disk(tmp_path)
    assert sz >= 300


def test_dir_size_on_disk_stat_raises_skipped(tmp_path: Path) -> None:
    """OSError during stat() is skipped; fallback when st_blocks is 0."""
    (tmp_path / "a.txt").write_text("x" * 100)
    bad = tmp_path / "bad.txt"
    bad.write_text("y")
    original_stat = Path.stat

    def mock_stat(self):
        if str(self) == str(bad):
            raise OSError("permission denied")
        return original_stat(self)

    with patch.object(Path, "stat", mock_stat):
        sz = dir_size_on_disk(tmp_path)
    assert sz >= 100  # At least a.txt counted


def test_dir_size_on_disk_fallback_when_no_st_blocks(tmp_path: Path) -> None:
    """When st_blocks is 0 or missing, use fallback_bytes (sum of st_size)."""
    f = tmp_path / "f.txt"
    f.write_text("hello")
    original_stat = Path.stat
    target = str(f)

    def mock_stat(self):
        st = original_stat(self)
        # For files in our tmp dir, use st_blocks=0 to trigger fallback path
        if str(self) == target:
            return type(
                "FakeStat",
                (),
                {
                    "st_ino": st.st_ino,
                    "st_dev": st.st_dev,
                    "st_size": st.st_size,
                    "st_blocks": 0,
                    "st_mode": st.st_mode,
                },
            )()
        return st

    with patch.object(Path, "stat", mock_stat):
        sz = dir_size_on_disk(tmp_path)
    assert sz >= 5  # fallback_bytes from st_size


def test_dir_size_on_disk_hardlink(tmp_path: Path) -> None:
    """dir_size_on_disk counts hard-linked file once (matches du), not 2x."""
    import os

    target = tmp_path / "target"
    target.write_text("content" * 100)
    link = tmp_path / "link"
    try:
        os.link(target, link)
    except OSError:
        return
    sz_with_link = dir_size_on_disk(tmp_path)
    link.unlink(missing_ok=True)
    sz_single = dir_size_on_disk(tmp_path)
    assert sz_with_link <= sz_single * 1.1
