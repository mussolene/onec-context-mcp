from pathlib import Path

import pytest

from onec_help.knowledge.kd2_metadata import (
    crawl_kd2_xml,
    is_kd2_snapshot_root,
    load_kd2_snapshot,
    load_kd2_snapshot_set,
    merge_kd2_crawls,
    snapshot_dir_for_xml,
    write_kd2_snapshot,
)

KD2_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Конфигурация Имя="ТестоваяКонфигурация">
  <CatalogObject.Конфигурации>
    <Ref>cfg-1</Ref>
    <Description>ТестоваяКонфигурация</Description>
    <Имя>ТестоваяКонфигурация</Имя>
    <Синоним>Тестовая конфигурация</Синоним>
    <Комментарий></Комментарий>
    <Версия>3.0.1.1</Версия>
  </CatalogObject.Конфигурации>
  <CatalogObject.Объекты>
    <Ref>doc-1</Ref>
    <IsFolder>false</IsFolder>
    <Description>РеализацияТоваровУслуг</Description>
    <Имя>РеализацияТоваровУслуг</Имя>
    <Синоним>Реализация товаров и услуг</Синоним>
    <Комментарий>Документ продажи</Комментарий>
    <Тип>Документ</Тип>
  </CatalogObject.Объекты>
  <CatalogObject.Объекты>
    <Ref>type-1</Ref>
    <IsFolder>false</IsFolder>
    <Description>СправочникСсылка.Организации</Description>
    <Имя>СправочникСсылка.Организации</Имя>
    <Синоним>Организации</Синоним>
    <Комментарий></Комментарий>
    <Тип>Справочник</Тип>
  </CatalogObject.Объекты>
  <CatalogObject.Свойства>
    <Ref>field-1</Ref>
    <Owner>doc-1</Owner>
    <Parent>00000000-0000-0000-0000-000000000000</Parent>
    <Description>Организация</Description>
    <Имя>Организация</Имя>
    <Синоним>Организация</Синоним>
    <Комментарий>Основная организация</Комментарий>
    <Использование></Использование>
    <Индексирование>true</Индексирование>
    <КвалификаторыЧисла_Длина>0</КвалификаторыЧисла_Длина>
    <КвалификаторыЧисла_Точность>0</КвалификаторыЧисла_Точность>
    <КвалификаторыСтроки_Длина>0</КвалификаторыСтроки_Длина>
    <Вид>Реквизит</Вид>
    <ТипыСтрокой></ТипыСтрокой>
    <Типы><Row><Тип>type-1</Тип></Row></Типы>
  </CatalogObject.Свойства>
  <CatalogObject.Свойства>
    <Ref>ts-1</Ref>
    <Owner>doc-1</Owner>
    <Parent>00000000-0000-0000-0000-000000000000</Parent>
    <Description>Товары</Description>
    <Имя>Товары</Имя>
    <Синоним>Товары</Синоним>
    <Комментарий></Комментарий>
    <Вид>ТабличнаяЧасть</Вид>
    <Типы></Типы>
  </CatalogObject.Свойства>
  <CatalogObject.Свойства>
    <Ref>ts-field-1</Ref>
    <Owner>doc-1</Owner>
    <Parent>ts-1</Parent>
    <Description>Номенклатура</Description>
    <Имя>Номенклатура</Имя>
    <Синоним>Номенклатура</Синоним>
    <Комментарий></Комментарий>
    <Использование></Использование>
    <Индексирование>false</Индексирование>
    <КвалификаторыЧисла_Длина>0</КвалификаторыЧисла_Длина>
    <КвалификаторыЧисла_Точность>0</КвалификаторыЧисла_Точность>
    <КвалификаторыСтроки_Длина>0</КвалификаторыСтроки_Длина>
    <Вид>Реквизит</Вид>
    <ТипыСтрокой></ТипыСтрокой>
    <Типы><Row><Тип>type-1</Тип></Row></Типы>
  </CatalogObject.Свойства>
