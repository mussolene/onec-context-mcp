"""Tests for MCP server (tools logic with mocked FastMCP)."""

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp.shared.exceptions import McpError

from onec_help.interfaces import mcp_server


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


def test_structured_api_sort_key_prefers_newer_platform_version() -> None:
    """Tiebreak after name match: topic_path starts with 8.x so lexicographic order favored 8.2 over 8.5."""
    old = {
        "full_name": "Тип.Метод",
        "name": "Метод",
        "version": "8.2.19.130",
        "topic_path": "8.2.19.130/shcntx_ru/a.html",
    }
    new = {
        "full_name": "Тип.Метод",
        "name": "Метод",
        "version": "8.5.1.1236",
        "topic_path": "8.5.1.1236/shcntx_ru/b.html",
    }
    q = "Тип.Метод"
    ordered = sorted(
        [old, new],
        key=lambda item: mcp_server._structured_api_sort_key(q, item),
    )
    assert ordered[0]["version"] == "8.5.1.1236"


def test_extract_fact_from_structured_includes_notes_compact() -> None:
    item = {
        "summary": "Кратко.",
        "notes": "Важное примечание из поля notes.",
        "source_sections": {"note": "Дубликат."},
    }
    fact = mcp_server._extract_fact_from_structured(item, "general", detail="compact")
    assert "Важное примечание" in fact
    assert "Примечание:" in fact


def test_filter_noise_api_hits_drops_web_colors_for_technical_query() -> None:
    """Technical search queries should not surface WebЦвета.* as top API members."""
    items = [
        {"full_name": "WebЦвета.Красный", "name": "Красный"},
        {"full_name": "ПроцессорКомпоновкиДанных.Инициализировать", "name": "Инициализировать"},
    ]
    out = mcp_server._filter_noise_api_hits(items, "компоновка данных инициализировать")
    assert len(out) == 1
    assert "ПроцессорКомпоновкиДанных" in (out[0].get("full_name") or "")


def test_filter_noise_api_hits_keeps_all_for_non_technical_query() -> None:
    out = mcp_server._filter_noise_api_hits(
        [{"full_name": "WebЦвета.Красный"}],
        "красный цвет интерфейса",
    )
    assert len(out) == 1


def test_candidate_plausible_for_dcs_rejects_table_form() -> None:
    """DCS questions should not accept ТаблицаФормы as answer source."""
    item = {"full_name": "ТаблицаФормы.СкопироватьСтроку", "name": "СкопироватьСтроку"}
    assert not mcp_server._candidate_plausible_for_dcs_question(
        "как выгрузить схему компоновки в таблицу значений",
        item,
    )


def test_candidate_plausible_for_dcs_accepts_processor() -> None:
    item = {
        "full_name": "ПроцессорВыводаРезультатаКомпоновкиДанныхВКоллекциюЗначений.Вывести",
        "name": "Вывести",
    }
    assert mcp_server._candidate_plausible_for_dcs_question(
        "как выгрузить схему компоновки в таблицу значений",
        item,
    )


def test_normalize_api_related_items_dedupes_and_drops_crumbs() -> None:
    raw = [
        {"target_name": "Foo", "link_kind": "see_also"},
        {"target_name": "Foo", "link_kind": "see_also"},
        {"target_name": ", метод", "link_kind": "see_also"},
        {"target_name": "Bar", "link_kind": "see_also"},
    ]
    out = mcp_server._normalize_api_related_items(raw)
    assert [x["target_name"] for x in out] == ["Foo", "Bar"]


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
    """When HELP_PATH is not set, _get_help_path returns help_structured path."""
    mcp_server._HELP_PATH = None
    with patch.dict(os.environ, {"HELP_PATH": ""}, clear=False):
        p = mcp_server._get_help_path()
    assert p.name == "help_structured"
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


def test_match_priority_prefers_exact_member_over_longer_prefix() -> None:
    """Exact member title should outrank longer prefix hits like ПолучитьЗаголовки."""
    exact = mcp_server._match_priority(
        "httpсоединение.получить",
        "httpсоединение.получить (httpconnection.get)",
    )
    longer = mcp_server._match_priority(
        "httpсоединение.получить",
        "httpсоединение.получитьзаголовки (httpconnection.head)",
    )
    assert exact < longer


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
    assert any(t.name == "search_1c_api" for t in tools)
    assert all(t.name != "get_1c_help_topic" for t in tools)


