"""Compatibility alias for shared HTTP helpers."""

import sys

from .shared import _http as _impl

sys.modules[__name__] = _impl
