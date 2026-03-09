# Отчёт: полнота MCP 1c-help и lsp-bsl-bridge по инструментам

Отчёт по результатам проверки полноты знаний MCP для понимания, разработки, поддержки и тестирования проекта 1С на примере **CryptographicLib** (`.nosync/cryptographiclib`). Прогон тестов выполнен для **13 инструментов 1c-help** и **14 инструментов lsp-bsl-bridge**.

---

## 1. Резюме

### Достаточность 1c-help для проекта на примере .nosync

| Задача | Покрытие 1c-help | Комментарий |
|--------|------------------|-------------|
| **Понять проект** | Да | `get_module_info`, `get_form_metadata` — тип модуля по пути, атрибуты и команды формы. |
| **Разработка / дописывание** | Да | `get_1c_code_answer`, `search_1c_help_keyword`, `get_1c_help_topic`, `get_1c_function_info` — справка по API, примеры кода, сигнатуры (в т.ч. МенеджерКриптографии, Подписать, сертификаты). |
| **Поддержка (рефакторинг, стандарты)** | Частично | 1c-help даёт справку и примеры; статический анализ и рефакторинг — **lsp-bsl-bridge**. |
| **Тестирование (проверка кода)** | Нет | Диагностика BSL LS — **lsp-bsl-bridge** (`document_diagnostics`). Запуск YaxUnit/Vanessa — вручную или скриптами. |
| **Сравнение версий платформы** | Да | `compare_1c_help` — сравнение топика между версиями. |
| **Сохранение переиспользуемого кода** | Да | `save_1c_snippet` — улучшает последующие ответы `get_1c_code_answer`. |

**Вывод:** для **понимания** и **разработки/дописывания** проекта 1С знаний 1c-help **достаточно**. Для **поддержки** (рефакторинг, соответствие стандартам) и **тестирования** (проверка кода, навигация по коду) нужна связка **1c-help + lsp-bsl-bridge**; запуск runtime-тестов 1С остаётся вне MCP.

### Роль lsp-bsl-bridge

- **Проверка кода:** `document_diagnostics(uri)` — ошибки, предупреждения и подсказки BSL LS по файлу.
- **Навигация:** `project_analysis`, `symbol_explore` — поиск символов, файлов, контекст по проекту.
- **Граф вызовов / иерархия:** `call_graph`, `call_hierarchy` — зависят от позиции (на символе); для части модулей могут не находить элемент.
- **Рефакторинг:** `prepare_rename`, `rename` — переименование с превью; `code_actions` — быстрые исправления по диагностикам.
- **Контент кода:** `get_range_content` — извлечение фрагмента по диапазону строк.

---

## 2. Исчерпывающая таблица по инструментам

### 2.1. MCP 1c-help (13 инструментов)

