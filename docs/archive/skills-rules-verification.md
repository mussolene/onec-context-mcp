# Верификация скиллов и правил (workflow агента)

Проверка того, что при типичных задачах по коду 1С (в т.ч. из проекта в .nosync) агент следует рекомендуемому порядку вызовов и правилам из skill 1c-mcp-development и rules (1c-mcp-workflow, 1c-project-conventions).

## Сценарии для проверки

### Сценарий 1: Написание кода по справке (криптография / библиотека из .nosync)

- **Задача:** «Напиши пример подписания данных через интерфейс из нашей библиотеки» или «как подписать данные в 1С».
- **Ожидаемый workflow (по [SKILL.md](../cursor-examples/1c-mcp-development/SKILL.md)):**
  1. Вызов `get_1c_code_answer(query)` для примеров.
  2. При скудном/нерелевантном результате — `search_1c_help_keyword("МенеджерКриптографии")` или точное имя API, затем `get_1c_help_topic(topic_path)`.
  3. Реализация или адаптация кода.
  4. Вызов `document_diagnostics(uri)` (BSL LS).
  5. При ERROR/WARNING — исправить и повторить diagnostics до чистоты.
  6. При переиспользуемом коде — вызов `save_1c_snippet(code_snippet, description, title)`.
- **Фиксировать:** какие инструменты вызывались, в каком порядке; соответствие матрице выбора инструментов из SKILL.

### Сценарий 2: Рефакторинг метода в .nosync

- **Задача:** рефакторинг метода в проекте библиотеки криптографии (переименование, вынос в общий модуль и т.п.).
- **Ожидаемый workflow:**
  1. Сначала `call_graph` и/или `project_analysis` для понимания влияния.
  2. `document_diagnostics(uri)` для базового состояния.
  3. Правка по одному файлу.
  4. После каждой правки — `document_diagnostics(uri)`.
  5. При ERROR — исправить и повторить.
  6. После batch правок — `did_change_watched_files`.
- **Фиксировать:** вызов call_graph/project_analysis до правок; вызов did_change_watched_files после batch.

### Сценарий 3: Точное имя API (get_1c_function_info)

- **Задача:** «описание метода КриптоГраф.Подписать» или «синтаксис МенеджерКриптографии.Подписать».
- **Ожидание:** при нескольких совпадениях — использование `get_1c_function_info(name=..., choose_index=N)` или `search_1c_help_keyword` + `get_1c_help_topic`; параметр `topic_path`, не `path`.

## Шаблон отчёта по прогону

| Сценарий | Ожидаемый workflow | Фактические вызовы (порядок) | Соответствует | Что скорректировать |
|----------|-------------------|------------------------------|---------------|---------------------|
| 1. Подписание данных | get_1c_code_answer → при нерелевантности search_1c_help_keyword → get_1c_help_topic → код → document_diagnostics → save_1c_snippet | | да/нет | |
| 2. Рефакторинг | call_graph/project_analysis → правки → document_diagnostics по файлу → did_change_watched_files | | да/нет | |
| 3. Точное API | search_1c_help_keyword или get_1c_function_info, get_1c_help_topic(topic_path) | | да/нет | |

## Где обновлять при расхождениях

- **Skill:** [docs/cursor-examples/1c-mcp-development/SKILL.md](../cursor-examples/1c-mcp-development/SKILL.md) — матрица выбора инструментов, циклы, типичные промахи.
- **Rules:** [docs/cursor-examples/rules/1c-mcp-workflow.mdc](../cursor-examples/rules/1c-mcp-workflow.mdc), [1c-project-conventions.mdc](../cursor-examples/rules/1c-project-conventions.mdc).
- После изменений в MCP или workflow обновлять также [AGENTS.md](../../AGENTS.md) и [docs/cursor-examples/README.md](../cursor-examples/README.md) при необходимости.
