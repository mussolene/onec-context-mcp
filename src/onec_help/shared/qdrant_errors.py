"""Detect transport failures when calling Qdrant (empty MCP/search fallbacks)."""

from __future__ import annotations

import errno


def is_qdrant_unreachable_error(exc: BaseException) -> bool:
    """True for refused connection, timeouts, DNS — not for logical/API errors."""
    if isinstance(exc, (ConnectionError, BrokenPipeError, TimeoutError)):
        return True
    if isinstance(exc, OSError):
        no = getattr(exc, "errno", None)
        if no in (
            errno.ECONNREFUSED,
            errno.ECONNRESET,
            errno.ETIMEDOUT,
            errno.EHOSTUNREACH,
            errno.ENETUNREACH,
        ):
            return True
    msg = str(exc).lower()
    return any(
        x in msg
        for x in (
            "connection refused",
            "connection reset",
            "failed to establish",
            "connecterror",
            "connect error",
            "name or service not known",
            "nodename nor servname",
            "timed out",
            "timeout",
            "no route to host",
            "network is unreachable",
        )
    )
