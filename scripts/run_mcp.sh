#!/usr/bin/env bash
# Run 1C Help MCP server from project root. Sets PYTHONPATH so pip install is not required.
# Requires Python 3.11+ for fastmcp.

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src"
HELP_DIR="${HELP_DIR:-.}"

# Prefer Python 3.11+ (required by fastmcp)
for py in python3.14 python3.12 python3.11 python3; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c "import fastmcp" 2>/dev/null; then
    exec "$py" -m onec_help mcp "$HELP_DIR"
  fi
done
echo "1c-help MCP: need Python 3.11+ and fastmcp. Run: pip install -e \".[mcp]\" (in a venv with Python 3.11+)." >&2
exit 1
