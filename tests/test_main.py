"""Test __main__ entry point."""

import runpy
from unittest.mock import patch

import pytest


def test_main_entry() -> None:
    with patch("sys.argv", ["onec_help", "unpack", "--help"]):
        from onec_help.__main__ import main

        with pytest.raises(SystemExit):
            main()


def test_main_module_as_main_raises_system_exit() -> None:
    """Running __main__ as script (run_name='__main__') raises SystemExit(main())."""
    with patch("sys.argv", ["onec_help", "--help"]):
        with patch("onec_help.interfaces.cli.main", return_value=0):
            with pytest.raises(SystemExit) as exc_info:
                runpy.run_module("onec_help.__main__", run_name="__main__")
            assert exc_info.value.code == 0
