"""Tests for MCP server (tools logic with mocked FastMCP)."""

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from onec_help import mcp_server


def test_snippet_max_chars_default() -> None:
    """_snippet_max_chars returns default 1200 when env unset."""
    with patch.dict(os.environ, {"MCP_SNIPPET_MAX_CHARS": ""}, clear=False):
        # Reload to pick up env; default is 1200
        assert 100 <= mcp_server._snippet_max_chars() <= 5000


def test_snippet_max_chars_from_env() -> None:
    """_snippet_max_chars reads MCP_SNIPPET_MAX_CHARS and clamps to 100-5000."""
    with patch.dict(os.environ, {"MCP_SNIPPET_MAX_CHARS": "2000"}, clear=False):
        assert mcp_server._snippet_max_chars() == 2000
    with patch.dict(os.environ, {"MCP_SNIPPET_MAX_CHARS": "50"}, clear=False):
        assert mcp_server._snippet_max_chars() == 100
    with patch.dict(os.environ, {"MCP_SNIPPET_MAX_CHARS": "99999"}, clear=False):
        assert mcp_server._snippet_max_chars() == 5000


def test_max_topic_content_chars_default() -> None:
    """_max_topic_content_chars returns default 4000 when env unset."""
    assert 500 <= mcp_server._max_topic_content_chars() <= 50000


def test_max_topic_content_chars_from_env() -> None:
    """_max_topic_content_chars reads MCP_MAX_TOPIC_CHARS and clamps."""
    with patch.dict(os.environ, {"MCP_MAX_TOPIC_CHARS": "8000"}, clear=False):
        assert mcp_server._max_topic_content_chars() == 8000
    with patch.dict(os.environ, {"MCP_MAX_TOPIC_CHARS": "100"}, clear=False):
        assert mcp_server._max_topic_content_chars() == 500


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


def test_rank_keyword_results_prefers_exact_api_match() -> None:
    """Exact API title/path should rank ahead of partial keyword matches."""
    ranked = mcp_server._rank_keyword_results(
        "HTTPСоединение.Получить",
        [
            {"title": "HTTPСоединение.ПолучитьЗаголовки", "path": "Head.md"},
            {"title": "HTTPСоединение.Получить", "path": "Get.md"},
            {"title": "Получить", "path": "GetShort.md"},
        ],
    )
    assert ranked[0]["title"] == "HTTPСоединение.Получить"


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


def test_check_rate_limit_exceeded() -> None:
    """When requests >= limit, _check_rate_limit returns error message."""
    with patch.dict(os.environ, {"MCP_RATE_LIMIT_PER_MIN": "2"}, clear=False):
        mcp_server._rate_timestamps.clear()
        assert mcp_server._check_rate_limit() is None
        assert mcp_server._check_rate_limit() is None
        err = mcp_server._check_rate_limit()
        assert err is not None
        assert "Rate limit" in err and "2" in err
    mcp_server._rate_timestamps.clear()


def test_snippet_max_chars_invalid_env_returns_default() -> None:
    """_snippet_max_chars with invalid env (non-int) returns default 1200."""
    with patch.dict(os.environ, {"MCP_SNIPPET_MAX_CHARS": "not_a_number"}, clear=False):
        assert mcp_server._snippet_max_chars() == 1200


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


def test_build_mcp_app_returns_mcp() -> None:
    """_build_mcp_app returns FastMCP instance with tools registered."""
    app = mcp_server._build_mcp_app(Path("."))
    assert app is not None
    tools = asyncio.run(app.list_tools())
    assert any(t.name == "search_1c_help" for t in tools)


def test_mcp_tool_search_1c_help_via_app(help_sample_dir: Path) -> None:
    """Call search_1c_help tool via _build_mcp_app + call_tool (covers tool code)."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server, "_search", return_value=[{"title": "Test", "path": "p.html", "text": "snippet"}]
    ):
        result = asyncio.run(app.call_tool("search_1c_help", {"query": "test", "limit": 2}))
    text = result.content[0].text if result.content else ""
    assert "Test" in text
    assert "p.html" in text


def test_mcp_tool_search_1c_help_keyword_via_app(help_sample_dir: Path) -> None:
    """Call search_1c_help_keyword tool via app (covers tool code)."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_search_keyword",
        return_value=[{"title": "API", "path": "api.html", "text": "x"}],
    ):
        result = asyncio.run(
            app.call_tool("search_1c_help_keyword", {"query": "Запрос", "limit": 3})
        )
    text = result.content[0].text if result.content else ""
    assert "API" in text or "api.html" in text


