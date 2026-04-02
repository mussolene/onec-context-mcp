"""Compatibility alias for knowledge form metadata helpers."""

import sys

from .knowledge import form_metadata as _impl

sys.modules[__name__] = _impl
