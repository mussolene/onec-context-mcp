# Mesh Scorecard

`mesh-scorecard` измеряет не extractor, а поведение нового deterministic mesh runtime:

- `resolver-first`
- `Qdrant-only runtime`
- `graph/exact route`
- `metadata deterministic route`
- `workflow-aware task context`

## Запуск

```bash
PYTHONPATH=src python3 -m onec_help mesh-scorecard
PYTHONPATH=src python3 -m onec_help mesh-scorecard --output-file data/help_structured/mesh_scorecard.json
PYTHONPATH=src python3 -m onec_help mesh-scorecard --benchmark-file path/to/custom_mesh_benchmark.json
```

Для Docker-first проверки используйте тот же runtime, что и MCP:

```bash
make up
docker compose -f docker-compose.base.yml -f docker-compose.yml exec mcp python -m onec_help mesh-scorecard --output-file /app/data/help_structured/mesh_scorecard.json
```

Это полный runtime-check, а не мгновенный healthcheck: он строит benchmark-набор, делает Qdrant/embedding calls и может идти несколько минут без промежуточного вывода. Для быстрой проверки живости после `make up` используйте `curl`/`dashboard` из [quick-start.md](../getting-started/quick-start.md); `mesh-scorecard` запускайте как stop-check поведения.

Если эмбеддинги даёт LM Studio на хосте, в `.env` для контейнеров обычно нужны:

```bash
EMBEDDING_API_URL=http://host.docker.internal:1234/v1
EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
EMBEDDING_DIMENSION=768
```

## Что меряет

Scorecard строится по benchmark-сценариям и считает:

- `summary.overall_case_pass_pct` — сколько сценариев прошло целиком
- `summary.route_hit_pct` — совпал ли ожидаемый `route_kind`
- `summary.help_hit_pct` — попал ли правильный help hit в top context
- `summary.metadata_hit_pct` — попал ли правильный metadata object
- `summary.workflow_hit_pct` — появилась ли правильная workflow-цепочка
- `summary.field_hit_pct` — сработал ли deterministic metadata field lookup
- latency:
  - `summary.latency.plan.median_ms`
  - `summary.latency.context.median_ms`

Отдельно прикладываются:

- `mesh_store` — оперативное состояние Qdrant mesh-слоя
- `mcp_metrics` — runtime-метрики MCP из Redis/SQLite
- `cards` — карточки по поведенческим профилям:
  - `exact_api_surface`
  - `metadata_navigation`
  - `workflow_context`

## Когда использовать

`structured-help-scorecard` отвечает на вопрос: “достаточно ли хорошо извлечена structured help”.

`mesh-scorecard` отвечает на вопрос: “насколько хорошо текущий runtime route реально решает задачи агента”.

Для time-to-market это быстрый smoke-test после изменений в resolver/orchestrator/docs: он показывает, что точные API, metadata navigation, workflow context и field lookup не требуют ручного обхода по нескольким инструментам.

Их стоит держать вместе:

1. `structured-help-scorecard` — stop-check extractor/snapshot.
2. `mesh-scorecard` — stop-check runtime/orchestrator/graph behavior.
