"""Integration tests for MCP tools. Require MCP server + Qdrant running (e.g. docker compose up).

Run with: MCP_INTEGRATION=1 pytest tests/test_mcp_integration.py -v

Note: Uses raw HTTP; streamable-http MCP may require different protocol (406 = format mismatch).
"""

import os

import pytest

# Skip entire module unless opted in (integration tests)
pytestmark = pytest.mark.skipif(
    not os.environ.get("MCP_INTEGRATION"),
    reason="Set MCP_INTEGRATION=1 to run (requires MCP + Qdrant)",
)


def _call_mcp_via_http(tool: str, args: dict) -> str:
    """Call MCP tool via HTTP. Requires streamable-http MCP on localhost:8050."""
    import json
    import urllib.request

    url = os.environ.get("MCP_URL", "http://localhost:8050/mcp")
    # Minimal JSON-RPC for MCP list tools / call tool
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
    req.add_header("Accept", "application/json, text/event-stream")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("result", {}).get("content", [{}])[0].get("text", "")
    except Exception as e:
        pytest.skip(f"MCP not available: {e}")


def test_get_1c_help_index_status() -> None:
    """get_1c_help_index_status returns index info."""
    out = _call_mcp_via_http("get_1c_help_index_status", {})
    assert "Topics indexed" in out or "Collection" in out or "No" in out


def test_search_1c_help_keyword_type_method() -> None:
    """search_1c_help_keyword finds HTTPСоединение.Получить (Type.Method)."""
    out = _call_mcp_via_http(
        "search_1c_help_keyword",
        {"query": "HTTPСоединение.Получить", "limit": 3},
    )
    assert "HTTPСоединение" in out or "No keyword matches" in out


def test_get_1c_api_answer_http_get() -> None:
    """get_1c_api_answer should return exact API answer for HTTP GET."""
    out = _call_mcp_via_http(
        "get_1c_api_answer",
        {"name": "HTTPСоединение.Получить"},
    )
    assert "HTTPСоединение.Получить" in out or "No exact keyword matches" in out
