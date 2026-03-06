"""Tests for indexer module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from onec_help import indexer as indexer_mod
from onec_help.indexer import (
    _apply_outgoing_links,
    _bm25_enabled,
    _build_path_to_section,
    _collection_info_int,
    _extract_keywords,
    _infer_entity_type,
    _path_to_point_id,
    _upsert_batch_with_retry,
    _version_sort_key,
    add_bm25_to_collection,
    build_index,
    compare_1c_help,
    get_1c_help_related,
    get_all_collections_status,
    get_collection_vector_size,
    get_embedding_dimension,
    get_index_status,
    get_topic_by_path,
    get_topic_content,
    get_topic_from_index,
    get_topic_metadata,
    list_index_nav_items,
    list_index_titles,
    search_hybrid,
    search_index,
    search_index_keyword,
)


def test_get_embedding_dimension_delegates_to_embedding() -> None:
    """indexer.get_embedding_dimension delegates to embedding module."""
    dim = get_embedding_dimension()
    assert isinstance(dim, int)
    assert dim > 0
    from onec_help import embedding

    assert dim == embedding.get_embedding_dimension()


def test_collection_info_int() -> None:
    """_collection_info_int reads from object attributes or dict keys."""
    from types import SimpleNamespace

    assert (
        _collection_info_int(SimpleNamespace(points_count=100), "points_count", "pointsCount")
        == 100
    )
    assert _collection_info_int({"indexed_vectors_count": 200}, "indexed_vectors_count") == 200
    assert _collection_info_int(SimpleNamespace(segments_count=0), "segments_count") == 0
    assert _collection_info_int(SimpleNamespace(), "points_count") == 0


def test_is_qdrant_500() -> None:
    """_is_qdrant_500 detects 500 and UnexpectedResponse."""

    class UnexpectedResponse(Exception):
        pass

    assert indexer_mod._is_qdrant_500(Exception("500 Internal Server Error")) is True
    assert indexer_mod._is_qdrant_500(Exception("Internal server error")) is True
    assert indexer_mod._is_qdrant_500(UnexpectedResponse("oops")) is True
    assert indexer_mod._is_qdrant_500(Exception("404 Not Found")) is False
    assert indexer_mod._is_qdrant_500(ValueError("bad")) is False


def test_upsert_batch_with_retry_retries_then_splits() -> None:
    """_upsert_batch_with_retry retries on 500, then splits batch on repeated failure."""
    from unittest.mock import Mock

    client = Mock()
    err_500 = Exception("Unexpected Response: 500 (Internal Server Error)")
    # First two upserts raise 500, then two half-batch upserts succeed
    client.upsert.side_effect = [err_500, err_500, None, None]
    points = [Mock(), Mock(), Mock(), Mock()]
    with patch("onec_help.indexer.time.sleep"):
        _upsert_batch_with_retry(client, "onec_help", points)
    assert client.upsert.call_count == 4
    # First call: full batch (fail), second: retry full (fail), third/fourth: half batches
    calls = client.upsert.call_args_list
    assert len(calls[0][1]["points"]) == 4
    assert len(calls[1][1]["points"]) == 4
    assert len(calls[2][1]["points"]) == 2
    assert len(calls[3][1]["points"]) == 2


@patch("onec_help.indexer.QdrantClient")
def test_get_collection_vector_size(mock_client: MagicMock) -> None:
    """get_collection_vector_size returns vector size from collection config."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    # config.params.vectors is VectorParams with size
    mock_vectors = MagicMock(size=768)
    mock_params = MagicMock(vectors=mock_vectors)
    mock_config = MagicMock(params=mock_params)
    mock_instance.get_collection.return_value = MagicMock(config=mock_config)
    assert get_collection_vector_size(collection="onec_help") == 768
    mock_instance.collection_exists.return_value = False
    assert get_collection_vector_size(collection="nonexistent") is None