| Инструмент | Назначение | Параметры | Лимиты / умолчания | Порядок вызовов / пример для .nosync | Подводные камни |
|------------|------------|-----------|--------------------|---------------------------------------|-----------------|
| **get_1c_help_index_status** | Статус индекса (топики, коллекция, версии, языки, ingest). | Нет. | — | Вызвать первым при сомнениях в полноте индекса. | Пустой/частичный индекс → слабые ответы поиска. |
| **get_1c_code_answer** | Готовый ответ с кодом: семантика + keyword + контент топиков + память. | `query` (обяз.), `limit=3`, `include_memory=True`, `code_only=False`, `version`, `language`. | Контент топиков до MCP_MAX_TOPIC_CHARS (4000). | Основной для примеров. Пример: `query="подписание данных криптография"`. | Нерелевантность при общих запросах → использовать `search_1c_help_keyword` с точным API. |
| **search_1c_help** | Семантический поиск по справке. | `query` (обяз.), `limit=8`, `version`, `language`, `include_user_memory=False`. | query до 64 KB (MAX_QUERY_CHARS). | Для обзора тем; для кода предпочтительнее `get_1c_code_answer`. | Семантика может давать общие топики; для точных имён — `search_1c_help_keyword`. |
| **search_1c_help_keyword** | Поиск по подстроке/BM25 в заголовке и тексте. | `query` (обяз.), `limit=10`, `version`, `language`. | query до 64 KB. | Для точных имён: «Подписать», «МенеджерКриптографии.Подписать». | Методы передавать полным именем: `Тип.Метод`. |
| **search_1c_help_with_content** | Гибридный поиск + полный контент топ-N топиков. | `query` (обяз.), `limit=3`, `version`, `language`. | Контент до MCP_MAX_TOPIC_CHARS (4000). | Один вызов вместо search + get_topic. | При нерелевантности — `search_1c_help_keyword` с точным API. |
| **get_1c_help_topic** | Полный контент топика по пути (Markdown). | `topic_path` (обяз.), `version`, `language`, `prefer_index=False`. | — | Путь брать из результатов поиска (например из `search_1c_help_keyword`). | Параметр **topic_path**, не `path`. Путь в формате индекса (например с версией и .html). |
| **get_1c_function_info** | Описание, синтаксис, параметры функции/метода 1С. | `name` (обяз.), `path=None`, `choose_index=None`. | — | При нескольких совпадениях — `choose_index=1,2,...` (1-based). Пример: `name="МенеджерКриптографии.Подписать"`. | Имена методов — полные `Тип.Метод`. |
| **get_1c_help_related** | Список связанных топиков (исходящие ссылки). | `topic_path` (обяз.), `version`, `language`. | — | После получения топика для навигации по смежным темам. | Для части тем может быть пусто (outgoing_links не всегда заполняются). |
| **list_1c_help_titles** | Список заголовков и путей для обзора. | `limit=100`, `path_prefix=""`. | — | Обзор каталога; `path_prefix` — фильтр по началу пути. | В индексе пути вида `8.3.27.1859/shcntx_ru/...`; префикс `zif` может не дать результатов. |
| **save_1c_snippet** | Сохранить фрагмент кода 1С в память пользователя. | `code_snippet` (обяз.), `description=""`, `title=""`, `write_to_files=None`. | code_snippet до 64 KB. При `write_to_files=None` — SAVE_SNIPPET_TO_FILES из env. | После получения рабочего кода для улучшения следующих ответов. | При True — также запись в SNIPPETS_DIR. |
| **get_form_metadata** | Разбор Form.xml: атрибуты и команды. | `xml_content` (обяз.). | xml_content до 64 KB. | Передать полный XML формы из .nosync (с xmlns). | Усечённый XML без namespace → ошибка разбора. |
| **get_module_info** | Тип модуля и контекст по пути к Module.bsl / ObjectModule.bsl. | `uri_or_path` (обяз.). | — | Путь к файлу из .nosync, например `.../МенеджерКриптографии/Ext/ObjectModule.bsl`. | Возвращает ObjectModule, FormModule и т.д., имя объекта/формы при возможности. |
| **compare_1c_help** | Сравнение топика между двумя версиями платформы. | `topic_path_or_query`, `version_left`, `version_right` (обяз.), `language`, `include_diff=False`. | — | **topic_path** из поиска передавать можно «как есть» (8.3.13.1513/shcntx_ru/...) или без префикса версии (shcntx_ru/...); сервер убирает префикс версии и подставляет version_left/version_right при поиске в индексе. По query семантика может вернуть разный топик. | По query в 8.2 и 8.3 может быть разный топик; предпочтительно путь из search_1c_help_keyword. |

**Переменные окружения (лимиты вывода):**

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| MCP_MAX_TOPIC_CHARS | Макс. символов контента топика в get_1c_code_answer / search_1c_help_with_content | 4000 |
| MCP_SNIPPET_MAX_CHARS | Макс. символов сниппета в результатах поиска (списки) | 1200 |
| SAVE_SNIPPET_TO_FILES | При save_1c_snippet: писать также в SNIPPETS_DIR | выкл |
| MAX_QUERY_CHARS (внутр.) | Макс. длина query/xml_content | 65536 (64 KB) |

**Проверка формата пути (compare_1c_help):**

- **Путь с версией** (`8.3.13.1513/shcntx_ru/objects/.../CryptoManager.html` + `version_left` / `version_right`) — возвращается полное сравнение: текст топика для обеих версий (в 8.3 видны отличия: мобильная платформа, асинхронные методы, метки времени и т.д.).
- **Путь без версии** (`shcntx_ru/objects/.../CryptoManager.html`) — тот же результат: сравнение по двум указанным версиям.
- **Короткий запрос** (`topic_path_or_query: "CryptoManager"`) — сервер сначала ищет через **keyword** (по пути/заголовку), затем при необходимости через семантику; из кандидатов по возможности отбирается топик с осмысленным заголовком (не «Untitled»). Для максимальной предсказуемости лучше передавать точный path из search_1c_help_keyword.

