"""Compatibility alias for search store embedding helpers."""

import sys

from .search_store import embedding as _impl

sys.modules[__name__] = _impl
