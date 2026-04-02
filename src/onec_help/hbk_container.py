"""Compatibility alias for help core HBK container helpers."""

import sys

from .help_core import hbk_container as _impl

sys.modules[__name__] = _impl