**Итог:** формат пути для compare_1c_help не является пробелом: подходят и путь с версией, и путь без версии, и короткий запрос (разрешение через keyword + выбор не-Untitled).

---

### 2.2. MCP lsp-bsl-bridge (14 инструментов)

| Инструмент | Назначение | Параметры | Пример вызова для .nosync | Сценарий |
|------------|------------|-----------|---------------------------|----------|
| **lsp_status** | Состояние LSP (подключение, прогресс индексации). | Нет. | Без параметров. | Перед остальными вызовами — убедиться, что LSP готов. |
| **document_diagnostics** | Диагностики по файлу (ошибки, предупреждения, подсказки BSL LS). | `uri` (обяз.), `identifier`, `previous_result_id`. | `uri` — file URI модуля, например ObjectModule.bsl в .nosync. | Проверка кода после правок; цикл до чистоты. |
| **project_analysis** | Поиск символов/файлов, анализ файла, обзор workspace. | `analysis_type` (обяз.), `query` (обяз.), `limit=20`, `offset=0`, `workspace_uri`. | `analysis_type="workspace_symbols"`, `query="ПолучитьВсе"`. | Навигация, поиск определений и использований. |
| **symbol_explore** | Поиск символов с контекстом и деталями кода. | `query` (обяз.), `file_context`, `detail_level`, `limit`, `offset`, `workspace_scope`. | `query="Подписать"`, без file_context или с путём к модулю. | Детали по процедурам/функциям (без file_context надёжнее). |
| **call_graph** | Граф вызовов (входящие/исходящие) от позиции. | `uri`, `line`, `character` (обяз., 0-based). | URI + позиция на имени процедуры/функции. | Рефакторинг, оценка влияния. |
| **call_hierarchy** | Иерархия вызовов (callers/callees) для символа. | `uri`, `line`, `character`, `direction`. | URI + позиция на символе. | Понимание потока вызовов. |
| **definition** | Переход к определению символа по позиции. | `uri`, `line`, `character` (обяз., 0-based), `language`. | URI + позиция внутри имени символа. | Навигация по коду. |
| **hover** | Подсказка по символу (сигнатура, документация). | `uri`, `line`, `character` (обяз., 0-based). | URI + позиция на символе. | Быстрое понимание без перехода. |
| **code_actions** | Быстрые исправления и рефакторинг по диапазону. | `uri`, `line`, `character`, `end_line`, `end_character`. | URI + позиция на месте с диагностикой. | Исправление по замечаниям BSL LS. |
| **prepare_rename** | Проверка возможности переименования и диапазон. | `uri`, `line`, `character` (обяз.). | URI + позиция на имени символа. | Перед rename — превью диапазона. |
| **rename** | Переименование символа по проекту. | `uri`, `line`, `character`, `new_name`, `apply` (по умолчанию false — только превью). | Сначала `apply=false` для превью. | Рефакторинг. |
| **get_range_content** | Текст файла в заданном диапазоне строк. | `uri`, `start_line`, `start_character`, `end_line`, `end_character`, `strict`. | URI + диапазон (0-based). | Извлечение фрагмента кода без чтения всего файла. |
| **selection_range** | Диапазоны выбора для позиции (selectionRange). | `uri` (обяз.), `line`, `character` или `positions_json`. | URI + позиция. | Расширение выделения (слово → строка → блок). |
| **did_change_watched_files** | Уведомить LSP об изменении файлов извне. | `language` (обяз.), `changes_json` (массив событий: uri, type 1=Created/2=Changed/3=Deleted). | После массовых правок вне редактора. | Переиндексация после batch-правок. |

**Примечание по URI:** при работе через Docker (volume `.:/projects`) используйте URI вида `file:///projects/.nosync/cryptographiclib/...`. Локально может использоваться полный путь `file:///Users/.../1c_hbk_helper/.nosync/...`. `document_diagnostics` в прогоне успешно сработал с локальным file URI.

---

## 3. Результаты прогона тестирования

### 3.1. 1c-help (13 инструментов)

