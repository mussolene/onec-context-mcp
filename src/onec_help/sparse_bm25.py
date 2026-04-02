"""Compatibility alias for search store sparse BM25 helpers."""

import sys

from .search_store import sparse_bm25 as _impl

sys.modules[__name__] = _impl
