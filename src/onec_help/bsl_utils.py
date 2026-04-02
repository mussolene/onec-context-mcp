"""Compatibility alias for knowledge BSL helpers."""

import sys

from .knowledge import bsl_utils as _impl

sys.modules[__name__] = _impl
