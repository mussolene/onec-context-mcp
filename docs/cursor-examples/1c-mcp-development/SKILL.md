---
name: 1c-mcp-development
description: AI-first skill для разработки 1С (BSL): MCP onec-context-mcp + BSL Language Server (CLI analyze/format, IDE или опционально Docker).
---

# Разработка 1С с MCP

## Когда применять

Использовать этот skill при:

- Генерации кода 1С/BSL (процедуры, функции, модули форм)
- Рефакторинге существующего кода 1С
- Запуске внешней диагностики BSL LS
- Поиске в справке 1С по API
- Работе с файлами `.bsl`, `.1c`, `Form.xml`

## Архитектурная граница

- **onec-context-mcp** — наш MCP: справка по платформе, память, метаданные, компактные AI-ориентированные ответы.
- **BSL LS** — отдельно: `java -jar … analyze` / `format`, расширение IDE или `make bsl-start` (см. `docs/reference/bsl-ls-mcp-setup.md`). Не является инструментом MCP onec-context-mcp.
- **Опционально — MCP lsp-bsl-bridge** (внешний сервер): диагностика и навигация по проекту (`document_diagnostics`, `project_analysis`, …) вместо или вместе с CLI; в этот репозиторий не входит.
- Базовый AI workflow начинается с `onec-context-mcp`; проверку `.bsl` делайте BSL LS после правок.

## Tiered toolset

### Tier 1 — основной маршрут

| Сценарий | Источник | Инструмент | Заметки |
|----------|----------|------------|---------|
| Старт задачи | onec-context-mcp | `get_1c_quick_guide` | Единственный канонический AI entry point. |
| Точный API / идентификатор | onec-context-mcp | `get_1c_api_answer` | Exact-first compact ответ для `Тип.Метод`. |
| Structured API object | onec-context-mcp | `get_1c_api_object` | Low-token truth-source из `onec_help_api`. |
| Официальные примеры из справки | onec-context-mcp | `search_1c_api` (`include_examples=True`, по умолчанию) | Те же hits, что раньше давал отдельный tool; не смешивать с `search_1c_snippets`. |
| Естественный вопрос / широкий API lookup | onec-context-mcp | `answer_1c_help_question`, `search_1c_api` | Structured DB-first route вместо topic-layer поиска. |
| Локальный task context | onec-context-mcp | `get_1c_task_context` | Компактный anti-hallucination context по `file_uri` / `symbol_name`. |
| Явные стандарты | onec-context-mcp | `search_1c_standards` | Только standards memory. |
| Явные сниппеты | onec-context-mcp | `search_1c_snippets` | Только code examples / community_help. |
| Объекты конфигурации | onec-context-mcp | `search_1c_metadata_exact`, `search_1c_metadata_semantic`, `search_1c_metadata_fields`, `get_1c_metadata_object` | Exact, semantic и field-level routes. |
| Метаданные формы | onec-context-mcp | `get_form_metadata` | Полный Form.xml. |
| Тип модуля | onec-context-mcp | `get_module_info` | По пути к `.bsl`. |
| Статус индекса | onec-context-mcp | `get_1c_help_index_status` | Проверка полноты/здоровья индекса. |
| Диагностика файла | BSL LS | `java -jar … analyze` | После каждой правки; см. **bsl-language-server-local**. |
| Форматирование | BSL LS | `java -jar … format` | По политике проекта. |
| Навигация | IDE / rg / git | — | Поиск символов и чтение модулей по путям выгрузки. |
| Опционально Docker | этот репозиторий | `make bsl-start` | Отдельный compose, не MCP onec-context-mcp. |

### Tier 2 — ситуативные

| Инструмент | Когда использовать |
|------------|--------------------|
| `compare_1c_help` | Сравнение версии платформы. |
| `get_1c_api_related` | Связанные API-элементы через structured links. |
| `save_1c_snippet` | Только для реально переиспользуемого и проверенного кода. |

### Tier 3 — legacy / expert

- длинные prompt-based guides и bundle outputs

## Архитектурное мышление

Думать как senior-разработчик 1С: понимать влияние правок до их внесения.

- **Перед любым изменением:** начать с `onec-context-mcp` для платформенного контекста; структуру кода смотреть поиском и IDE.
- **Перед рефакторингом:** найти все вхождения символа (rg) и затронутые модули.
- **Модульность:** использовать `#Область ПрограммныйИнтерфейс` и `#Область СлужебныеПроцедурыИФункции`; избегать монолитных процедур.
- **Контекст выполнения:** учитывать клиент/сервер, реквизиты формы, СКД vs запрос, толстый/тонкий клиент.
- **Антипаттерны:** процедуры >100 строк, магические числа, отсутствие явной обработки ошибок.

## Токен-бюджет MCP onec-context-mcp

Подробный чеклист: skill **1c-mcp-token-budget**. Кратко: метаданные или точное `Тип.Метод` → `get_1c_api_answer` (**compact** по умолчанию), затем `search_1c_api`; `answer_1c_help_question` — когда нет имени API; не раздувать параллельные вызовы.

## Циклические workflows

### Написание кода (цикл до чистоты)

