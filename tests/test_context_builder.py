from unittest.mock import patch

from onec_help.context_builder import ContextRequest, build_context


def test_build_context_includes_help_and_memory_and_metadata() -> None:
    """build_context aggregates help_topics, memory and metadata_objects."""

    with (
        patch("onec_help.indexer.search_hybrid") as mock_help,
        patch("onec_help.memory.get_memory_store") as mock_mem_store,
        patch("onec_help.metadata_graph.search_metadata_by_name") as mock_meta_search,
    ):
        mock_help.return_value = [
            {"path": "a.html", "title": "A", "text": "help snippet"},
        ]
        mock_mem_store.return_value.search_long.return_value = [
            {"payload": {"title": "Snippet", "code_snippet": "Сообщить(1);"}},
        ]
        mock_meta_search.return_value = [
            {"id": "Document/Sales", "object_type": "Document", "name": "Sales"},
        ]

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
        patch("onec_help.indexer.search_hybrid") as mock_help,
        patch("onec_help.memory.get_memory_store") as mock_mem_store,
        patch("onec_help.metadata_graph.search_metadata_by_name") as mock_meta_search,
    ):
        mock_help.return_value = []
        mock_mem_store.return_value.search_long.return_value = []
        mock_meta_search.return_value = [{"id": "Document/Sales", "name": "Sales"}]

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
    mock_meta_search.assert_called_once_with("Sales", type_filter="Document", config_version="CfgVer")