@patch("onec_help.indexer.QdrantClient")
def test_get_collection_vector_size_vectors_dict(mock_client: MagicMock) -> None:
    """get_collection_vector_size returns size when vectors is Dict[str, VectorParams]."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    mock_first = MagicMock(size=384)
    mock_params = MagicMock(vectors={"default": mock_first})
    mock_config = MagicMock(params=mock_params)
    mock_instance.get_collection.return_value = MagicMock(config=mock_config)
    assert get_collection_vector_size(collection="onec_help") == 384


def test_build_index_no_qdrant_client(tmp_path: Path) -> None:
    """When QdrantClient is not available, build_index raises RuntimeError."""
    (tmp_path / "a.md").write_text("# A\n\nBody.", encoding="utf-8")
    with patch.object(indexer_mod, "QdrantClient", None):
        with pytest.raises(RuntimeError, match="qdrant-client"):
            build_index(tmp_path)


def test_get_topic_by_path(help_sample_dir: Path) -> None:
    content = get_topic_by_path(help_sample_dir, "field626.html")
    assert content
    content2 = get_topic_by_path(help_sample_dir, "field626")
    assert content2


def test_get_topic_by_path_missing(help_sample_dir: Path) -> None:
    assert get_topic_by_path(help_sample_dir, "nonexistent") == ""


def test_get_topic_by_path_traversal_rejected(help_sample_dir: Path) -> None:
    """Path traversal outside help_path returns empty string (no file read)."""
    assert get_topic_by_path(help_sample_dir, "../../../etc/passwd") == ""
    assert get_topic_by_path(help_sample_dir, "..") == ""


@patch("onec_help.indexer.QdrantClient")
def test_search_index(mock_client: MagicMock) -> None:
    mock_client.return_value.search.return_value = []
    result = search_index("query", limit=5)
    assert isinstance(result, list)


@patch("onec_help.indexer.search_index_keyword")
@patch("onec_help.indexer.search_index")
def test_search_hybrid_rrf_merge(mock_search: MagicMock, mock_keyword: MagicMock) -> None:
    """search_hybrid merges semantic and keyword results with RRF."""
    mock_search.return_value = [{"path": "a.html", "title": "A"}, {"path": "b.html", "title": "B"}]
    mock_keyword.return_value = [{"path": "b.html", "title": "B"}, {"path": "c.html", "title": "C"}]
    result = search_hybrid("query", limit=5, qdrant_host="localhost", qdrant_port=6333)
    assert len(result) <= 5
    paths = [r["path"] for r in result]
    assert "a.html" in paths
    assert "b.html" in paths
    assert "c.html" in paths
    mock_search.assert_called_once()
    mock_keyword.assert_called_once()


def test_infer_entity_type() -> None:
    """_infer_entity_type infers from section_path and breadcrumb."""
    assert _infer_entity_type("obj/Запрос/Методы/Выполнить", []) == "method"
    assert _infer_entity_type("obj/Form/Properties/Title", []) == "property"
    assert _infer_entity_type("", ["Свойства"]) == "property"
    assert _infer_entity_type("Types/СправочникСсылка", ["Типы"]) == "type"
    assert _infer_entity_type("", []) == "topic"
    assert _infer_entity_type("obj/Документ/События/ОбработкаПроведения", []) == "event"


def test_version_sort_key() -> None:
    """_version_sort_key parses version strings for comparison (newest first)."""
    assert _version_sort_key("8.3.27.1859") == (8, 3, 27, 1859)
    assert _version_sort_key("8.3.26") == (8, 3, 26)
    assert _version_sort_key("8.3.27.1859") > _version_sort_key("8.3.26")
    assert _version_sort_key("8.3.27") > _version_sort_key("8.3.26")
    assert _version_sort_key("") == (0,)
    assert _version_sort_key("invalid") == (0,)


def test_extract_keywords() -> None:
    """_extract_keywords extracts CamelCase and Cyrillic identifiers."""
    assert "ОбработкаДанных" in _extract_keywords("ОбработкаДанных.Выполнить")
    assert "Выполнить" in _extract_keywords("ОбработкаДанных.Выполнить")
    assert "GetValue" in _extract_keywords("Object.GetValue(x)")
    assert _extract_keywords("ab") == []  # min 3 chars
    assert _extract_keywords("") == []


@patch("onec_help.indexer.QdrantClient")
def test_build_index(mock_client: MagicMock, help_sample_dir: Path, tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# Test\n\nBody.", encoding="utf-8")
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    n = build_index(tmp_path, qdrant_host="localhost", qdrant_port=6333)
    assert n >= 1
    mock_instance.recreate_collection.assert_called_once()
    mock_instance.upsert.assert_called_once()


@patch("onec_help.indexer.QdrantClient")
def test_build_index_uses_toc_json(mock_client: MagicMock, tmp_path: Path) -> None:
    """When source_dir has .toc.json, payload uses title/section_path/breadcrumb from TOC."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "one.md").write_text("# Fallback\n\nBody.", encoding="utf-8")
    toc = tmp_path / "source"
    toc.mkdir()
    (toc / ".toc.json").write_text(
        '[{"path": "one.html", "title_ru": "From TOC", "title_en": "From TOC en", '
        '"breadcrumb": ["Раздел", "Страница"], "entity_type": "topic"}]',
        encoding="utf-8",
    )
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    n = build_index(
        docs,
        qdrant_host="localhost",
        qdrant_port=6333,
        source_dir=str(toc),
    )
    assert n >= 1
    call = mock_instance.upsert.call_args
    points = call.kwargs.get("points", call.args[0] if call.args else [])
    assert points
    payload = points[0].payload if hasattr(points[0], "payload") else {}
    assert payload.get("title") == "From TOC"
    assert payload.get("breadcrumb") == ["Раздел", "Страница"]
    assert "section_path" in payload


@patch("onec_help.indexer.QdrantClient")
def test_build_index_keywords_in_payload(mock_client: MagicMock, tmp_path: Path) -> None:
    """build_index adds keywords from title and first paragraph to payload."""
    (tmp_path / "func.md").write_text(
        "# ОбработкаДанных.Выполнить\n\nВыполняет операцию.", encoding="utf-8"
    )
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    build_index(tmp_path, qdrant_host="localhost", qdrant_port=6333)
    call = mock_instance.upsert.call_args
    points = call.kwargs.get("points", call.args[0] if call.args else [])
    assert points
    payload = points[0].payload if hasattr(points[0], "payload") else {}
    kw = payload.get("keywords", []) if isinstance(payload, dict) else []
    assert kw, "keywords should be present"
    assert "ОбработкаДанных" in kw or "Выполнить" in kw


