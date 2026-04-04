from onec_help.knowledge.metadata_ids import (
    legacy_slash_metadata_id_to_dot,
    make_metadata_object_id,
)


def test_make_metadata_object_id() -> None:
    assert make_metadata_object_id("Document", "Sales") == "Document.Sales"
    assert make_metadata_object_id("  Document ", " Реализация ") == "Document.Реализация"


def test_legacy_slash_metadata_id_to_dot() -> None:
    assert legacy_slash_metadata_id_to_dot("Document/Sales") == "Document.Sales"
    assert legacy_slash_metadata_id_to_dot("Document.Sales") is None
    assert (
        legacy_slash_metadata_id_to_dot("Form/Document.Sales.Форма") == "Form.Document.Sales.Форма"
    )
    assert legacy_slash_metadata_id_to_dot("A/B/C") is None
    assert legacy_slash_metadata_id_to_dot("Document/") is None
    assert legacy_slash_metadata_id_to_dot("/Sales") is None