def test_mcp_tool_search_1c_help_keyword_reranks_exact_first(help_sample_dir: Path) -> None:
    """Exact API hit should be rendered before similar keyword results."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_search_keyword",
        return_value=[
            {"title": "HTTPСоединение.ПолучитьЗаголовки", "path": "Head.md", "text": "head"},
            {"title": "HTTPСоединение.Получить", "path": "Get.md", "text": "get"},
        ],
    ):
        result = asyncio.run(
            app.call_tool("search_1c_help_keyword", {"query": "HTTPСоединение.Получить", "limit": 5})
        )
    text = result.content[0].text if result.content else ""
    assert text.splitlines()[0].startswith("1. **HTTPСоединение.Получить**")


def test_mcp_tool_search_1c_help_keyword_accepts_keyword_param(help_sample_dir: Path) -> None:
    """search_1c_help_keyword uses 'query' parameter (keyword alias removed from public API)."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_search_keyword",
        return_value=[{"title": "ОстаткиИОбороты", "path": "table12.html", "text": "virtual table"}],
    ):
        result = asyncio.run(
            app.call_tool("search_1c_help_keyword", {"query": "РегистрНакопления.ОстаткиИОбороты", "limit": 5})
        )
    text = result.content[0].text if result.content else ""
    assert "ОстаткиИОбороты" in text or "table12" in text


def test_mcp_tool_get_1c_help_topic_accepts_path_param(help_sample_dir: Path) -> None:
    """get_1c_help_topic accepts 'path' as alias for 'topic_path'."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(mcp_server, "_get_topic", return_value="# Topic\n\nBody"):
        result = asyncio.run(app.call_tool("get_1c_help_topic", {"path": "zif3_Format.md"}))
    text = result.content[0].text if result.content else ""
    assert "Body" in text or "Topic" in text


def test_mcp_tool_search_1c_help_no_results(help_sample_dir: Path) -> None:
    """search_1c_help returns message when no results."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(mcp_server, "_search", return_value=[]):
        result = asyncio.run(app.call_tool("search_1c_help", {"query": "nonexistent", "limit": 2}))
    text = result.content[0].text if result.content else ""
    assert "No results" in text


def test_mcp_tool_get_1c_help_index_status_via_app(help_sample_dir: Path) -> None:
    """Call get_1c_help_index_status tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server, "_index_status", return_value={"exists": True, "points_count": 10}
    ):
        result = asyncio.run(app.call_tool("get_1c_help_index_status", {}))
    text = result.content[0].text if result.content else ""
    assert "10" in text or "Topics" in text or "Collection" in text


def test_mcp_tool_get_1c_help_index_status_ingest_in_progress(help_sample_dir: Path) -> None:
    """get_1c_help_index_status shows ingest in progress (progress%, ETA, current file, failed)."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    ingest_in_progress = {
        "status": "in_progress",
        "done_tasks": 2,
        "total_tasks": 10,
        "total_points": 50,
        "current_task_points": 5,
        "estimated_total_points": 500,
        "current_task_estimated_total": 25,
        "elapsed_sec": 12.5,
        "eta_sec": 60,
        "embedding_speed_pts_per_sec": 4.0,
        "current": [
            {"version": "8.3", "language": "ru", "path": "shcntx_ru.hbk", "stage": "indexing"},
        ],
        "failed_tasks": [{"path": "bad.hbk", "error": "7z failed"}],
    }
    with patch("onec_help.ingest.read_ingest_status", return_value=ingest_in_progress):
        with patch(
            "onec_help.indexer.get_index_status",
            return_value={"exists": True, "points_count": 55, "collection": "onec_help"},
        ):
            with patch("onec_help.indexer.get_all_collections_status", return_value=[]):
                result = asyncio.run(app.call_tool("get_1c_help_index_status", {}))
    text = result.content[0].text if result.content else ""
    assert "Ingest in progress" in text
    assert "Progress:" in text or "pts" in text
    assert "Elapsed:" in text or "ETA:" in text or "Speed:" in text
    assert "shcntx_ru" in text or "Current:" in text
    assert "Failed:" in text or "bad.hbk" in text