@patch("onec_help.indexer.QdrantClient")
def test_build_index_html_only(mock_client: MagicMock, help_sample_dir: Path) -> None:
    """Index when only .html exist (no .md) - uses html2md fallback."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    n = build_index(help_sample_dir, qdrant_host="localhost", qdrant_port=6333)
    assert n >= 1
    mock_instance.upsert.assert_called_once()


@patch("onec_help.indexer.QdrantClient")
def test_build_index_extensionless_html(mock_client: MagicMock, tmp_path: Path) -> None:
    """Index when only extension-less file that looks like HTML exists."""
    (tmp_path / "noext").write_text("<html><body><h1>Title</h1></body></html>", encoding="utf-8")
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    n = build_index(tmp_path, qdrant_host="localhost", qdrant_port=6333)
    assert n >= 1
    mock_instance.upsert.assert_called_once()


@patch("onec_help.indexer.QdrantClient")
def test_build_index_incremental_creates_collection(mock_client: MagicMock, tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# One\n\nBody.", encoding="utf-8")
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = False
    n = build_index(tmp_path, qdrant_host="localhost", qdrant_port=6333, incremental=True)
    assert n >= 1
    mock_instance.create_collection.assert_called_once()
    mock_instance.upsert.assert_called_once()


def test_path_to_point_id() -> None:
    a = _path_to_point_id("a.md", version="8.3", language="ru")
    b = _path_to_point_id("a.md", version="8.3", language="ru")
    assert a == b
    c = _path_to_point_id("b.md", version="8.3", language="ru")
    assert a != c
    assert isinstance(a, int)
    assert 0 <= a < 2**63


@patch("onec_help.indexer.QdrantClient")
def test_get_index_status_no_collection(mock_client: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = False
    s = get_index_status(qdrant_host="localhost", qdrant_port=6333)
    assert s["exists"] is False
    assert s.get("points_count", 0) == 0


@patch("onec_help.indexer.QdrantClient")
def test_get_index_status_exists(mock_client: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    mock_instance.get_collection.return_value = MagicMock(points_count=100)
    mock_instance.scroll.return_value = (
        [
            MagicMock(payload={"version": "8.3", "language": "ru"}),
            MagicMock(payload={"version": "8.3", "language": "en"}),
        ],
        None,
    )
    s = get_index_status(qdrant_host="localhost", qdrant_port=6333)
    assert s["exists"] is True
    assert s["points_count"] == 100
    assert "8.3" in s.get("versions", [])
    assert "ru" in s.get("languages", [])
    assert "en" in s.get("languages", [])


@patch("onec_help.indexer.QdrantClient", None)
def test_get_index_status_no_qdrant_client() -> None:
    s = get_index_status(qdrant_host="localhost", qdrant_port=6333)
    assert s.get("error") == "qdrant-client not available"
    assert s["exists"] is False


@patch("onec_help.indexer.QdrantClient")
def test_get_index_status_connection_error(mock_client: MagicMock) -> None:
    mock_client.side_effect = RuntimeError("connection refused")
    s = get_index_status(qdrant_host="localhost", qdrant_port=6333)
    assert "error" in s
    assert s["exists"] is False


@patch("onec_help.indexer.QdrantClient")
def test_get_index_status_get_collection_raises(mock_client: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    mock_instance.get_collection.side_effect = RuntimeError("timeout")
    s = get_index_status(qdrant_host="localhost", qdrant_port=6333)
    assert s["exists"] is True
    assert "error" in s
    assert s.get("points_count") is None


@patch("onec_help.indexer.QdrantClient")
def test_get_all_collections_status(mock_client: MagicMock) -> None:
    """get_all_collections_status returns list of collection stats from get_collections."""
    from types import SimpleNamespace

    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.get_collections.return_value = MagicMock(
        collections=[
            SimpleNamespace(name="onec_help"),
            SimpleNamespace(name="onec_help_memory"),
        ]
    )
    mock_instance.get_collection.side_effect = [
        MagicMock(points_count=100, indexed_vectors_count=100, segments_count=2),
        MagicMock(points_count=50, indexed_vectors_count=50, segments_count=1),
    ]
    result = get_all_collections_status(qdrant_host="localhost", qdrant_port=6333)
    assert len(result) == 2
    assert result[0]["name"] == "onec_help"
    assert result[0]["points_count"] == 100
    assert result[0]["indexed_vectors_count"] == 100
    assert result[0]["segments_count"] == 2
    assert result[1]["name"] == "onec_help_memory"
    assert result[1]["points_count"] == 50


@patch("onec_help.indexer.QdrantClient", None)
def test_get_all_collections_status_no_client() -> None:
    assert get_all_collections_status(qdrant_host="localhost", qdrant_port=6333) == []


@patch("onec_help.indexer.QdrantClient")
def test_get_all_collections_status_connection_error(mock_client: MagicMock) -> None:
    mock_client.side_effect = RuntimeError("connection refused")
    assert get_all_collections_status(qdrant_host="localhost", qdrant_port=6333) == []


@patch("onec_help.indexer.QdrantClient")
def test_search_index_query_points(mock_client: MagicMock) -> None:
    """search_index uses query_points when available (qdrant-client 2.x)."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.query_points.return_value = MagicMock(points=[])
    result = search_index("query", limit=5)
    assert isinstance(result, list)
    assert mock_instance.query_points.called or mock_instance.search.called


@patch("onec_help.indexer.QdrantClient")
def test_search_index_entity_type_filter(mock_client: MagicMock) -> None:
    """search_index passes entity_type to query_filter when set."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.query_points.return_value = MagicMock(points=[])
    search_index("query", limit=5, entity_type="method")
    call_kw = mock_instance.query_points.call_args[1]
    assert call_kw.get("query_filter") is not None
    must = getattr(call_kw["query_filter"], "must", [])
    assert any(getattr(c, "key", None) == "entity_type" for c in must), (
        "entity_type filter should be in must"
    )


@patch("onec_help.indexer.QdrantClient")
def test_search_index_keyword_empty_query(mock_client: MagicMock) -> None:
    assert search_index_keyword("  ", limit=5) == []
    assert search_index_keyword("", limit=5) == []


@patch("onec_help.indexer.QdrantClient", None)
def test_search_index_keyword_no_client() -> None:
    assert search_index_keyword("term") == []


@patch("onec_help.indexer.QdrantClient")
def test_search_index_keyword_hits(mock_client: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.scroll.return_value = (
        [MagicMock(payload={"path": "a.md", "title": "Term here", "text": "body"})],
        None,
    )
    result = search_index_keyword("term", limit=5)
    assert len(result) == 1
    assert result[0]["path"] == "a.md"
    assert result[0]["title"] == "Term here"


@patch("onec_help.indexer.QdrantClient")
def test_search_index_keyword_type_method_mode_sorts_title_first(mock_client: MagicMock) -> None:
    """Query with '.' (Type.Method) uses substring mode and ranks title matches first."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    # First batch: text-only match, then title match (scroll order arbitrary)
    mock_instance.scroll.return_value = (
        [
            MagicMock(
                payload={
                    "path": "text_match.md",
                    "title": "Other",
                    "text": "HTTPСоединение.Получить does something",
                }
            ),
            MagicMock(
                payload={
                    "path": "title_match.md",
                    "title": "HTTPСоединение.Получить (HTTPConnection.Get)",
                    "text": "body",
                }
            ),
        ],
        None,
    )
    result = search_index_keyword("HTTPСоединение.Получить", limit=5)
    assert len(result) == 2
    # Title match must come first
    assert result[0]["path"] == "title_match.md"
    assert result[1]["path"] == "text_match.md"


@patch("onec_help.indexer.QdrantClient", None)
def test_list_index_titles_no_client() -> None:
    assert list_index_titles() == []


