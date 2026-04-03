import json
from pathlib import Path

from onec_help.knowledge.config_crawler import (
    ConfigObject,
    CrawlResult,
    crawl_config,
    find_config_root,
    find_config_roots,
)


def test_crawl_config_reads_basic_metadata(tmp_path: Path) -> None:
    meta = {
        "config_name": "Test Config",
        "config_version": "1.2.3.4",
        "platform_version": "8.5.1.1150",
    }
    (tmp_path / "config.json").write_text(json.dumps(meta), encoding="utf-8")

    result = crawl_config(tmp_path)

    assert isinstance(result, CrawlResult)
    assert result.config_name == "Test Config"
    assert result.config_version == "1.2.3.4"
    assert result.platform_version == "8.5.1.1150"
    # Пустая конфигурация (нет папок объектов) → одна синтетическая точка "Configuration".
    assert len(result.objects) == 1
    assert result.objects[0].id == "Configuration"
    assert result.objects[0].object_type == "Configuration"
    assert result.relations == []


def test_crawl_config_defaults_when_no_meta(tmp_path: Path) -> None:
    # No config.json: crawler should still return a minimal result with defaults.
    result = crawl_config(tmp_path)

    assert result.config_name == tmp_path.name
    assert result.config_version == "0.0.0.0"
    assert result.platform_version is None
    # Пустая конфигурация: одна синтетическая точка, чтобы версия отображалась в индексе.
    assert len(result.objects) == 1 and result.objects[0].id == "Configuration"


def test_crawl_config_empty_config_yields_synthetic_configuration_node(tmp_path: Path) -> None:
    """When only Configuration.xml exists (no Documents/Catalogs etc.), one synthetic 'Configuration' object is returned."""
    cfg_xml = """<?xml version="1.0"?>
<Configuration xmlns="http://v8.1c.ru/8.3/MDClasses">
  <Properties>
    <Name>EmptyCfg</Name>
    <Version>1.0.0.1</Version>
    <Synonym><item><lang>ru</lang><content>Пустая конфигурация</content></item></Synonym>
  </Properties>
</Configuration>"""
    (tmp_path / "Configuration.xml").write_text(cfg_xml, encoding="utf-8")

    result = crawl_config(tmp_path)

    # config_name берётся из Synonym (представление), когда есть в Configuration.xml
    assert result.config_name == "Пустая конфигурация"
    assert result.config_version == "1.0.0.1"
    assert len(result.objects) == 1
    assert result.objects[0].id == "Configuration"
    assert result.objects[0].object_type == "Configuration"
    assert result.objects[0].full_name == "Пустая конфигурация"


def test_crawl_result_iter_helpers() -> None:
    obj1 = ConfigObject(id="doc/Sales", object_type="Document", name="Sales")
    obj2 = ConfigObject(id="cat/Items", object_type="Catalog", name="Items")
    result = CrawlResult(
        root_dir=Path("/fake"),
        config_name="Cfg",
        config_version="1.0.0.0",
        platform_version=None,
        objects=[obj1, obj2],
        relations=[],
    )

    docs = list(result.iter_objects("Document"))
    assert docs == [obj1]


def test_crawl_config_discovers_basic_objects_from_folders(tmp_path: Path) -> None:
    # Simulate a minimal configuration layout:
    # <root>/Documents/Sales/
    docs_dir = tmp_path / "Documents" / "Sales"
    docs_dir.mkdir(parents=True)
    meta = {"config_name": "Cfg", "config_version": "1.0.0.0"}
    (tmp_path / "config.json").write_text(json.dumps(meta), encoding="utf-8")

    result = crawl_config(tmp_path)

    assert len(result.objects) == 1
    obj = result.objects[0]
    assert obj.object_type == "Document"
    assert obj.name == "Sales"
    # Path should be relative to root
    assert obj.path.replace("\\", "/") in ("Documents/Sales", "Documents/Sales/")


def test_find_config_root_returns_base_when_already_root(tmp_path: Path) -> None:
    """find_config_root returns base_dir when it already looks like a config root."""
    (tmp_path / "Documents").mkdir()
    assert find_config_root(tmp_path) == tmp_path.resolve()


def test_find_config_root_returns_first_subdir_when_base_is_container(tmp_path: Path) -> None:
    """find_config_root returns first subdir that looks like export when base is a container."""
    (tmp_path / "AccountingCorp30_latest" / "Documents").mkdir(parents=True)
    (tmp_path / "EmptyConfig").mkdir()
    found = find_config_root(tmp_path)
    assert found is not None
    assert found.name == "AccountingCorp30_latest"


def test_find_config_root_returns_none_when_empty(tmp_path: Path) -> None:
    """find_config_root returns None when no config root found."""
    (tmp_path / "some_file.txt").write_text("x")
    assert find_config_root(tmp_path) is None