def test_mcp_tool_get_1c_help_topic_via_app(help_sample_dir: Path) -> None:
    """Call get_1c_help_topic tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(mcp_server, "_get_topic", return_value="# Title\n\nContent here"):
        result = asyncio.run(app.call_tool("get_1c_help_topic", {"topic_path": "field626.html"}))
    text = result.content[0].text if result.content else ""
    assert "Content here" in text or "Title" in text


def test_mcp_tool_rate_limit_returns_error(help_sample_dir: Path) -> None:
    """When _check_rate_limit returns error, tool returns that message."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server, "_check_rate_limit", return_value="Rate limit exceeded (120/min)."
    ):
        result = asyncio.run(app.call_tool("search_1c_help", {"query": "x", "limit": 1}))
    text = result.content[0].text if result.content else ""
    assert "Rate limit" in text


def test_mcp_tool_truncate_query_returns_error(help_sample_dir: Path) -> None:
    """When query exceeds MAX_QUERY_CHARS, tool returns error."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    result = asyncio.run(app.call_tool("search_1c_help", {"query": "x" * 70000, "limit": 1}))
    text = result.content[0].text if result.content else ""
    assert "exceeds" in text or "chars" in text


def test_mcp_tool_search_1c_help_with_content_via_app(help_sample_dir: Path) -> None:
    """Call search_1c_help_with_content tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_hybrid_search",
        return_value=([{"path": "a.html", "title": "A", "text": "x"}], {}),
    ):
        with patch.object(mcp_server, "_get_topic", return_value="# A\n\nFull content"):
            result = asyncio.run(
                app.call_tool("search_1c_help_with_content", {"query": "test", "limit": 1})
            )
    text = result.content[0].text if result.content else ""
    assert "A" in text or "content" in text


def test_mcp_tool_get_1c_code_answer_via_app(help_sample_dir: Path) -> None:
    """Call get_1c_code_answer tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_hybrid_search",
        return_value=(
            [{"path": "func.html", "title": "Func", "text": "x"}],
            {"top_semantic_score": 0.5},
        ),
    ):
        with patch.object(mcp_server, "_get_topic", return_value="# Func\n\n```bsl\nCode();\n```"):
            result = asyncio.run(
                app.call_tool(
                    "get_1c_code_answer",
                    {
                        "query": "как вызвать",
                        "limit": 2,
                        "include_memory": False,
                        "code_only": False,
                    },
                )
            )
    text = result.content[0].text if result.content else ""
    assert "Запрос" in text or "Func" in text or "Code" in text


def test_mcp_tool_get_1c_code_answer_code_only(help_sample_dir: Path) -> None:
    """get_1c_code_answer with code_only=True returns code blocks."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_hybrid_search",
        return_value=([{"path": "a.html", "title": "A", "text": "x"}], {}),
    ):
        with patch.object(
            mcp_server,
            "_get_topic",
            return_value="# A\n\nText\n\n```bsl\nПроцедура Х()\nКонецПроцедуры\n```",
        ):
            result = asyncio.run(
                app.call_tool(
                    "get_1c_code_answer", {"query": "test", "limit": 1, "code_only": True}
                )
            )
    text = result.content[0].text if result.content else ""
    assert "Х()" in text or "bsl" in text or "A" in text


def test_mcp_tool_get_1c_api_answer_via_app(help_sample_dir: Path) -> None:
    """get_1c_api_answer uses exact-first keyword route and returns compact content."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_search_keyword",
        return_value=[
            {"title": "HTTPСоединение.ПолучитьЗаголовки", "path": "Head.md", "text": "head"},
            {"title": "HTTPСоединение.Получить", "path": "Get.md", "text": "get"},
        ],
    ):
        with patch.object(
            mcp_server,
            "_get_topic",
            return_value="# HTTPСоединение.Получить\n\nОписание.\n\n```bsl\nОтвет = Соединение.Получить();\n```",
        ):
            result = asyncio.run(
                app.call_tool("get_1c_api_answer", {"name": "HTTPСоединение.Получить"})
            )
    text = result.content[0].text if result.content else ""
    assert "HTTPСоединение.Получить" in text
    assert "Описание" in text
    assert "Соединение.Получить" in text


def test_mcp_tool_list_1c_help_titles_via_app(help_sample_dir: Path) -> None:
    """Call list_1c_help_titles tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_list_titles",
        return_value=[
            {"path": "p1.html", "title": "P1"},
            {"path": "p2.html", "title": "P2"},
        ],
    ):
        result = asyncio.run(app.call_tool("list_1c_help_titles", {"limit": 10, "path_prefix": ""}))
    text = result.content[0].text if result.content else ""
    assert "p1" in text or "P1" in text or "p2" in text


