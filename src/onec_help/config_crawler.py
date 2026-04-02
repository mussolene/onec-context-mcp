"""Compatibility alias for knowledge config crawler helpers."""

import sys

from .knowledge import config_crawler as _impl

sys.modules[__name__] = _impl
