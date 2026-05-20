# Справочник MCP-инструментов onec-context-mcp

Читайте этот файл, когда уже нужен полный reference по MCP tools: параметры, лимиты, порядок вызовов и частые ошибки в аргументах.

Быстрая версия без деталей: [mcp-tools-cheatsheet.md](mcp-tools-cheatsheet.md).

## Рекомендуемый порядок вызовов

1. **Старт AI-сессии** — `get_1c_quick_guide(task="develop"|"refactor"|"test")`.
2. **Surface-chain / exact resolve** — `resolve_1c_api_name(name)` для форм вроде `Документы.Имя.Метод`, `Константы.Имя.Получить`, `Метаданные.СвойстваОбъектов.РежимСовместимости`.
3. **Точное API `Тип.Метод`** — `get_1c_api_answer(name)`; полный structured текст — `detail="full"`.
4. **Structured API truth-source** — `get_1c_api_object(name)`.
5. **Широкий structured lookup по платформе** — `search_1c_api(query)`; официальные примеры из справки — тот же вызов с `include_examples=True` (по умолчанию уже `True`).
6. **Естественный вопрос по справке** — `answer_1c_help_question(question)`.
7. **Локальный anti-hallucination context** — `get_1c_task_context(query, file_uri, symbol_name)`.
8. **Стандарты и сниппеты** — `search_1c_standards(query)` / `search_1c_snippets(query)`.
9. **Метаданные** — `search_1c_metadata_exact` / `search_1c_metadata_semantic` / `search_1c_metadata_fields`.
10. **После генерации рабочего кода** — `save_1c_snippet` только для реально переиспользуемого и уже проверенного результата.

---

## Имена параметров (избежание ошибок валидации)

При вызове MCP-инструментов **имена параметров в JSON должны совпадать** с сигнатурой. Частые ошибки:

| Инструмент | Передавать | Не передавать |
|------------|-------------|----------------|
| **search_1c_api** | `query` | — |
| **resolve_1c_api_name** | `name` | — |
| **get_1c_help_index_status** | без параметров (пустой объект `{}`) | — |
| **get_1c_metadata_object** | `object_id`, при нескольких конфигурациях — `config_version` | — |
| **search_1c_metadata_exact** | `query`, при нескольких конфигурациях — `config_version` | — |
| **search_1c_metadata_semantic** | `query`, при нескольких конфигурациях — `config_version` | — |
| **search_1c_metadata_fields** | `object_query`, `field_query`, при нескольких конфигурациях — `config_version` | — |
| **get_module_info** | `uri_or_path` | Не `module_name` / `symbol`. |
| **get_form_metadata** | `xml_content` (сырой XML Form.xml) | Не `form_uri`. |

Основной публичный broad-search параметр теперь только `query` у `search_1c_api`.

---

## Поиск и чтение

| Инструмент | Параметры | Описание | Лимиты / примечания |
|------------|-----------|----------|---------------------|
| **search_1c_api** | `query`, `limit=10`, `version`, `language`, `include_examples=True` | Широкий structured lookup по `api_members`, `api_objects` и официальным примерам. | query до 64 KB. Основной broad-search route вместо topic-layer search. |
| **resolve_1c_api_name** | `name` | Resolver surface-синтаксиса языка 1С в канонические кандидаты structured help / metadata graph. | Первый выбор для `Документы.Имя.Метод`, `Константы.Имя.Получить`, `Метаданные.…`. |
| **get_1c_api_answer** | `name`, `version=None`, `language=None`, `detail="compact"` | Compact exact-first ответ по точному API/функции/методу. | Первый выбор для `Тип.Метод`; `detail="full"` возвращает enriched structured payload. |
| **get_1c_api_object** | `name`, `version=None`, `language=None` | Structured API object/type из `onec_help_api_objects`. | Low-token truth-source для агента и отладки exact API route. |
| **answer_1c_help_question** | `question`, `version=None`, `language=None`, `detail="compact"` | Естественный вопрос по справке через structured Qdrant-first route; вопросы про **СКД/компоновку** дополнительно маршрутизируются в structured API search. | Пустые тела примеров в индексе не выводятся как пустой блок `bsl`. |
| **search_1c_standards** | `query`, `limit=5` | Поиск только по стандартам в памяти (v8std, v8-code-style, ITS). | Первый выбор для style/rule вопросов. |
| **search_1c_snippets** | `query`, `limit=5` | Поиск только по примерам кода и snippets/community_help. | Первый выбор для code examples. |
| **get_1c_api_related** | `name`, `version=None`, `language=None` | Связанные API-элементы (`see_also` и другие structured links). | Structured replacement для topic-related lookup. |

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