@patch("onec_help.indexer.QdrantClient")
def test_list_index_titles_with_prefix(mock_client: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.scroll.return_value = (
        [
            MagicMock(payload={"path": "zif/a.html", "title": "A"}),
            MagicMock(payload={"path": "other/b.html", "title": "B"}),
        ],
        None,
    )
    result = list_index_titles(path_prefix="zif", limit=10)
    assert len(result) == 1
    assert result[0]["path"] == "zif/a.html"


@patch("onec_help.indexer.QdrantClient")
@patch("onec_help.indexer.Filter")
@patch("onec_help.indexer.FieldCondition")
@patch("onec_help.indexer.MatchValue")
def test_get_topic_from_index_found(
    mock_mv: MagicMock,
    mock_fc: MagicMock,
    mock_f: MagicMock,
    mock_client: MagicMock,
) -> None:
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.scroll.return_value = (
        [MagicMock(payload={"path": "topic.md", "text": "Full topic text"})],
        None,
    )
    text = get_topic_from_index("topic.md", qdrant_host="localhost", qdrant_port=6333)
    assert text == "Full topic text"


def test_get_topic_content_from_disk(help_sample_dir: Path) -> None:
    content = get_topic_content(help_sample_dir, "field626.html")
    assert content
    assert "реквизит" in content.lower() or "field" in content.lower()


@patch("onec_help.indexer.get_topic_from_index", return_value="# From index\nContent")
def test_get_topic_content_prefer_index(mock_from_index: MagicMock) -> None:
    """get_topic_content with prefer_index=True skips disk and uses index only."""
    content = get_topic_content(
        "/any/path", "topic.md", qdrant_host="localhost", qdrant_port=6333, prefer_index=True
    )
    assert "From index" in content
    mock_from_index.assert_called_once()


@patch("onec_help.indexer.get_topic_by_path")
@patch("onec_help.indexer.get_topic_from_index")
def test_get_topic_content_fallback_to_index(
    mock_from_index: MagicMock,
    mock_by_path: MagicMock,
) -> None:
    mock_by_path.return_value = ""
    mock_from_index.return_value = "From index"
    content = get_topic_content("/none", "path/to/topic")
    assert content == "From index"
    mock_from_index.assert_called_once()


@patch("onec_help.indexer.QdrantClient")
def test_get_index_status_scroll_raises(mock_client: MagicMock) -> None:
    """When scroll raises, status still returns exists/points_count without versions."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    mock_instance.get_collection.return_value = MagicMock(points_count=50)
    mock_instance.scroll.side_effect = RuntimeError("scroll error")
    s = get_index_status(qdrant_host="localhost", qdrant_port=6333)
    assert s["exists"] is True
    assert s["points_count"] == 50
    assert "versions" not in s or s.get("versions") is None


@patch("onec_help.indexer.QdrantClient")
@patch("onec_help.indexer.Filter")
@patch("onec_help.indexer.FieldCondition")
@patch("onec_help.indexer.MatchValue")
def test_get_topic_from_index_fallback_scroll(
    mock_mv: MagicMock,
    mock_fc: MagicMock,
    mock_f: MagicMock,
    mock_client: MagicMock,
) -> None:
    """First scroll (with filter) returns empty; fallback scroll finds by path."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.scroll.side_effect = [
        ([], None),
        ([MagicMock(payload={"path": "sub/topic.html", "text": "Fallback text"})], None),
    ]
    text = get_topic_from_index("topic.html", qdrant_host="localhost", qdrant_port=6333)
    assert text == "Fallback text"


@patch("onec_help.indexer.QdrantClient")
@patch("onec_help.indexer.Filter")
@patch("onec_help.indexer.FieldCondition")
@patch("onec_help.indexer.MatchValue")
def test_get_topic_from_index_path_variants_tries_md_then_html(
    mock_mv: MagicMock,
    mock_fc: MagicMock,
    mock_f: MagicMock,
    mock_client: MagicMock,
) -> None:
    """get_topic_from_index with path without extension tries .md then .html."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    # First variant "path/to/topic" -> empty; second "path/to/topic.md" -> found
    mock_instance.scroll.side_effect = [
        ([], None),
        ([MagicMock(payload={"path": "path/to/topic.md", "text": "Topic body"})], None),
    ]
    text = get_topic_from_index(
        "path/to/topic",
        qdrant_host="localhost",
        qdrant_port=6333,
    )
    assert text == "Topic body"


@patch("onec_help.indexer.QdrantClient")
def test_get_topic_from_index_apply_outgoing_links(mock_client: MagicMock) -> None:
    """get_topic_from_index applies _apply_outgoing_links when payload has outgoing_links."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.scroll.side_effect = [
        ([], None),
        (
            [
                MagicMock(
                    payload={
                        "path": "topic.html",
                        "text": "See [Other](other.html) for details.",
                        "outgoing_links": [
                            {
                                "href": "other.html",
                                "resolved_path": "other.md",
                                "link_text": "Other",
                            },
                        ],
                    }
                )
            ],
            None,
        ),
    ]
    text = get_topic_from_index("topic.html", qdrant_host="localhost", qdrant_port=6333)
    assert "other.md" in text
    assert "Связанные темы" in text or "Other" in text


@patch("onec_help.indexer.QdrantClient")
def test_build_index_multiple_batches(mock_client: MagicMock, tmp_path: Path) -> None:
    """Multiple .md files trigger multiple upsert batches when batch_size is small."""
    for i in range(5):
        (tmp_path / f"doc{i}.md").write_text(f"# Doc {i}\n\nBody.", encoding="utf-8")
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    n = build_index(tmp_path, qdrant_host="localhost", qdrant_port=6333, batch_size=2)
    assert n == 5
    assert mock_instance.upsert.call_count >= 2


def test_get_1c_help_related_no_qdrant_returns_empty() -> None:
    """get_1c_help_related returns [] when Filter is unavailable."""
    with patch.object(indexer_mod, "Filter", None):
        out = get_1c_help_related("topic.md", qdrant_host="localhost", qdrant_port=6333)
    assert out == []


