"""Compatibility alias for MCP server entry points."""

import sys

from .interfaces import mcp_server as _impl

if __name__ == "__main__":
    _impl._main()

sys.modules[__name__] = _impl