def test_find_config_roots_returns_all_export_subdirs(tmp_path: Path) -> None:
    """find_config_roots returns all subdirs that look like config exports, not only the first."""
    (tmp_path / "AccountingCorp30_latest" / "Documents").mkdir(parents=True)
    (tmp_path / "Enterprise20_latest").mkdir(parents=True)
    (tmp_path / "Enterprise20_latest" / "Configuration.xml").write_text(
        "<Configuration/>", encoding="utf-8"
    )
    (tmp_path / "EmptyConfig").mkdir()
    roots = find_config_roots(tmp_path)
    assert len(roots) == 2
    names = {p.name for p in roots}
    assert names == {"AccountingCorp30_latest", "Enterprise20_latest"}
    # EmptyConfig has no Documents/Catalogs/Configuration.xml — not a config root
    assert not any(p.name == "EmptyConfig" for p in roots)


def test_read_config_dump_info_extracts_requisites_and_tabular_sections(tmp_path: Path) -> None:
    """ConfigDumpInfo.xml (hierarchical export) provides requisites and tabular sections by object."""
    from onec_help.knowledge.config_crawler import _read_config_dump_info

    dump_xml = """<?xml version="1.0" encoding="UTF-8"?>
<ConfigDumpInfo xmlns="http://v8.1c.ru/8.3/xcf/dumpinfo">
    <Metadata name="Document.Sales" id="abc" configVersion="1"/>
    <Metadata name="Document.Sales.Attribute.Date" id="d1"/>
    <Metadata name="Document.Sales.Attribute.Partner" id="d2"/>
    <Metadata name="Document.Sales.TabularSection.Goods" id="ts1"/>
    <Metadata name="Document.Sales.TabularSection.Goods.Attribute.Nomenclature" id="tsa1"/>
</ConfigDumpInfo>"""
    (tmp_path / "ConfigDumpInfo.xml").write_text(dump_xml, encoding="utf-8")

    result = _read_config_dump_info(tmp_path)

    assert "Document/Sales" in result
    data = result["Document/Sales"]
    assert len(data["requisites"]) == 2
    names = {r["name"] for r in data["requisites"]}
    assert names == {"Date", "Partner"}
    tabs = data["tabular_sections"]
    assert any(isinstance(t, dict) and t.get("name") == "Goods" for t in tabs)
    goods_ts = next(t for t in tabs if isinstance(t, dict) and t.get("name") == "Goods")
    assert [r.get("name") for r in goods_ts.get("requisites", [])] == ["Nomenclature"]


def test_crawl_config_reads_object_xml_synonym_and_requisites(tmp_path: Path) -> None:
    """When object dir contains Object.xml with Synonym and Attributes, crawler fills full_name and attributes."""
    (tmp_path / "config.json").write_text(
        '{"config_name": "Cfg", "config_version": "1.0.0.0"}',
        encoding="utf-8",
    )
    docs_dir = tmp_path / "Documents" / "Sales"
    docs_dir.mkdir(parents=True)
    # Minimal 1C-style object XML: Synonym and Attributes/Attribute (no namespace for predictable parsing)
    object_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document>
    <Synonym>Реализация товаров и услуг</Synonym>
    <Attributes>
        <Attribute><Name>Date</Name><Type>DocumentRef.Sales</Type></Attribute>
        <Attribute><Name>Partner</Name><Type>Catalog.Counterparties</Type></Attribute>
    </Attributes>
    <TabularSections>
        <TabularSection><Name>Goods</Name></TabularSection>
    </TabularSections>
</Document>"""
    (docs_dir / "Object.xml").write_text(object_xml, encoding="utf-8")

    result = crawl_config(tmp_path)

    assert len(result.objects) == 1
    obj = result.objects[0]
    assert obj.name == "Sales"
    assert obj.full_name == "Реализация товаров и услуг"
    assert obj.attributes.get("requisites")
    req = obj.attributes["requisites"]
    assert len(req) == 2
    assert req[0]["name"] == "Date"
    assert req[1]["name"] == "Partner"
    assert obj.attributes.get("tabular_sections") == [{"name": "Goods", "requisites": []}]


def test_crawl_config_forms_have_parent_id_and_relations(tmp_path: Path) -> None:
    """Forms are separate objects with parent_id; relations link object → form (has_form)."""
    (tmp_path / "config.json").write_text(
        '{"config_name": "Cfg", "config_version": "1.0.0.0"}',
        encoding="utf-8",
    )
    docs_dir = tmp_path / "Documents" / "Sales"
    docs_dir.mkdir(parents=True)
    form_dir = docs_dir / "Forms" / "ФормаДокумента" / "Ext"
    form_dir.mkdir(parents=True)
    (form_dir / "Form.xml").write_text(
        '<?xml version="1.0"?><Form><Attributes/><Commands/></Form>',
        encoding="utf-8",
    )

    result = crawl_config(tmp_path)

    doc_obj = next((o for o in result.objects if o.object_type == "Document"), None)
    form_obj = next((o for o in result.objects if o.object_type == "Form"), None)
    assert doc_obj is not None and doc_obj.name == "Sales"
    assert form_obj is not None and form_obj.name == "ФормаДокумента"
    assert form_obj.attributes.get("parent_id") == doc_obj.id
    has_form = [r for r in result.relations if r.relation_type == "has_form"]
    assert len(has_form) == 1
    assert has_form[0].from_id == doc_obj.id
    assert has_form[0].to_id == form_obj.id