@patch("onec_help.indexer.QdrantClient")
@patch("onec_help.indexer.Filter")
@patch("onec_help.indexer.FieldCondition")
@patch("onec_help.indexer.MatchValue")
def test_get_1c_help_related(
    _mock_mv: MagicMock,
    _mock_fc: MagicMock,
    _mock_f: MagicMock,
    mock_client: MagicMock,
) -> None:
    """get_1c_help_related returns outgoing_links from payload."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.scroll.return_value = (
        [
            MagicMock(
                payload={
                    "path": "topic.md",
                    "outgoing_links": [
                        {
                            "href": "a.html",
                            "resolved_path": "a.md",
                            "target_title": "A",
                            "link_text": "A",
                        },
                        {
                            "href": "#",
                            "resolved_path": None,
                            "target_title": "Anchor",
                            "link_text": "Anchor",
                        },
                    ],
                }
            )
        ],
        None,
    )
    result = get_1c_help_related("topic.md", qdrant_host="localhost", qdrant_port=6333)
    assert len(result) == 1
    assert result[0]["path"] == "a.md"
    assert result[0]["title"] == "A"


@patch("onec_help.indexer.QdrantClient")
def test_list_index_nav_items(mock_client: MagicMock) -> None:
    """list_index_nav_items returns path, title, breadcrumb from scroll payloads."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    mock_instance.scroll.return_value = (
        [
            MagicMock(
                payload={"path": "topic1.html", "title": "Topic 1", "breadcrumb": ["A", "B"]}
            ),
            MagicMock(payload={"path": "topic2.html", "title": "Topic 2"}),
        ],
        None,
    )
    out = list_index_nav_items(qdrant_host="localhost", qdrant_port=6333)
    assert len(out) == 2
    assert out[0]["path"] == "topic1.html"
    assert out[0]["title"] == "Topic 1"
    assert out[0]["breadcrumb"] == ["A", "B"]
    assert out[1]["path"] == "topic2.html"
    assert out[1]["title"] == "Topic 2"


@patch("onec_help.indexer.QdrantClient")
def test_list_index_nav_items_no_collection(mock_client: MagicMock) -> None:
    """list_index_nav_items returns [] when collection does not exist."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = False
    assert list_index_nav_items(qdrant_host="localhost", qdrant_port=6333) == []


@patch("onec_help.indexer.QdrantClient")
def test_list_index_nav_items_deduplicates_and_skips_empty_path(mock_client: MagicMock) -> None:
    """list_index_nav_items deduplicates by path and skips points with empty path."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    mock_instance.scroll.return_value = (
        [
            MagicMock(payload={"path": "a.html", "title": "A"}),
            MagicMock(payload={"path": "", "title": "No path"}),
            MagicMock(payload={"path": "a.html", "title": "A again"}),  # duplicate
            MagicMock(payload={"path": "b.html"}),
        ],
        None,
    )
    out = list_index_nav_items(qdrant_host="localhost", qdrant_port=6333, limit=10)
    assert len(out) == 2
    assert out[0]["path"] == "a.html"
    assert out[1]["path"] == "b.html"


@patch("onec_help.indexer.QdrantClient")
def test_list_index_nav_items_pagination(mock_client: MagicMock) -> None:
    """list_index_nav_items follows scroll offset until next_offset is None."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    mock_instance.scroll.side_effect = [
        (
            [MagicMock(payload={"path": "p1.html", "title": "P1"})],
            "offset1",
        ),
        (
            [MagicMock(payload={"path": "p2.html", "title": "P2"})],
            None,
        ),
    ]
    out = list_index_nav_items(qdrant_host="localhost", qdrant_port=6333, limit=10)
    assert len(out) == 2
    assert out[0]["path"] == "p1.html"
    assert out[1]["path"] == "p2.html"
    assert mock_instance.scroll.call_count == 2


def test_build_path_to_section() -> None:
    """_build_path_to_section returns path and stem keys with section_path and breadcrumb."""
    nodes = [
        {"title": "Root", "path": "root.html", "children": []},
        {
            "title": "Child",
            "path": "root/child.html",
            "children": [{"title": "Leaf", "path": "root/child/leaf.html", "children": []}],
        },
    ]
    result = _build_path_to_section(nodes, base_path="", breadcrumb=[])
    assert "root.html" in result
    assert result["root.html"] == ("", [])
    assert "root" in result
    assert "root/child.html" in result
    assert result["root/child.html"][0] == "" and result["root/child.html"][1] == []
    assert "root/child/leaf.html" in result
    # Leaf is under Child, so breadcrumb is ["Child"]
    assert result["root/child/leaf.html"][1] == ["Child"]


def test_bm25_enabled() -> None:
    """_bm25_enabled reads BM25_ENABLED env (default True)."""
    assert _bm25_enabled() is True
    with patch.dict("os.environ", {"BM25_ENABLED": "0"}, clear=False):
        assert _bm25_enabled() is False
    with patch.dict("os.environ", {"BM25_ENABLED": "false"}, clear=False):
        assert _bm25_enabled() is False
    with patch.dict("os.environ", {"BM25_ENABLED": "1"}, clear=False):
        assert _bm25_enabled() is True


def test_version_sort_key_edge_cases() -> None:
    """_version_sort_key handles mixed numeric and invalid parts (ValueError -> 0)."""
    assert _version_sort_key("8.3.27.1859") == (8, 3, 27, 1859)
    assert _version_sort_key("8.3.bad.4") == (8, 3, 0, 4)


@patch("onec_help.indexer.QdrantClient")
def test_get_all_collections_status_dict_collection(mock_client: MagicMock) -> None:
    """get_all_collections_status handles dict-style collection (name from key)."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.get_collections.return_value = MagicMock(collections=[{"name": "my_coll"}])
    mock_instance.get_collection.return_value = MagicMock(
        points_count=10, indexed_vectors_count=10, segments_count=1
    )
    result = get_all_collections_status(qdrant_host="localhost", qdrant_port=6333)
    assert len(result) == 1
    assert result[0]["name"] == "my_coll"


