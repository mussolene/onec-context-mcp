# Справочник MCP-инструментов 1c-help

Единая ссылка на все инструменты MCP-сервера 1c-help: параметры, лимиты, рекомендуемый порядок вызовов.

## Рекомендуемый порядок вызовов

1. **Старт AI-сессии** — `get_1c_quick_guide(task="develop"|"refactor"|"test")`.
2. **Точное API `Тип.Метод`** — `get_1c_api_answer(name)`.
3. **Неточный вопрос по коду** — `get_1c_code_answer(query)`; по умолчанию ответ компактный.
4. **Локальный anti-hallucination context** — `get_1c_task_context(query, file_uri, symbol_name)`.
5. **При нерелевантных результатах** — `search_1c_help_keyword` с точным именем API, затем `get_1c_help_topic(topic_path)` по `path` из результата.
6. **Гарантированно стандарты и сниппеты** — `search_1c_memory(query, domains="standards,snippets")`.
7. **После генерации рабочего кода** — `save_1c_snippet` только для реально переиспользуемого и уже проверенного результата.

---

## Имена параметров (избежание ошибок валидации)

При вызове MCP-инструментов **имена параметров в JSON должны совпадать** с сигнатурой. Частые ошибки:

| Инструмент | Передавать | Не передавать |
|------------|-------------|----------------|
| **search_1c_help_keyword** | `query` | `keyword` |
| **get_1c_help_topic** | `topic_path` **или** `path` (оба допустимы) | — |
| **get_1c_help_related** | `topic_path` **или** `path` (оба допустимы) | — |
| **get_1c_help_index_status** | без параметров (пустой объект `{}`) | — |
| **get_1c_metadata_object** | `object_id`, при нескольких конфигурациях — `config_version` | — |
| **search_1c_metadata** | `query`, при нескольких конфигурациях — `config_version` | — |

Ошибка вида `query: Missing required argument` / `keyword: Unexpected keyword argument` при вызове `search_1c_help_keyword` означает, что был передан параметр **keyword** в среде, которая ожидает только **query**. В текущей версии публичный контракт — только `{"query": "..."}`.

---

## Поиск и чтение

| Инструмент | Параметры | Описание | Лимиты / примечания |
|------------|-----------|----------|---------------------|
| **search_1c_help** | `query`, `limit=8`, `version`, `language`, `include_user_memory=False` | Семантический поиск по справке. Для кода предпочтительнее `get_1c_code_answer`; для точных имён API — `search_1c_help_keyword`. | query до 64 KB (MAX_QUERY_CHARS). При нерелевантности — попробовать `search_1c_help_keyword` с точным именем. |
| **search_1c_help_keyword** | `query`, `limit=10`, `version`, `language` | Поиск по подстроке/BM25 в заголовке и тексте с локальным exact-first rerank. Идеален для точных имён: `РегистрНакопления.ОстаткиИОбороты`, `Тип.Метод`. | Передавать только `query`. До 64 KB. |
| **search_1c_help_with_content** | `query`, `limit=3`, `version`, `language` | Legacy/deprecated: гибридный поиск + полный контент топ-результатов. | Для AI по умолчанию не использовать; предпочитать `get_1c_code_answer`. |
| **get_1c_api_answer** | `name`, `version=None`, `language=None`, `detail="compact"` | Compact exact-first ответ по точному API/функции/методу. | Первый выбор для `Тип.Метод`; `detail="full"` возвращает полный топик. |
| **get_1c_code_answer** | `query`, `limit=1`, `include_memory=True`, `code_only=False`, `version`, `language` | Готовый компактный ответ с кодом: семантика + keyword + контент топиков + память. Основной инструмент для неточных вопросов. | По умолчанию 1 топик и компактный output. Для большего контекста повышать `max_chars_per_topic`. |
| **search_1c_memory** | `query`, `limit=5`, `domains=None` | Поиск только по памяти (сниппеты, стандарты, community_help). Возвращает блоки [пример] / [стандарт] по смыслу запроса. | `domains`: фильтр — `"standards"`, `"snippets"`, `"community_help"` или через запятую `"standards,snippets"`; без параметра — по всей памяти. Использовать, когда нужен гарантированный контекст из стандартов и сниппетов в дополнение к get_1c_code_answer. |
| **get_1c_help_topic** | `topic_path` **или** `path`, `version`, `language`, `prefer_index=False` | Полный контент топика по пути (Markdown). Путь брать из результатов поиска (напр. `zif3_CryptoManager.md`). | Оба параметра допустимы: **topic_path** или **path**. `prefer_index=True` — читать только из индекса. |
| **get_1c_function_info** | `name`, `path=None`, `choose_index=None` | Описание, синтаксис, параметры функции/метода 1С. | `path` — точный путь топика (если известен). При нескольких совпадениях — `choose_index=1,2,...` (1-based). Имена методов — полные `Тип.Метод`. |
| **get_1c_help_related** | `topic_path`, `version`, `language` | Список связанных топиков (исходящие ссылки). | Для части тем может быть пусто (outgoing_links не всегда заполняются при парсинге). |
| **list_1c_help_titles** | `limit=100`, `path_prefix=""` | Список заголовков и путей для обзора. | path_prefix — фильтр по началу пути (напр. `zif`). |

