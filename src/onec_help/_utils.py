"""Compatibility alias for shared utility helpers."""

import sys

from .shared import _utils as _impl

sys.modules[__name__] = _impl
