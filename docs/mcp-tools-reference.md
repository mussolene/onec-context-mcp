# Справочник MCP-инструментов 1c-help

Единая ссылка на все инструменты MCP-сервера 1c-help: параметры, лимиты, рекомендуемый порядок вызовов.

## Рекомендуемый порядок вызовов

1. **Ответ с кодом** — `get_1c_code_answer` (при необходимости `code_only=True`).
2. **При нерелевантных результатах** — вызвать `search_1c_help_keyword` с точным именем API (например `Тип.Метод`), затем `get_1c_help_topic(topic_path)` по `path` из результата.
3. **Недостаток деталей по топику** — `get_1c_help_topic(topic_path)` (параметр **topic_path**, не `path`).
4. **Точные имена API** — `search_1c_help_keyword` с полным именем (в т.ч. `Тип.Метод`).
5. **Несколько совпадений в get_1c_function_info** — указывать `choose_index` (1-based).
6. **После генерации рабочего кода** — `save_1c_snippet` для сохранения полезных примеров (улучшает `get_1c_code_answer` в следующих сессиях).

---

## Поиск и чтение

| Инструмент | Параметры | Описание | Лимиты / примечания |
|------------|-----------|----------|---------------------|
| **search_1c_help** | `query`, `limit=8`, `version`, `language`, `include_user_memory=False` | Семантический поиск по справке. Для кода предпочтительнее `get_1c_code_answer`; для точных имён API — `search_1c_help_keyword`. | query до 64 KB (MAX_QUERY_CHARS). При нерелевантности — попробовать `search_1c_help_keyword` с точным именем. |
| **search_1c_help_keyword** | `query`, `limit=10`, `version`, `language` | Поиск по подстроке/BM25 в заголовке и тексте. Идеален для точных имён: `ПроцессорВыводаРезультатаКомпоновкиДанныхВКоллекциюЗначений`, `Тип.Метод`. | query до 64 KB. Для методов передавать полное имя (напр. `HTTPСоединение.Получить`). |
| **search_1c_help_with_content** | `query`, `limit=3`, `version`, `language` | Гибридный поиск + полный контент топ-результатов в одном вызове. | limit — число топиков с полным контентом; контент обрезается до MCP_MAX_TOPIC_CHARS (по умолчанию 4000). При нерелевантности — `search_1c_help_keyword` с точным API. |
| **get_1c_code_answer** | `query`, `limit=3`, `include_memory=True`, `code_only=False`, `version`, `language` | Готовый ответ с кодом: семантика + keyword + контент топиков + память. Основной инструмент для примеров и API. | Контент топиков до MCP_MAX_TOPIC_CHARS (4000). При нерелевантности — вызвать `search_1c_help_keyword` с точным именем API, затем `get_1c_help_topic`. Если результат использован как финальный код — вызвать `save_1c_snippet`. |
| **get_1c_help_topic** | `topic_path`, `version`, `language`, `prefer_index=False` | Полный контент топика по пути (Markdown). Путь брать из результатов поиска (напр. `zif3_CryptoManager.md`). | **Параметр только topic_path** (не `path`). `prefer_index=True` — читать только из индекса. |
| **get_1c_function_info** | `name`, `path=None`, `choose_index=None` | Описание, синтаксис, параметры функции/метода 1С. | `path` — точный путь топика (если известен). При нескольких совпадениях — `choose_index=1,2,...` (1-based). Имена методов — полные `Тип.Метод`. |
| **get_1c_help_related** | `topic_path`, `version`, `language` | Список связанных топиков (исходящие ссылки). | Для части тем может быть пусто (outgoing_links не всегда заполняются при парсинге). |
| **list_1c_help_titles** | `limit=100`, `path_prefix=""` | Список заголовков и путей для обзора. | path_prefix — фильтр по началу пути (напр. `zif`). |

---

## Сохранение и метаданные

| Инструмент | Параметры | Описание | Лимиты / примечания |
|------------|-----------|----------|---------------------|
| **save_1c_snippet** | `code_snippet`, `description=""`, `title=""`, `write_to_files=None` | Сохранить фрагмент кода 1С в память пользователя. | code_snippet до 64 KB. `write_to_files`: при `None` используется SAVE_SNIPPET_TO_FILES из env; при True — также запись в SNIPPETS_DIR. |
| **get_form_metadata** | `xml_content` | Разбор Form.xml: атрибуты и команды. | xml_content до 64 KB. Нужен полный XML с xmlns (v8, cfg, xs и т.д.). |
| **get_module_info** | `uri_or_path` | Тип модуля и контекст по пути к Module.bsl / ObjectModule.bsl. | Возвращает FormModule, ObjectModule и т.д., имя формы/объекта при возможности. |

---

## Сравнение и статус

| Инструмент | Параметры | Описание | Лимиты / примечания |
|------------|-----------|----------|---------------------|
| **compare_1c_help** | `topic_path_or_query`, `version_left`, `version_right`, `language`, `include_diff=False` | Сравнение топика между двумя версиями платформы. | Предпочтительно передавать **topic_path** из поиска; по query семантика может вернуть другой топик в разных версиях. |
| **trigger_reindex** | — | Запуск полной переиндексации (ingest) в фоне. | Проверять прогресс через `get_1c_help_index_status`. |
| **get_1c_help_index_status** | — | Статус индекса (число топиков, коллекция, версии, языки) и прогресс ingest. | При запущенном ingest: текущий файл, ETA, скорость, ошибки. |

---

## Переменные окружения (лимиты вывода)

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| MCP_MAX_TOPIC_CHARS | Макс. символов контента топика в get_1c_code_answer / search_1c_help_with_content | 4000 |
| MCP_SNIPPET_MAX_CHARS | Макс. символов сниппета в результатах поиска (списки) | 1200 |
| SAVE_SNIPPET_TO_FILES | При save_1c_snippet: писать также в SNIPPETS_DIR (1/true/yes) | выкл |

---

## См. также

- [AGENTS.md](../AGENTS.md) — порядок вызовов, два MCP (1c-help + lsp-bsl-bridge), workflow.
- [docs/cursor-examples/](cursor-examples/README.md) — Skill и Rules для Cursor.
- [docs/mcp-analysis.md](mcp-analysis.md) — анализ использования и типовые просадки.
- [docs/quality-and-pitfalls-analysis.md](quality-and-pitfalls-analysis.md) — влияние индексации, обрезка эмбеддингов, как получать готовый код и типичные подводные камни.
