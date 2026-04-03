"""Tests for Qdrant transport error classification."""

import errno

import pytest

from onec_help.shared.qdrant_errors import is_qdrant_unreachable_error


def test_connection_refused_oserror() -> None:
    exc = OSError(errno.ECONNREFUSED, "Connection refused")
    assert is_qdrant_unreachable_error(exc) is True


def test_oserror_host_unreachable_errno() -> None:
    exc = OSError(errno.EHOSTUNREACH, "No route to host")
    assert is_qdrant_unreachable_error(exc) is True


def test_broken_pipe() -> None:
    assert is_qdrant_unreachable_error(BrokenPipeError()) is True


def test_connection_error_subclass() -> None:
    assert is_qdrant_unreachable_error(ConnectionRefusedError()) is True


def test_value_error_not_unreachable() -> None:
    assert is_qdrant_unreachable_error(ValueError("bad payload")) is False


@pytest.mark.parametrize(
    "msg",
    [
        "ConnectError: connection refused",
        "[Errno 111] Connection refused",
        "timed out waiting",
    ],
)
def test_message_heuristics(msg: str) -> None:
    assert is_qdrant_unreachable_error(RuntimeError(msg)) is True
