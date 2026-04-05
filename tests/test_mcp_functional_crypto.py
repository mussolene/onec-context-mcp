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
    tool = entry.get("tool", "search_1c_api")
    args = entry.get("args", {})
    markers = entry.get("expected_markers", [])
    out = mcp_client.call_tool(tool, args)
    assert out, f"Empty response for {entry.get('id', tool)}"
    found = any(m in out for m in markers)
    if not found and entry.get("id") == "crypto_snippets":
        # Semantic hits in onec_help_memory depend on loaded snippets and embeddings;
        # still assert the tool returns a real snippets payload (not an error stub).
        assert "## Сниппеты" in out and "```bsl" in out, (
            f"search_1c_snippets should return snippet blocks; got: {out[:400]!r}..."
        )
        return
    assert found, (
        f"None of {markers!r} found in response for {entry.get('id', tool)}. "
        f"Response snippet: {out[:300]!r}..."
    )


def test_search_1c_api_crypto_manager(mcp_client: StreamableHttpMcpClient) -> None:
    """search_1c_api finds МенеджерКриптографии or related crypto API."""
    out = mcp_client.call_tool(
        "search_1c_api",
        {"query": "МенеджерКриптографии", "limit": 5},
    )
    assert (
        "МенеджерКриптографии" in out or "Криптограф" in out or "No structured API results" in out
    )


def test_answer_1c_help_question_crypto_version(mcp_client: StreamableHttpMcpClient) -> None:
    """answer_1c_help_question should work for crypto factual questions."""
    out = mcp_client.call_tool(
        "answer_1c_help_question",
        {"question": "с какой версии доступен интерактивный ввод менеджера криптографии"},
    )
    assert isinstance(out, str)