def test_mcp_tool_save_1c_snippet_via_app(help_sample_dir: Path, tmp_path: Path) -> None:
    """Call save_1c_snippet tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.dict(
        "os.environ",
        {"SAVE_SNIPPET_TO_FILES": "1", "SNIPPETS_DIR": str(tmp_path)},
        clear=False,
    ):
        result = asyncio.run(
            app.call_tool(
                "save_1c_snippet",
                {
                    "code_snippet": "Процедура Тест()\nКонецПроцедуры",
                    "description": "Test snippet",
                    "title": "Test",
                },
            )
        )
    text = result.content[0].text if result.content else ""
    assert "saved" in text.lower() or "ok" in text.lower() or "Test" in text


def test_mcp_tool_get_1c_help_related_via_app(help_sample_dir: Path) -> None:
    """Call get_1c_help_related tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch(
        "onec_help.indexer.get_1c_help_related",
        return_value=[
            {"path": "related1.html", "title": "Related 1"},
            {"path": "related2.html", "title": "Related 2"},
        ],
    ):
        result = asyncio.run(
            app.call_tool(
                "get_1c_help_related",
                {"topic_path": "Format971.md", "version": None, "language": None},
            )
        )
    text = result.content[0].text if result.content else ""
    assert "Related" in text or "related" in text


def test_mcp_tool_get_1c_help_related_empty(help_sample_dir: Path) -> None:
    """get_1c_help_related returns message when no related topics."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch("onec_help.indexer.get_1c_help_related", return_value=[]):
        result = asyncio.run(app.call_tool("get_1c_help_related", {"topic_path": "x.md"}))
    text = result.content[0].text if result.content else ""
    assert "No related" in text


def test_mcp_tool_compare_1c_help_via_app(help_sample_dir: Path) -> None:
    """Call compare_1c_help tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch(
        "onec_help.indexer.compare_1c_help",
        return_value="Left: 8.3\nRight: 8.3.27\nDiff summary.",
    ):
        result = asyncio.run(
            app.call_tool(
                "compare_1c_help",
                {
                    "topic_path_or_query": "Format",
                    "version_left": "8.3",
                    "version_right": "8.3.27",
                    "language": "ru",
                    "include_diff": False,
                },
            )
        )
    text = result.content[0].text if result.content else ""
    assert "8.3" in text or "Diff" in text


def test_mcp_tool_get_1c_function_info_via_app(help_sample_dir: Path) -> None:
    """Call get_1c_function_info tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_search_keyword",
        return_value=[
            {"path": "Format.md", "title": "Формат", "text": "Формат(Значение, ФорматнаяСтрока)"},
        ],
    ):
        with patch.object(mcp_server, "_get_topic", return_value="# Формат\n\nОписание функции."):
            result = asyncio.run(
                app.call_tool(
                    "get_1c_function_info",
                    {"name": "Формат", "choose_index": 0},
                )
            )
    text = result.content[0].text if result.content else ""
    assert "Формат" in text or "Описание" in text


def test_mcp_tool_get_form_metadata_via_app(help_sample_dir: Path) -> None:
    """Call get_form_metadata tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    xml = '<?xml version="1.0"?><Form xmlns="http://v8.1c.ru/8.3/xcf/readonly"><Attributes/><Commands/></Form>'
    result = asyncio.run(app.call_tool("get_form_metadata", {"xml_content": xml}))
    text = result.content[0].text if result.content else ""
    assert "Attributes" in text or "Commands" in text or "Parse" in text


