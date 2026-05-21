# Справка: разработка 1С с MCP

## Пути к .bsl

Используйте пути в workspace (относительные или абсолютные). Для BSL LS CLI:

```bash
java -jar "$JAR" analyze -s ./Documents/MyDoc/Ext/ObjectModule.bsl -r console -q
```

Опционально `make bsl-start` монтирует `.:/projects:ro` — пути внутри контейнера `/projects/...`.

## Пример вызова get_1c_api_answer

```
get_1c_api_answer(name="Формат", detail="full")
```

## Пример вызова search_1c_api

```
search_1c_api(query="ФайловыеОперации.НачатьУдалениеФайлов")
```

Для exact route использовать полные квалифицированные имена типов и методов в `get_1c_api_answer`.

## Запросы про формы (реквизит, элемент, обработчик)

При запросе вида «добавить реквизит на форму и отобразить программно» broad structured route лучше стартовать так:

- **Управляемая форма (сервер):** `get_1c_api_answer(name="ВсеЭлементыФормы.Добавить", detail="full")`
- **Толстый клиент:** `get_1c_api_answer(name="ЭлементыФормы.Добавить", detail="full")`
- Если точное имя неизвестно: `search_1c_api(query="добавить элемент формы программно")`. Привязка элемента к реквизиту — свойство элемента (ПутьКДанным); обработчик — команда формы или подписка на событие.

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

## onec-context-mcp и BSL LS

- **onec-context-mcp** (MCP): справка, сниппеты, память, метаданные.
- **BSL LS**: CLI `analyze`/`format`, IDE, опционально Docker в этом репо.

Если индекса справки нет: опираться на BSL LS и локальные файлы проекта.

## Python-тесты (onec_help)

Запуск тестов и проверка покрытия (≥70%):

```bash
pip install -e ".[dev]"
PYTHONPATH=src python3 -m pytest tests -v --cov=src/onec_help --cov-report=term-missing --cov-fail-under=74
```

Линтинг:

```bash
ruff check src tests && ruff format src tests
```

## Инструменты тестирования 1С/BSL

Подробно: `docs/reference/1c-testing-guide.md` в репозитории.

- **BSL LS** (`analyze` / IDE): статический анализ — ошибки, предупреждения, стиль. После правок по BSL; это не runtime-тесты.
- **YaxUnit** (или xUnitFor1C): unit-тесты процедур/функций 1С. **Где искать:** `Tests/`, подсистемы тестов, модули `*Тест*`. Запуск через 1С:Предприятие, EDT или CLI.
- **Vanessa-Automation** (xdd, UI): BDD (Gherkin `.feature`), data-driven (xdd), UI-автоматизация, приёмочные тесты. **Где искать:** `features/`, `BDD/`, каталоги с `.feature` и шагами.
- **CoverageBSL**: измерение покрытия кода BSL в 1С:Предприятие и OneScript.

При добавлении новой логики 1С — предлагать unit-тесты (YaxUnit) для модулей или BDD/сценарии (Vanessa) для приёмки. Если в проекте есть `Tests/` или `features/` — считать тесты частью workflow.