</Конфигурация>
"""

# Формат как после MetadataExport 2.1.9+: примитив «НаборКонстант» + отдельные Объекты с Тип=Константа.
KD2_CONSTANTS_SET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Конфигурация Имя="CfgConst" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <CatalogObject.Конфигурации>
    <Ref>cfg-c</Ref>
    <Description>CfgConst</Description>
    <Имя>CfgConst</Имя>
    <Версия>1.0.0.1</Версия>
  </CatalogObject.Конфигурации>
  <CatalogObject.Объекты>
    <Ref>cs-1</Ref>
    <IsFolder>false</IsFolder>
    <Owner xsi:type="CatalogRef.Конфигурации">cfg-c</Owner>
    <Parent>00000000-0000-0000-0000-000000000000</Parent>
    <Description>КонстантыНабор</Description>
    <Имя>КонстантыНабор</Имя>
    <Тип>НаборКонстант</Тип>
  </CatalogObject.Объекты>
  <CatalogObject.Объекты>
    <Ref>c-disc</Ref>
    <IsFolder>false</IsFolder>
    <Owner xsi:type="CatalogRef.Конфигурации">cfg-c</Owner>
    <Parent>00000000-0000-0000-0000-000000000000</Parent>
    <Description>Константа.ИспользоватьСкидки</Description>
    <Имя>ИспользоватьСкидки</Имя>
    <Синоним>Использовать скидки</Синоним>
    <Комментарий></Комментарий>
    <Тип>Константа</Тип>
  </CatalogObject.Объекты>
  <CatalogObject.Объекты>
    <Ref>c-ver</Ref>
    <IsFolder>false</IsFolder>
    <Owner xsi:type="CatalogRef.Конфигурации">cfg-c</Owner>
    <Parent>00000000-0000-0000-0000-000000000000</Parent>
    <Description>Константа.НомерВерсии</Description>
    <Имя>НомерВерсии</Имя>
    <Синоним>Номер версии</Синоним>
    <Комментарий></Комментарий>
    <Тип>Константа</Тип>
  </CatalogObject.Объекты>
  <CatalogObject.Свойства>
    <Ref>p-1</Ref>
    <Owner>c-disc</Owner>
    <Parent>00000000-0000-0000-0000-000000000000</Parent>
    <Description>ТипЗначения</Description>
    <Имя>ТипЗначения</Имя>
    <Синоним>Тип значения</Синоним>
    <Вид>Реквизит</Вид>
    <Типы></Типы>
  </CatalogObject.Свойства>
  <CatalogObject.Свойства>
    <Ref>p-2</Ref>
    <Owner>c-ver</Owner>
    <Parent>00000000-0000-0000-0000-000000000000</Parent>
    <Description>ТипЗначения</Description>
    <Имя>ТипЗначения</Имя>
    <Синоним>Тип значения</Синоним>
    <Вид>Реквизит</Вид>
    <Типы></Типы>
  </CatalogObject.Свойства>
</Конфигурация>
"""


def test_crawl_kd2_xml_extracts_objects_and_fields(tmp_path: Path) -> None:
    xml_path = tmp_path / "kd2.xml"
    xml_path.write_text(KD2_XML, encoding="utf-8")

    crawl = crawl_kd2_xml(xml_path)

    assert crawl.config_name == "ТестоваяКонфигурация"
    assert crawl.config_version == "3.0.1.1"
    assert len(crawl.objects) == 2

    doc = next(obj for obj in crawl.objects if obj.object_type == "Document")
    assert doc.id == "Document.РеализацияТоваровУслуг"
    assert doc.name == "РеализацияТоваровУслуг"
    assert doc.full_name == "Реализация товаров и услуг"
    assert doc.attributes["requisites"][0]["name"] == "Организация"
    assert doc.attributes["requisites"][0]["type"] == "СправочникСсылка.Организации"
    assert doc.attributes["tabular_sections"][0]["name"] == "Товары"
    assert doc.attributes["tabular_sections"][0]["requisites"][0]["name"] == "Номенклатура"


