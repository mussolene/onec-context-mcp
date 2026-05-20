"""1C Context MCP: unpack HBK, build structured JSONL, index, MCP server."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("onec-context-mcp")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"