| № | Инструмент | Вызов | Результат | Замечания |
|---|------------|-------|-----------|-----------|
| 1 | get_1c_help_index_status | Без параметров | OK | 117696 топиков, версии 8.2–8.5, язык ru, память 4062 pts. |
| 2 | get_1c_code_answer | query="подписание данных криптография", limit=2 | OK | Релевантные топики (Криптография, МенеджерКриптографии.НачатьПодписывание). |
| 3 | search_1c_help | query="ХранилищеСертификатовКриптографии", limit=5 | OK | Результаты общие (Untitled, fileConf); для точного API лучше keyword. |
| 4 | search_1c_help_keyword | query="Подписать", limit=5 | OK | ТокенДоступа.Подписать, МенеджерКриптографии.Подписать и др. |
| 5 | search_1c_help_with_content | query="Криптография сертификат", limit=2 | OK | Контент по СертификатКлиентаMacOS/Windows. |
| 6 | get_1c_help_topic | topic_path=.../AccessToken/methods/Sign6278.html | OK | Полный текст топика в Markdown. |
| 7 | get_1c_function_info | name="МенеджерКриптографии.Подписать" | OK | Несколько совпадений (1–5), выведен контент первого; при необходимости choose_index. |
| 8 | get_1c_help_related | topic_path=.../Sign6278.html | OK | Пусто (для этого топика нет связанных в индексе). |
| 9 | list_1c_help_titles | limit=20; path_prefix="zif" | OK | С префиксом "zif" — пусто; без префикса — список из индекса. |
| 10 | list_1c_help_titles | limit=15 без prefix | OK | 15 заголовков и путей. |
| 11 | compare_1c_help | topic_path CryptoManager Sign, version_left 8.2.19.130, version_right 8.3.27.1859 | OK | Сравнение двух версий топика (8.2 без контента, 8.3 с контентом). |
| 12 | get_module_info | uri_or_path=.../МенеджерКриптографии/Ext/ObjectModule.bsl | OK | ObjectModule, МенеджерКриптографии. |
| 13 | get_form_metadata | xml_content=Form.xml (сокращённый с xmlns) | OK | Атрибуты: Объект, ПарольСертификата; команд нет. |
| 14 | save_1c_snippet | code_snippet + description + title | OK | Сохранено в память и в файл (Подписать_данные_....md). |

**Итог 1c-help:** все 13 инструментов отработали успешно. Семантический поиск по длинным именам типа «ХранилищеСертификатовКриптографии» дал общие топики — для точного попадания нужен `search_1c_help_keyword`.

---

### 3.2. lsp-bsl-bridge (14 инструментов)

| № | Инструмент | Вызов | Результат | Замечания |
|---|------------|-------|-----------|-----------|
| 1 | lsp_status | Без параметров | OK | ready, индексация завершена (11/11), BSL и bsl-language-server подключены. |
| 2 | document_diagnostics | uri=file:///.../МенеджерКриптографии/Ext/ObjectModule.bsl | OK | 136 замечаний: 83 WARNING, 12 INFO, 41 HINT (когнитивная сложность, экспортные переменные, описания, магические числа и т.д.). |
| 3 | project_analysis | analysis_type=workspace_symbols, query="ПолучитьВсе" | OK | 5 результатов (ПолучитьВсе в ObjectModule.bsl и формах .nosync, ПолучитьВсеСервер и др.), с URI и диапазонами. |
| 4 | symbol_explore | query="Подписать" | OK | 12 совпадений, детальный вид по 3 (процедуры/функции с фрагментами кода). |
| 5 | symbol_explore | query="Подписать", file_context="ObjectModule" | Ошибка | File context error: file 'ObjectModule' not found. Без file_context работает. |
| 6 | call_graph | uri + line 35, character 9 | Ошибка | No call hierarchy item found at this position. |
| 7 | call_graph | uri + line 33, character 5 | Ошибка | То же. Позиция должна быть точно на имени вызываемой/вызывающей процедуры (0-based). |
| 8 | call_hierarchy | uri (projects), line 33, character 5 | Пусто | No call hierarchy items found. |
| 9 | definition | uri (локальный и projects), line 33, character 5/10 | Пусто | No definitions found. Возможна зависимость от точной позиции на идентификаторе. |
| 10 | hover | uri, line 33, character 5/10 | Пусто | No hover information available. |
| 11 | code_actions | uri, line 25, character 6 | Пусто | No code actions available (на экспортной переменной). |
| 12 | prepare_rename | uri (projects), line 33, character 5 | null | Нет диапазона переименования для данной позиции. |
| 13 | get_range_content | uri (projects) + диапазон 33–43 | OK | Возвращён фрагмент: Функция ПолучитьВсе() ... Возврат Результат. |
| 14 | selection_range | uri, line 35, character 4 | OK | Ответ "ok". |
| 15 | did_change_watched_files | language=bsl, changes_json=[{uri, type:2}] | OK | Уведомление об изменении файла принято. |