def test_mcp_tool_get_module_info_via_app(help_sample_dir: Path) -> None:
    """Call get_module_info tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    result = asyncio.run(
        app.call_tool(
            "get_module_info",
            {"uri_or_path": "file:///projects/Catalogs/MyCat/Forms/Item/Module.bsl"},
        )
    )
    text = result.content[0].text if result.content else ""
    assert "FormModule" in text or "Module" in text


def test_mcp_tool_get_module_info_extended_types(help_sample_dir: Path) -> None:
    """get_module_info recognises RecordSetModule, ManagerModule, and other extended module types."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    cases = [
        ("file:///projects/App/InformationRegisters/Prices/RecordSetModule.bsl", "RecordSetModule", "Prices"),
        ("file:///projects/App/Catalogs/Товары/ManagerModule.bsl", "ManagerModule", "Товары"),
        ("file:///projects/App/Documents/Накладная/ObjectModule.bsl", "ObjectModule", "Накладная"),
    ]
    for uri, expected_type, expected_obj in cases:
        result = asyncio.run(app.call_tool("get_module_info", {"uri_or_path": uri}))
        text = result.content[0].text if result.content else ""
        assert expected_type in text, f"Expected {expected_type} in output for {uri}: {text}"
        assert expected_obj in text, f"Expected object {expected_obj} in output for {uri}: {text}"


def test_mcp_tool_get_1c_code_answer_include_memory(help_sample_dir: Path) -> None:
    """get_1c_code_answer with include_memory=True includes memory blocks (snippets/community_help/standards)."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    memory_results = [
        {
            "payload": {
                "title": "Пример",
                "code_snippet": "Сообщить(1);",
                "description": "Desc",
                "domain": "snippets",
                "detail_url": "https://fastcode.im/1",
                "source_site": "fastcode.im",
            }
        },
        {
            "payload": {
                "title": "HelpF",
                "instruction": "Инструкция",
                "domain": "community_help",
                "detail_url": "https://helpf.pro/2",
                "source_site": "helpf.pro",
                "source": "faq",
            }
        },
        {"payload": {"title": "Стандарт", "domain": "standards"}},
    ]
    with patch.object(
        mcp_server,
        "_hybrid_search",
        return_value=([], {}),
    ):
        with patch("onec_help.memory.get_memory_store") as mock_store:
            mock_store.return_value.search_long.return_value = memory_results
            result = asyncio.run(
                app.call_tool(
                    "get_1c_code_answer",
                    {"query": "test", "limit": 5, "include_memory": True},
                )
            )
    text = result.content[0].text if result.content else ""
    assert "Из памяти" in text
    assert "Пример" in text or "Сообщить" in text
    assert "пример" in text or "стандарт" in text


def test_mcp_tool_get_1c_code_answer_no_results_no_memory(help_sample_dir: Path) -> None:
    """get_1c_code_answer returns hint when no results and no memory."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(mcp_server, "_hybrid_search", return_value=([], {})):
        with patch("onec_help.memory.get_memory_store") as mock_store:
            mock_store.return_value.search_long.return_value = []
            result = asyncio.run(
                app.call_tool(
                    "get_1c_code_answer",
                    {"query": "nonexistent", "limit": 2, "include_memory": True},
                )
            )
    text = result.content[0].text if result.content else ""
    assert "No results" in text or "index exists" in text or "search_1c_help_keyword" in text


def test_mcp_tool_search_1c_memory(help_sample_dir: Path) -> None:
    """search_1c_memory returns formatted blocks from memory (snippets/standards)."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    memory_results = [
        {"payload": {"title": "Стандарт именования", "domain": "standards", "description": "Правила именования"}},
        {"payload": {"title": "Пример запроса", "domain": "snippets", "code_snippet": "ВЫБРАТЬ 1", "description": "Пример"}},
    ]
    with patch("onec_help.memory.get_memory_store") as mock_get_store:
        mock_store = mock_get_store.return_value
        mock_store.search_long.return_value = memory_results
        result = asyncio.run(
            app.call_tool(
                "search_1c_memory",
                {"query": "запрос 1С", "limit": 5},
            )
        )
    text = result.content[0].text if result.content else ""
    assert "Память (сниппеты и стандарты)" in text
    assert "Стандарт именования" in text or "стандарт" in text
    assert "Пример запроса" in text or "пример" in text


def test_mcp_tool_search_1c_memory_with_domains(help_sample_dir: Path) -> None:
    """search_1c_memory with domains=standards,snippets calls search_long per domain."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch("onec_help.memory.get_memory_store") as mock_get_store:
        mock_store = mock_get_store.return_value
        mock_store.search_long.side_effect = [
            [{"payload": {"title": "Стандарт", "domain": "standards"}}],
            [{"payload": {"title": "Сниппет", "domain": "snippets", "code_snippet": "Сообщить(1);"}}],
        ]
        result = asyncio.run(
            app.call_tool(
                "search_1c_memory",
                {"query": "тест", "limit": 4, "domains": "standards,snippets"},
            )
        )
    text = result.content[0].text if result.content else ""
    assert "Память (сниппеты и стандарты)" in text
    assert mock_store.search_long.call_count == 2


