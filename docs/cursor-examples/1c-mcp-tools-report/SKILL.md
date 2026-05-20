---
name: 1c-mcp-tools-report
description: Выжимка по роли MCP onec-context-mcp и проверке BSL через Language Server (CLI/IDE). Применять при вопросах «какой tool когда» и настройке workflow.
---

# Отчёт по инструментам MCP (выжимка)

Основано на [docs/archive/mcp-1c-help-tools-report.md](../../archive/mcp-1c-help-tools-report.md). Полный отчёт — таблицы по инструментам onec-context-mcp и исторический контекст BSL LS, лимиты и подводные камни.

## Полнота знаний: когда чего хватает

| Задача | onec-context-mcp | BSL LS (CLI/IDE) | Комментарий |
|--------|---------|------------------|-------------|
| Понять проект (тип модуля, форма) | Да | — | `get_module_info`, `get_form_metadata` |
| Разработка / дописывание (API, примеры) | Да | — | `get_1c_api_answer`, `get_1c_api_object`, `answer_1c_help_question`, `search_1c_api` (примеры — `include_examples=True`), `search_1c_snippets` |
| Поддержка (рефакторинг, стандарты) | Частично | Да | onec-context-mcp — справка; анализ и стиль — BSL LS |
| Тестирование (проверка кода) | Нет | Да | `analyze` / IDE; YaxUnit/Vanessa — вручную |
| Сравнение версий платформы | Да | — | `compare_1c_help` |
| Сохранение переиспользуемого кода | Да | — | `save_1c_snippet` |

**Вывод:** `onec-context-mcp` — MCP справки этого репозитория. BSL LS — отдельно (см. `bsl-language-server-local`, `docs/reference/bsl-ls-mcp-setup.md`).

## Иерархия выбора инструментов

| Задача | Инструмент |
|--------|-----------|
| Старт AI-сессии | **`get_1c_quick_guide`** |
| Точный API / идентификатор | `get_1c_api_answer("Тип.Метод")` |
| Общий API-вопрос / широкий structured lookup | `answer_1c_help_question(...)` или `search_1c_api(...)` |
| Нужны объекты конфигурации тоже | `search_1c_metadata_exact` / `search_1c_metadata_semantic` → `get_1c_metadata_object` |
| Только имя функции/метода | `get_1c_api_answer("Тип.Метод")` или `detail="full"` |
| Только стандарты/сниппеты | `search_1c_standards` / `search_1c_snippets` |
| Проверка .bsl | BSL LS `analyze` или диагностики IDE |
| Навигация по коду | Поиск (rg), символы IDE, чтение файлов |

## Порядок вызовов (кратко)

1. **Старт задачи (AI):** `get_1c_quick_guide(task="develop"|"refactor"|"test")`.
2. **Точный API:** `get_1c_api_answer("Тип.Метод")`.
3. **Общий API-вопрос:** `answer_1c_help_question(query)` или `search_1c_api(query)`.
4. **Стандарты/сниппеты:** `search_1c_standards(query)` / `search_1c_snippets(query)`.
5. **Метаданные:** `search_1c_metadata_exact` / `search_1c_metadata_semantic` / `search_1c_metadata_fields` → `get_1c_metadata_object`.
6. **Проверка .bsl:** BSL LS `analyze` (или IDE) → цикл до приемлемого уровня замечаний.
7. **Навигация:** rg/IDE/чтение модулей по путям выгрузки.
8. **После рабочего кода:** `save_1c_snippet` только для действительно переиспользуемого результата.

## Подводные камни (из отчёта)

- **Пустые/нерелевантные ответы onec-context-mcp:** проверить `get_1c_help_index_status`; перейти на `get_1c_api_answer` с точным именем API (`Тип.Метод`) или `search_1c_api`.
- **compare_1c_help:** специализированный low-level tool поверх внутреннего topic index; не использовать как основной runtime route.
- **get_form_metadata:** передавать полный XML формы с xmlns; усечённый без namespace даёт ошибку разбора.
- **Пути:** для `get_module_info` — путь к `.bsl` в workspace; при `file://` с кириллицей — URL-encoding.
- **Навигация:** поиск по репозиторию и IDE надёжнее, чем позиционные LSP-вызовы из сторонних MCP.

**Чек-лист перед коммитом/ревью:** правило 1c-mcp-workflow: справка использована? BSL LS без критичных замечаний? `save_1c_snippet` только для проверенного кода?

## Лимиты onec-context-mcp

- query / xml_content: до 64 KB (MAX_QUERY_CHARS).
- Сниппет в результатах поиска: MCP_SNIPPET_MAX_CHARS (1200).
- Результаты поиска включают entity_type (method/property/type) и breadcrumb (последние 2 уровня иерархии справки) для лучшего понимания контекста.

## Ссылки

- **В этом репозитории (onec-context-mcp):** шпаргалка [mcp-tools-cheatsheet.md](../../reference/mcp-tools-cheatsheet.md), отчёт [mcp-1c-help-tools-report.md](../../archive/mcp-1c-help-tools-report.md), [mcp-tools-reference.md](../../reference/mcp-tools-reference.md), [AGENTS.md](../../../AGENTS.md).
- **Вне этого репозитория:** те же руководства можно получить через MCP onec-context-mcp — промпт **get_mcp_guides_bundle** (если сервер запущен с MCP_CURSOR_DOCS_PATH).
