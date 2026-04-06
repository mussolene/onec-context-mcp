# Structured Help Scorecard

`structured-help-scorecard` измеряет, насколько `structured help` уже может быть primary runtime-layer для справки 1С и сколько ещё смысла остаётся только в full topic layer.

Команда:

```bash
python -m onec_help structured-help-scorecard
```

Полезные варианты:

```bash
python -m onec_help structured-help-scorecard \
  --snapshot-dir data/help_structured \
  --output-file data/help_structured/scorecard.json

python -m onec_help structured-help-scorecard \
  --benchmark-file src/onec_help/knowledge/help_structured_benchmark.json
```

## Что считает

Scorecard читает:

- `api_objects.jsonl`
- `api_members.jsonl`
- `api_examples.jsonl`
- `api_links.jsonl`

Затем сравнивает их с полным help index `onec_help` и benchmark-набором exact API запросов.

Основные группы метрик:

- coverage по `summary`, `syntax`, `params`, `returns`, `availability`, `owner_name`
- доля `kind=topic` внутри member-layer
- path coverage: сколько путей темы уже представлены structured слоем. Сравнение идёт по **каноническому пути** (без префикса версии платформы): те же правила, что и в JSONL v5 (`canonical_topic_path` в коде), чтобы не было ложного gap между полным путём распаковки и `topic_path` в JSONL.
- benchmark exact quality:
  - `exact_top1_pct`
  - `exact_top3_pct`
  - `structured_sufficient_pct`

## Целевые пороги

Scorecard считает итерацию extractor практически достаточной, если выполняются такие минимальные пороги:

- `summary_pct >= 95`
- `syntax_pct >= 70`
- `availability_pct >= 85`
- `owner_name_pct >= 99.5`
- `method_like_params_pct >= 60`
- `method_like_returns_pct >= 60`
- `exact_top1_pct >= 95`
- `structured_sufficient_pct >= 80`

`method_like_*` считаются только для `method`, `function`, `constructor`, чтобы property-страницы не размывали картину.

## Как интерпретировать

- Если `exact_top1_pct` высокий, но `path_coverage` низкий, structured layer уже хорош для точного API lookup, но full topics ещё нужны как knowledge fallback.
- Если `summary/syntax/params/returns` растут, а `exact_top1_pct` почти не меняется, extractor стал богаче, но не обязательно лучше как search route.
- Если две последовательные итерации дают прирост меньше `1-2%` по ключевым метрикам, это нормальная practical stop condition.

## Рекомендуемый workflow

1. Изменить extractor в `help_structured.py`.
2. Пересобрать structured snapshot и индексы.
3. Запустить `structured-help-scorecard`.
4. Сравнить JSON-отчёт с предыдущей итерацией.
5. Только после этого решать, можно ли ещё ослаблять cold fallback в `onec_help`.

## Что scorecard не заменяет

Scorecard не доказывает, что full topic layer можно удалить полностью.

Он показывает:

- насколько structured layer уже годится как primary runtime route;
- какие API-поля ещё теряются;
- сколько тем остаётся только в cold fallback.
