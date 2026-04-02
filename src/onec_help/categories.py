"""Compatibility alias for help core categories helpers."""

import sys

from .help_core import categories as _impl

sys.modules[__name__] = _impl