---

## Сохранение и метаданные

| Инструмент | Параметры | Описание | Лимиты / примечания |
|------------|-----------|----------|---------------------|
| **save_1c_snippet** | `code_snippet`, `description=""`, `title=""`, `write_to_files=None` | Сохранить фрагмент кода 1С в память пользователя. | code_snippet до 64 KB. `write_to_files`: при `None` используется SAVE_SNIPPET_TO_FILES из env; при True — также запись в SNIPPETS_DIR. |
| **get_form_metadata** | `xml_content` | Разбор Form.xml: атрибуты и команды. | xml_content до 64 KB. Ожидаемая структура: элементы с локальными именами **Attribute** (атрибуты формы) и **Command** (команды); при формате с другими тегами (напр. только FormAttribute) результат может быть пустым. См. раздел «Формат Form.xml» ниже. |
| **get_module_info** | `uri_or_path` | Тип модуля и контекст по пути к Module.bsl / ObjectModule.bsl. | Возвращает FormModule, ObjectModule и т.д., имя формы/объекта при возможности. |
| **get_1c_task_context** | `query`, `file_uri=None`, `symbol_name=None`, `diagnostics_json=None`, `config_version=None` | Компактный task-local контекст: file/module hints + metadata + help + memory. | Предпочтителен для AI вместо широкого bundle-контекста. |

---

## Метаданные конфигурации и контекст

Работают после построения графа метаданных: выгрузка в ONEC_CONFIG_SOURCE_DIR и команда `metadata-graph-build` (или watchdog). При пустом графе инструменты возвращают пустой результат или «not found»; проверка: `get_1c_help_index_status` показывает коллекцию **onec_config_metadata**.

**Поиск:** `search_1c_metadata` выполняет **семантический поиск** (эмбеддинг запроса + векторный поиск по коллекции) с объединением по RRF с поиском по подстроке по имени/синониму. Запросы естественным языком (например «документ реализация товаров и услуг») находят объекты по смыслу при наличии синонима и реквизитов в выгрузке.

**config_version:** при сборке графа версия берётся из `config.json` в корне выгрузки (ключ `config_version`); при отсутствии — `"0.0.0.0"`. В логе `metadata-graph-build` выводится строка `use config_version='...' in search_1c_metadata`. В вызовах можно передавать эту версию; **если в коллекции только одна версия**, параметр `config_version` можно не передавать — подставится автоматически. Иначе нужно указать версию или убедиться, что в графе одна версия.

**Данные объектов:** краулер поддерживает иерархическую выгрузку («Выгрузить в файлы») и выгрузку с Object.xml. В корне читаются **ConfigDumpInfo.xml** и **Configuration.xml**. Для каждого объекта (папка Documents/ИмяДокумента/ и т.д.) метаданные берутся: (1) из файла **в папке** (Object.xml, Document.xml, Catalog.xml и т.д.), если есть; (2) из **соседнего файла** того же имени (Documents/ИмяДокумента.xml) — в нём полное описание с типами реквизитов (Type/v8:Type) и табличными частями; (3) при отсутствии — из ConfigDumpInfo. Данные попадают в payload графа и в `get_1c_metadata_object` (блоки **Requisites** с типами, **Tabular sections**).

| Инструмент | Параметры | Описание | Лимиты / примечания |
|------------|-----------|----------|---------------------|
| **search_1c_metadata** | `query` (обяз.), `config_version=None`, `object_type=None`, `limit=20` | Поиск объектов конфигурации по запросу (семантика + подстрока по имени/синониму). | `config_version` опционален. Если в графе одна версия — поиск идёт только по ней. Если версий несколько и `config_version` не указан, поиск выполняется **по всем доступным версиям**; в выдаче каждая строка помечается `config_version: '...'`. Без `metadata-graph-build` — «Metadata graph is empty». |
| **get_1c_metadata_object** | `object_id` (обяз.), `config_version=None` | Детали объекта по id из search_1c_metadata (id, type, name, full_name, path, attributes: requisites, tabular_sections). | При нескольких конфигурациях в графе нужно передать `config_version`. При отсутствии графа или объекта — «Metadata object not found». |
| **get_1c_context_bundle** | `query`, `config_version=None`, `file_uri=None`, `symbol_name=None`, `limit=5` | Legacy broad context: справка + память + объекты метаданных. | Использовать только когда нужен расширенный bundle; для AI по умолчанию предпочитать `get_1c_task_context`. |

---

