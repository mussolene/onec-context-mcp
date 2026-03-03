"""Tests for MCP server (tools logic with mocked FastMCP)."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from onec_help import mcp_server


def test_get_help_path_default_when_unset() -> None:
    """When HELP_PATH is not set, _get_help_path returns data/ resolved from cwd."""
    mcp_server._HELP_PATH = None
    with patch.dict(os.environ, {"HELP_PATH": ""}, clear=False):
        p = mcp_server._get_help_path()
    assert p.name == "data"
    assert p.is_absolute()


def test_run_mcp_requires_fastmcp(help_sample_dir: Path) -> None:
    with patch.object(mcp_server, "_HAS_FASTMCP", False):
        with pytest.raises(RuntimeError, match="fastmcp"):
            mcp_server.run_mcp(help_sample_dir, transport="stdio")


@patch.object(mcp_server, "_HAS_FASTMCP", True)
@patch.object(mcp_server, "_search")
@patch.object(mcp_server, "_get_topic")
def test_search_and_get_topic(mock_get, mock_search, help_sample_dir: Path) -> None:
    mcp_server._HELP_PATH = help_sample_dir
    mock_search.return_value = [{"title": "Test", "path": "field626.html", "text": "snippet"}]
    mock_get.return_value = "# Test\n\nContent"
    assert mcp_server._search("query", limit=5)
    assert mcp_server._get_topic("field626.html") == "# Test\n\nContent"
    mcp_server._HELP_PATH = None


@patch.object(mcp_server, "_search_keyword")
@patch.object(mcp_server, "_search")
def test_hybrid_search_handles_score_none(mock_search, mock_search_keyword) -> None:
    """_hybrid_search must not fail when keyword results have score=None."""
    mock_search.return_value = [{"path": "a.md", "title": "A", "text": "x", "score": 0.9}]
    mock_search_keyword.return_value = [{"path": "b.md", "title": "B", "text": "y", "score": None}]
    results, _ = mcp_server._hybrid_search("test", limit=5)
    paths = [r.get("path") for r in results]
    assert "a.md" in paths
    assert "b.md" in paths


def test_extract_keyword_tokens_type_method() -> None:
    """_extract_keyword_tokens extracts Type.Method as whole string."""
    tokens = mcp_server._extract_keyword_tokens("HTTPСоединение.Получить пример")
    assert "HTTPСоединение.Получить" in tokens
    tokens2 = mcp_server._extract_keyword_tokens("Запрос.ВыполнитьПакет")
    assert "Запрос.ВыполнитьПакет" in tokens2


def test_extract_keyword_tokens_edge_cases() -> None:
    """_extract_keyword_tokens: empty, short tokens excluded, limit 8, multiple Type.Method."""
    assert mcp_server._extract_keyword_tokens("") == []
    assert mcp_server._extract_keyword_tokens("ab") == []  # < 3 chars
    # Only identifiers >= 3 chars
    tokens = mcp_server._extract_keyword_tokens("СКД вывод Формат")
    assert "СКД" in tokens
    assert "вывод" in tokens
    assert "Формат" in tokens
    # Limit 8
    long_query = " ".join([f"Токен{i}" for i in range(15)])
    tokens_long = mcp_server._extract_keyword_tokens(long_query)
    assert len(tokens_long) <= 8
    # Multiple Type.Method
    tokens_multi = mcp_server._extract_keyword_tokens(
        "HTTPСоединение.Получить и Запрос.ВыполнитьПакет"
    )
    assert "HTTPСоединение.Получить" in tokens_multi
    assert "Запрос.ВыполнитьПакет" in tokens_multi


def test_hybrid_search_returns_meta() -> None:
    """_hybrid_search returns (results, meta) with has_keyword_hits and top_semantic_score."""
    with (
        patch.object(mcp_server, "_search") as mock_search,
        patch.object(mcp_server, "_search_keyword") as mock_kw,
    ):
        mock_search.return_value = [
            {"path": "a.md", "title": "A", "text": "x", "score": 0.35},
        ]
        mock_kw.return_value = []
        results, meta = mcp_server._hybrid_search("тест", limit=5)
        assert meta["has_keyword_hits"] is False
        assert meta["top_semantic_score"] == 0.35
        assert len(results) == 1

        mock_search.return_value = [{"path": "b.md", "title": "B", "text": "y", "score": 0.9}]
        mock_kw.return_value = [{"path": "c.md", "title": "C", "text": "z", "score": None}]
        results2, meta2 = mcp_server._hybrid_search("HTTPСоединение.Получить", limit=5)
        assert meta2["has_keyword_hits"] is True
        assert meta2["top_semantic_score"] == 0.9
        paths = [r.get("path") for r in results2]
        assert "c.md" in paths
        assert "b.md" in paths

        # RRF: doc in both lists ranks higher (scores from both)
        mock_search.return_value = [
            {"path": "both.md", "title": "Both", "text": "x", "score": 0.5},
            {"path": "sem_only.md", "title": "Sem", "text": "y", "score": 0.9},
        ]
        mock_kw.return_value = [{"path": "both.md", "title": "Both", "text": "x", "score": 1.0}]
        results3, _ = mcp_server._hybrid_search("API.Метод", limit=5)
        paths3 = [r.get("path") for r in results3]
        assert paths3[0] == "both.md"  # RRF: in both lists → highest score


def test_should_show_low_score_hint() -> None:
    """_should_show_low_score_hint: True when no keyword hits, low score, has results."""
    assert (
        mcp_server._should_show_low_score_hint(
            [{"path": "a.md"}], [], {"has_keyword_hits": False, "top_semantic_score": 0.3}
        )
        is True
    )
    assert (
        mcp_server._should_show_low_score_hint(
            [], ["mem"], {"has_keyword_hits": False, "top_semantic_score": 0.4}
        )
        is True
    )
    # No hint when keyword hits
    assert (
        mcp_server._should_show_low_score_hint(
            [{"path": "a.md"}], [], {"has_keyword_hits": True, "top_semantic_score": 0.3}
        )
        is False
    )
    # No hint when score above threshold
    assert (
        mcp_server._should_show_low_score_hint(
            [{"path": "a.md"}], [], {"has_keyword_hits": False, "top_semantic_score": 0.6}
        )
        is False
    )
    # No hint when no results
    assert (
        mcp_server._should_show_low_score_hint(
            [], [], {"has_keyword_hits": False, "top_semantic_score": 0.3}
        )
        is False
    )


def test_extract_code_blocks() -> None:
    """_extract_code_blocks extracts bsl and generic code blocks from markdown."""
    md = """
