from unittest.mock import patch

from onec_help.knowledge.context_builder import ContextRequest, build_context


def test_build_context_includes_help_and_memory_and_metadata() -> None:
    """build_context aggregates help_topics, memory and metadata_objects."""

    with (
        patch("onec_help.search_store.indexer.search_hybrid") as mock_help,
        patch("onec_help.knowledge.memory.get_memory_store") as mock_mem_store,
        patch("onec_help.knowledge.metadata_graph.search_metadata_exact") as mock_meta_exact,
        patch("onec_help.knowledge.metadata_graph.search_metadata_semantic") as mock_meta_semantic,
    ):
        mock_help.return_value = [
            {"path": "a.html", "title": "A", "text": "help snippet"},
        ]
        mock_mem_store.return_value.search_long.return_value = [
            {"payload": {"title": "Snippet", "code_snippet": "Сообщить(1);"}},
        ]
        mock_meta_exact.return_value = [
            {"id": "Document.Sales", "object_type": "Document", "name": "Sales"},
        ]
        mock_meta_semantic.return_value = []

        req = ContextRequest(
            query="Sales",
            config_version="CfgVer",
            file_uri="file:///projects/Module.bsl",
            symbol_name="Procedure",
            limit=3,
        )
        ctx = build_context(req)

    assert ctx["request"]["query"] == "Sales"
    assert ctx["query_type"] in {"metadata", "mixed"}
    assert len(ctx["help_topics"]) == 1
    assert len(ctx["memory"]) == 1
    assert len(ctx["metadata_objects"]) == 1


def test_build_context_uses_file_uri_to_focus_metadata() -> None:
    """Object name and type from file path should drive metadata lookup."""
    with (
        patch("onec_help.search_store.indexer.search_hybrid") as mock_help,
        patch("onec_help.knowledge.memory.get_memory_store") as mock_mem_store,
        patch("onec_help.knowledge.metadata_graph.search_metadata_exact") as mock_meta_exact,
        patch("onec_help.knowledge.metadata_graph.search_metadata_semantic") as mock_meta_semantic,
    ):
        mock_help.return_value = []
        mock_mem_store.return_value.search_long.return_value = []
        mock_meta_exact.return_value = [{"id": "Document.Sales", "name": "Sales"}]
        mock_meta_semantic.return_value = []

        ctx = build_context(
            ContextRequest(
                query="провести документ",
                config_version="CfgVer",
                file_uri="file:///projects/Documents/Sales/ObjectModule.bsl",
                symbol_name="ОбработкаПроведения",
                limit=5,
            )
        )

    assert ctx["local_context"]["object_type"] == "Document"
    assert ctx["local_context"]["object_name"] == "Sales"
    mock_meta_exact.assert_called_once_with("Sales", "Document", "CfgVer", limit=2)


def test_build_context_uses_keyword_route_for_api_queries() -> None:
    """API-like queries should use exact keyword lookup, not broad hybrid search."""
    with (
        patch("onec_help.search_store.indexer.search_index_keyword") as mock_kw,
        patch("onec_help.search_store.indexer.search_hybrid") as mock_help,
        patch("onec_help.knowledge.memory.get_memory_store") as mock_mem_store,
    ):
        mock_kw.return_value = [{"path": "Get.html", "title": "HTTPСоединение.Получить"}]
        mock_help.return_value = []
        mock_mem_store.return_value.search_long.return_value = []

        ctx = build_context(
            ContextRequest(
                query="HTTPСоединение.Получить",
                config_version=None,
                file_uri=None,
                symbol_name=None,
                limit=3,
            )
        )

    assert ctx["query_type"] == "api"
    assert ctx["help_topics"][0]["path"] == "Get.html"
    mock_kw.assert_called_once()
    mock_help.assert_not_called()
