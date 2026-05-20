# Metadata Export

Читайте этот файл, если нужно выгрузить и проиндексировать метаданные конфигурации 1С рекомендуемым способом.

Основной артефакт для метаданных 1С в этом репозитории:

- [tools/1c/MetadataExport.epf](../../tools/1c/MetadataExport.epf)

Primary route — **эта обработка** (KD2 XML). Старую выгрузку конфигурации «в файлы»
не используйте как источник для этого runtime: crawler штатной file-dump выгрузки удалён,
а `metadata-graph-build` принимает только KD2 XML или compact snapshot.

## Рекомендуемый маршрут

1. Открыть в 1С обработку `tools/1c/MetadataExport.epf`.
2. Выгрузить XML метаданных конфигурации в `data/metadata_export/<Имя>.xml`.
3. Основной рабочий каталог один: **`data/metadata_export`** (KD2 XML и производные файлы внутри него).
   `watchdog` и `metadata-graph-build` умеют автоматически обновлять snapshot в этой же папке,
   но snapshot хранится **по конфигурациям отдельно** (подкаталог `snapshots/`).
4. При необходимости можно явно построить snapshot:

```bash
PYTHONPATH=src python3 -m onec_help metadata-snapshot-build data/metadata_export/<Имя>.xml -o data/metadata_export
```

5. Построить граф метаданных:

```bash
PYTHONPATH=src python3 -m onec_help metadata-graph-build data/metadata_export
```

Или напрямую из XML:

```bash
PYTHONPATH=src python3 -m onec_help metadata-graph-build data/metadata_export/<Имя>.xml --source-format metadata-xml
```

### Переименование с прежнего `data/kd2`

Раньше каталог по умолчанию назывался `data/kd2`. Переименуйте его в **`data/metadata_export`** или задайте **`ONEC_CONFIG_SOURCE_DIR`** на старый путь.

## Что лежит в `data/metadata_export`

- входной артефакт: `*.xml` из `MetadataExport.epf`
- производные snapshot-файлы по конфигурациям:
  - `snapshots/<config-key>/manifest.json` (поле `format`: `onec_kd2_snapshot_v2`; в `objects.jsonl`/`fields.jsonl` поле `id`/`object_id` — канон **`EnglishType.ИмяОбъекта`**)
  - `snapshots/<config-key>/objects.jsonl`
  - `snapshots/<config-key>/fields.jsonl`

Именно эти per-config snapshot'ы используются для стабильной downstream-индексации,
но их больше не нужно складывать или обновлять вручную.

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

## Константы (MetadataExport 2.1.9+)

Исходники обработки: `.nosync/MetadataExportEpf` (см. [bsl-language-server-local skill](../cursor-examples/bsl-language-server-local/SKILL.md) для проверки BSL).

- Раньше все константы шли только как `CatalogObject.Свойства` с владельцем «примитив» `НаборКонстант` — в `objects.jsonl` не появлялось строк `object_type: Constant`.
- С версии **2.1.9** для каждой константы дополнительно пишется **`CatalogObject.Объекты`** с **`Тип=Константа`**, `Description`/`Имя` как в метаданных (`Константа.<Имя>`), плюс реквизит **`ТипЗначения`** с типом из `КонстантаМД.Тип`.
- Синтетический узел **`НаборКонстант`** в XML сохраняется (типизация примитива), но строки констант под ним **больше не дублируются** — источником для индекса служат объекты **`Constant.<Имя>`**.

После обновления обработки пересоберите XML → `metadata-snapshot-build` → `metadata-graph-build`.
