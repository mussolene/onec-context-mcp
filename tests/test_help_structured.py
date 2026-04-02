"""Tests for structured API snapshot built from help topics."""

from pathlib import Path

from onec_help.knowledge.help_structured import (
    build_structured_api_snapshot,
    extract_api_records_from_topic,
    extract_structured_records_from_html_topic,
    extract_structured_records_from_topic,
    get_api_member,
    index_structured_api_members,
    index_structured_api_objects,
    load_api_examples,
    load_api_members,
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
        manifest = build_structured_api_snapshot(tmp_path, unpacked_dir=tmp_path / "missing-unpacked")
    assert manifest["objects"] == 1
    assert manifest["members"] == 1
    assert manifest["examples"] == 1
    assert manifest["source"] == "indexed_topics"
    assert len(load_api_objects(tmp_path)) == 1
    assert len(load_api_members(tmp_path)) == 1
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
        manifest = build_structured_api_snapshot(tmp_path, unpacked_dir=tmp_path / "missing-unpacked")
    assert manifest["objects"] == 1
    assert manifest["members"] == 1
    members = load_api_members(tmp_path)
    assert len(members) == 1
    assert members[0]["full_name"] == "HTTPСоединение.Получить"
    assert manifest["source"] == "indexed_topics"


def test_index_structured_api_objects_uses_dummy_vector(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    (tmp_path / "api_objects.jsonl").write_text(
        '{"id":1,"object_name":"HTTPСоединение","full_name":"HTTPСоединение","kind":"type","title":"HTTPСоединение","summary":"Описание","availability":"","version":"8.3.27.1859","language":"ru","topic_path":"HTTPConnection.html","breadcrumb":["Объекты"]}\n',
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


def test_index_structured_api_members_uses_dummy_vector(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    (tmp_path / "api_members.jsonl").write_text(
        '{"id":1,"owner_name":"HTTPСоединение","owner_kind":"type","member_name":"Получить","full_name":"HTTPСоединение.Получить","kind":"method","title":"HTTPСоединение.Получить","summary":"Описание","syntax":"HTTPСоединение.Получить(<Адрес>)","params":[],"returns":"HTTPОтвет","availability":"","version":"8.3.27.1859","language":"ru","topic_path":"Get.md","breadcrumb":["Объекты","HTTPСоединение"],"aliases":[],"see_also":[]}\n',
        encoding="utf-8",
    )
    client = MagicMock()
    client.collection_exists.return_value = False
    with patch("qdrant_client.QdrantClient", return_value=client):
        inserted = index_structured_api_members(tmp_path, recreate=True)
    assert inserted == 1
    points = client.upsert.call_args.kwargs["points"]
    assert points[0].vector == [0.0]
    assert points[0].payload["source_sections"] == {}


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


def test_extract_structured_records_from_topic_builds_links() -> None:
    topic = {
        "path": "8.3.27/shcntx_ru/Get.md",
        "title": "HTTPСоединение.Получить",
        "text": (
            "# HTTPСоединение.Получить\n\n"
            "Описание.\n\n"
            "## Синтаксис\n\nHTTPСоединение.Получить(<Адрес>)\n\n"
            "## См. также\n\nHTTPСоединение.ПолучитьЗаголовки\nHTTPЗапрос\n"
        ),
        "version": "8.3.27.1859",
        "language": "ru",
        "entity_type": "method",
        "breadcrumb": ["Объекты", "HTTPСоединение"],
    }
    obj, member, _examples, links = extract_structured_records_from_topic(topic)
    assert obj is not None
    assert member is not None
    assert member["full_name"] == "HTTPСоединение.Получить"
    assert [link["target_name"] for link in links] == [
        "HTTPСоединение.ПолучитьЗаголовки",
        "HTTPЗапрос",
    ]


def test_extract_structured_records_from_topic_parses_inline_sections() -> None:
    topic = {
        "path": "8.3.27/shcntx_ru/Get.md",
        "title": "HTTPСоединение.Получить (HTTPConnection.Get)",
        "text": (
            "# HTTPСоединение.Получить (HTTPConnection.Get)\n\n"
            "HTTPСоединение (HTTPConnection)\n"
            "Получить (Get)\n"
            "Синтаксис: Получить(<HTTPЗапрос>, <ИмяВыходногоФайла>) "
            "Параметры: <HTTPЗапрос> (обязательный) Тип: HTTPЗапрос . HTTP-запрос. "
            "<ИмяВыходногоФайла> (необязательный) Тип: Строка . Имя файла. "
            "Возвращаемое значение: Тип: HTTPОтвет . "
            "Описание: Получает данные с ресурса. "
            "Доступность: Сервер, толстый клиент. "
        ),
        "version": "8.3.27.1859",
        "language": "ru",
        "entity_type": "method",
        "breadcrumb": ["Объекты", "HTTPСоединение"],
    }
    _obj, member, _examples, _links = extract_structured_records_from_topic(topic)
    assert member is not None
    assert member["syntax"] == "Получить(<HTTPЗапрос>, <ИмяВыходногоФайла>)"
    assert member["returns"] == "Тип: HTTPОтвет ."
    assert [param["name"] for param in member["params"]] == ["<HTTPЗапрос>", "<ИмяВыходногоФайла>"]
    assert member["params"][0]["type"] == "HTTPЗапрос"
    assert member["availability"] == "Сервер, толстый клиент."
    assert member["summary"] == "Получает данные с ресурса."


def test_extract_structured_records_from_topic_parses_property_type_from_description() -> None:
    topic = {
        "path": "8.3.27/shcntx_ru/Visible.md",
        "title": "Automation сервер.Visible (Automation server.Visible)",
        "text": (
            "# Automation сервер.Visible (Automation server.Visible)\n\n"
            "Automation сервер (Automation server)\n"
            "Visible (Visible)\n"
            "Использование: Чтение и запись. "
            "Описание: Тип: Булево . Показывает или скрывает UI. "
            "Доступность: Интеграция. "
            "Примечание: Истина - показан, Ложь - скрыт."
        ),
        "version": "8.3.27.1859",
        "language": "ru",
        "entity_type": "property",
        "breadcrumb": ["Объекты", "Automation сервер"],
    }
    _obj, member, _examples, _links = extract_structured_records_from_topic(topic)
    assert member is not None
    assert member["returns"] == "Булево"
    assert member["syntax"] == "Automation сервер.Visible"
    assert member["summary"] == "Тип: Булево . Показывает или скрывает UI."
    assert member["description"] == "Тип: Булево . Показывает или скрывает UI."
    assert member["notes"] == "Истина - показан, Ложь - скрыт."
    assert "Интеграция" in member["restrictions"]
    assert member["availability"] == "Интеграция."
    assert member["source_sections"]["syntax_fallback"] == "Automation сервер.Visible"


def test_extract_structured_records_from_topic_keeps_source_sections() -> None:
    topic = {
        "path": "8.3.27/shcntx_ru/Get.md",
        "title": "HTTPСоединение.Получить",
        "text": (
            "# HTTPСоединение.Получить\n\n"
            "Описание метода.\n\n"
            "## Синтаксис\n\nHTTPСоединение.Получить(<Адрес>)\n\n"
            "## Доступность\n\nСервер.\n\n"
            "## Примечание\n\nТолько на сервере.\n"
        ),
        "version": "8.3.27.1859",
        "language": "ru",
        "entity_type": "method",
        "breadcrumb": ["Объекты", "HTTPСоединение"],
    }
    _obj, member, _examples, _links = extract_structured_records_from_topic(topic)
    assert member is not None
    assert member["source_sections"]["syntax"] == "HTTPСоединение.Получить(<Адрес>)"
    assert member["source_sections"]["availability"] == "Сервер."
    assert member["source_sections"]["note"] == "Только на сервере."
    assert "Только на сервере" in member["restrictions"]


def test_extract_structured_records_from_html_topic_reads_v8_sections(tmp_path: Path) -> None:
    html_path = tmp_path / "Get.html"
    html_path.write_text(
        """<html><body>
<h1 class="V8SH_pagetitle">COMSafeArray.GetDimensions (COMSafeArray.GetDimensions)</h1>
<p class="V8SH_title">COMSafeArray (COMSafeArray)</p>
<p class="V8SH_heading">GetDimensions (GetDimensions)</p>
<p class="V8SH_chapter">Синтаксис:</p>GetDimensions()
<p class="V8SH_chapter">Возвращаемое значение:</p>Тип: Число.
<p class="V8SH_chapter">Описание:</p><p>Получает количество измерений массива.</p>
<p class="V8SH_chapter">Доступность: </p><p>Сервер, толстый клиент.</p>
<p class="V8SH_chapter">Пример:</p><table><tr><td>КоличествоИзмерений = Массив.GetDimensions();</td></tr></table>
</body></html>""",
        encoding="utf-8",
    )
    _obj, member, examples, _links = extract_structured_records_from_html_topic(
        html_path,
        version="8.3.27.1859",
        language="ru",
        topic_path="8.3.27.1859/shcntx_ru/objects/catalog234/COMSafeArray/methods/GetDimensions1600.html",
        title="GetDimensions",
        breadcrumb=["COMSafeArray"],
        entity_type="topic",
    )
    assert member is not None
    assert member["full_name"] == "COMSafeArray.GetDimensions"
    assert member["syntax"] == "GetDimensions()"
    assert member["returns"] == "Тип: Число."
    assert member["availability"] == "Сервер, толстый клиент."
    assert member["description"] == "Получает количество измерений массива."
    assert examples and "GetDimensions" in examples[0]["code"]


def test_extract_structured_records_from_html_topic_uses_shared_legacy_v8sh_parser(
    tmp_path: Path,
) -> None:
    html_path = tmp_path / "Connect.html"
    html_path.write_text(
        """<html><body>
<h1 class="V8SH_pagetitle">Automation сервер.Connect (Automation server.Connect)</h1>
<div class="V8SH_title">Automation сервер (Automation server)</div>
<div class="V8SH_heading">Connect (Connect)</div>
<div class="V8SH_chapter"><p>Синтаксис:</p></div>Connect(&lt;СтрокаСоединения&gt;)
<div class="V8SH_chapter"><p>Параметры:</p></div>
<div class="V8SH_rubric"><p>&lt;СтрокаСоединения&gt; (обязательный)</p></div>
Тип: <a href="v8help://SyntaxHelperLanguage/def_String">Строка</a>. <br>Строка параметров соединения.
<div class="V8SH_chapter"><p>Возвращаемое значение:</p></div>Тип: <a href="v8help://SyntaxHelperLanguage/def_Boolean">Булево</a>. <br>Истина при успехе.
<div class="V8SH_chapter"><p>Описание:</p></div>Выполняет соединение системы 1С:Предприятие с информационной базой.<br>
<div class="V8SH_chapter"><p>Доступность:</p></div>Интеграция.
</body></html>""",
        encoding="utf-8",
    )
    _obj, member, _examples, _links = extract_structured_records_from_html_topic(
        html_path,
        version="8.2.19.130",
        language="ru",
        topic_path="8.2.19.130/shcntx_ru/objects/catalog1369/Automation server/methods/Connect2743.html",
        title="Connect",
        breadcrumb=["Automation сервер"],
        entity_type="topic",
    )
    assert member is not None
    assert member["full_name"] == "Automation сервер.Connect"
    assert member["syntax"] == "Connect(<СтрокаСоединения>)"
    assert member["params"][0]["name"] == "<СтрокаСоединения> (обязательный)"
    assert member["params"][0]["type"] == "Строка"
    assert "Строка параметров соединения." in member["params"][0]["description"]
    assert member["returns"] == "Тип: Булево . Истина при успехе."
    assert "Интеграция" in member["availability"]


def test_build_structured_api_snapshot_prefers_unpacked_html(tmp_path: Path) -> None:
    unpacked_dir = tmp_path / "unpacked"
    stem_dir = unpacked_dir / "8.3.27.1859" / "shcntx_ru"
    html_dir = stem_dir / "objects" / "catalog63" / "catalog578" / "catalog2125" / "HTTPConnection" / "methods"
    html_dir.mkdir(parents=True, exist_ok=True)
    (stem_dir / ".hbk_info.json").write_text(
        '{"version":"8.3.27.1859","language":"ru","label":"Синтаксис"}',
        encoding="utf-8",
    )
    (stem_dir / ".toc.json").write_text(
        '[{"path":"/objects/catalog63/catalog578/catalog2125/HTTPConnection/methods/Get1442.html","title_ru":"Получить","title_en":"Get","breadcrumb":["HTTPСоединение"],"entity_type":"topic"}]',
        encoding="utf-8",
    )
    (html_dir / "Get1442.html").write_text(
        """<html><body>
<h1 class="V8SH_pagetitle">HTTPСоединение.Получить (HTTPConnection.Get)</h1>
<p class="V8SH_title">HTTPСоединение (HTTPConnection)</p>
<p class="V8SH_heading">Получить (Get)</p>
<p class="V8SH_chapter">Синтаксис:</p>Получить(&lt;HTTPЗапрос&gt;)
<p class="V8SH_chapter">Параметры:</p><div class="V8SH_rubric"><p>&lt;HTTPЗапрос&gt;</p><a>HTTPЗапрос</a></div>
<p class="V8SH_chapter">Возвращаемое значение:</p>Тип: HTTPОтвет.
<p class="V8SH_chapter">Описание:</p><p>Получает ресурс.</p>
<p class="V8SH_chapter">Доступность: </p><p>Сервер.</p>
</body></html>""",
        encoding="utf-8",
    )
    manifest = build_structured_api_snapshot(tmp_path / "snapshot", unpacked_dir=unpacked_dir)
    members = load_api_members(tmp_path / "snapshot")
    assert manifest["source"] == "unpacked_html"
    assert manifest["members"] == 1
    assert members[0]["full_name"] == "HTTPСоединение.Получить"
    assert members[0]["syntax"] == "Получить(<HTTPЗапрос>)"
    assert members[0]["params"][0]["type"] == "HTTPЗапрос"


def test_get_api_member_prefers_exact_member_name_for_bare_query() -> None:
    from unittest.mock import patch

    class _Client:
        def collection_exists(self, _name):
            return True

        def scroll(self, *, collection_name, scroll_filter, limit, with_payload, with_vectors):
            field = scroll_filter.must[0].key
            value = scroll_filter.must[0].match.value
            rows = []
            if collection_name == "onec_help_api_members" and value == "Формат":
                if field == "name":
                    rows = []
                elif field == "full_name":
                    rows = []
                elif field == "member_name":
                    rows = [
                        type(
                            "P",
                            (),
                            {
                                "payload": {
                                    "full_name": "Глобальный контекст.Формат",
                                    "member_name": "Формат",
                                    "owner_name": "Глобальный контекст",
                                    "version": "8.3.27.1719",
                                    "topic_path": "GlobalContext/Format.html",
                                }
                            },
                        )(),
                        type(
                            "P",
                            (),
                            {
                                "payload": {
                                    "full_name": "Картинка.Формат",
                                    "member_name": "Формат",
                                    "owner_name": "Картинка",
                                    "version": "8.3.27.1719",
                                    "topic_path": "Picture/Format.html",
                                }
                            },
                        )(),
                    ]
            return rows, None

    with patch("qdrant_client.QdrantClient", return_value=_Client()):
        results = get_api_member("Формат")
    assert results[0]["full_name"] == "Глобальный контекст.Формат"
