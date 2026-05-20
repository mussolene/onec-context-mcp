# Mesh Scorecard

`mesh-scorecard` измеряет не extractor, а поведение нового deterministic mesh runtime:

- `resolver-first`
- `Qdrant-only runtime`
- `graph/exact route`
- `metadata deterministic route`
- `workflow-aware task context`

## Запуск

```bash
python -m onec_help mesh-scorecard
python -m onec_help mesh-scorecard --output-file data/help_structured/mesh_scorecard.json
python -m onec_help mesh-scorecard --benchmark-file path/to/custom_mesh_benchmark.json
```

## Что меряет

Scorecard строится по benchmark-сценариям и считает:

- `overall_case_pass_pct` — сколько сценариев прошло целиком
- `route_hit_pct` — совпал ли ожидаемый `route_kind`
- `help_hit_pct` — попал ли правильный help hit в top context
- `metadata_hit_pct` — попал ли правильный metadata object
- `workflow_hit_pct` — появилась ли правильная workflow-цепочка
- `field_hit_pct` — сработал ли deterministic metadata field lookup
- latency:
  - `median_plan_ms`
  - `median_context_ms`

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

Их стоит держать вместе:

1. `structured-help-scorecard` — stop-check extractor/snapshot.
2. `mesh-scorecard` — stop-check runtime/orchestrator/graph behavior.
