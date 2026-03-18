---
name: 1c-mcp-tools-report
description: Ориентация по отчёту о полноте MCP 1c-help и lsp-bsl-bridge. Применять при вопросах «достаточно ли инструментов», «какой инструмент когда», при пустых/нерелевантных ответах MCP, при настройке workflow разработки 1С.
---

# Отчёт по инструментам MCP (выжимка)

Основано на [docs/mcp-1c-help-tools-report.md](../../mcp-1c-help-tools-report.md). Полный отчёт — таблицы по всем 13 инструментам 1c-help и 14 lsp-bsl-bridge, результаты прогона, лимиты и подводные камни.

## Полнота знаний: когда чего хватает

| Задача | 1c-help | lsp-bsl-bridge | Комментарий |
|--------|---------|----------------|-------------|
| Понять проект (тип модуля, форма) | Да | — | `get_module_info`, `get_form_metadata` |
| Разработка / дописывание (API, примеры) | Да | — | `get_1c_code_answer`, `search_1c_help_keyword`, `get_1c_help_topic`, `get_1c_function_info` |
| Поддержка (рефакторинг, стандарты) | Частично | Да | 1c-help — справка; BSL LS и навигация — lsp-bsl-bridge |
| Тестирование (проверка кода) | Нет | Да | `document_diagnostics`; запуск YaxUnit/Vanessa — вручную |
| Сравнение версий платформы | Да | — | `compare_1c_help` |
| Сохранение переиспользуемого кода | Да | — | `save_1c_snippet` |

**Вывод:** для понимания и разработки/дописывания проекта 1С достаточно 1c-help. Для поддержки и проверки кода нужна связка **1c-help + lsp-bsl-bridge**.

## Иерархия выбора инструментов

| Задача | Инструмент |
|--------|-----------|
| Любой вопрос по коду 1С | **`get_1c_code_answer`** — ПЕРВЫЙ вызов |
| Нужны объекты конфигурации тоже | `get_1c_context_bundle` (help + память + метаданные) |
| Только имя функции/метода | `get_1c_function_info("Тип.Метод")` |
| Точный API, идентификатор | `search_1c_help_keyword("Тип.Метод")` → `get_1c_help_topic` |
| Только стандарты/сниппеты | `search_1c_memory(domains="standards,snippets")` |
| Объекты конфигурации | `search_1c_metadata` → `get_1c_metadata_object` |
| Несколько топиков сразу | `get_1c_help_topics_bulk(paths=[...], max_chars_per_topic=4000)` |
| Что изменилось между версиями | `compare_1c_help(topic, v1, v2)` |

## Порядок вызовов (кратко)

1. **Старт задачи (AI):** `get_1c_quick_guide(task="develop"|"refactor"|"test")` — компактная инструкция для автономного агента.
2. **Примеры кода / API:** `get_1c_code_answer(query, include_memory=True)` (ПЕРВЫЙ вызов).
   - Больше деталей: `max_chars_per_topic=8000`. Только код: `code_only=True`.
   - При нерелевантности: `search_1c_help_keyword("Тип.Метод")` → `get_1c_help_topic(topic_path=<path>)` (параметр **topic_path**, не `path`). Несколько: `get_1c_help_topics_bulk(paths=[...])`.
3. **Нужны объекты конфигурации:** `get_1c_context_bundle(query[, config_version])`.
4. **Явные стандарты/сниппеты:** `search_1c_memory(query, domains="standards,snippets")`.
5. **Проверка индекса:** `get_1c_help_index_status`.
6. **Проверка кода:** `document_diagnostics(uri)` → цикл до отсутствия ERROR/WARNING.
7. **Рефакторинг:** `project_analysis` → `symbol_explore`; координаты из project_analysis (Recommended hover coordinate), 0-based.
8. **После рабочего кода:** `save_1c_snippet(code_snippet, description, title)`.
9. **Ловушки 1С:** промпт `get_1c_common_pitfalls()`.

## Подводные камни (из отчёта)

- **Пустые/нерелевантные ответы 1c-help:** проверить `get_1c_help_index_status`; перейти на `search_1c_help_keyword` с точным именем API (`Тип.Метод`).
- **get_1c_help_topic:** параметр только **topic_path**, не `path`. Путь в формате индекса (с версией и .html).
- **compare_1c_help:** путь можно передать из поиска «как есть» или без версии; сервер подставляет version_left/version_right. Короткий запрос (напр. "CryptoManager") разрешается через keyword-поиск (приоритет) и семантику; результаты с заголовком «Untitled» по возможности отбираются в пользу топиков с осмысленным заголовком. Для максимальной предсказуемости по-прежнему лучше передавать точный path из search_1c_help_keyword.
- **get_form_metadata:** передавать полный XML формы с xmlns; усечённый без namespace даёт ошибку разбора.
- **symbol_explore:** без `file_context` надёжнее; с `file_context="ObjectModule"` может быть «file not found».
- **call_graph / call_hierarchy / definition / hover:** зависят от точной позиции на символе (0-based line, character); подставлять координаты из `project_analysis`.
- **URI (единый формат):** Docker — `file:///projects/<путь>`; кириллица в путях — URL-encoding в URI. Локально — полный file URI.
- **Навигация:** основной способ — `project_analysis` → `symbol_explore` или `get_range_content`; definition/hover/call_graph часто пусты — опциональны.

**Чек-лист перед коммитом/ревью:** правило 1c-mcp-workflow: справка использована? document_diagnostics без ERROR/WARNING? save_1c_snippet после нового кода?

## Лимиты 1c-help

- query / xml_content: до 64 KB (MAX_QUERY_CHARS).
- Контент топика в get_1c_code_answer: MCP_MAX_TOPIC_CHARS (по умолчанию 4000); переопределить параметром `max_chars_per_topic` (0 = env-дефолт). Полный топик — через `get_1c_help_topic(topic_path)`.
- get_1c_help_topics_bulk: до 10 путей за вызов; max_chars_per_topic настраивается.
- Сниппет в результатах поиска: MCP_SNIPPET_MAX_CHARS (1200).
- Результаты поиска включают entity_type (method/property/type) и breadcrumb (последние 2 уровня иерархии справки) для лучшего понимания контекста.

## Ссылки

- **В этом репозитории (1c_hbk_helper):** шпаргалка [mcp-tools-cheatsheet.md](../../mcp-tools-cheatsheet.md), отчёт [mcp-1c-help-tools-report.md](../../mcp-1c-help-tools-report.md), [mcp-tools-reference.md](../../mcp-tools-reference.md), [AGENTS.md](../../AGENTS.md).
- **Вне этого репозитория:** те же руководства можно получить через MCP 1c-help — промпт **get_mcp_guides_bundle** (если сервер запущен с MCP_CURSOR_DOCS_PATH).
