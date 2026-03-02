# Архитектура 1C Help MCP

## Сервисы и ответственность

| Сервис | Роль | Ресурсы | Порт |
|--------|------|---------|------|
| **qdrant** | Векторная БД (onec_help, onec_help_memory) | Хранилище | 6333 |
| **mcp** | MCP API — поиск, чтение топиков, get_1c_code_answer | I/O, embedding для memory | 8050 |
| **ingest-worker** | Batch ETL: ingest, cron, load-snippets, watchdog | CPU, RAM, embedding API | — |
| **serve** | Веб-просмотр справки (Flask), профиль `serve` | I/O | 8000 |
| **bsl-bridge** | BSL LS MCP — диагностика, рефакторинг (отдельно: `make bsl-start`) | Java/BSL LS | — |

## Коллекции Qdrant

- **onec_help** — основной индекс справки 1С (пишет ingest/indexer)
- **onec_help_memory** — snippets, standards, session events (пишут memory, load-snippets, load-standards)

Подробнее об embedding, batch-пайплайне, retry и переменных — см. [docs/embedding.md](embedding.md).

## Режимы развёртывания

### Split (по умолчанию)

`mcp` только MCP API (`MCP_MODE=api`), `ingest-worker` — все write-операции. Рекомендуется для большинства сценариев.

```mermaid
flowchart LR
    subgraph split [Split mode]
        mcpApi[mcp]
        ingestWorker[ingest-worker]
        qdrant[qdrant]
    end
    mcpApi -->|read| qdrant
    ingestWorker -->|write| qdrant
```

Запуск:
```bash
docker compose up -d
# или: make up
```

С веб-просмотром (профиль `serve`):
```bash
docker compose --profile serve up -d
```

Индексация: `make ingest` или `docker compose exec ingest-worker python -m onec_help ingest`.

### Full (один контейнер)

Один контейнер `mcp` выполняет MCP API, ingest при старте, cron, load-snippets и watchdog. `MCP_MODE=full`. Подходит для локальной разработки или малой нагрузки.

```mermaid
flowchart LR
    subgraph full [Full mode]
        mcp[mcp]
        qdrant[qdrant]
    end
    mcp -->|read/write| qdrant
```

Запуск:
```bash
docker compose -f docker-compose.full.yml up -d
# или: make up-full
```

Индексация: `make ingest-full` или `docker compose -f docker-compose.full.yml exec mcp python -m onec_help ingest`.

## Будущие улучшения (при росте)

- **Очередь задач:** замена cron на Celery/RQ + Redis или API webhook для ingest — масштабирование и retry при сбоях.

## Когда использовать full (один контейнер)

- Локальная разработка
- Один пользователь, малая нагрузка
- Минимизация ресурсов (меньше контейнеров)

## Переменная MCP_MODE

- **`api`** (split, по умолчанию) — только основной процесс (MCP), без фоновых jobs
- **`full`** — entrypoint запускает ingest, cron, watchdog, load-snippets в фоне

## Пересборка и обновление при изменениях

### Split (по умолчанию)

Сборка отдельно от запуска (принцип единственной ответственности):

```bash
# Сборка образов
make build
# или один сервис: make build SERVICE=mcp

# Запуск (после сборки)
make up
```

### Full

```bash
make build-full
make up-full
```

### Типовой workflow при изменениях

| Что меняли | Команда (split) | Команда (full) |
|------------|-----------------|----------------|
| Код Python (onec_help) | `make build && make up` | `make build-full && make up-full` |
| Только MCP API | `make build SERVICE=mcp && make up` | `make build-full && make up-full` |
| Только ingest/cron | `make build SERVICE=ingest-worker && make up` | `make build-full && make up-full` |
| Dockerfile, requirements | `make build && make up` | `make build-full && make up-full` |
| Только env/volumes в compose | `make up` | `make up-full` |

Изменение env или volumes не требует пересборки — Compose пересоздаёт только затронутые контейнеры.
