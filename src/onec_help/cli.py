"""Compatibility alias for CLI entry points."""

import sys

from .interfaces import cli as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())

sys.modules[__name__] = _impl