def test_mcp_tool_search_1c_api_via_app(help_sample_dir: Path) -> None:
    """Call search_1c_api tool via _build_mcp_app + call_tool (covers tool code)."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_search_api_members",
        return_value=[
            {"name": "Test.Method", "summary": "snippet", "entity_type": "method", "breadcrumb": []}
        ],
    ):
        with patch.object(mcp_server, "_search_api_objects", return_value=[]):
            with patch.object(mcp_server, "_search_official_examples", return_value=[]):
                result = asyncio.run(app.call_tool("search_1c_api", {"query": "test", "limit": 2}))
    text = result.content[0].text if result.content else ""
    assert "API members" in text
    assert "Test.Method" in text


def test_mcp_tool_search_1c_api_renders_examples(help_sample_dir: Path) -> None:
    """search_1c_api renders official examples when include_examples=True."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(mcp_server, "_search_api_members", return_value=[]):
        with patch.object(mcp_server, "_search_api_objects", return_value=[]):
            with patch.object(
                mcp_server,
                "_search_official_examples",
                return_value=[{"title": "HTTP GET", "description": "GET example"}],
            ):
                result = asyncio.run(
                    app.call_tool("search_1c_api", {"query": "HTTP GET", "limit": 3})
                )
    text = result.content[0].text if result.content else ""
    assert "Official examples" in text
    assert "HTTP GET" in text


def test_mcp_tool_search_1c_api_no_results(help_sample_dir: Path) -> None:
    """search_1c_api returns message when no results (including after topic fallback)."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(mcp_server, "_search_api_members", return_value=[]):
        with patch.object(mcp_server, "_search_api_objects", return_value=[]):
            with patch.object(mcp_server, "_search_official_examples", return_value=[]):
                with patch.object(mcp_server, "_search_api_topics", return_value=[]):
                    result = asyncio.run(
                        app.call_tool("search_1c_api", {"query": "nonexistent", "limit": 2})
                    )
    text = result.content[0].text if result.content else ""
    assert "Нет результатов" in text or "structured API" in text


def test_mcp_tool_search_1c_api_topic_fallback(help_sample_dir: Path) -> None:
    """When structured API sections are empty, search_1c_api surfaces help topics with same flow."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    topic_hit = {
        "title": "Общая тема",
        "summary": "Краткое описание",
        "entity_type": "topic",
        "breadcrumb": [],
        "topic_path": "platform/some/topic",
    }
    with patch.object(mcp_server, "_search_api_members", return_value=[]):
        with patch.object(mcp_server, "_search_api_objects", return_value=[]):
            with patch.object(mcp_server, "_search_official_examples", return_value=[]):
                with patch.object(mcp_server, "_search_api_topics", return_value=[topic_hit]):
                    result = asyncio.run(
                        app.call_tool("search_1c_api", {"query": "что-то редкое", "limit": 3})
                    )
    text = result.content[0].text if result.content else ""
    assert "Help topics" in text
    assert "Общая тема" in text
    assert "topic_path" in text


def test_mcp_tool_get_1c_help_index_status_via_app(help_sample_dir: Path) -> None:
    """Call get_1c_help_index_status tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server, "_api_index_status", return_value={"exists": True, "points_count": 10}
    ):
        result = asyncio.run(app.call_tool("get_1c_help_index_status", {}))
    text = result.content[0].text if result.content else ""
    assert "10" in text or "Structured API entries" in text or "Collection" in text


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
    with patch("onec_help.runtime.ingest.read_ingest_status", return_value=ingest_in_progress):
        with patch(
            "onec_help.search_store.indexer.get_index_status",
            return_value={"exists": True, "points_count": 55, "collection": "onec_help"},
        ):
            with patch(
                "onec_help.search_store.indexer.get_all_collections_status",
                return_value=[
                    {"name": "onec_help_api_members", "points_count": 12},
                    {"name": "onec_help_api_objects", "points_count": 4},
                    {"name": "onec_help_api_links", "points_count": 9},
                ],
            ):
                result = asyncio.run(app.call_tool("get_1c_help_index_status", {}))
    text = result.content[0].text if result.content else ""
    assert "Ingest in progress" in text
    assert "onec_help_api_members" in text
    assert "Progress:" in text or "pts" in text
    assert "Elapsed:" in text or "ETA:" in text or "Speed:" in text
    assert "shcntx_ru" in text or "Current:" in text
    assert "Failed:" in text or "bad.hbk" in text


def test_mcp_tool_rate_limit_returns_error(help_sample_dir: Path) -> None:
    """When _check_rate_limit returns error, tool returns that message."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server, "_check_rate_limit", return_value="Rate limit exceeded (120/min)."
    ):
        result = asyncio.run(app.call_tool("search_1c_api", {"query": "x", "limit": 1}))
    text = result.content[0].text if result.content else ""
    assert "Rate limit" in text


