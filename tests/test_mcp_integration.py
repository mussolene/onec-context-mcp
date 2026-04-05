"""Integration tests for MCP tools over session-aware streamable-http."""

import os

import pytest

from tests._mcp_http import StreamableHttpMcpClient

# Skip entire module unless opted in (integration tests)
pytestmark = pytest.mark.skipif(
    not os.environ.get("MCP_INTEGRATION"),
    reason="Set MCP_INTEGRATION=1 to run (requires MCP + Qdrant)",
)


@pytest.fixture(scope="module")
def mcp_client() -> StreamableHttpMcpClient:
    return StreamableHttpMcpClient.from_env_or_skip()


def test_live_tool_list_matches_narrow_surface(mcp_client: StreamableHttpMcpClient) -> None:
    """Live MCP should expose the narrow tool surface and hide removed broad tool."""
    names = mcp_client.list_tools()
    assert "get_1c_code_answer" not in names
    assert "get_1c_help_topic" not in names
    assert "search_1c_help" not in names
    assert "search_1c_help_keyword" not in names
    assert "get_1c_api_answer" in names
    assert "get_1c_api_object" in names
    assert "answer_1c_help_question" in names
    assert "search_1c_api" in names
    assert "search_1c_snippets" in names
    assert "search_1c_standards" in names
    assert "search_1c_official_examples" not in names
    assert "search_1c_memory" not in names
    assert "get_1c_function_info" not in names
    assert "get_1c_context_bundle" not in names
    assert "search_1c_metadata_exact" in names
    assert "search_1c_metadata_semantic" in names
    assert "search_1c_metadata_fields" in names


def test_get_1c_help_index_status(mcp_client: StreamableHttpMcpClient) -> None:
    """get_1c_help_index_status returns index info."""
    out = mcp_client.call_tool("get_1c_help_index_status", {})
    assert "Topics indexed" in out or "Collection" in out or "No" in out


def test_search_1c_api_type_method(mcp_client: StreamableHttpMcpClient) -> None:
    """search_1c_api finds HTTPСоединение.Получить (Type.Method)."""
    out = mcp_client.call_tool(
        "search_1c_api",
        {"query": "HTTPСоединение.Получить", "limit": 3},
    )
    assert "HTTPСоединение" in out or "No structured API results" in out


def test_get_1c_api_answer_http_get(mcp_client: StreamableHttpMcpClient) -> None:
    """get_1c_api_answer should return exact API answer for HTTP GET."""
    out = mcp_client.call_tool(
        "get_1c_api_answer",
        {"name": "HTTPСоединение.Получить"},
    )
    assert "HTTPСоединение.Получить" in out or "No exact keyword matches" in out
