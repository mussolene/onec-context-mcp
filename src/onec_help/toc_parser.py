"""Compatibility alias for help core TOC parser helpers."""

import sys

from .help_core import toc_parser as _impl

sys.modules[__name__] = _impl
