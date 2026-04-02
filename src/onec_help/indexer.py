"""Compatibility alias for search store index helpers."""

import sys

from .search_store import indexer as _impl

sys.modules[__name__] = _impl
