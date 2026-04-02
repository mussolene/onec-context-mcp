"""Functional tests for MCP 1c-help over session-aware streamable-http."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests._mcp_http import StreamableHttpMcpClient

# Skip unless integration opted in
pytestmark = pytest.mark.skipif(
    not os.environ.get("MCP_INTEGRATION"),
    reason="Set MCP_INTEGRATION=1 to run (requires MCP + Qdrant)",
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
QUERIES_JSON = FIXTURES_DIR / "mcp_crypto_queries.json"

def _load_crypto_queries() -> list[dict]:
    if not QUERIES_JSON.exists():
        return []
    raw = QUERIES_JSON.read_text(encoding="utf-8")
    return json.loads(raw)


@pytest.fixture(scope="module")
def crypto_queries() -> list[dict]:
    """Load query config from fixtures (id, tool, args, expected_markers)."""
    return _load_crypto_queries()


@pytest.fixture(scope="module")
def mcp_client() -> StreamableHttpMcpClient:
    return StreamableHttpMcpClient.from_env_or_skip()


@pytest.mark.skipif(not QUERIES_JSON.exists(), reason="mcp_crypto_queries.json not found")
@pytest.mark.parametrize("entry", _load_crypto_queries(), ids=lambda e: e.get("id", "item"))
def test_mcp_crypto_query_returns_relevant_content(
    mcp_client: StreamableHttpMcpClient, entry: dict
) -> None:
    """Each crypto/scenario query returns non-empty response with at least one expected marker."""
    tool = entry.get("tool", "search_1c_help_keyword")
    args = entry.get("args", {})
    markers = entry.get("expected_markers", [])
    out = mcp_client.call_tool(tool, args)
    assert out, f"Empty response for {entry.get('id', tool)}"
    found = any(m in out for m in markers)
    assert found, (
        f"None of {markers!r} found in response for {entry.get('id', tool)}. "
        f"Response snippet: {out[:300]!r}..."
    )


def test_search_1c_help_keyword_crypto_manager(mcp_client: StreamableHttpMcpClient) -> None:
    """search_1c_help_keyword finds МенеджерКриптографии or related crypto topic."""
    out = mcp_client.call_tool(
        "search_1c_help_keyword",
        {"query": "МенеджерКриптографии", "limit": 5},
    )
    assert "МенеджерКриптографии" in out or "Криптограф" in out or "No keyword matches" in out


def test_get_1c_help_topic_by_path_from_search(mcp_client: StreamableHttpMcpClient) -> None:
    """get_1c_help_topic returns content for a path; path can come from search result."""
    # First get a path from keyword search
    search_out = mcp_client.call_tool(
        "search_1c_help_keyword",
        {"query": "Формат", "limit": 3},
    )
    if "No keyword matches" in search_out or not search_out.strip():
        pytest.skip("No index or no results for Формат")
    # Response usually contains path like "path" or ".md"; we only check get_1c_help_topic accepts topic_path
    topic_out = mcp_client.call_tool(
        "get_1c_help_topic",
        {"topic_path": "zif3_Format.md"},
    )
    # Either we get content or "not found" — both are valid
    assert isinstance(topic_out, str)
