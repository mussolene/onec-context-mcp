"""Compatibility alias for knowledge memory helpers."""

import sys

from .knowledge import memory as _impl

sys.modules[__name__] = _impl
