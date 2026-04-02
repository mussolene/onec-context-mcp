"""Compatibility alias for runtime Redis cache helpers."""

import sys

from .runtime import redis_cache as _impl

sys.modules[__name__] = _impl
