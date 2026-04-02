"""Compatibility alias for shared environment helpers."""

import sys

from .shared import env_config as _impl

sys.modules[__name__] = _impl