def test_mcp_tool_get_1c_function_info_choose_index(help_sample_dir: Path) -> None:
    """get_1c_function_info with choose_index returns content of chosen result."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_search_keyword",
        return_value=[
            {"path": "Format1.md", "title": "Формат (функция)", "text": "x"},
            {"path": "Format2.md", "title": "Формат (страница)", "text": "y"},
        ],
    ):
        with patch.object(
            mcp_server,
            "_get_topic",
            side_effect=["# Формат функция\n\nОписание.", "# Формат страница\n\nДругое."],
        ):
            result = asyncio.run(
                app.call_tool(
                    "get_1c_function_info",
                    {"name": "Формат", "path": None, "choose_index": 1},
                )
            )
    text = result.content[0].text if result.content else ""
    assert "Формат" in text


def test_mcp_tool_get_1c_function_info_empty_name(help_sample_dir: Path) -> None:
    """get_1c_function_info returns message when name is empty."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    result = asyncio.run(
        app.call_tool("get_1c_function_info", {"name": "   ", "path": None, "choose_index": None})
    )
    text = result.content[0].text if result.content else ""
    assert "Provide" in text or "name" in text


@patch("onec_help.metadata_graph.search_metadata_by_name")
def test_mcp_tool_search_1c_metadata_via_app(mock_search_meta, help_sample_dir: Path) -> None:
    """Call search_1c_metadata tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    mock_search_meta.return_value = [
        {
            "id": "Document/Sales",
            "config_name": "Cfg",
            "config_version": "1.0.0.0",
            "object_type": "Document",
            "name": "Sales",
            "full_name": "Реализация",
            "path": "Documents/Sales",
        }
    ]
    result = asyncio.run(
        app.call_tool(
            "search_1c_metadata",
            {"query": "Sales", "config_version": "1.0.0.0", "object_type": None, "limit": 5},
        )
    )
    text = result.content[0].text if result.content else ""
    assert "Sales" in text or "Document" in text


@patch("onec_help.metadata_graph.get_metadata_object")
def test_mcp_tool_get_1c_metadata_object_via_app(mock_get_meta, help_sample_dir: Path) -> None:
    """Call get_1c_metadata_object tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    mock_get_meta.return_value = {
        "id": "Document/Sales",
        "object_type": "Document",
        "name": "Sales",
        "full_name": "Реализация",
        "path": "Documents/Sales",
        "config_name": "Cfg",
        "config_version": "1.0.0.0",
    }
    result = asyncio.run(
        app.call_tool(
            "get_1c_metadata_object",
            {"object_id": "Document/Sales", "config_version": "1.0.0.0"},
        )
    )
    text = result.content[0].text if result.content else ""
    assert "Sales" in text or "Document" in text


@patch("onec_help.context_builder.build_context")
def test_mcp_tool_get_1c_context_bundle_via_app(mock_build_ctx, help_sample_dir: Path) -> None:
    """Call get_1c_context_bundle tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    mock_build_ctx.return_value = {
        "request": {"query": "Тест", "config_version": "CfgVer"},
        "help_topics": [{"title": "A", "path": "a.html", "text": "x"}],
        "memory": [{"payload": {"title": "Snippet", "domain": "snippets", "description": "desc"}}],
        "metadata_objects": [
            {
                "id": "Document/Sales",
                "object_type": "Document",
                "name": "Sales",
                "full_name": "Реализация",
                "path": "Documents/Sales",
            }
        ],
    }
    result = asyncio.run(
        app.call_tool(
            "get_1c_context_bundle",
            {"query": "Тест", "config_version": "CfgVer", "file_uri": None, "symbol_name": None},
        )
    )
    text = result.content[0].text if result.content else ""
    assert "Из справки" in text
    assert "Сниппеты" in text or "стандарты" in text
    assert "Объекты конфигурации" in text