## Сравнение и статус

| Инструмент | Параметры | Описание | Лимиты / примечания |
|------------|-----------|----------|---------------------|
| **compare_1c_help** | `topic_path_or_query`, `version_left`, `version_right`, `language`, `include_diff=False` | Сравнение топика между двумя версиями платформы. | Путь из поиска можно передать «как есть» (8.3.13.1513/shcntx_ru/...) или без префикса версии (shcntx_ru/...); сервер сам подставляет version_left/version_right. По query семантика может вернуть другой топик. |
| **get_1c_help_index_status** | — | Статус индекса (число топиков, коллекция, версии, языки) и прогресс ingest. | При запущенном ingest: текущий файл, ETA, скорость, ошибки. |

---

## Переменные окружения (лимиты вывода)

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| MCP_MAX_TOPIC_CHARS | Макс. символов контента топика в get_1c_code_answer / search_1c_help_with_content | 4000 |
| MCP_SNIPPET_MAX_CHARS | Макс. символов сниппета в результатах поиска (списки) | 1200 |
| SAVE_SNIPPET_TO_FILES | При save_1c_snippet: писать также в SNIPPETS_DIR (1/true/yes) | выкл |

---

## Формат выгрузки конфигурации (иерархический)

При выгрузке из конфигуратора по кнопке **«Выгрузить в файлы»** (штатный функционал) в корне выгрузки появляются:

- **Configuration.xml** — свойства конфигурации: `Properties/Name`, `Properties/Version`, `Properties/Synonym` (v8:item/v8:lang/v8:content). Краулер использует их для `config_name`, `config_version` и отображаемого имени конфигурации.
- **ConfigDumpInfo.xml** — список метаданных с именами вида `Document.ИмяДокумента`, `Document.ИмяДокумента.Attribute.ИмяРеквизита`, `Document.ИмяДокумента.TabularSection.ИмяТабличнойЧасти`. Краулер извлекает из него реквизиты и табличные части для каждого объекта (Document, Catalog, Register и т.д.). Типы реквизитов в этом файле не хранятся.

В папках объектов (например `Documents/РеализацияТоваровУслуг/`) в иерархическом формате лежат подпапки Ext, Forms, Templates; рядом с папкой часто лежит **файл объекта** `Documents/РеализацияТоваровУслуг.xml` (имя совпадает с папкой). В нём — полное описание объекта в формате MetaDataObject (Document/Properties/Synonym, ChildObjects/Attribute с Properties/Name и Type/v8:Type, ChildObjects/TabularSection с Properties/Name). Краулер читает этот файл и подмешивает из него синоним (full_name), реквизиты **с типами** (например `cfg:CatalogRef.Организации`, `xs:boolean`) и табличные части. Если такого файла нет, используются только данные из ConfigDumpInfo.xml (имена без типов).

**Формы объектов:** для каждого объекта (документ, справочник и т.д.) краулер обходит подпапку **Forms/** и для каждой формы (например `ФормаДокумента`) читает **Forms/ИмяФормы/Ext/Form.xml** (логическая структура формы). Оттуда извлекаются реквизиты формы (имя и тип из `<Attribute>`/`<Type>`/`<v8:Type>`) и команды формы (имя, действие, заголовок из `<Command>`). Синоним формы при наличии берётся из соседнего файла **Forms/ИмяФормы.xml**. Формы попадают в граф с идентификатором вида `Form/Document.РеализацияТоваровУслуг.ФормаДокумента` и в ответе `get_1c_metadata_object` отображаются блоки **Form requisites** и **Form commands**.

---

## Формат Form.xml для get_form_metadata

Парсер извлекает **атрибуты** и **команды** формы по элементам с локальными именами (после снятия namespace):
- **Attribute** — атрибуты формы (name, type);
- **Command** — команды формы (name, action).

Полный XML с xmlns (v8, cfg, xs и т.д.) обязателен. Если в выгрузке используется другая разметка (напр. только `FormAttribute` без вложенных `Attribute`/`Command`), атрибуты и команды могут не извлечься — в ответе будут пустые списки.

---

## См. также

- [docs/mcp-1c-help-tools-report.md](mcp-1c-help-tools-report.md) — исчерпывающий отчёт по всем инструментам 1c-help и lsp-bsl-bridge, результаты прогона, полнота знаний для проекта 1С.
- [AGENTS.md](../AGENTS.md) — порядок вызовов, два MCP (1c-help + lsp-bsl-bridge), workflow.
- [docs/cursor-examples/](cursor-examples/README.md) — Skill и Rules для Cursor.
- [docs/mcp-analysis.md](mcp-analysis.md) — анализ использования и типовые просадки.
- [docs/quality-and-pitfalls-analysis.md](quality-and-pitfalls-analysis.md) — влияние индексации, обрезка эмбеддингов, как получать готовый код и типичные подводные камни.
