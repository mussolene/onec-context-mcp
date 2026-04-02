from pathlib import Path

from onec_help.knowledge.kd2_metadata import (
    crawl_kd2_xml,
    load_kd2_snapshot,
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


def test_crawl_kd2_xml_extracts_objects_and_fields(tmp_path: Path) -> None:
    xml_path = tmp_path / "kd2.xml"
    xml_path.write_text(KD2_XML, encoding="utf-8")

    crawl = crawl_kd2_xml(xml_path)

    assert crawl.config_name == "ТестоваяКонфигурация"
    assert crawl.config_version == "3.0.1.1"
    assert len(crawl.objects) == 2

    doc = next(obj for obj in crawl.objects if obj.object_type == "Document")
    assert doc.name == "РеализацияТоваровУслуг"
    assert doc.full_name == "Реализация товаров и услуг"
    assert doc.attributes["requisites"][0]["name"] == "Организация"
    assert doc.attributes["requisites"][0]["type"] == "СправочникСсылка.Организации"
    assert doc.attributes["tabular_sections"][0]["name"] == "Товары"
    assert doc.attributes["tabular_sections"][0]["requisites"][0]["name"] == "Номенклатура"


def test_kd2_snapshot_roundtrip(tmp_path: Path) -> None:
    xml_path = tmp_path / "kd2.xml"
    xml_path.write_text(KD2_XML, encoding="utf-8")
    snapshot_dir = tmp_path / "snapshot"

    crawl = crawl_kd2_xml(xml_path)
    manifest = write_kd2_snapshot(crawl, snapshot_dir)
    loaded = load_kd2_snapshot(snapshot_dir)

    assert manifest["format"] == "onec_kd2_snapshot_v1"
    assert manifest["objects"] == len(crawl.objects)
    assert loaded.config_version == "3.0.1.1"
    assert len(loaded.objects) == len(crawl.objects)
    assert (snapshot_dir / "objects.jsonl").is_file()
    assert (snapshot_dir / "fields.jsonl").is_file()
    assert (snapshot_dir / "manifest.json").is_file()