def test_crawl_kd2_constants_export_has_set_and_constant_objects(tmp_path: Path) -> None:
    """Выгрузка MetadataExport 2.1.9+: набор-тип + отдельные Constant для индексации."""
    xml_path = tmp_path / "kd2const.xml"
    xml_path.write_text(KD2_CONSTANTS_SET_XML, encoding="utf-8")
    crawl = crawl_kd2_xml(xml_path)
    by_type: dict[str, list] = {}
    for o in crawl.objects:
        by_type.setdefault(o.object_type, []).append(o)
    assert "ConstantsSet" in by_type and len(by_type["ConstantsSet"]) == 1
    assert "Constant" in by_type and len(by_type["Constant"]) == 2
    c0 = next(o for o in crawl.objects if o.name == "ИспользоватьСкидки")
    assert c0.id == "Constant.ИспользоватьСкидки"
    assert c0.object_type == "Constant"
    row = next(r for r in c0.attributes["requisites"] if r["name"] == "ТипЗначения")
    assert "Константы.ИспользоватьСкидки.Получить()" in (row.get("constant_bsl_hint") or "")


def test_load_kd2_snapshot_rejects_unknown_format(tmp_path: Path) -> None:
    snap = tmp_path / "bad"
    snap.mkdir()
    (snap / "manifest.json").write_text(
        '{"format":"onec_kd2_snapshot_v0","config_name":"X","config_version":"1"}',
        encoding="utf-8",
    )
    (snap / "objects.jsonl").write_text("", encoding="utf-8")
    (snap / "fields.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported KD2 snapshot format"):
        load_kd2_snapshot(snap)


def test_kd2_snapshot_roundtrip(tmp_path: Path) -> None:
    xml_path = tmp_path / "kd2.xml"
    xml_path.write_text(KD2_XML, encoding="utf-8")
    snapshot_dir = tmp_path / "snapshot"

    crawl = crawl_kd2_xml(xml_path)
    manifest = write_kd2_snapshot(crawl, snapshot_dir)
    loaded = load_kd2_snapshot(snapshot_dir)

    assert manifest["format"] == "onec_kd2_snapshot_v2"
    assert manifest["objects"] == len(crawl.objects)
    assert loaded.config_version == "3.0.1.1"
    assert len(loaded.objects) == len(crawl.objects)
    assert (snapshot_dir / "objects.jsonl").is_file()
    assert (snapshot_dir / "fields.jsonl").is_file()
    assert (snapshot_dir / "manifest.json").is_file()


def test_merge_kd2_crawls_merges_multiple_files(tmp_path: Path) -> None:
    xml_one = tmp_path / "one.xml"
    xml_two = tmp_path / "two.xml"
    xml_one.write_text(KD2_XML.replace("3.0.1.1", "3.0.1.1"), encoding="utf-8")
    xml_two.write_text(
        KD2_XML.replace("ТестоваяКонфигурация", "ВтораяКонфигурация")
        .replace("3.0.1.1", "5.0.0.2")
        .replace("РеализацияТоваровУслуг", "ЗаказПокупателя"),
        encoding="utf-8",
    )

    crawl = merge_kd2_crawls([crawl_kd2_xml(xml_one), crawl_kd2_xml(xml_two)])

    assert crawl.config_version == "multiple"
    assert len(crawl.objects) == 4
    names = {obj.name for obj in crawl.objects}
    assert "РеализацияТоваровУслуг" in names
    assert "ЗаказПокупателя" in names


def test_snapshot_set_roundtrip_per_config_dirs(tmp_path: Path) -> None:
    base = tmp_path / "kd2"
    base.mkdir()
    xml_one = base / "one.xml"
    xml_two = base / "two.xml"
    xml_one.write_text(KD2_XML, encoding="utf-8")
    xml_two.write_text(
        KD2_XML.replace("ТестоваяКонфигурация", "ВтораяКонфигурация").replace("3.0.1.1", "5.0.0.2"),
        encoding="utf-8",
    )
    crawl_one = crawl_kd2_xml(xml_one)
    crawl_two = crawl_kd2_xml(xml_two)
    write_kd2_snapshot(crawl_one, snapshot_dir_for_xml(base, xml_one))
    write_kd2_snapshot(crawl_two, snapshot_dir_for_xml(base, xml_two))

    assert is_kd2_snapshot_root(base)
    merged = load_kd2_snapshot_set(base)
    assert merged.config_version == "multiple"
    assert len(merged.objects) == len(crawl_one.objects) + len(crawl_two.objects)