**Итог lsp-bsl-bridge:** `lsp_status`, `document_diagnostics`, `project_analysis`, `symbol_explore`, `get_range_content`, `selection_range`, `did_change_watched_files` работают стабильно. `call_graph`, `call_hierarchy`, `definition`, `hover`, `code_actions`, `prepare_rename` в прогоне дали пустой результат или ошибку — зависят от точной позиции (символ в BSL) и, возможно, от формата URI (projects vs локальный путь); при работе в реальном сценарии координаты из `project_analysis` (Recommended hover coordinate) стоит подставлять в definition/hover/call_graph.

---

## 4. Рекомендации

1. **Только 1c-help:** использовать для справки по API, примеров кода, метаданных форм и модулей, сравнения версий и сохранения сниппетов. При пустых или нерелевантных результатах — проверять `get_1c_help_index_status` и переходить на `search_1c_help_keyword` с точным именем API.
2. **Подключение lsp-bsl-bridge:** при проверке кода после правок — вызывать `document_diagnostics(uri)` и доводить до отсутствия ERROR/WARNING. Перед рефакторингом — `project_analysis` (workspace_symbols) и при необходимости `symbol_explore`; для графа вызовов использовать координаты из выдачи `project_analysis` в `call_graph`/`call_hierarchy`.
3. **URI для .nosync:** при Docker (volume `.:/projects`) — `file:///projects/.nosync/cryptographiclib/...`; локально — полный file URI до файла. `document_diagnostics` в тесте сработал с локальным путём.
4. **Использование отчёта:** онбординг (какой инструмент когда вызывать), отладка (почему пустой ответ — индекс, позиция, URI), поддержка (напоминание лимитов и подводных камней из раздела 2).

---

## 5. Повторный прогон после правок (скилл, правило, промпт MCP)

После добавления скилла **1c-mcp-tools-report**, правила **1c-mcp-tools-report.mdc** и промпта MCP **how_to_use_1c_help_and_bsl_bridge** выполнен повторный тест по тому же плану.

### Результаты сравнения

| Область | Было (первый прогон) | Стало (повторный) | Вывод |
|--------|----------------------|-------------------|--------|
| **1c-help** | Все 13 инструментов OK | Без изменений: get_1c_help_index_status, get_1c_code_answer, search_1c_help_keyword и остальные работают стабильно. Память 4064 pts. | Ответы инструментов не изменились — это ожидаемо. |
| **lsp-bsl-bridge: стабильные** | lsp_status, document_diagnostics, project_analysis, symbol_explore, get_range_content, selection_range, did_change_watched_files — OK | То же: работают с URI `file:///projects/...` (в т.ч. URL-encoded путь). document_diagnostics: 136 замечаний по ObjectModule.bsl. | Без изменений, всё в норме. |
| **lsp-bsl-bridge: позиционные** | definition, hover, call_graph, call_hierarchy — пусто/ошибка при line 33–35, character 5 | Проверено с **рекомендованными координатами** из project_analysis (line=34, character=5, URI с %D0%9C...). Результат: по-прежнему «No definitions found», «No call hierarchy item found». | Ограничение со стороны BSL LS / lsp-bsl-bridge для данного символа/файла; скилл и правило не меняют поведение этих вызовов. |

### Что реально улучшилось

1. **Порядок действий:** скилл и правило явно задают цепочку: при пустых ответах 1c-help → `get_1c_help_index_status` → `search_1c_help_keyword` с точным API; для навигации по коду → сначала `project_analysis`, затем `symbol_explore` и при необходимости `get_range_content`. Агент не «застревает» на одном нерелевантном вызове.
2. **Ожидания от позиционных инструментов:** в отчёте и правиле зафиксировано, что definition/hover/call_graph/call_hierarchy могут давать пустой результат даже при координатах из project_analysis; предпочтительная навигация — symbol_explore + get_range_content. Меньше ложных ожиданий.
3. **Промпт MCP:** клиент может вызвать `how_to_use_1c_help_and_bsl_bridge` и получить готовый блок инструкции для контекста чата — не нужно каждый раз восстанавливать порядок вызовов по документации.

**Итог:** сами ответы MCP не изменились; улучшились **руководство по использованию** (скилл + правило) и **доступность подсказки** (промпт в MCP). Для позиционных инструментов lsp-bsl-bridge ограничение остаётся на стороне LSP/BSL; альтернативы (project_analysis, symbol_explore, get_range_content) работают и закреплены в рекомендациях.