@patch("onec_help.indexer.QdrantClient")
def test_get_all_collections_status_get_collection_raises(mock_client: MagicMock) -> None:
    """get_all_collections_status appends None stats when get_collection raises."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.get_collections.return_value = MagicMock(
        collections=[MagicMock(name="onec_help")]
    )
    mock_instance.get_collection.side_effect = RuntimeError("timeout")
    result = get_all_collections_status(qdrant_host="localhost", qdrant_port=6333)
    assert len(result) == 1
    assert result[0]["points_count"] is None
    assert result[0]["indexed_vectors_count"] is None


@patch("onec_help.indexer.get_topic_content")
@patch("onec_help.indexer.QdrantClient")
def test_compare_1c_help_with_path(mock_client: MagicMock, mock_get_content: MagicMock) -> None:
    """compare_1c_help returns left/right content and optional diff."""
    mock_get_content.side_effect = ["Left version content", "Right version content"]
    out = compare_1c_help(
        "Format.md",
        version_left="8.3",
        version_right="8.3.27",
        qdrant_host="localhost",
        qdrant_port=6333,
        include_diff=True,
    )
    assert "8.3" in out
    assert "8.3.27" in out
    assert "Left version" in out
    assert "Right version" in out
    assert "Diff" in out
    assert mock_get_content.call_count == 2


@patch("onec_help.indexer.get_topic_content")
@patch("onec_help.indexer.search_index")
def test_compare_1c_help_query_resolves_path_then_compares(
    mock_search: MagicMock, mock_get_content: MagicMock
) -> None:
    """compare_1c_help with query (no .md/.html) resolves path via search_index then compares."""
    mock_search.return_value = [{"path": "Format.md", "title": "Format"}]
    mock_get_content.side_effect = ["Left", "Right"]
    out = compare_1c_help(
        "Format",
        version_left="8.3",
        version_right="8.3.27",
        qdrant_host="localhost",
        qdrant_port=6333,
    )
    assert "8.3" in out and "8.3.27" in out
    assert "Left" in out and "Right" in out
    mock_search.assert_called()
    assert mock_get_content.call_count == 2


@patch("onec_help.indexer.get_topic_content")
def test_compare_1c_help_topic_not_found_returns_message(mock_get_content: MagicMock) -> None:
    """compare_1c_help when both contents empty returns not found message."""
    mock_get_content.return_value = ""
    out = compare_1c_help(
        "Missing.md",
        version_left="8.3",
        version_right="8.3.27",
        qdrant_host="localhost",
        qdrant_port=6333,
    )
    assert "Topic not found" in out or "нет контента" in out


@patch("onec_help.indexer.search_index")
def test_compare_1c_help_query_no_results_returns_not_found(mock_search: MagicMock) -> None:
    """compare_1c_help when query has no .md/.html and search returns empty."""
    mock_search.return_value = []
    out = compare_1c_help(
        "NonexistentTopic",
        version_left="8.3",
        version_right="8.3.27",
        qdrant_host="localhost",
        qdrant_port=6333,
    )
    assert "Topic not found" in out or "not found" in out


@patch("onec_help.indexer.QdrantClient")
def test_add_bm25_to_collection_not_exists(mock_client: MagicMock) -> None:
    """add_bm25_to_collection raises when collection does not exist."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = False
    with pytest.raises(RuntimeError, match="does not exist"):
        add_bm25_to_collection(qdrant_host="localhost", qdrant_port=6333)


@patch("onec_help.indexer.get_collection_vector_size", return_value=384)
@patch("onec_help.embedding.get_embedding", return_value=[0.1] * 384)
@patch("onec_help.indexer.QdrantClient")
def test_search_index_uses_search_fallback(mock_client: MagicMock, mock_emb, mock_dim) -> None:
    """search_index uses client.search when query_points is not available."""
    mock_instance = MagicMock()
    del mock_instance.query_points
    mock_instance.search.return_value = [
        MagicMock(payload={"path": "a.md", "title": "A", "text": "x"}, score=0.9),
    ]
    mock_client.return_value = mock_instance
    result = search_index("q", limit=5)
    assert len(result) == 1
    assert result[0]["path"] == "a.md"
    mock_instance.search.assert_called_once()


@patch("onec_help.indexer.get_collection_vector_size", return_value=384)
@patch("onec_help.embedding.get_embedding", return_value=[0.1] * 384)
@patch("onec_help.indexer.QdrantClient")
def test_search_index_with_version_returns_raw(mock_client: MagicMock, mock_emb, mock_dim) -> None:
    """search_index with version filter returns raw list (no dedup)."""
    mock_instance = MagicMock()
    mock_instance.query_points.return_value = MagicMock(
        points=[
            MagicMock(
                payload={"path": "p.md", "title": "T", "text": "x", "version": "8.3"}, score=0.8
            )
        ]
    )
    mock_client.return_value = mock_instance
    result = search_index("q", limit=5, version="8.3")
    assert len(result) == 1
    assert result[0].get("version") == "8.3"


@patch("onec_help.indexer.QdrantClient")
def test_list_index_titles_path_prefix_filters(mock_client: MagicMock) -> None:
    """list_index_titles filters by path_prefix and paginates."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.scroll.side_effect = [
        (
            [
                MagicMock(payload={"path": "zif_1.md", "title": "Z1"}),
                MagicMock(payload={"path": "other.md", "title": "O"}),
                MagicMock(payload={"path": "zif_2.md", "title": "Z2"}),
            ],
            None,
        ),
    ]
    out = list_index_titles(qdrant_host="localhost", qdrant_port=6333, limit=10, path_prefix="zif")
    assert len(out) == 2
    assert all(r["path"].startswith("zif") for r in out)


@patch("onec_help.indexer.QdrantClient")
def test_list_index_titles_scroll_exception(mock_client: MagicMock) -> None:
    """list_index_titles returns partial result when scroll raises."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.scroll.side_effect = [
        ([MagicMock(payload={"path": "a.md", "title": "A"})], "off"),
        RuntimeError("conn"),
    ]
    out = list_index_titles(qdrant_host="localhost", qdrant_port=6333, limit=10)
    assert len(out) == 1


def test_apply_outgoing_links_substitutes_and_appends_section() -> None:
    """_apply_outgoing_links substitutes href with resolved_path and appends Связанные темы."""
    text = "See [link](old/path.html) for details."
    payload = {
        "outgoing_links": [
            {"href": "old/path.html", "resolved_path": "new/path.md", "target_title": "New"},
        ],
    }
    out = _apply_outgoing_links(text, payload)
    assert "new/path.md" in out
    assert "Связанные темы" in out
    assert "- [New](new/path.md)" in out


def test_get_topic_metadata_no_qdrant_returns_defaults() -> None:
    """get_topic_metadata returns default dict when Filter/FieldCondition/MatchValue unavailable."""
    with patch.object(indexer_mod, "Filter", None):
        out = get_topic_metadata("doc.md", qdrant_host="localhost", qdrant_port=6333)
    assert out["breadcrumb"] == []
    assert out["outgoing_links"] == []
    assert out["entity_type"] == "topic"
    assert out["hbk_slug"] == ""


