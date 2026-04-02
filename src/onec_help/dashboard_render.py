"""Compatibility alias for dashboard rendering helpers."""

import sys

from .interfaces import dashboard_render as _impl

sys.modules[__name__] = _impl