def test_mcp_tool_truncate_query_returns_error(help_sample_dir: Path) -> None:
    """When query exceeds MAX_QUERY_CHARS, tool returns error."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    result = asyncio.run(app.call_tool("search_1c_api", {"query": "x" * 70000, "limit": 1}))
    text = result.content[0].text if result.content else ""
    assert "exceeds" in text or "chars" in text


def test_mcp_tool_get_1c_code_answer_removed_from_app(help_sample_dir: Path) -> None:
    """Legacy broad answer tool should not be exposed in MCP app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with pytest.raises(McpError, match="Unknown tool"):
        asyncio.run(app.call_tool("get_1c_code_answer", {"query": "test"}))


def test_mcp_tool_get_1c_api_answer_via_app(help_sample_dir: Path) -> None:
    """get_1c_api_answer uses structured API layer only."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_get_api_member",
        return_value=[
            {
                "name": "HTTPСоединение.Получить",
                "full_name": "HTTPСоединение.Получить",
                "title": "HTTPСоединение.Получить",
                "summary": "Описание.",
                "syntax": "HTTPСоединение.Получить(<Адрес>)",
                "topic_path": "Get.md",
                "version": "8.3.27.1859",
                "kind": "method",
                "entity_type": "method",
                "breadcrumb": ["Объекты", "HTTPСоединение"],
            }
        ],
    ):
        result = asyncio.run(
            app.call_tool("get_1c_api_answer", {"name": "HTTPСоединение.Получить"})
        )
    text = result.content[0].text if result.content else ""
    assert "HTTPСоединение.Получить" in text
    assert "Описание" in text
    assert "Синтаксис" in text


def test_mcp_tool_get_1c_api_answer_no_member_same_wording(help_sample_dir: Path) -> None:
    """get_1c_api_answer explains missing name as undocumented platform API, not reindex hint."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with (
        patch.object(mcp_server, "_get_api_member", return_value=[]),
        patch.object(mcp_server, "_get_api_object", return_value=[]),
    ):
        result = asyncio.run(
            app.call_tool("get_1c_api_answer", {"name": "СоздатьПустуюТаблицу"}),
        )
        text = result.content[0].text if result.content else ""
        assert "нет в индексе" in text
        assert "search_1c_api" in text
    assert "search_1c_api" in text


def test_mcp_tool_get_1c_api_answer_redirects_natural_language(help_sample_dir: Path) -> None:
    """Long prose in name= should suggest answer_1c_help_question, not «not found»."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(mcp_server, "_get_api_member") as gm:
        result = asyncio.run(
            app.call_tool(
                "get_1c_api_answer",
                {"name": "Как вызвать исключение во встроенном языке?"},
            )
        )
        gm.assert_not_called()
    text = result.content[0].text if result.content else ""
    assert "answer_1c_help_question" in text


def test_mcp_tool_get_1c_api_answer_falls_back_to_api_object(help_sample_dir: Path) -> None:
    """When the name is a type (api_objects) but not a member row, still return help."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with (
        patch.object(mcp_server, "_get_api_member", return_value=[]),
        patch.object(
            mcp_server,
            "_get_api_object",
            return_value=[
                {
                    "name": "ТаблицаЗначений",
                    "full_name": "ТаблицаЗначений",
                    "title": "ТаблицаЗначений",
                    "summary": "Коллекция строк и колонок.",
                    "topic_path": "ValueTable.md",
                    "version": "8.3.27.1859",
                    "kind": "type",
                }
            ],
        ),
    ):
        result = asyncio.run(
            app.call_tool("get_1c_api_answer", {"name": "ТаблицаЗначений"}),
        )
    text = result.content[0].text if result.content else ""
    assert "ТаблицаЗначений" in text
    assert "Коллекция строк" in text


