# Отчёт проверки MCP 1c-help (инструменты и соответствие skill/правилам)

**Дата проверки:** 2025-03-09  
**Проверено:** юнит-тесты MCP, интеграционные тесты (условия), соответствие skill и mcp-tools-reference.

**Актуализация (2026-04):** состав tools и тестов изменился (structured route, удалены `get_1c_context_bundle`, `get_1c_function_info`, `search_1c_memory`, `search_1c_official_examples` и др.). Таблицы ниже — снимок 2025-03; ориентир для текущего surface — [mcp-tools-reference.md](../reference/mcp-tools-reference.md).

---

## 1. Резюме

| Категория | Результат |
|-----------|------------|
| **Юнит-тесты (test_mcp_server.py)** | 47 тестов пройдено |
| **Интеграционные тесты** | 10 тестов пропущены (требуется запущенный MCP на localhost:8050) |
| **Соответствие skill / правилам** | Параметры и порядок вызовов совпадают с документацией |
| **Покрытие инструментов юнит-тестами** | Все 16 инструментов 1c-help покрыты тестами |

---

## 2. Список инструментов MCP 1c-help и статус тестов

Все перечисленные инструменты имеют юнит-тесты в `tests/test_mcp_server.py` (через `build_mcp_app` и вызов через app).

| № | Инструмент | Юнит-тест | Назначение (по skill / mcp-tools-reference) |
|---|------------|-----------|--------------------------------------------|
| 1 | `get_1c_help_index_status` | ✅ test_mcp_tool_get_1c_help_index_status_via_app | Статус индекса (топики, коллекция, ingest) |
| 2 | `get_1c_code_answer` | ✅ test_mcp_tool_get_1c_code_answer_* (в т.ч. code_only, include_memory) | Ответ с кодом: семантика + keyword + контент + память |
| 3 | `search_1c_help` | ✅ test_mcp_tool_search_1c_help_via_app, _no_results | Семантический поиск по справке |
| 4 | `search_1c_help_keyword` | ✅ test_mcp_tool_search_1c_help_keyword_via_app | Поиск по подстроке/BM25 (точные имена API, Тип.Метод) |
| 5 | `search_1c_help_with_content` | ✅ test_mcp_tool_search_1c_help_with_content_via_app | Гибридный поиск + полный контент топ-N топиков |
| 6 | `get_1c_help_topic` | ✅ test_mcp_tool_get_1c_help_topic_via_app | Контент топика по пути (параметр **topic_path**) |
| 7 | `get_1c_function_info` | ✅ test_mcp_tool_get_1c_function_info_* (choose_index, empty_name) | Описание, синтаксис, параметры функции/метода |
| 8 | `get_1c_help_related` | ✅ test_mcp_tool_get_1c_help_related_* (via_app, empty) | Связанные топики (исходящие ссылки) |
| 9 | `list_1c_help_titles` | ✅ test_mcp_tool_list_1c_help_titles_via_app | Список заголовков и путей (path_prefix, limit) |
| 10 | `save_1c_snippet` | ✅ test_mcp_tool_save_1c_snippet_via_app | Сохранение фрагмента кода в память (и при необходимости в файлы) |
| 11 | `get_form_metadata` | ✅ test_mcp_tool_get_form_metadata_via_app | Разбор Form.xml (атрибуты, команды) |
| 12 | `get_module_info` | ✅ test_mcp_tool_get_module_info_via_app | Тип модуля по пути (ObjectModule, FormModule и т.д.) |
| 13 | `compare_1c_help` | ✅ test_mcp_tool_compare_1c_help_via_app | Сравнение топика между двумя версиями платформы |
| 14 | `search_1c_metadata` | ✅ test_mcp_tool_search_1c_metadata_via_app | Поиск по метаданным конфигурации (граф метаданных) |
| 15 | `get_1c_metadata_object` | ✅ test_mcp_tool_get_1c_metadata_object_via_app | Данные объекта метаданных по ID |
| 16 | `get_1c_context_bundle` | ✅ test_mcp_tool_get_1c_context_bundle_via_app | Собранный контекст для разработки (справка + метаданные) |

Дополнительно проверены: лимиты (rate limit, truncate query), гибридный поиск при `score=None`, извлечение токенов для keyword (Тип.Метод), извлечение блоков кода, подсказка при низкой релевантности.

---

## 3. Соответствие skill и правилам

- **Параметр топика:** в `get_1c_help_topic` используется **topic_path** (не `path`) — в коде и в тестах соблюдено.
- **Порядок вызовов (skill / AGENTS.md):**  
  1) `get_1c_code_answer` для ответа с кодом;  
  2) при нерелевантности — `search_1c_help_keyword` с точным именем API → `get_1c_help_topic(topic_path)`;  
  3) при нескольких совпадениях в `get_1c_function_info` — `choose_index` (1-based);  
  4) после рабочего кода — `save_1c_snippet`.  
  Реализация инструментов и описание в `docs/reference/mcp-tools-reference.md` этому соответствуют.
- **Типичные ошибки из skill:** в коде используется только `topic_path`; в справочнике явно указано «параметр только topic_path (не path)».

---

## 4. Интеграционные и функциональные тесты

- **Файлы:** `tests/test_mcp_integration.py`, `tests/test_mcp_functional_crypto.py`.
- **Условие запуска:** переменная окружения `MCP_INTEGRATION=1` и доступный MCP-сервер (по умолчанию `http://localhost:8050/mcp`).
- **Текущий результат:** при запуске без поднятого MCP все 10 тестов пропускаются (skip с сообщением «MCP not available»).

