# MCP 1c-help и lsp-bsl-bridge — шпаргалка

Одна страница: инструмент → ключевой параметр → назначение. Подробно: [mcp-1c-help-tools-report.md](mcp-1c-help-tools-report.md).

---

## 1c-help (15)

| Инструмент | Ключевой параметр | Назначение |
|------------|-------------------|------------|
| get_1c_help_index_status | — | Статус индекса и ingest; при сомнениях в полноте вызвать первым. |
| get_1c_code_answer | query | Ответ с кодом по справке и памяти; основной для примеров. |
| search_1c_help | query | Семантический поиск; для кода лучше get_1c_code_answer. |
| search_1c_help_keyword | query | Поиск по подстроке/BM25; для точных имён API — **Тип.Метод**. |
| search_1c_help_with_content | query | Поиск + контент топ-N топиков в одном вызове. |
| get_1c_help_topic | **topic_path** | Контент топика по пути из поиска (параметр topic_path, не path). |
| get_1c_function_info | name | Синтаксис и параметры метода; name = полное **Тип.Метод**. |
| get_1c_help_related | topic_path | Связанные топики по исходящим ссылкам. |
| list_1c_help_titles | path_prefix | Список заголовков и путей для обзора. |
| save_1c_snippet | code_snippet | Сохранить код в память; после рабочего кода — улучшает ответы. |
| get_form_metadata | xml_content | Разбор Form.xml (атрибуты, команды); передавать полный XML с xmlns. |
| get_module_info | uri_or_path | Тип модуля (ObjectModule и т.д.) по пути к .bsl. |
| compare_1c_help | topic_path_or_query, version_left, version_right | Сравнение топика между версиями. Путь можно передать «как из поиска» (8.3.13.1513/shcntx_ru/...) или без версии (shcntx_ru/...); сервер сам подставит version_left/version_right. |
| get_1c_help_topics_bulk | paths (list) | Контент нескольких топиков за один вызов (до 10 путей). Эффективнее N вызовов get_1c_help_topic. |
| search_1c_metadata | query, config_version | Поиск объектов конфигурации (Documents, Catalogs…). Требует metadata-graph-build. |
| get_1c_metadata_object | object_id | Детали объекта (реквизиты, ТЧ). object_id из search_1c_metadata. |
| get_1c_context_bundle | query | Справка + память + метаданные за один вызов. |

---

## lsp-bsl-bridge (14)

| Инструмент | Ключевой параметр | Назначение |
|------------|-------------------|------------|
| lsp_status | — | Готовность LSP и прогресс индексации. |
| document_diagnostics | uri | Ошибки/предупреждения BSL LS по файлу; после правок — до чистоты. |
| project_analysis | analysis_type, query | Поиск символов (workspace_symbols), файлов; основа навигации. |
| symbol_explore | query | Детали по символам; без file_context надёжнее. |
| get_range_content | uri, start_line, end_line | Фрагмент кода по диапазону; навигация без definition/hover. |
| call_graph | uri, line, character | Граф вызовов от позиции (0-based); часто пусто — опционально. |
| call_hierarchy | uri, line, character | Иерархия вызовов; опционально. |
| definition | uri, line, character | Переход к определению; координаты из project_analysis. |
| hover | uri, line, character | Подсказка по символу; опционально. |
| code_actions | uri, line, end_line | Быстрые исправления по диагностикам. |
| prepare_rename | uri, line, character | Превью переименования перед rename. |
| rename | uri, line, character, new_name, apply | Переименование по проекту; сначала apply=false. |
| selection_range | uri, line, character | Диапазоны выбора (слово → строка → блок). |
| did_change_watched_files | language, changes_json | Уведомить LSP после массовых правок (type: 2 = Changed). |

---

## Инструменты (tools) 1c-help для AI

| Инструмент | Параметр | Назначение |
|------------|----------|------------|
| **get_1c_quick_guide** | task=develop\|refactor\|test | Компактная инструкция для автономного AI (150-300 токенов). Вызывать в начале задачи. |

## Промпты 1c-help

| Промпт | Назначение |
|--------|------------|
| how_to_use_1c_help_and_bsl_bridge | Инструкция по двум MCP; task=develop\|refactor\|test — короткий блок. |
| get_1c_common_pitfalls | Типичные ловушки 1С/BSL с wrong/right примерами кода (11+ паттернов). |
| get_mcp_workflow_guide | Текст руководства по порядку вызовов (workflow). |
| get_mcp_tools_tips | Подсказки: пустые ответы, URI, координаты. |
| get_mcp_tools_summary | Выжимка отчёта: когда какой MCP, лимиты. |
| get_mcp_guides_bundle | Все три руководства одним блоком. |

---

**URI:** Docker — `file:///projects/<путь>`; кириллица — URL-encoding (Менеджер → %D0%9C%D0%B5...). **Координаты** LSP: 0-based. **Порядок:** примеры → get_1c_code_answer; точный API → search_1c_help_keyword → get_1c_help_topic(**topic_path**); несколько топиков → get_1c_help_topics_bulk; проверка кода → document_diagnostics; навигация → project_analysis → symbol_explore.