def test_mcp_tool_get_1c_api_object_via_app(help_sample_dir: Path) -> None:
    """get_1c_api_object returns structured API payload from onec_help_api_objects."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_get_api_object",
        return_value=[
            {
                "name": "HTTPСоединение",
                "full_name": "HTTPСоединение",
                "title": "HTTPСоединение",
                "summary": "Описание типа.",
                "topic_path": "HTTPConnection.md",
                "version": "8.3.27.1859",
                "kind": "type",
                "entity_type": "type",
                "breadcrumb": ["Объекты"],
            }
        ],
    ):
        result = asyncio.run(app.call_tool("get_1c_api_object", {"name": "HTTPСоединение"}))
    text = result.content[0].text if result.content else ""
    assert "HTTPСоединение" in text
    assert "HTTPConnection.md" in text


def test_mcp_tool_get_1c_api_related_via_app(help_sample_dir: Path) -> None:
    """get_1c_api_related returns structured links for one API name."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_get_api_related",
        return_value=[
            {
                "source_full_name": "HTTPСоединение.Получить",
                "target_name": "HTTPСоединение.ПолучитьЗаголовки",
                "link_kind": "see_also",
                "topic_path": "Get.md",
            }
        ],
    ):
        result = asyncio.run(
            app.call_tool("get_1c_api_related", {"name": "HTTPСоединение.Получить"})
        )
    text = result.content[0].text if result.content else ""
    assert "ПолучитьЗаголовки" in text


def test_mcp_tool_answer_1c_help_question_uses_structured_availability(
    help_sample_dir: Path,
) -> None:
    """Natural-language factual question should answer from structured availability when possible."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_search_help_question_candidates",
        return_value=[
            {
                "name": "МенеджерКриптографии.ИнтерактивныйВвод",
                "full_name": "МенеджерКриптографии.ИнтерактивныйВвод",
                "summary": "Интерактивный ввод параметров криптографии.",
                "availability": "Использование в версии: 8.3.27.1859 и выше.",
                "topic_path": "CryptoInput.md",
                "version": "8.3.27.1859",
            }
        ],
    ):
        result = asyncio.run(
            app.call_tool(
                "answer_1c_help_question",
                {"question": "с какой версии в менеджере криптографии доступен интерактивный ввод"},
            )
        )
    text = result.content[0].text if result.content else ""
    assert "Использование в версии" in text
    assert "МенеджерКриптографии.ИнтерактивныйВвод" in text


def test_mcp_tool_answer_1c_help_question_falls_back_to_topic_fact(help_sample_dir: Path) -> None:
    """Natural-language factual question should answer from structured source sections without topic fallback."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_search_help_question_candidates",
        return_value=[
            {
                "name": "МенеджерКриптографии.ИнтерактивныйВвод",
                "full_name": "МенеджерКриптографии.ИнтерактивныйВвод",
                "summary": "",
                "availability": "",
                "description": "Доступно начиная с версии 8.3.27.1859.",
                "source_sections": {"availability": "Доступно начиная с версии 8.3.27.1859."},
                "topic_path": "CryptoInput.md",
                "version": "8.3.27.1859",
            }
        ],
    ):
        result = asyncio.run(
            app.call_tool(
                "answer_1c_help_question",
                {"question": "с какой версии доступен интерактивный ввод менеджера криптографии"},
            )
        )
    text = result.content[0].text if result.content else ""
    assert "8.3.27.1859" in text
    assert "Источник" in text


