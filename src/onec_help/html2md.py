"""Compatibility alias for help core HTML-to-Markdown helpers."""

import sys

from .help_core import html2md as _impl

sys.modules[__name__] = _impl