Работают после построения графа метаданных: KD2 XML или compact snapshot в `ONEC_CONFIG_SOURCE_DIR` и команда `metadata-graph-build` (или watchdog). При пустом графе инструменты возвращают пустой результат или «not found»; проверка: `get_1c_help_index_status` показывает коллекцию **onec_config_metadata**.

**Поиск:** `search_1c_metadata_exact` делает exact-first lookup по `id`, `name`, `full_name`, `path` внутри `config_version`. **Канонический id в индексе** — **`EnglishType.ИмяОбъекта`** (например `Document.РеализацияТоваровУслуг`): это соглашение KD2/Qdrant (payload `id`), **не** синтаксис языка запросов (в запросах — **`Документ.Имя`**, **`Справочник.Имя`** и т.д.). Устаревший вид `Type/Name` по-прежнему можно подставить в поиск и в `get_1c_metadata_object` до полной пересборки графа.

В BSL к объектам конфигурации обращаются через глобальные коллекции (**`Метаданные.Документы.Имя`**, **`Документы.Имя`**, **`Перечисления.ИмяПеречисления.…`** и т.д.); дальше в цепочке идут **методы и свойства менеджера** конкретного типа — их перечень не хардкодится в MCP: в индексе structured help это объекты вида **`ДокументМенеджер.<Имя документа>`**, **`СправочникМенеджер.<Имя справочника>`** и т.п. (шаблоны совпадают с `object_name` в `data/help_structured/api_objects.jsonl` и собраны в коде в **`src/onec_help/knowledge/platform_help_manager_templates.py`**). Подставьте имя объекта из вашей конфигурации и вызовите **`get_1c_api_object("…")`** или **`search_1c_api`**. В типовой конфигурации **имя объекта метаданных — идентификатор без точки**; для графа KD2 MCP берёт **первый сегмент после префикса типа** (в т.ч. для `Документы.Авансы` и `Справочники.Авансы` — различаются префиксом; при коллизии имён задайте **`object_type`**). Повтор **`Метаданные.`**, **`Metadata.`**, пробелы вокруг точек и префикс **`Глобальный контекст.…`** нормализуются; для EN-клиента — коллекции вроде **`Documents.Имя`**. Корень дерева метаданных в справке: **`get_1c_api_answer("Глобальный контекст.Метаданные")`**, обобщённо **`search_1c_api("ОбъектМетаданных")`**.

`search_1c_metadata_semantic` сочетает векторный поиск с prepended exact; для узкого поиска задавайте **`object_type`**. `search_1c_metadata_fields` ищет по **имени или синониму поля** в реквизитах, измерениях/ресурсах регистров, стандартных свойствах, колонках табличных частей и командах.

**Переиндексация метаданных (Qdrant `onec_config_metadata`):** после исправлений, которые **только читают** уже записанный в payload `attributes` (например логика полей в `search_1c_metadata_fields`), полная пересборка графа **не обязательна**. Пересборка **`metadata-graph-build`** нужна при изменении текста для эмбеддинга, схемы payload, отдельной коллекции полей или источника выгрузки.

**config_version:** при сборке графа версия берётся из KD2 XML / compact snapshot; при отсутствии — `"0.0.0.0"`. В логе `metadata-graph-build` выводится строка `use config_version='...'` для metadata tools. В вызовах можно передавать эту версию; **если в коллекции только одна версия**, параметр `config_version` можно не передавать — подставится автоматически. Иначе нужно указать версию или убедиться, что в графе одна версия.

**Данные объектов:** graph payload строится из `objects.jsonl` и `fields.jsonl`, которые создаёт KD2 parser. В `get_1c_metadata_object` выводятся объект, реквизиты/поля, табличные части и команды, если они присутствуют в snapshot. Штатная иерархическая выгрузка «Выгрузить в файлы» (`Configuration.xml`, `Documents/…`) больше не читается runtime-кодом.

