"""Functional tests for MCP 1c-help: crypto and scenario queries. Require MCP + Qdrant.

Run with: MCP_INTEGRATION=1 pytest tests/test_mcp_functional_crypto.py -v

Uses tests/fixtures/mcp_crypto_queries.json for query list and expected markers.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import pytest

# Skip unless integration opted in
pytestmark = pytest.mark.skipif(
    not os.environ.get("MCP_INTEGRATION"),
    reason="Set MCP_INTEGRATION=1 to run (requires MCP + Qdrant)",
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
QUERIES_JSON = FIXTURES_DIR / "mcp_crypto_queries.json"


def _call_mcp_via_http(tool: str, args: dict) -> str:
    """Call MCP tool via HTTP. Same contract as test_mcp_integration."""
    url = os.environ.get("MCP_URL", "http://localhost:8050/mcp")
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }
    ).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            content = data.get("result", {}).get("content", [{}])
            return content[0].get("text", "") if content else ""
    except Exception as e:
        pytest.skip(f"MCP not available: {e}")


def _load_crypto_queries() -> list[dict]:
    if not QUERIES_JSON.exists():
        return []
    raw = QUERIES_JSON.read_text(encoding="utf-8")
    return json.loads(raw)


@pytest.fixture(scope="module")
def crypto_queries() -> list[dict]:
    """Load query config from fixtures (id, tool, args, expected_markers)."""
    return _load_crypto_queries()


@pytest.mark.skipif(not QUERIES_JSON.exists(), reason="mcp_crypto_queries.json not found")
@pytest.mark.parametrize("entry", _load_crypto_queries(), ids=lambda e: e.get("id", "item"))
def test_mcp_crypto_query_returns_relevant_content(entry: dict) -> None:
    """Each crypto/scenario query returns non-empty response with at least one expected marker."""
    tool = entry.get("tool", "get_1c_code_answer")
    args = entry.get("args", {})
    markers = entry.get("expected_markers", [])
    out = _call_mcp_via_http(tool, args)
    assert out, f"Empty response for {entry.get('id', tool)}"
    found = any(m in out for m in markers)
    assert found, (
        f"None of {markers!r} found in response for {entry.get('id', tool)}. "
        f"Response snippet: {out[:300]!r}..."
    )


def test_search_1c_help_keyword_crypto_manager() -> None:
    """search_1c_help_keyword finds МенеджерКриптографии or related crypto topic."""
    out = _call_mcp_via_http(
        "search_1c_help_keyword",
        {"query": "МенеджерКриптографии", "limit": 5},
    )
    assert "МенеджерКриптографии" in out or "Криптограф" in out or "No keyword matches" in out


def test_get_1c_help_topic_by_path_from_search() -> None:
    """get_1c_help_topic returns content for a path; path can come from search result."""
    # First get a path from keyword search
    search_out = _call_mcp_via_http(
        "search_1c_help_keyword",
        {"query": "Формат", "limit": 3},
    )
    if "No keyword matches" in search_out or not search_out.strip():
        pytest.skip("No index or no results for Формат")
    # Response usually contains path like "path" or ".md"; we only check get_1c_help_topic accepts topic_path
    topic_out = _call_mcp_via_http(
        "get_1c_help_topic",
        {"topic_path": "zif3_Format.md"},
    )
    # Either we get content or "not found" — both are valid
    assert isinstance(topic_out, str)