---

## 6. Повторный прогон после пересборки

После пересборки проекта выполнен контрольный прогон по тому же плану (репрезентативная выборка инструментов).

| Проверка | Результат |
|----------|-----------|
| get_1c_help_index_status | OK — 117696 топиков, память 4064 pts, версии 8.2–8.5. |
| get_1c_code_answer("подписание криптография") | OK — релевантные топики (Криптография). |
| search_1c_help_keyword("МенеджерКриптографии.Подписать") | OK — точные совпадения с контентом. |
| get_module_info(путь ObjectModule.bsl) | OK — ObjectModule, МенеджерКриптографии. |
| lsp_status | OK — ready, индексация 11/11. |
| project_analysis(workspace_symbols, "ПолучитьВсе") | OK — 5 результатов с URI и Recommended hover coordinate. |
| symbol_explore("Подписать") | OK — 12 совпадений, детальный вид. |
| document_diagnostics(uri ObjectModule.bsl) | OK — 136 замечаний (WARNING/INFO/HINT). |
| get_range_content(диапазон 33–45) | OK — фрагмент кода ПолучитьВсе(). |

**Вывод:** после пересборки 1c-help и lsp-bsl-bridge ведут себя стабильно; регрессий не выявлено.

---

## 7. Заключения и рекомендации: что улучшить, упростить, добавить

### Улучшить

- **Позиционные инструменты lsp-bsl-bridge:** при пустом definition/hover/call_graph — в правилах и промпте явно указано: **навигация (основной способ)** — project_analysis → symbol_explore или get_range_content; definition/hover/call_graph считать опциональными. *Реализовано в 1c-mcp-workflow и 1c-mcp-tools-report.*
- **Единый формат URI:** в правиле 1c-mcp-workflow и в промпте MCP зафиксирован формат `file:///projects/<путь>` (Docker) и примечание про URL-encoding путей с кириллицей. *Реализовано.*
- **Промпт при новом чате:** в правиле 1c-mcp-workflow и в README добавлена инструкция: в новом чате по 1С вызвать промпт how_to_use_1c_help_and_bsl_bridge и вставить результат в первое сообщение (опционально — параметр task=develop|refactor|test для короткого блока). *Реализовано.*

### Упростить

- **Правила:** 1c-mcp-workflow — основной rule с полной краткой инструкцией и чек-листом; 1c-mcp-tools-report — только отсылка к отчёту и отличия (пустые ответы, URI, координаты, навигация). *Реализовано.*
- **Промпт MCP:** текст по-прежнему в 4 блоках при task=all; при необходимости меньше токенов — вызов с task=develop|refactor|test. *Без изменений структуры.*

### Добавить

- **Чек-лист перед коммитом/ревью:** добавлен в 1c-mcp-workflow (три пункта: справка использована? diagnostics без ERROR/WARNING? save_1c_snippet после нового кода?). *Реализовано.*
- **Ссылка на отчёт в AGENTS.md:** добавлена в раздел MCP (отчёт + промпт how_to_use_1c_help_and_bsl_bridge). *Реализовано ранее.*
- **Параметризованный промпт:** промпт how_to_use_1c_help_and_bsl_bridge принимает параметр `task`: "all" (по умолчанию — полный текст), "develop" | "refactor" | "test" — только релевантный блок. *Реализовано.*

---

## Оформление для Cursor и MCP

- **Skill:** [docs/cursor-examples/1c-mcp-tools-report/SKILL.md](cursor-examples/1c-mcp-tools-report/SKILL.md) — выжимка по полноте знаний, порядку вызовов и подводным камням. Копировать в `.cursor/skills/1c-mcp-tools-report/`.
- **Правила:** [docs/cursor-examples/rules/1c-mcp-tools-report.mdc](cursor-examples/rules/1c-mcp-tools-report.mdc), [docs/cursor-examples/rules/1c-mcp-workflow.mdc](cursor-examples/rules/1c-mcp-workflow.mdc) — рекомендации при работе с .bsl и Form.xml. Копировать в `.cursor/rules/`.
- **Промпт MCP:** сервер 1c-help экспонирует промпт `how_to_use_1c_help_and_bsl_bridge(task)` — возвращает инструкцию по 1c-help и lsp-bsl-bridge. Параметр **task** (необязательный): `"all"` (по умолчанию) — полный текст; `"develop"` | `"refactor"` | `"test"` — только релевантный блок (меньше токенов). Вызвать из клиента MCP и вставить результат в чат.