**Как выполнить проверку на живом сервере:**

1. Поднять стек: `make up` (qdrant + mcp + redis) или `make ingest-up` при необходимости индекса.
2. Дождаться готовности MCP (и при необходимости завершения ingest).
3. Запустить интеграционные тесты:
   ```bash
   MCP_INTEGRATION=1 PYTHONPATH=src python3 -m pytest tests/test_mcp_integration.py tests/test_mcp_functional_crypto.py -v --no-cov
   ```
4. Для проверки с проектом в `.nosync` убедиться, что индекса справки и (при использовании метаданных) граф метаданных построены (`make metadata-build` при необходимости).

---

## 5. Рекомендации

1. **Регрессия:** перед изменениями в `mcp_server.py` запускать:
   ```bash
   PYTHONPATH=src python3 -m pytest tests/test_mcp_server.py -v --no-cov
   ```
   чтобы не задевать контракт инструментов.
2. **Живая проверка:** периодически запускать интеграционные тесты с поднятым MCP (`MCP_INTEGRATION=1`) для проверки связки MCP + Qdrant + Redis.
3. **Документация:** при добавлении новых инструментов обновлять `docs/reference/mcp-tools-reference.md` и при необходимости `docs/archive/mcp-1c-help-tools-report.md` и skill в `docs/cursor-examples/`.

---

## 6. Повторная проверка (вызовы в чате)

Все 16 инструментов вызваны через MCP (сервер user-1c-help). Результаты сверены с планируемым поведением из плана аудита и mcp-tools-reference.

| № | Инструмент | Результат вызова | Соответствие плану |
|---|------------|------------------|--------------------|
| 1 | get_1c_help_index_status | Collection, Topics, Memory, Last ingest | OK. При наличии коллекции onec_config_metadata выводится строка Metadata (реализовано в коде). |
| 2 | get_1c_code_answer | Ответ с топиками и контентом по запросу (МенеджерКриптографии.Подписать) | OK. Релевантный контент, структура «Запрос» + «Из справки». |
| 3 | search_1c_help_keyword | Точные совпадения по «Запрос.ВыполнитьПакет» с path и сигнатурами | OK. Планируемое поведение для точных имён API. |
| 4 | search_1c_help | Семантические результаты по «формат даты» | OK. Список топиков с path/snippet. |
| 5 | search_1c_help_with_content | Гибридный поиск + полный контент по «Формат даты строка» | OK. Топики с контентом (Надпись.Формат и др.). |
| 6 | get_1c_help_topic | Полный текст топика по topic_path (ExecuteBatch3663) | OK. Параметр topic_path, полный Markdown. |
| 7 | get_1c_function_info | Несколько совпадений + подсказка choose_index + контент первого | OK. Планируемое поведение при нескольких версиях. |
| 8 | get_1c_help_related | «No related topics found» для топика Подписать | OK. Документированное ограничение (не все топики имеют outgoing_links). |
| 9 | list_1c_help_titles | Список заголовков и путей (limit=3) | OK. |
| 10 | compare_1c_help | Сравнение двух версий по topic_path_or_query (Query.Text для 8.2 и 8.3) | OK. Две версии, контент по каждой. |
| 11 | save_1c_snippet | «Snippet saved to memory and to … .md» | OK. |
| 12 | get_module_info | ObjectModule, Sales по пути Documents/Sales/Ext/ObjectModule.bsl | OK. Тип модуля и имя объекта. |
| 13 | get_form_metadata | При XML с элементами Attribute и Command — атрибуты и команды извлечены (Object: Document.Sales; Create) | OK. Соответствует документированному формату (Attribute, Command). |
| 14 | search_1c_metadata | «No metadata objects found… Ensure metadata-graph-build was run…» при пустом графе | OK. Обязательный config_version, подсказка при пустом графе. |
| 15 | get_1c_metadata_object | «Metadata object not found. Ensure metadata-graph-build…» при отсутствии объекта | OK. Подсказка в сообщении. |
| 16 | get_1c_context_bundle | Комбинированный контекст из справки (подписание данных) — топики без метаданных при пустом графе | OK. Один limit, при пустом графе возвращает справку и память. |

**Заключение повторной проверки:** все инструменты работают корректно и соответствуют планируемому поведению. Параметры (topic_path, config_version, limit), сообщения при пустом графе метаданных с подсказкой про metadata-graph-build и разбор Form.xml при формате Attribute/Command ведут себя как задумано. Полнота знаний по справке и памяти достаточна для сценариев помощи ассистенту; инструменты метаданных готовы к использованию после выполнения metadata-graph-build.

---

## 7. Связанные документы

- [docs/reference/mcp-tools-reference.md](../reference/mcp-tools-reference.md) — параметры и лимиты всех инструментов.
- [docs/archive/mcp-1c-help-tools-report.md](mcp-1c-help-tools-report.md) — полнота знаний и примеры прогона по проекту (.nosync).
- [AGENTS.md](../../AGENTS.md) — порядок вызовов, два MCP (1c-help + lsp-bsl-bridge).
- Skill: `.cursor/skills/1c-mcp-development/SKILL.md` — матрица выбора инструментов и циклы (написание кода, рефакторинг).

*(Раздел 6 добавлен по результатам повторной проверки вызовов всех инструментов в чате.)*
