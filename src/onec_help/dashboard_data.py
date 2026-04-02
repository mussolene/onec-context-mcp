"""Compatibility alias for runtime dashboard data helpers."""

import sys

from .runtime import dashboard_data as _impl

sys.modules[__name__] = _impl
