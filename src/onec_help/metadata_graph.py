"""Compatibility alias for knowledge metadata graph helpers."""

import sys

from .knowledge import metadata_graph as _impl

sys.modules[__name__] = _impl
