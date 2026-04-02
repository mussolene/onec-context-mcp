"""Compatibility alias for help core unpack helpers."""

import sys

from .help_core import unpack as _impl

sys.modules[__name__] = _impl