def test_mcp_tool_search_1c_api_ranks_structured_member_first(help_sample_dir: Path) -> None:
    """search_1c_api should render structured API member in the member section."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch.object(
        mcp_server,
        "_search_api_members",
        return_value=[
            {
                "name": "HTTPСоединение.Получить",
                "full_name": "HTTPСоединение.Получить",
                "summary": "Описание.",
                "topic_path": "Get.md",
                "kind": "method",
                "entity_type": "method",
                "breadcrumb": ["Объекты", "HTTPСоединение"],
            }
        ],
    ):
        with patch.object(mcp_server, "_search_api_objects", return_value=[]):
            with patch.object(mcp_server, "_search_official_examples", return_value=[]):
                result = asyncio.run(
                    app.call_tool("search_1c_api", {"query": "HTTPСоединение.Получить", "limit": 5})
                )
    text = result.content[0].text if result.content else ""
    assert "## API members" in text
    assert "HTTPСоединение.Получить" in text


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


def test_mcp_tool_save_1c_snippet_empty_rejected(help_sample_dir: Path) -> None:
    """save_1c_snippet rejects whitespace-only code."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    result = asyncio.run(
        app.call_tool(
            "save_1c_snippet",
            {"code_snippet": "   \n\t", "description": "x", "title": "y"},
        )
    )
    text = result.content[0].text if result.content else ""
    assert "non-empty" in text.lower() or "Provide" in text


def test_mcp_tool_compare_1c_help_via_app(help_sample_dir: Path) -> None:
    """Call compare_1c_help tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    with patch(
        "onec_help.search_store.indexer.compare_1c_help",
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
        (
            "file:///projects/App/InformationRegisters/Prices/RecordSetModule.bsl",
            "RecordSetModule",
            "Prices",
        ),
        ("file:///projects/App/Catalogs/Товары/ManagerModule.bsl", "ManagerModule", "Товары"),
        ("file:///projects/App/Documents/Накладная/ObjectModule.bsl", "ObjectModule", "Накладная"),
    ]
    for uri, expected_type, expected_obj in cases:
        result = asyncio.run(app.call_tool("get_module_info", {"uri_or_path": uri}))
        text = result.content[0].text if result.content else ""
        assert expected_type in text, f"Expected {expected_type} in output for {uri}: {text}"
        assert expected_obj in text, f"Expected object {expected_obj} in output for {uri}: {text}"


def test_mcp_tool_search_1c_standards(help_sample_dir: Path) -> None:
    """search_1c_standards isolates standards-only output."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    memory_results = [
        {"payload": {"title": "Стандарт", "domain": "standards"}},
    ]
    with patch("onec_help.knowledge.memory.get_memory_store") as mock_store:
        mock_store.return_value.search_long.return_value = memory_results
        result = asyncio.run(
            app.call_tool(
                "search_1c_standards",
                {"query": "тест", "limit": 5},
            )
        )
    text = result.content[0].text if result.content else ""
    assert "Стандарты" in text
    assert "Стандарт" in text


def test_mcp_tool_search_1c_snippets(help_sample_dir: Path) -> None:
    """search_1c_snippets isolates snippets/community_help output with code blocks."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    memory_results = [
        {"payload": {"title": "Пример", "domain": "snippets", "code_snippet": "Сообщить(1);"}},
    ]
    with patch("onec_help.knowledge.memory.get_memory_store") as mock_store:
        mock_store.return_value.search_long.return_value = memory_results
        result = asyncio.run(
            app.call_tool(
                "search_1c_snippets",
                {"query": "тест", "limit": 5},
            )
        )
    text = result.content[0].text if result.content else ""
    assert "Сниппеты" in text
    assert "Сообщить(1)" in text or "Пример" in text


@patch("onec_help.knowledge.metadata_graph.search_metadata_exact")
def test_mcp_tool_search_1c_metadata_exact_via_app(mock_search_meta, help_sample_dir: Path) -> None:
    """Call search_1c_metadata_exact tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    mock_search_meta.return_value = [
        {
            "id": "Document.Sales",
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
            "search_1c_metadata_exact",
            {"query": "Sales", "config_version": "1.0.0.0", "object_type": None, "limit": 5},
        )
    )
    text = result.content[0].text if result.content else ""
    assert "Sales" in text or "Document" in text
    assert "`Cfg`" in text and "`1.0.0.0`" in text