@patch("onec_help.indexer.QdrantClient")
def test_get_topic_metadata_returns_payload_fields(mock_client: MagicMock) -> None:
    """get_topic_metadata returns breadcrumb, outgoing_links, entity_type, hbk_slug from scroll."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.scroll.return_value = (
        [
            MagicMock(
                payload={
                    "path": "doc.md",
                    "breadcrumb": ["Справка", "Типы"],
                    "outgoing_links": [{"href": "a.html", "resolved_path": "a.md"}],
                    "entity_type": "topic",
                    "hbk_slug": "doc",
                }
            )
        ],
        None,
    )
    out = get_topic_metadata("doc.md", qdrant_host="localhost", qdrant_port=6333)
    assert out["breadcrumb"] == ["Справка", "Типы"]
    assert len(out["outgoing_links"]) == 1
    assert out["entity_type"] == "topic"
    assert out["hbk_slug"] == "doc"


@patch("onec_help.indexer.QdrantClient")
def test_get_topic_metadata_no_match_returns_defaults(mock_client: MagicMock) -> None:
    """get_topic_metadata returns default dict when no point matches."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.scroll.return_value = ([], None)
    out = get_topic_metadata("missing.md", qdrant_host="localhost", qdrant_port=6333)
    assert out["breadcrumb"] == []
    assert out["outgoing_links"] == []
    assert out["entity_type"] == "topic"
    assert out["hbk_slug"] == ""


@patch("onec_help.indexer.QdrantClient")
def test_get_topic_metadata_fallback_suffix_match(mock_client: MagicMock) -> None:
    """get_topic_metadata fallback: scroll without filter finds point by path suffix."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.scroll.side_effect = [
        ([], None),
        (
            [
                MagicMock(
                    payload={
                        "path": "8.3/ru/doc.md",
                        "breadcrumb": ["A", "B"],
                        "outgoing_links": [],
                        "entity_type": "topic",
                        "hbk_slug": "doc",
                    }
                )
            ],
            None,
        ),
    ]
    out = get_topic_metadata("doc.md", qdrant_host="localhost", qdrant_port=6333)
    assert out["breadcrumb"] == ["A", "B"]
    assert out["hbk_slug"] == "doc"


@patch("onec_help.indexer.QdrantClient")
def test_list_index_nav_items_scroll_raises_returns_partial(mock_client: MagicMock) -> None:
    """list_index_nav_items returns partial list when scroll raises after first batch."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    mock_instance.scroll.side_effect = [
        (
            [
                MagicMock(payload={"path": "a.md", "title": "A", "breadcrumb": []}),
            ],
            "next",
        ),
        RuntimeError("conn"),
    ]
    out = list_index_nav_items(qdrant_host="localhost", qdrant_port=6333, limit=10)
    assert len(out) == 1
    assert out[0]["path"] == "a.md"


@patch("onec_help.indexer.QdrantClient", None)
def test_get_topic_from_index_no_client() -> None:
    """get_topic_from_index returns '' when QdrantClient is not available."""
    assert get_topic_from_index("topic.md", qdrant_host="localhost", qdrant_port=6333) == ""


@patch("onec_help.indexer.QdrantClient", None)
def test_search_index_no_client_returns_empty() -> None:
    """search_index returns [] when QdrantClient is not available."""
    assert search_index("query", limit=5) == []


@patch("onec_help.indexer._collection_has_sparse", return_value=True)
@patch("onec_help.indexer.QdrantClient")
def test_add_bm25_already_has_sparse_saves_vocab(mock_client: MagicMock, mock_has_sparse) -> None:
    """add_bm25 when collection already has BM25 scrolls points and saves vocab."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    mock_instance.scroll.return_value = (
        [MagicMock(payload={"title": "T", "text": "Body"})],
        None,
    )
    mock_instance.get_collection.return_value = MagicMock(points_count=1)
    with patch("onec_help.sparse_bm25.build_bm25_vectors", return_value=([], {}, {})):
        with patch("onec_help.sparse_bm25.save_vocab"):
            n = add_bm25_to_collection(qdrant_host="localhost", qdrant_port=6333, verbose=False)
    assert n == 1


@patch("onec_help.indexer.QdrantClient", None)
def test_get_collection_vector_size_no_client() -> None:
    """get_collection_vector_size returns None when QdrantClient is not available."""
    assert get_collection_vector_size() is None


@patch("onec_help.indexer.QdrantClient", None)
def test_get_index_status_no_client() -> None:
    """get_index_status returns error dict when QdrantClient is not available."""
    out = get_index_status()
    assert out.get("error") == "qdrant-client not available"
    assert out.get("exists") is False
    assert out.get("points_count") == 0


@patch("onec_help.indexer.QdrantClient")
def test_get_index_status_connection_fails(mock_client: MagicMock) -> None:
    """get_index_status returns error when QdrantClient() raises."""
    mock_client.side_effect = OSError("Connection refused")
    out = get_index_status(qdrant_host="localhost", qdrant_port=6333)
    assert "error" in out
    assert out.get("exists") is False


@patch("onec_help.indexer.QdrantClient")
def test_get_index_status_scroll_raises_logs(mock_client: MagicMock) -> None:
    """get_index_status handles scroll exception and still returns points_count."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    mock_instance.get_collection.return_value = MagicMock(points_count=100)
    mock_instance.scroll.side_effect = RuntimeError("scroll failed")
    out = get_index_status(qdrant_host="localhost", qdrant_port=6333)
    assert out.get("exists") is True
    assert out.get("points_count") == 100
    assert "versions" not in out or out.get("versions") is None


def test_index_status_sample_size_env() -> None:
    """_index_status_sample_size reads env and clamps to 50..2000."""
    with patch.dict("os.environ", {"INDEX_STATUS_SAMPLE_SIZE": "500"}, clear=False):
        assert indexer_mod._index_status_sample_size() == 500
    with patch.dict("os.environ", {"INDEX_STATUS_SAMPLE_SIZE": "10"}, clear=False):
        assert indexer_mod._index_status_sample_size() == 50
    with patch.dict("os.environ", {"INDEX_STATUS_SAMPLE_SIZE": "9999"}, clear=False):
        assert indexer_mod._index_status_sample_size() == 2000


@patch("onec_help.indexer.QdrantClient")
def test_get_all_collections_status_connect_raises(mock_client: MagicMock) -> None:
    """get_all_collections_status returns [] when connection fails."""
    mock_client.side_effect = OSError("refused")
    assert get_all_collections_status(qdrant_host="localhost", qdrant_port=6333) == []