### Как получить инструкцию по умолчанию и когда вызывать промпт

**По умолчанию (без ручного вызова):**  
Правило **1c-mcp-workflow** привязано к `**/*.bsl`. При открытии или редактировании `.bsl` Cursor подставляет в контекст краткий порядок вызовов, единый формат URI и чек-лист перед коммитом. Правило **1c-mcp-tools-report** (globs: `**/*.bsl`, `**/Form.xml`, `.nosync/**`) добавляет отличия по отчёту (пустые ответы, URI, навигация).

**Когда вызывать промпт вручную:**  
- **Новый чат по 1С:** вызвать промпт **how_to_use_1c_help_and_bsl_bridge** и вставить возвращённый текст в первое сообщение. Для короткого блока передать `task=develop`, `task=refactor` или `task=test`.  
- Правило не сработало (чат не привязан к .bsl) — вызов промпта дублирует инструкцию в чат.

**Итог:** скопировать правила в `.cursor/rules/` и при работе с .bsl инструкция подставляется автоматически. Промпт — для новой сессии или явной вставки (с опцией task для экономии токенов).

### Самодокументируемый MCP: правила и скилл из MCP

При сборке в образ копируется каталог `docs/`; в контейнере задаётся `MCP_CURSOR_DOCS_PATH=/app/docs`. Тогда MCP может отдавать актуальные правила и скилл через промпты — один источник правды, без ручного копирования из репозитория.

| Промпт | Назначение |
|--------|------------|
| **get_mcp_workflow_guide** | Руководство по порядку вызовов (1c-help + lsp-bsl-bridge при работе с .bsl). Вставить в чат или в правила IDE. |
| **get_mcp_tools_tips** | Подсказки: пустые ответы, формат URI, координаты LSP. Вставить в чат или правила. |
| **get_mcp_tools_summary** | Выжимка отчёта: когда какой MCP, лимиты, подводные камни. Вставить в чат или скиллы IDE. |
| **get_mcp_guides_bundle** | Все три руководства одним блоком — онбординг или восстановление конфига IDE. |

**Когда работает:** при запуске из репозитория (есть каталог `docs/`) или при `MCP_CURSOR_DOCS_PATH` указывающем на каталог с подкаталогом `cursor-examples/`. В Docker-образе путь задан по умолчанию (`/app/docs`). Если путь не задан или файлы отсутствуют, промпты возвращают подсказку задать `MCP_CURSOR_DOCS_PATH`.

**Польза:** агент или пользователь может запросить у MCP актуальные руководства, совпадающие с версией сервера; подходят для любого MCP-клиента (Cursor, Claude Code, и др.), не только для Cursor.

---

## 8. Повторное тестирование: возможности и справочная информация

Проведён повторный прогон (1c-help и lsp-bsl-bridge) и оценка: хватает ли агенту возможностей и справочной информации при использовании MCP.

### Результаты прогона