# Title
Text before.
```bsl
Код = 1;
```
More text.
```
plain block
```
"""
    blocks = mcp_server._extract_code_blocks(md)
    assert len(blocks) == 2
    assert "Код = 1;" in blocks[0]
    assert "plain block" in blocks[1]


def test_check_rate_limit_disabled() -> None:
    """Rate limit disabled when MCP_RATE_LIMIT_PER_MIN=0."""
    with patch.dict(os.environ, {"MCP_RATE_LIMIT_PER_MIN": "0"}, clear=False):
        assert mcp_server._check_rate_limit() is None


def test_truncate_if_needed_ok() -> None:
    """_truncate_if_needed returns value when within limit."""
    val, err = mcp_server._truncate_if_needed("short", 100, "query")
    assert val == "short"
    assert err is None


def test_truncate_if_needed_exceeds() -> None:
    """_truncate_if_needed returns error when over limit."""
    val, err = mcp_server._truncate_if_needed("x" * 200, 100, "query")
    assert val == ""
    assert "exceeds 100 chars" in (err or "")


def test_write_snippet_to_file(help_sample_dir: Path) -> None:
    """_write_snippet_to_file creates .md with frontmatter."""
    out_dir = help_sample_dir / "snippets_out"
    path = mcp_server._write_snippet_to_file(
        out_dir, "Процедура Тест()\nКонецПроцедуры", "Описание", "Мой сниппет"
    )
    assert path is not None
    assert path.endswith(".md")
    full = out_dir / path
    assert full.exists()
    text = full.read_text(encoding="utf-8")
    assert "Мой сниппет" in text
    assert "Процедура Тест" in text


def test_path_parts() -> None:
    """_path_parts extracts parts from URI or path."""
    assert mcp_server._path_parts("file:///projects/doc.html") == ("projects", "doc.html")
    assert mcp_server._path_parts("dir/sub/file.bsl") == ("dir", "sub", "file.bsl")
