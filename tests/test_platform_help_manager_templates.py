"""platform_help_manager_templates mirrors api_objects.jsonl manager object_name values."""

from onec_help.knowledge import platform_help_manager_templates as ph


def test_manager_template_document_matches_help_export() -> None:
    assert ph.TEMPLATE_BY_METADATA_OBJECT_TYPE["Document"] == "ДокументМенеджер.<Имя документа>"
    assert ph.TEMPLATE_BY_METADATA_OBJECT_TYPE["Catalog"] == "СправочникМенеджер.<Имя справочника>"
    assert (
        ph.manager_template_for_metadata_object_type("Document")
        == "ДокументМенеджер.<Имя документа>"
    )
    assert ph.manager_template_for_metadata_object_type(None) is None


def test_manager_help_hint_line_includes_examples() -> None:
    line = ph.manager_help_hint_line()
    assert "ДокументМенеджер" in line
    assert "СправочникМенеджер" in line
    assert "get_1c_api_object" in line
