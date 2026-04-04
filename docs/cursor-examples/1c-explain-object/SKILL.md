---
name: 1c-explain-object
description: Авто-документирование объектов конфигурации 1С. Применять при вопросах «как работает X», «где заполняется реквизит Y», «что делает кнопка Z», «объясни логику объекта», «как устроен документ/справочник». Требует оба MCP: 1c-help + lsp-bsl-bridge.
---

# Авто-документирование объекта/поля/кнопки 1С

## Когда применять

- «Как заполняется реквизит Валюта в Реализации?»
- «Что происходит при нажатии кнопки Провести?»
- «Как устроен документ ЗаказПокупателя?»
- «Где проверяется остаток при записи?»
- «Что изменилось в обработке X между версиями 2.0 и 2.1?»

## Полный workflow

### Шаг 1 — Структура объекта (1c-help)

```
get_1c_metadata_object(object_id="Document.Sales")
```

Даёт: тип объекта, реквизиты с типами, табличные части, full_name.
При поиске объекта сначала: `search_1c_metadata_exact(query, config_version?)`; если точное имя неизвестно — `search_1c_metadata_semantic(query, config_version?)`.

### Шаг 2 — Структура формы (1c-help)

```
get_form_metadata(xml_content=<содержимое Form.xml>)
```

Даёт: элементы формы → `DataPath` (привязка к реквизиту) → события (`onChange`, `onClick`) → имена обработчиков BSL.

Путь к форме обычно: `Documents/<Объект>/Forms/<ИмяФормы>/Ext/Form/Form.xml`

### Шаг 3 — Найти символ в коде (lsp-bsl-bridge)

```
project_analysis(analysis_type="workspace_symbols", query="ИмяРеквизита")
```

Даёт: файл, строку, тип символа. Из ответа взять «Recommended hover coordinate» (0-based) для следующих шагов.

### Шаг 4 — Все места использования (lsp-bsl-bridge)

```
project_analysis(analysis_type="references", query="ИмяРеквизита")
```

Даёт: полный список файлов и строк, где реквизит читается или пишется (присвоения, условия, передача в вызовы).

### Шаг 5 — Граф вызовов из обработчика (lsp-bsl-bridge)

```
call_graph(uri="file:///projects/...", line=<0-based>, character=<0-based>)
```

Координаты — из шага 3. Даёт: дерево вызовов «что этот обработчик вызывает» и кто вызывает его (`call_hierarchy`).

Дополнительно для impact-анализа:

```
project_analysis(analysis_type="symbol_relationships", query="ИмяОбработчика")
```

### Шаг 6 — Платформенный контекст (1c-help)

```
get_1c_api_answer(name="<Тип.Метод>")
// или
answer_1c_help_question(question="<платформенный вопрос>") или search_1c_api(query="<API или широкий вопрос>")
// или
search_1c_standards(query="<правило>")
search_1c_snippets(query="<пример кода>")
```

Даёт: точный API, полный topic, стандарты и примеры кода без смешивания всего в одном ответе.

---

## Структура ответа агента

```
**Что это**
<тип, синоним, тип данных> из get_1c_metadata_object

**Где заполняется**
- В форме: элемент <X>, обработчик <Y> (из get_form_metadata)
- В коде: <файл>:<строка> — присвоение (из references)

**Как изменяется**
- При изменении поля: <обработчик> → вызывает <список> (из call_graph)
- Подписки: <модуль>.<процедура> (из workspace_symbols/references)

**Где проверяется**
- ПриЗаписи / ПередЗаписью: <файл>:<строка> (из references + call_graph)

**Как исправить / где изменить**
- <файл>, процедура <имя>, строка <N> (из get_range_content для кода)
```

---

## Сравнение версий конфигурации

**Платформенный API изменился:**
```
compare_1c_help(topic="имя топика или path", version_left="8.3.22", version_right="8.3.25")
```

**Код конфигурации изменился между версиями:**
```bash
git diff v1.0..v2.0 -- path/to/Documents/Sales/Ext/ObjectModule.bsl
```

Если конфигурации двух версий в разных каталогах — два контейнера lsp-bridge с разными `HOST_PROJECTS_ROOT`.

---

## Пример: «Как заполняется реквизит Валюта в Реализации?»

```
1. get_1c_metadata_object("Document.Sales")
   → реквизит Валюта, тип СправочникСсылка.Валюты

2. get_form_metadata(xml_content=Form.xml)
   → элемент Валюта, DataPath="Валюта", onChange="ВалютаПриИзменении"

3. project_analysis("workspace_symbols", "ВалютаПриИзменении")
   → Documents/Sales/Forms/FormDoc/Ext/Form/Module.bsl, line 47

4. project_analysis("references", "Валюта")
   → строки 47, 112, 203 — присвоение; строки 88, 150 — чтение

5. call_graph(uri="file:///projects/Documents/Sales/.../Module.bsl", line=46, character=10)
   → ВалютаПриИзменении → ПересчитатьСуммыСтрок → ОбновитьКурс

6. search_1c_standards("валюта документа пересчёт сумм 1С")
   + search_1c_snippets("валюта документа пересчёт сумм 1С")
   → платформенные правила + примеры

Ответ:
  Поле Валюта заполняется вручную пользователем на форме.
  При изменении вызывается ВалютаПриИзменении → пересчитываются суммы строк
  и обновляется курс из регистра сведений КурсыВалют.
  При записи (ПриЗаписи, строка 203) проверяется, что курс на дату задан.
  Исправить: Documents/Sales/Forms/FormDoc/Ext/Form/Module.bsl, процедура ВалютаПриИзменении.
```

---

## Подводные камни

| Ситуация | Решение |
|---|---|
| lsp-bridge не запущен | `docker compose up -d` в `deps/mcp-bsl-lsp-bridge/` |
| container не видит BSL файлов | Проверить `HOST_PROJECTS_ROOT` в `.env` контейнера |
| `workspace_symbols` возвращает пусто | LSP ещё индексирует — вызвать `lsp_status`, подождать |
| Кириллица в пути к файлу | URL-encode: `%D0%94%D0%BE%D0%BA...` в file URI |
| Координаты off-by-one | Координаты в lsp-bridge 0-based; брать «Recommended hover coordinate» из `project_analysis` |
| Form.xml с namespace ошибкой | Передавать полный XML с `xmlns=` — без namespace парсер упадёт |