| Инструмент | Параметры | Описание | Лимиты / примечания |
|------------|-----------|----------|---------------------|
| **search_1c_metadata_exact** | `query` (обяз.), `config_version=None`, `object_type=None`, `limit=20` | Exact-first поиск объектов конфигурации по id/name/full_name/path. | Первый выбор для object lookup. Если версий несколько и `config_version` не указан, поиск выполняется по всем доступным версиям. |
| **search_1c_metadata_semantic** | `query` (обяз.), `config_version=None`, `object_type=None`, `limit=20` | Семантический поиск объектов конфигурации по natural-language запросу. | После exact, если имя неизвестно; **`object_type`** сильно снижает шум (например только документы). |
| **search_1c_metadata_fields** | `object_query`, `field_query`, `config_version=None`, `object_type=None`, `limit=10`, `exact_object_first=True` | Поиск реквизитов, табличных частей и команд внутри объектов конфигурации. | Для field-level вопросов. При нескольких конфигурациях без `config_version` поиск идёт по всем версиям. |
| **get_1c_metadata_object** | `object_id` (обяз.), `config_version=None` | Детали объекта по id из `search_1c_metadata_exact` / `search_1c_metadata_semantic` (id, type, name, full_name, path, attributes: requisites, tabular_sections). | При нескольких конфигурациях в графе нужно передать `config_version`. При отсутствии графа или объекта — «Metadata object not found». |

---

## Сравнение и статус

| Инструмент | Параметры | Описание | Лимиты / примечания |
|------------|-----------|----------|---------------------|
| **compare_1c_help** | `topic_path_or_query`, `version_left`, `version_right`, `language`, `include_diff=False` | Низкоуровневое сравнение статьи внутреннего topic index между двумя версиями платформы. | Сервисный tool для version diff; не является основным runtime route для агента. |
| **get_1c_help_index_status** | — | Статус индекса (число топиков, коллекция, версии, языки) и прогресс ingest. | При запущенном ingest: текущий файл, ETA, скорость, ошибки. |

---

## Переменные окружения (лимиты вывода)

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| MCP_SNIPPET_MAX_CHARS | Макс. символов сниппета в результатах поиска (списки) | 1200 |
| SAVE_SNIPPET_TO_FILES | При save_1c_snippet: писать также в SNIPPETS_DIR (1/true/yes) | выкл |

---

## Формат источника метаданных

Runtime-источник для `onec_config_metadata` — **KD2 XML из `tools/1c/MetadataExport.epf`**
или compact snapshot `manifest.json|objects.jsonl|fields.jsonl`, созданный из этого XML.
Старый crawler штатной выгрузки «Выгрузить в файлы»
(`Configuration.xml`, `Documents/…`, `Catalogs/…`) удалён из runtime: такой каталог
не является валидным источником для `metadata-graph-build`.

Основной путь:

```bash
PYTHONPATH=src python3 -m onec_help metadata-graph-build data/metadata_export
```

Если в `data/metadata_export` лежит KD2 XML, команда обновляет per-config snapshot в
`data/metadata_export/snapshots/<config-key>/` и индексирует его в Qdrant. Если передан
уже готовый snapshot root или snapshot dir, он используется напрямую.

---

## Формат Form.xml для get_form_metadata

Парсер извлекает **атрибуты** и **команды** формы по элементам с локальными именами (после снятия namespace):
- **Attribute** — атрибуты формы (name, type);
- **Command** — команды формы (name, action).

Полный XML с xmlns (v8, cfg, xs и т.д.) обязателен. Если в выгрузке используется другая разметка (напр. только `FormAttribute` без вложенных `Attribute`/`Command`), атрибуты и команды могут не извлечься — в ответе будут пустые списки.

---

## См. также

- [../archive/mcp-1c-help-tools-report.md](../archive/mcp-1c-help-tools-report.md) — исторический отчёт по инструментам и прогонам (в т.ч. BSL LS).
- [../../AGENTS.md](../../AGENTS.md) — порядок вызовов: MCP onec-context-mcp + BSL LS (CLI/IDE).
- [../cursor-examples/README.md](../cursor-examples/README.md) — Skill и Rules для Cursor.
- [../archive/mcp-analysis.md](../archive/mcp-analysis.md) — анализ использования и типовые просадки.
- [../archive/quality-and-pitfalls-analysis.md](../archive/quality-and-pitfalls-analysis.md) — влияние индексации, обрезка эмбеддингов, как получать готовый код и типичные подводные камни.
