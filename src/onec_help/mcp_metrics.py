"""Compatibility alias for runtime MCP metrics helpers."""

import sys

from .runtime import mcp_metrics as _impl

sys.modules[__name__] = _impl