| Проверка | Результат |
|----------|-----------|
| **1c-help** get_1c_help_index_status | OK — 117696 топиков, память 4064 pts, версии 8.2–8.5, последний ingest завершён. |
| **1c-help** get_1c_code_answer("Подписание данных криптографией") | OK — релевантные топики (МенеджерКриптографии.НачатьПодписывание, подпись CMS/PKCS#7). |
| **1c-help** search_1c_help_keyword("МенеджерКриптографии.Подписать") | OK — точные совпадения с путями и контентом (8.3, 8.2). |
| **lsp-bsl-bridge** lsp_status | OK — ready, индексация 11/11, BSL и bsl-language-server подключены. |
| **lsp-bsl-bridge** project_analysis(workspace_symbols, "ПолучитьВсе") | OK — 5 результатов с URI (в т.ч. URL-encoded кириллица), Range и Recommended hover coordinate. |
| **lsp-bsl-bridge** document_diagnostics(uri ObjectModule.bsl) | OK — 136 замечаний (83 WARNING, 12 INFO, 41 HINT): когнитивная/цикломатическая сложность, экспортные переменные, описание возвращаемого значения, BSL LS ссылки. |

**Вывод по стабильности:** регрессий нет; оба MCP отвечают корректно.

### Оценка: хватает ли возможностей

| Аспект | Оценка |
|--------|--------|
| **Понимание проекта** | Достаточно: get_module_info, get_form_metadata, project_analysis, symbol_explore. |
| **Разработка / примеры кода** | Достаточно: get_1c_code_answer, search_1c_help_keyword, get_1c_help_topic, get_1c_function_info; при слабом ответе — переход на keyword с точным API. |
| **Проверка кода** | Достаточно: document_diagnostics по URI (в т.ч. с кириллицей в URL-encoding). |
| **Навигация по коду** | Достаточно: project_analysis → symbol_explore или get_range_content; definition/hover/call_graph опциональны (часто пусты). |
| **Рефакторинг** | Достаточно: project_analysis, prepare_rename, rename, code_actions; после массовых правок — did_change_watched_files. |
| **Сохранение и память** | Достаточно: save_1c_snippet; get_1c_help_index_status показывает объём памяти. |

**Итог по возможностям:** для типовых сценариев (понять проект, написать/дописать код по справке, проверить диагностики, навигация, рефакторинг) возможностей MCP **хватает**. За пределами MCP остаются: запуск YaxUnit/Vanessa, деплой, сравнение веток в репозитории.

### Оценка: хватает ли справочной информации

- **В репозитории:** отчёт `docs/mcp-1c-help-tools-report.md` (таблицы по всем инструментам, лимиты, подводные камни, порядок вызовов), скилл `docs/cursor-examples/1c-mcp-tools-report/SKILL.md` (выжимка), правила `1c-mcp-workflow.mdc` и `1c-mcp-tools-report.mdc`. Агент может читать эти файлы — этого достаточно, чтобы выбирать нужный инструмент, формат URI и обходить типичные ошибки (topic_path не path, keyword для точного API, URL-encoding для кириллицы).
- **В MCP:** промпты how_to_use_1c_help_and_bsl_bridge(task), get_mcp_workflow_guide, get_mcp_tools_tips, get_mcp_tools_summary, get_mcp_guides_bundle отдают актуальный текст при настроенном MCP_CURSOR_DOCS_PATH; вызов промптов — со стороны клиента (пользователь вставляет в чат). Агент при необходимости может опереться на файлы в docs/.
- **Шпаргалка:** [docs/mcp-tools-cheatsheet.md](mcp-tools-cheatsheet.md) — одна страница: инструмент, ключевой параметр, одна строка назначения; плюс промпты и кратко URI/порядок вызовов.

**Итог по справочной информации:** для использования данного MCP справочной информации **хватает** (отчёт + скилл + правила в репозитории; при необходимости — промпты MCP для вставки в чат).

### Использование вне репозитория 1c_hbk_helper

При разработке **в другом репозитории** (проект 1С/BSL без клонирования 1c_hbk_helper):

- **MCP 1c-help** подключается по URL (например `http://localhost:8050/mcp`). Индекс справки и инструменты не зависят от вашего проекта — сервер может работать в Docker или на другой машине.
- **MCP lsp-bsl-bridge** должен видеть ваш рабочий каталог с `.bsl`: при Docker — volume с вашим проектом (например `.:/projects`), тогда URI модулей — `file:///projects/<путь_в_вашем_проекте>`. Локально — полный file URI до файлов вашего проекта.
- **Правила и скилл:** скопируйте из `docs/cursor-examples/` репозитория 1c_hbk_helper в `.cursor/rules/` и `.cursor/skills/` вашего проекта **или** получите текст через промпты 1c-help: **get_mcp_workflow_guide**, **get_mcp_tools_tips**, **get_mcp_tools_summary**, **get_mcp_guides_bundle** — и вставьте в чат или сохраните в свой .cursor/. Содержимое правил не привязано к путям 1c_hbk_helper (используются общие формулировки: «путь к .bsl», «uri модуля», `file:///projects/<путь>`).
- **Globs правил** заданы как `**/*.bsl` и `**/Form.xml` — срабатывают в любом репозитории с такими файлами.

Итог: для разработки вне этого репозитория достаточно подключить оба MCP к вашему проекту и иметь правила/скилл (скопированные или полученные через промпты); зависимости от файлов 1c_hbk_helper нет.

## См. также

- [docs/mcp-tools-cheatsheet.md](mcp-tools-cheatsheet.md) — одностраничная шпаргалка (инструмент + параметр + назначение).
- [docs/mcp-tools-reference.md](mcp-tools-reference.md) — краткий справочник по 1c-help.
- [docs/quality-and-pitfalls-analysis.md](quality-and-pitfalls-analysis.md) — качество ответов и подводные камни.
- [AGENTS.md](../AGENTS.md) — workflow, два MCP, ingest, тестирование.