@patch("onec_help.knowledge.metadata_graph.search_metadata_semantic")
def test_mcp_tool_search_1c_metadata_semantic_via_app(
    mock_search_meta, help_sample_dir: Path
) -> None:
    """Call search_1c_metadata_semantic tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    mock_search_meta.return_value = [
        {
            "id": "Document.Sales",
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
            "search_1c_metadata_semantic",
            {
                "query": "документ продажи",
                "config_version": "1.0.0.0",
                "object_type": None,
                "limit": 5,
            },
        )
    )
    text = result.content[0].text if result.content else ""
    assert "Sales" in text or "Document" in text
    assert "`Cfg`" in text


@patch("onec_help.knowledge.metadata_graph.search_metadata_fields")
def test_mcp_tool_search_1c_metadata_fields_via_app(
    mock_search_fields, help_sample_dir: Path
) -> None:
    """Call search_1c_metadata_fields tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    mock_search_fields.return_value = [
        {
            "object_id": "Document.Sales",
            "object_name": "Sales",
            "object_type": "Document",
            "config_name": "Cfg",
            "config_version": "1.0.0.0",
            "field_group": "requisites",
            "field_name": "Организация",
            "field_synonym": "Организация",
            "field_type": "СправочникСсылка.Организации",
        }
    ]
    result = asyncio.run(
        app.call_tool(
            "search_1c_metadata_fields",
            {
                "object_query": "Sales",
                "field_query": "Организация",
                "config_version": "1.0.0.0",
                "object_type": "Document",
                "limit": 5,
                "exact_object_first": True,
            },
        )
    )
    text = result.content[0].text if result.content else ""
    assert "Организация" in text
    assert "Document Sales" in text
    assert "`Cfg`" in text


@patch("onec_help.knowledge.metadata_graph.get_metadata_object")
def test_mcp_tool_get_1c_metadata_object_via_app(mock_get_meta, help_sample_dir: Path) -> None:
    """Call get_1c_metadata_object tool via app."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    mock_get_meta.return_value = {
        "id": "Document.Sales",
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
            {"object_id": "Document.Sales", "config_version": "1.0.0.0"},
        )
    )
    text = result.content[0].text if result.content else ""
    assert "Sales" in text or "Document" in text


@patch("onec_help.knowledge.context_builder.build_context")
def test_mcp_tool_get_1c_task_context_via_app(mock_build_ctx, help_sample_dir: Path) -> None:
    """get_1c_task_context returns compact local context and top results."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    mock_build_ctx.return_value = {
        "query_type": "metadata",
        "local_context": {
            "module_type": "ObjectModule",
            "object_type": "Document",
            "object_name": "Sales",
            "form_name": "",
            "symbol_name": "ОбработкаПроведения",
        },
        "help_topics": [
            {"title": "Проведение", "path": "post.md", "text": "Описание проведения документа"}
        ],
        "memory": [
            {
                "payload": {
                    "title": "Стандарт",
                    "domain": "standards",
                    "description": "Проверяйте движения",
                }
            }
        ],
        "metadata_objects": [{"id": "Document.Sales", "object_type": "Document", "name": "Sales"}],
    }
    result = asyncio.run(
        app.call_tool(
            "get_1c_task_context",
            {
                "query": "провести документ",
                "file_uri": "file:///projects/Documents/Sales/ObjectModule.bsl",
                "symbol_name": "ОбработкаПроведения",
                "diagnostics_json": '[{"severity":"warning"}]',
                "config_version": "CfgVer",
            },
        )
    )
    text = result.content[0].text if result.content else ""
    assert "Task context" in text
    assert "ObjectModule" in text
    assert "Document Sales" in text
    assert "diagnostics" in text


def test_mcp_tool_get_1c_quick_guide_develop_via_app(help_sample_dir: Path) -> None:
    """Quick guide should expose the AI-first route and BSL LS validation hint."""
    app = mcp_server._build_mcp_app(help_sample_dir)
    result = asyncio.run(app.call_tool("get_1c_quick_guide", {"task": "develop"}))
    text = result.content[0].text if result.content else ""
    assert "get_1c_api_answer" in text
    assert "get_1c_api_object" in text
    assert "include_examples" in text
    assert "get_1c_task_context" in text
    assert "search_1c_standards" in text
    assert "search_1c_metadata_exact" in text
    assert "BSL Language Server" in text or "bsl-language-server" in text.lower()
