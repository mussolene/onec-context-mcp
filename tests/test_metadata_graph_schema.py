from pathlib import Path

from onec_help.config_crawler import ConfigObject, ConfigRelation, CrawlResult
from onec_help.metadata_graph import (
    _edge_payload_from_relation,
    _node_payload_from_object,
    _object_to_markdown,
    format_requisite_type_display,
    format_type_readable,
)


def _dummy_crawl() -> CrawlResult:
    return CrawlResult(
        root_dir=Path("/cfg"),
        config_name="CfgName",
        config_version="2.0.1.0",
        platform_version="8.5.1.1150",
        objects=[],
        relations=[],
    )


def test_node_payload_includes_config_and_object_fields() -> None:
    crawl = _dummy_crawl()
    obj = ConfigObject(
        id="doc/Sales",
        object_type="Document",
        name="Sales",
        full_name="Реализация товаров и услуг",
        path="Documents/Sales",
        attributes={"Subtype": "Sales"},
    )

    payload = _node_payload_from_object(obj, crawl)

    assert payload["config_name"] == "CfgName"
    assert payload["config_version"] == "2.0.1.0"
    assert payload["platform_version"] == "8.5.1.1150"
    assert payload["object_type"] == "Document"
    assert payload["name"] == "Sales"
    assert payload["full_name"] == "Реализация товаров и услуг"
    assert payload["path"] == "Documents/Sales"
    assert payload["attributes"]["Subtype"] == "Sales"
    # Text is markdown in Russian (same style as help) for uniform semantic search.
    assert "CfgName" in payload["text"]
    assert "Sales" in payload["text"]
    assert "Документ" in payload["text"] or "Document" in payload["text"]
    assert "Конфигурация" in payload["text"]
    assert "Представление" in payload["text"]


def test_object_to_markdown_includes_requisites_and_tabular_sections() -> None:
    """_object_to_markdown produces structured md for embedding (like help topics)."""
    crawl = _dummy_crawl()
    obj = ConfigObject(
        id="doc/Sales",
        object_type="Document",
        name="Sales",
        full_name="Реализация товаров и услуг",
        path="Documents/Sales",
        attributes={
            "requisites": [
                {"name": "Организация", "type": "CatalogRef.Организации"},
                {"name": "Склад", "type": "CatalogRef.Склады"},
            ],
            "tabular_sections": ["Товары", "Услуги"],
        },
    )
    md = _object_to_markdown(obj, crawl)
    assert "Документ" in md and "Sales" in md
    assert "Представление" in md and "Реализация товаров и услуг" in md
    assert "## Реквизиты" in md
    assert "Организация:" in md and "СправочникСсылка.Организации" in md
    assert "Склад:" in md and "СправочникСсылка.Склады" in md
    assert "## Табличные части" in md
    assert "Товары" in md
    assert "Услуги" in md


def test_node_payload_form_has_parent_id_document_has_form_ids() -> None:
    """Payload has parent_id for forms and form_ids for objects that have forms (graph links)."""
    from pathlib import Path

    doc = ConfigObject(
        id="Document/Sales",
        object_type="Document",
        name="Sales",
        full_name="Реализация",
        path="Documents/Sales",
        attributes={},
    )
    form = ConfigObject(
        id="Form/Document.Sales.ФормаДокумента",
        object_type="Form",
        name="ФормаДокумента",
        full_name="Форма документа",
        path="Documents/Sales/Forms/ФормаДокумента",
        attributes={"parent_id": "Document/Sales", "form_requisites": []},
    )
    crawl = CrawlResult(
        root_dir=Path("/cfg"),
        config_name="Cfg",
        config_version="2.0.1.0",
        platform_version=None,
        objects=[doc, form],
        relations=[],
    )
    doc_payload = _node_payload_from_object(doc, crawl)
    form_payload = _node_payload_from_object(form, crawl)
    assert form_payload.get("parent_id") == "Document/Sales"
    assert doc_payload.get("form_ids") == ["Form/Document.Sales.ФормаДокумента"]


def test_format_type_readable_russian_and_ref_types() -> None:
    """format_type_readable converts cfg:/xs: types to readable Russian (СправочникСсылка, Строка, etc.)."""
    assert format_type_readable("cfg:CatalogRef.Организации") == "СправочникСсылка.Организации"
    assert format_type_readable("cfg:DocumentRef.СчетНаОплатуПокупателю") == "ДокументСсылка.СчетНаОплатуПокупателю"
    assert format_type_readable("cfg:EnumRef.ВидыОперацийРеализацияТоваров") == "ПеречислениеСсылка.ВидыОперацийРеализацияТоваров"
    assert format_type_readable("xs:string") == "Строка"
    assert format_type_readable("xs:string", length=150) == "Строка(150)"
    assert format_type_readable("xs:decimal") == "Число"
    assert format_type_readable("xs:boolean") == "Булево"
    assert format_type_readable("xs:dateTime") == "Дата и время"
    assert format_type_readable("cfg:CatalogRef.Организации", append_raw_in_brackets=True) == "СправочникСсылка.Организации (cfg:CatalogRef.Организации)"


def test_format_requisite_type_display_multiple_and_defined_type() -> None:
    """format_requisite_type_display handles union types and ОпределяемыйТип."""
    # Single type
    assert "Строка(100)" in format_requisite_type_display({"name": "X", "type": "xs:string", "length": 100})
    # Multiple types (union)
    out = format_requisite_type_display(
        {"type": "xs:string", "types": ["xs:string", "xs:integer"]},
        append_raw_in_brackets=False,
    )
    assert "Строка" in out and "Целое число" in out and " или " in out
    # Defined type with contained types
    out2 = format_requisite_type_display(
        {"type": "cfg:CatalogRef.Орг", "types": ["cfg:CatalogRef.Орг"], "defined_type": "СсылкаНаОрганизацию"},
        append_raw_in_brackets=False,
    )
    assert "Определяемый тип" in out2 and "СсылкаНаОрганизацию" in out2 and "СправочникСсылка" in out2


def test_edge_payload_includes_versions_and_endpoints() -> None:
    crawl = _dummy_crawl()
    rel = ConfigRelation(from_id="doc/Sales", to_id="reg/Sales", relation_type="writes_to")

    payload = _edge_payload_from_relation(rel, crawl)

    assert payload["config_version"] == "2.0.1.0"
    assert payload["from_id"] == "doc/Sales"
    assert payload["to_id"] == "reg/Sales"
    assert payload["relation_type"] == "writes_to"
