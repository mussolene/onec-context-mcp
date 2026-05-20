# MCP onec-context-mcp — шпаргалка

Читайте этот файл, если нужна короткая памятка по выбору инструмента без полного reference.

Одна страница: инструмент → ключевой параметр → назначение. Подробно: [../archive/mcp-1c-help-tools-report.md](../archive/mcp-1c-help-tools-report.md).

---

## onec-context-mcp: Tier 1, Tier 2, Tier 3

| Tier | Инструмент | Ключевой параметр | Назначение |
|------|------------|-------------------|------------|
| 1 | get_1c_quick_guide | task | Канонический AI entry point; короткий маршрут без лишних ветвлений. |
| 1 | get_1c_api_answer | name | Exact-first compact ответ для `Тип.Метод`. |
| 1 | get_1c_api_object | name | Structured API truth-source из `onec_help_api`. |
| 1 | answer_1c_help_question | question | Естественный вопрос по справке через structured Qdrant-first route. |
| 1 | search_1c_api | query, include_examples | Широкий structured lookup по API members/objects/examples; примеры из справки — `include_examples=True` (по умолчанию). |
| 1 | search_1c_standards | query | Только стандарты из памяти. |
| 1 | search_1c_snippets | query | Только code snippets и community_help. |
| 1 | search_1c_metadata_exact | query, config_version | Exact-first поиск объектов конфигурации. |
| 1 | search_1c_metadata_semantic | query, config_version | Natural-language поиск объектов конфигурации. |
| 1 | search_1c_metadata_fields | object_query, field_query | Поиск реквизитов/табличных частей/команд. |
| 1 | get_1c_metadata_object | object_id | Детали найденного объекта конфигурации. |
| 1 | get_form_metadata | xml_content | Разбор Form.xml (атрибуты, команды). |
| 1 | get_module_info | uri_or_path | Тип модуля по пути к `.bsl`. |
| 1 | get_1c_help_index_status | — | Статус индекса и ingest. |
| 2 | compare_1c_help | topic_path_or_query, version_left, version_right | Сравнение топика между версиями. |
| 2 | get_1c_api_related | name | Связанные API-элементы через structured links. |
| 2 | save_1c_snippet | code_snippet | Сохранить проверенный переиспользуемый код. |

---

## BSL Language Server (не MCP этого репозитория)

Проверка `.bsl`: exec-JAR `analyze` / `format` ([bsl-language-server-local](../cursor-examples/bsl-language-server-local/SKILL.md)), расширение IDE или опционально `make bsl-start`. См. [bsl-ls-mcp-setup.md](bsl-ls-mcp-setup.md).

---

## Инструменты (tools) onec-context-mcp для AI

| Инструмент | Параметр | Назначение |
|------------|----------|------------|
| **get_1c_quick_guide** | task=develop\|refactor\|test | Единственный канонический AI entry point. Вызывать в начале задачи. |

## Промпты onec-context-mcp

| Промпт | Назначение |
|--------|------------|
| how_to_use_1c_help_and_bsl_ls | Длинная human/onboarding инструкция: onec-context-mcp + BSL LS (CLI/IDE). |
| get_1c_common_pitfalls | Типичные ловушки 1С/BSL с wrong/right примерами кода (11+ паттернов). |
| get_mcp_workflow_guide | Текст руководства по порядку вызовов (workflow). |
| get_mcp_tools_tips | Подсказки: пустые ответы, URI, координаты. |
| get_mcp_tools_summary | Выжимка отчёта: когда какой MCP, лимиты. |
| get_mcp_guides_bundle | Все три руководства одним блоком. |

---

**Канонический AI route:** `get_1c_quick_guide` → exact API: `get_1c_api_answer` (`detail="full"` при необходимости) / natural-language help: `answer_1c_help_question` / structured API: `get_1c_api_object` / broad structured lookup: `search_1c_api` (официальные примеры — `include_examples=True`) → standards/snippets: `search_1c_standards` / `search_1c_snippets` → metadata: `search_1c_metadata_exact` / `search_1c_metadata_semantic` / `search_1c_metadata_fields` → BSL LS `analyze` или IDE. Пути к `.bsl` — обычные пути в workspace.
