"""Tests for structured API snapshot built from help topics."""

from pathlib import Path

from onec_help.knowledge.help_structured import (
    build_structured_api_snapshot,
    extract_api_records_from_topic,
    index_structured_api_objects,
    load_api_examples,
    load_api_objects,
    search_official_examples,
)


def test_extract_api_records_from_topic_with_sections() -> None:
    topic = {
        "path": "8.3.27/shcntx_ru/Get.md",
        "title": "HTTPСоединение.Получить",
        "text": (
            "# HTTPСоединение.Получить\n\n"
            "Краткое описание.\n\n"
            "## Синтаксис\n\nHTTPСоединение.Получить(<Адрес>)\n\n"
            "## Параметры\n\n- **Адрес** (Строка)\n\n"
            "## Возвращаемое значение\n\nHTTPОтвет\n\n"
            "## Пример\n\n```bsl\nОтвет = Соединение.Получить(\"/\");\n```\n"
        ),
        "version": "8.3.27.1859",
        "language": "ru",
        "entity_type": "method",
        "breadcrumb": ["Объекты", "HTTPСоединение"],
    }
    api_object, examples = extract_api_records_from_topic(topic)
    assert api_object["name"] == "HTTPСоединение.Получить"
    assert api_object["kind"] == "method"
    assert api_object["syntax"] == "HTTPСоединение.Получить(<Адрес>)"
    assert api_object["params"][0]["name"] == "Адрес"
    assert api_object["returns"] == "HTTPОтвет"
    assert len(examples) == 1
    assert "Соединение.Получить" in examples[0]["code"]


def test_extract_api_records_from_topic_without_sections() -> None:
    topic = {
        "path": "8.3.27/shcntx_ru/Format.md",
        "title": "Формат",
        "text": "# Формат\n\nФункция форматирует значение по строке формата.",
        "version": "8.3.27.1859",
        "language": "ru",
        "entity_type": "function",
        "breadcrumb": ["Глобальный контекст"],
    }
    api_object, examples = extract_api_records_from_topic(topic)
    assert api_object["name"] == "Формат"
    assert "форматирует значение" in api_object["summary"]
    assert examples == []


def test_build_structured_api_snapshot_from_mocked_index(tmp_path: Path) -> None:
    from unittest.mock import patch

    topics = [
        {
            "path": "8.3.27/shcntx_ru/Get.md",
            "title": "HTTPСоединение.Получить",
            "text": "# HTTPСоединение.Получить\n\nОписание.\n\n## Пример\n\n```bsl\nОтвет = 1;\n```",
            "version": "8.3.27.1859",
            "language": "ru",
            "entity_type": "method",
            "breadcrumb": ["Объекты", "HTTPСоединение"],
        }
    ]
    with patch("onec_help.knowledge.help_structured.iter_help_topics_from_index", return_value=topics):
        manifest = build_structured_api_snapshot(tmp_path)
    assert manifest["objects"] == 1
    assert manifest["examples"] == 1
    assert len(load_api_objects(tmp_path)) == 1
    assert len(load_api_examples(tmp_path)) == 1


def test_build_structured_api_snapshot_skips_generic_topic(tmp_path: Path) -> None:
    from unittest.mock import patch

    topics = [
        {
            "path": "8.3.27/shcntx_ru/Index.md",
            "title": "Обзор раздела",
            "text": "# Обзор раздела\n\nПросто вводный текст без API-структуры.",
            "version": "8.3.27.1859",
            "language": "ru",
            "entity_type": "topic",
            "breadcrumb": ["Объекты"],
        },
        {
            "path": "8.3.27/shcntx_ru/Get.md",
            "title": "HTTPСоединение.Получить",
            "text": "# HTTPСоединение.Получить\n\nОписание.\n\n## Синтаксис\n\nHTTPСоединение.Получить(<Адрес>)",
            "version": "8.3.27.1859",
            "language": "ru",
            "entity_type": "topic",
            "breadcrumb": ["Объекты", "HTTPСоединение"],
        },
    ]
    with patch("onec_help.knowledge.help_structured.iter_help_topics_from_index", return_value=topics):
        manifest = build_structured_api_snapshot(tmp_path)
    assert manifest["objects"] == 1
    objects = load_api_objects(tmp_path)
    assert len(objects) == 1
    assert objects[0]["name"] == "HTTPСоединение.Получить"


def test_index_structured_api_objects_uses_dummy_vector(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    (tmp_path / "api_objects.jsonl").write_text(
        '{"id":1,"name":"HTTPСоединение.Получить","kind":"method","title":"HTTPСоединение.Получить","summary":"Описание","syntax":"HTTPСоединение.Получить(<Адрес>)","params":[],"returns":"HTTPОтвет","availability":"","version":"8.3.27.1859","language":"ru","topic_path":"Get.md","breadcrumb":["Объекты","HTTPСоединение"],"entity_type":"method"}\n',
        encoding="utf-8",
    )
    client = MagicMock()
    client.collection_exists.return_value = False
    with patch("qdrant_client.QdrantClient", return_value=client):
        inserted = index_structured_api_objects(tmp_path, recreate=True)
    assert inserted == 1
    client.recreate_collection.assert_called_once()
    points = client.upsert.call_args.kwargs["points"]
    assert points[0].vector == [0.0]


def test_search_official_examples_prefers_api_name_match(tmp_path: Path) -> None:
    (tmp_path / "api_examples.jsonl").write_text(
        "\n".join(
            [
                '{"api_name":"HTTPСоединение.Получить","title":"HTTPСоединение.Получить — пример 1","code":"Ответ = Соединение.Получить(\\"/\\");","description":"GET","topic_path":"Get.md","version":"8.3.27.1859","language":"ru","entity_type":"method"}',
                '{"api_name":"HTTPСоединение.ПолучитьЗаголовки","title":"HTTPСоединение.ПолучитьЗаголовки — пример 1","code":"Заголовки = Соединение.ПолучитьЗаголовки(\\"/\\");","description":"HEAD","topic_path":"Head.md","version":"8.3.27.1859","language":"ru","entity_type":"method"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    results = search_official_examples(
        "HTTPСоединение.Получить",
        snapshot_dir=tmp_path,
        limit=2,
        version="8.3.27.1859",
        language="ru",
    )
    assert results[0]["api_name"] == "HTTPСоединение.Получить"