@patch("onec_help.indexer.QdrantClient")
def test_get_collection_vector_size_config_none(mock_client: MagicMock) -> None:
    """get_collection_vector_size returns None when collection config is None."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    mock_instance.get_collection.return_value = MagicMock(config=None)
    assert get_collection_vector_size(collection="onec_help") is None


@patch("onec_help.indexer.QdrantClient")
def test_get_collection_vector_size_params_none(mock_client: MagicMock) -> None:
    """get_collection_vector_size returns None when config.params is None."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    mock_config = MagicMock(params=None)
    mock_instance.get_collection.return_value = MagicMock(config=mock_config)
    assert get_collection_vector_size(collection="onec_help") is None


@patch("onec_help.indexer.QdrantClient")
def test_get_collection_vector_size_exception_returns_none(mock_client: MagicMock) -> None:
    """get_collection_vector_size returns None when get_collection raises."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.collection_exists.return_value = True
    mock_instance.get_collection.side_effect = RuntimeError("connection failed")
    assert get_collection_vector_size(collection="onec_help") is None


@patch("onec_help.indexer.QdrantClient")
def test_build_index_progress_callback_type_error_then_ok(
    mock_client: MagicMock, tmp_path: Path
) -> None:
    """build_index progress_callback: TypeError then one-arg call then success."""
    (tmp_path / "a.md").write_text("# A\n\nBody.", encoding="utf-8")
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    calls = []

    def cb(*args):
        calls.append(args)
        if len(calls) == 1:
            raise TypeError("need 1 arg")
        if len(calls) == 2:
            raise ValueError("err")
        return None

    with patch("onec_help.embedding.get_embedding_batch", return_value=[[0.1] * 384]):
        n = build_index(
            tmp_path,
            qdrant_host="localhost",
            qdrant_port=6333,
            progress_callback=cb,
        )
    assert n == 1
    assert len(calls) >= 2


@patch("onec_help.indexer.QdrantClient")
def test_build_index_embedding_mismatch_retry_succeeds(
    mock_client: MagicMock, tmp_path: Path
) -> None:
    """build_index retries embedding batch when count mismatch, then succeeds."""
    (tmp_path / "a.md").write_text("# A\n\nBody.", encoding="utf-8")
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    dim = 384
    vec = [0.1] * dim
    with patch("onec_help.embedding.get_embedding_batch") as mock_batch:
        mock_batch.side_effect = [[], [vec]]
        n = build_index(tmp_path, qdrant_host="localhost", qdrant_port=6333)
    assert n == 1
    assert mock_batch.call_count >= 2


@patch("onec_help.indexer.QdrantClient")
def test_search_index_keyword_empty_query_returns_empty(mock_client: MagicMock) -> None:
    """search_index_keyword returns [] for empty or whitespace-only query."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    assert search_index_keyword("", qdrant_host="localhost", qdrant_port=6333) == []
    assert search_index_keyword("   ", qdrant_host="localhost", qdrant_port=6333) == []


@patch("onec_help.sparse_bm25.query_vector", return_value={"indices": [1], "values": [1.0]})
@patch("onec_help.sparse_bm25.load_vocab", return_value=({"word": 0}, {0: 1}, 1))
@patch("onec_help.sparse_bm25.bm25_vocab_path", return_value=MagicMock(exists=True))
@patch("onec_help.indexer._collection_has_sparse", return_value=True)
@patch("onec_help.indexer.QdrantClient")
def test_search_index_keyword_bm25_with_filters(
    mock_client: MagicMock,
    mock_has_sparse: MagicMock,
    _mock_vocab_path: MagicMock,
    _mock_load_vocab: MagicMock,
    _mock_query_vector: MagicMock,
) -> None:
    """search_index_keyword BM25 path with version/language filter returns results."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    mock_instance.query_points = MagicMock(
        return_value=MagicMock(
            points=[
                MagicMock(
                    payload={
                        "path": "doc.md",
                        "title": "Doc",
                        "text": "Content",
                        "version": "8.3",
                        "language": "ru",
                    },
                    score=0.9,
                )
            ]
        )
    )
    result = search_index_keyword(
        "Запрос",
        qdrant_host="localhost",
        qdrant_port=6333,
        version="8.3",
        language="ru",
    )
    assert isinstance(result, list)
    if result:
        assert result[0].get("path") == "doc.md"


@patch("onec_help.indexer._collection_has_sparse", return_value=False)
@patch("onec_help.indexer.QdrantClient")
def test_search_index_keyword_fallback_scroll_substring(
    mock_client: MagicMock, mock_has_sparse: MagicMock
) -> None:
    """search_index_keyword fallback: keyword scroll returns no points, retry scroll finds by _matches."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    # First scroll (with keyword filter) returns empty -> out_dict empty -> fallback
    # Second scroll (no keyword filter) returns point that matches substring
    point = MagicMock(
        payload={
            "path": "doc.md",
            "title": "Запрос к данным",
            "text": "Описание запроса",
            "version": "8.3",
        }
    )
    mock_instance.scroll.side_effect = [
        ([], None),  # keyword filter returns no points
        ([point], None),
    ]
    result = search_index_keyword(
        "Запрос",
        qdrant_host="localhost",
        qdrant_port=6333,
        limit=5,
    )
    assert isinstance(result, list)
    assert len(result) >= 1
    assert result[0]["path"] == "doc.md"


@patch("onec_help.sparse_bm25.load_vocab", side_effect=OSError("vocab read failed"))
@patch("onec_help.sparse_bm25.bm25_vocab_path", return_value=MagicMock(exists=True))
@patch("onec_help.indexer._collection_has_sparse", return_value=True)
@patch("onec_help.indexer.QdrantClient")
def test_search_index_keyword_bm25_exception_falls_back_to_scroll(
    mock_client: MagicMock,
    mock_has_sparse: MagicMock,
    _mock_vocab_path: MagicMock,
    _mock_load_vocab: MagicMock,
) -> None:
    """When BM25 path raises (e.g. load_vocab), search_index_keyword falls back to scroll."""
    mock_instance = MagicMock()
    mock_client.return_value = mock_instance
    point = MagicMock(
        payload={
            "path": "doc.md",
            "title": "Запрос",
            "text": "Text",
            "version": "8.3",
        }
    )
    mock_instance.scroll.side_effect = [([], None), ([point], None)]
    result = search_index_keyword("Запрос", qdrant_host="localhost", qdrant_port=6333)
    assert isinstance(result, list)
    assert len(result) >= 1
    assert result[0]["path"] == "doc.md"