1. Вызвать `get_1c_quick_guide(task="develop")` в начале сессии.
2. Если запрос точный: `get_1c_api_answer("Тип.Метод")` по умолчанию **compact**; `detail="full"` — только если не хватает секций; при необходимости truth-source `get_1c_api_object("Тип.Метод")`.
3. Если нужны официальные примеры из справки: `search_1c_api(query, include_examples=True)`.
4. Если есть локальный файл/символ: `get_1c_task_context(query, file_uri, symbol_name)`.
5. Если нужен широкий поиск по API/объектам: `search_1c_api(query)` или `answer_1c_help_question(question)`.
6. Если нужны стандарты явно: `search_1c_standards(query)`. Если нужны curated примеры кода: `search_1c_snippets(query)`.
7. Реализовать или адаптировать код.
8. Запустить BSL LS `analyze` на изменённых путях (или проверить IDE).
9. **При Error/Warning:** исправить → повторить п. 8.
10. `save_1c_snippet` только если код переиспользуемый и уже проверен LS.

### Рефакторинг (цикл по файлам)

1. Найти символы и вхождения (IDE, rg).
2. Baseline `analyze` на затронутых каталогах.
3. Редактировать по одному файлу.
4. После каждой правки — снова `analyze` на изменённых путях.
5. **При Error:** исправить → повторить п. 4.
6. Повторить для следующего файла.

### Тестирование (Python onec_help)

При изменении Python-кода в этом проекте:

1. Редактировать код.
2. Запустить `PYTHONPATH=src python -m pytest tests -v --cov=src/onec_help --cov-report=term-missing --cov-fail-under=70`.
3. **При падении тестов или покрытии < 70%:** исправить → повторить п. 2.
4. Запустить `ruff check src tests && ruff format src tests`.

Подробнее — [reference.md](reference.md): pytest, xUnitFor1C, CoverageBSL.

## Метаданные конфигурации (search_1c_metadata_exact / semantic / fields, get_1c_task_context)

Использовать при работе с объектами конфигурации (Документы, Справочники, Регистры и т.д.): `search_1c_metadata_exact` для object lookup, `search_1c_metadata_semantic` для естественного языка, `search_1c_metadata_fields` для реквизитов/табличных частей/команд, затем `get_1c_metadata_object(object_id)` для truth-source (payload.id вида `Document.ИмяОбъекта`). Требуется `metadata-graph-build` для выгрузки (ONEC_CONFIG_SOURCE_DIR); в `get_1c_help_index_status` отображается коллекция **onec_config_metadata**. Параметр `config_version` опционален — при одной версии в графе подставляется автоматически. При выгрузке «в файлы» в граф попадают синоним (full_name), реквизиты и табличные части из XML объекта. Для компактного AI-контекста: `get_1c_task_context(query[, file_uri][, symbol_name][, config_version])`.

## Запросы: несколько соединений (стандарты v8std)

**Несколько внутренних соединений** в одном запросе по «плоским» таблицам (справочники, документы, таблицы регистров) **допускаются** языком и стандартами. Ограничения v8std касаются не количества соединений, а **что** соединять: не использовать в качестве одной из сторон соединения вложенные запросы и виртуальные таблицы (ст. 655); не использовать вложенные запросы **в условии** соединения (ПО …) — переписывать с временными таблицами (ст. 656). Подробнее: `docs/query-joins-standards.md`.

## Типичные промахи поиска

Structured route (`answer_1c_help_question`, `search_1c_api`) иногда требует уточнения при:

- Описательных запросах («как вывести СКД в таблицу», «синтаксис ОбъединитьПериодов»)
- Именах API, которые в справке называются иначе
- Коротких или общих терминах («таблица», «формат»)

**Действия при нерелевантных результатах:**

1. Вызвать `get_1c_api_answer` с **полным** именем API (`Тип.Метод`).
2. Если точное имя неизвестно — попробовать синонимы (см. ниже).
3. Если нужен широкий подбор кандидатов — вызвать `search_1c_api(query)` с коротким переформулированным запросом.

**Частые синонимы API (в справке может быть другое имя):**

| Интуитивное имя | Имя в справке 1С |
|-----------------|------------------|
| `Запрос.ПакетПолучения` | `Запрос.ВыполнитьПакет` |
| `Формат` (функция) | искать `Format` или `Глобальный контекст`, категория «Формат» |
| Вывод СКД в таблицу | `ПроцессорВыводаРезультатаКомпоновкиДанныхВКоллекциюЗначений` или `...ВТабличныйДокумент` |
| Добавить реквизит/элемент на форму программно | **Управляемая форма:** `ВсеЭлементыФормы.Добавить`, раздел «Данные формы»; **толстый клиент:** `ЭлементыФормы.Добавить` (Controls.Add). Привязка к реквизиту — свойство элемента (ПутьКДанным и т.п.); обработчики — подписка на событие или команда формы. |

Если broad structured route даёт шум, перейти на exact route `get_1c_api_answer` с точным именем API.

## Типичные ошибки

| Ошибка | Исправление |
|--------|-------------|
| `ПрочитатьJSON` возвращает Соответствие | Добавить `ПрочитатьВСоответствие=Истина` |
| `HTTPСоединение.Получить` на клиенте | Только сервер; использовать HTTPЗапрос или RPC |
| Поиск только по `Метод` | Передавать полное `Тип.Метод` в `get_1c_api_answer` |
| Пропуск повторного `analyze` после batch | Прогнать analyze на затронутый каталог |
| Продолжение при неисправленных замечаниях LS | Цикл: исправить → снова analyze до приемлемого уровня |

## Дополнительно

См. [reference.md](reference.md): URI, примеры вызовов, команды тестирования (pytest, YaxUnit, Vanessa, CoverageBSL). См. `docs/reference/1c-testing-guide.md`: что тестировать YaxUnit, что — Vanessa (xdd/UI), где искать тесты. По запросам и соединениям — `docs/query-joins-standards.md`.
