# Metadata Export

Читайте этот файл, если нужно выгрузить и проиндексировать метаданные конфигурации 1С рекомендуемым способом.

Основной артефакт для метаданных 1С в этом репозитории:

- [tools/1c/MetadataExport.epf](/Users/maxon/git/me/1c_hbk_helper/tools/1c/MetadataExport.epf)

Использовать нужно **эту обработку**, а не выгрузку конфигурации в файлы (`data/config`).

## Рекомендуемый маршрут

1. Открыть в 1С обработку `tools/1c/MetadataExport.epf`.
2. Выгрузить XML метаданных конфигурации в `data/kd2/<Имя>.xml`.
3. Основной рабочий каталог теперь один: `data/kd2`.
   `watchdog` и `metadata-graph-build` умеют автоматически обновлять snapshot в этой же папке.
4. При необходимости можно явно построить snapshot:

```bash
python -m onec_help kd2-snapshot-build data/kd2/<Имя>.xml -o data/kd2
```

5. Построить граф метаданных:

```bash
python -m onec_help metadata-graph-build data/kd2
```

Или напрямую из XML:

```bash
python -m onec_help metadata-graph-build data/kd2/<Имя>.xml --source-format kd2-xml
```

## Что считается deprecated

Deprecated fallback:

- `data/config`
- `ONEC_CONFIG_SOURCE_DIR=<dir with Configuration.xml/Documents/...>`
- route через `config_crawler`

Этот путь оставлен только для редких случаев, когда нужен full-fidelity source по формам, модулям или UI-слою.

## Что лежит в `data/kd2`

- входной артефакт: `*.xml` из `MetadataExport.epf`
- производные snapshot-файлы:
  - `manifest.json`
  - `objects.jsonl`
  - `fields.jsonl`

Именно `objects.jsonl` и `fields.jsonl` используются для стабильной downstream-индексации,
но их больше не нужно складывать в отдельную папку вручную.

## Что должно быть в XML

Минимально ожидаемые поля:

- `CatalogObject.Конфигурации`
  - `Имя`
  - `Версия`
  - `РежимСовместимости`
  - `МинимальнаяВерсияПлатформы`
  - `ВерсияПлатформыРазработки`
- `CatalogObject.Свойства`
  - `Имя`
  - `Синоним`
  - `OwnerType`
  - `ParentType`
  - `Вид`
  - `ТипыСтрокой`
  - `ТипПредставление`
  - `Типы`

Шумные квалификаторы (`КвалификаторыЧисла_*`, `КвалификаторыСтроки_*`, `КвалификаторыДаты_*`) в XML не нужны.
