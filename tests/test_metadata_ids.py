from onec_help.knowledge.metadata_ids import make_metadata_object_id


def test_make_metadata_object_id() -> None:
    assert make_metadata_object_id("Document", "Sales") == "Document.Sales"
    assert make_metadata_object_id("  Document ", " Реализация ") == "Document.Реализация"
