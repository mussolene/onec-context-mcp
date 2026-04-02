# Как Это Работает

Читайте этот файл, если нужно быстро понять устройство проекта без погружения в полный reference.

## Поток данных

Основной pipeline выглядит так:

```text
.hbk -> unpack -> html -> markdown -> embeddings -> Qdrant -> MCP
```

Что это означает на практике:

1. Проект находит `.hbk` в `HELP_SOURCE_BASE`.
2. `ingest` распаковывает архивы и собирает структуру в `data/unpacked`.
3. HTML справки конвертируется в Markdown.
4. Для текстов строятся embeddings.
5. Документы и memory points попадают в Qdrant.
6. MCP-сервер читает эти индексы и отдает tools для поиска, чтения топиков, snippets, standards и metadata.

## Роли сервисов

- `mcp` - API-слой для клиентов и IDE
- `ingest-worker` - batch/write операции: ingest, watchdog, load-snippets, load-standards
- `qdrant` - хранилище индексов
- `redis` - cache и состояние ingest/watchdog

В split-режиме чтение и запись разведены: `mcp` читает, `ingest-worker` пишет. Это основной рекомендованный режим.

## Split и Full

Есть два режима deployment:

- `split` - основной вариант; `mcp` и `ingest-worker` разделены
- `full` - один контейнер делает и API, и фоновые задачи

Выбирайте `split`, если нужен обычный рабочий сценарий и понятное разделение ответственности. `full` полезен в локальной разработке и маленьких установках.

Технические детали и compose-сценарии: [../reference/architecture.md](../reference/architecture.md).

## Что индексируется

В проекте есть несколько логических слоев данных:

- help - основная справка 1С
- memory - snippets, standards, session-related memory
- metadata - граф метаданных конфигурации 1С

Для метаданных рекомендуемый route: `MetadataExport.epf -> KD 2.0 XML export -> kd2-snapshot-build -> metadata-graph-build`.

Подробно: [../reference/metadata-export.md](../reference/metadata-export.md).

## Где лежат данные

По умолчанию проект использует каталог `data/`:

- `data/unpacked` - распакованная справка
- `data/qdrant` - данные Qdrant
- `data/redis` - Redis state
- `data/snippets` и `data/standards` - входные данные для memory

Если нужны operational details, recovery и расширенные команды, переходите в [../reference/run.md](../reference/run.md).
