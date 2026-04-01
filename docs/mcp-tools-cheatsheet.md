# MCP 1c-help и внешний lsp-bsl-bridge — шпаргалка

Одна страница: инструмент → ключевой параметр → назначение. Подробно: [mcp-1c-help-tools-report.md](mcp-1c-help-tools-report.md).

---

## 1c-help: Tier 1, Tier 2, Tier 3

| Tier | Инструмент | Ключевой параметр | Назначение |
|------|------------|-------------------|------------|
| 1 | get_1c_quick_guide | task | Канонический AI entry point; короткий маршрут без лишних ветвлений. |
| 1 | get_1c_code_answer | query | Основной ответ с кодом; для неточного запроса или вопроса по сценарию. |
| 1 | search_1c_help_keyword | query | Точный поиск по API/идентификатору; передавать **Тип.Метод** целиком. |
| 1 | get_1c_help_topic | **topic_path** | Полный контент топика по пути из поиска. |
| 1 | search_1c_memory | query | Точечный вызов для стандартов и сниппетов. |
| 1 | search_1c_metadata | query, config_version | Поиск объектов конфигурации; использовать только когда нужен объектный контекст. |
| 1 | get_1c_metadata_object | object_id | Детали найденного объекта конфигурации. |
| 1 | get_form_metadata | xml_content | Разбор Form.xml (атрибуты, команды). |
| 1 | get_module_info | uri_or_path | Тип модуля по пути к `.bsl`. |
| 1 | get_1c_help_index_status | — | Статус индекса и ingest. |
| 2 | get_1c_function_info | name | Синтаксис и параметры точного метода/функции. |
| 2 | compare_1c_help | topic_path_or_query, version_left, version_right | Сравнение топика между версиями. |
| 2 | get_1c_help_related | topic_path | Смежные темы по исходящим ссылкам. |
| 2 | get_1c_help_topics_bulk | paths | Несколько тем за вызов. |
| 2 | save_1c_snippet | code_snippet | Сохранить проверенный переиспользуемый код. |
| 3 | search_1c_help | query | Общий семантический поиск; не основной AI route. |
| 3 | list_1c_help_titles | path_prefix | Обзор индекса. |
| 3 | get_1c_context_bundle | query | Широкий bundle-контекст; expert/legacy tool. |
| 3 | search_1c_help_with_content | query | Legacy/deprecated путь. |

---

## Внешний lsp-bsl-bridge

Этот MCP подключается дополнительно. Он **не разрабатывается** в этом репозитории; здесь фиксируется только рекомендуемый маршрут использования.

| Роль | Инструмент | Назначение |
|------|------------|------------|
| Основной | document_diagnostics | Проверка кода после каждой правки. |
| Основной | project_analysis | Поиск символов и файлов. |
| Основной | symbol_explore | Детали по символу без позиционной хрупкости. |
| Основной | get_range_content | Фрагмент кода по диапазону. |
| Основной | did_change_watched_files | Синхронизация после batch-правок. |
| Основной | prepare_rename / rename | Управляемое переименование. |
| Вторичный | lsp_status | Health-check. |
| Опциональный | definition / hover / call_graph / call_hierarchy / code_actions / selection_range | Использовать как дополнительный probe, не как базовый маршрут. |

---

## Инструменты (tools) 1c-help для AI

| Инструмент | Параметр | Назначение |
|------------|----------|------------|
| **get_1c_quick_guide** | task=develop\|refactor\|test | Единственный канонический AI entry point. Вызывать в начале задачи. |

## Промпты 1c-help

| Промпт | Назначение |
|--------|------------|
| how_to_use_1c_help_and_bsl_bridge | Человеко-ориентированная инструкция по `1c-help` и внешнему `lsp-bsl-bridge`. |
| get_1c_common_pitfalls | Типичные ловушки 1С/BSL с wrong/right примерами кода (11+ паттернов). |
| get_mcp_workflow_guide | Текст руководства по порядку вызовов (workflow). |
| get_mcp_tools_tips | Подсказки: пустые ответы, URI, координаты. |
| get_mcp_tools_summary | Выжимка отчёта: когда какой MCP, лимиты. |
| get_mcp_guides_bundle | Все три руководства одним блоком. |

---

**Канонический AI route:** `get_1c_quick_guide` → exact API: `search_1c_help_keyword` / общий вопрос: `get_1c_code_answer` → при необходимости `get_1c_help_topic` → внешний `document_diagnostics`. **URI для внешнего LSP:** Docker — `file:///projects/<путь>`; кириллица — URL-encoding. Координаты LSP: 0-based.
