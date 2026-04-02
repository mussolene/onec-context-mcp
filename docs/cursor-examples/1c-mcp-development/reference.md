# Справка: разработка 1С с MCP

## Соответствие URI (хост ↔ контейнер)

Когда bsl-bridge в Docker с `.:/projects`:

| Путь на хосте | URI в контейнере (для document_diagnostics) |
|---------------|---------------------------------------------|
| `./src/.../Module.bsl` | `file:///projects/src/.../Module.bsl` |
| `./DataProcessors/X/Module.bsl` | `file:///projects/DataProcessors/X/Module.bsl` |

Правило: хост `./` → `/projects`; добавлять префикс `file://`.

## Пример вызова document_diagnostics

```
document_diagnostics(
  uri="file:///projects/src/DataProcessors/.../Forms/.../Ext/Form/Module.bsl"
)
```

## Пример вызова get_1c_help_topic

```
get_1c_help_topic(topic_path="Format971.md")
```

Параметр **не** `path` — только `topic_path`.

## Пример вызова search_1c_help_keyword

```
search_1c_help_keyword(query="ФайловыеОперации.НачатьУдалениеФайлов")
```

Использовать полные квалифицированные имена типов и методов.

## Запросы про формы (реквизит, элемент, обработчик)

При запросе вида «добавить реквизит на форму и отобразить программно» семантика часто даёт нерелевантные топики. Сразу вызывать keyword-поиск:

- **Управляемая форма (сервер):** `search_1c_help_keyword(query="ВсеЭлементыФормы.Добавить")`, раздел «Данные формы» — реквизиты и элементы.
- **Толстый клиент:** `search_1c_help_keyword(query="ЭлементыФормы.Добавить")` → Controls.Add.
- По результатам взять `path` и вызвать `get_1c_help_topic(topic_path=...)` для полного текста. Привязка элемента к реквизиту — свойство элемента (ПутьКДанным); обработчик — команда формы или подписка на событие.

## Пример вызова get_form_metadata

Прочитать Form.xml, передать содержимое:

```
# 1. Прочитать файл (напр. .nosync/.../Forms/X/Ext/Form.xml)
# 2. Вызвать с xml_content
get_form_metadata(xml_content="<Form ...>...</Form>")
```

## Пример вызова save_1c_snippet

```
save_1c_snippet(
  code_snippet="...",
  description="Удаление временных файлов через НачатьУдалениеФайлов",
  title="УдалениеФайлов"
)
```

## BSL LS: диагностики без быстрого исправления

Многие диагностики BSL LS (SemicolonPresence, LineLength и др.) не имеют quick-fix в `code_actions`. Исправлять вручную:

- Добавить точку с запятой после `ВызватьИсключение "..."`
- Разбить длинные строки или добавить `// BSLLS:LineLength-off` с кратким обоснованием
- Использовать `#Область` / `#КонецОбласти` для структуры

## Два MCP вместе

- **1c-help**: справка, сниппеты, память
- **lsp-bsl-bridge**: навигация, диагностика, рефакторинг

Если 1c-help недоступен (нет индекса): опираться только на lsp-bsl-bridge и memory.

## Python-тесты (onec_help)

Запуск тестов и проверка покрытия (≥70%):

```bash
pip install -e ".[dev]"
PYTHONPATH=src python -m pytest tests -v --cov=src/onec_help --cov-report=term-missing --cov-fail-under=70
```

Линтинг:

```bash
ruff check src tests && ruff format src tests
```

## Инструменты тестирования 1С/BSL

Подробно: `docs/reference/1c-testing-guide.md` в репозитории.

- **BSL LS** (`document_diagnostics`): статический анализ — ошибки, предупреждения, стиль. Вызывать после каждой правки; это не runtime-тесты.
- **YaxUnit** (или xUnitFor1C): unit-тесты процедур/функций 1С. **Где искать:** `Tests/`, подсистемы тестов, модули `*Тест*`. Запуск через 1С:Предприятие, EDT или CLI.
- **Vanessa-Automation** (xdd, UI): BDD (Gherkin `.feature`), data-driven (xdd), UI-автоматизация, приёмочные тесты. **Где искать:** `features/`, `BDD/`, каталоги с `.feature` и шагами.
- **CoverageBSL**: измерение покрытия кода BSL в 1С:Предприятие и OneScript.

При добавлении новой логики 1С — предлагать unit-тесты (YaxUnit) для модулей или BDD/сценарии (Vanessa) для приёмки. Если в проекте есть `Tests/` или `features/` — считать тесты частью workflow.
