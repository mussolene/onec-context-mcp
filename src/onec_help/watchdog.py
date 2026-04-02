"""Compatibility alias for runtime watchdog helpers."""

import sys

from .runtime import watchdog as _impl

sys.modules[__name__] = _impl
