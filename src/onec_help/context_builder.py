"""Compatibility alias for knowledge task context helpers."""

import sys

from .knowledge import context_builder as _impl

sys.modules[__name__] = _impl
