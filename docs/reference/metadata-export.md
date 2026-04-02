# Metadata Export

Читайте этот файл, если нужно выгрузить и проиндексировать метаданные конфигурации 1С рекомендуемым способом.

Основной артефакт для метаданных 1С в этом репозитории:

- [tools/1c/MetadataExport.epf](/Users/maxon/git/me/1c_hbk_helper/tools/1c/MetadataExport.epf)

Использовать нужно **эту обработку**, а не выгрузку конфигурации в файлы (`data/config`).

## Рекомендуемый маршрут

1. Открыть в 1С обработку `tools/1c/MetadataExport.epf`.
2. Выгрузить XML метаданных конфигурации, например в `data/kd2/<Имя>.xml`.
3. Построить compact snapshot:

```bash
python -m onec_help kd2-snapshot-build data/kd2/<Имя>.xml -o data/kd2_snapshot
```

4. Построить граф метаданных:

```bash
python -m onec_help metadata-graph-build data/kd2_snapshot --source-format kd2-snapshot
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
