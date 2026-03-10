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
    assert len(ctx["help_topics"]) == 1
    assert len(ctx["memory"]) == 1
    assert len(ctx["metadata_objects"]) == 1
