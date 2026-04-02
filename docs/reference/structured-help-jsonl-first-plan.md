# JSONL-First Help Plan

Цель: сделать `structured help` основным и самодостаточным runtime-слоем для справки 1С, без runtime-зависимости от Markdown/topic-layer.

## Target State

Основной маршрут:

1. `HBK -> unpacked HTML`
2. `HTML -> structured JSONL`
3. `JSONL -> Qdrant structured collections`
4. MCP работает в первую очередь через:
   - `onec_help_api_objects`
   - `onec_help_api_members`
   - `onec_help_examples`
   - `onec_help_api_links`

Исторический topic-layer больше не входит в основной runtime route.

## Why HTML-First

Для structured слоя важнее исходный HTML, а не Markdown:

- в HTML уже есть секции `Синтаксис`, `Параметры`, `Возвращаемое значение`, `Доступность`, `Пример`
- в Markdown часть этой структуры уже теряется или схлопывается
- HTML-first extraction даёт более полный `jsonl` и требует меньше эвристик

Markdown может оставаться только как ручной derived-артефакт для отладки и проверки extractor.

## Migration Phases

### Phase 1. HTML-first snapshot

Сделано:

- `build-api-structured` читает `data/unpacked`
- использует `.toc.json` и `.hbk_info.json`
- строит `api_objects.jsonl`, `api_members.jsonl`, `api_examples.jsonl`, `api_links.jsonl`
- runtime fallback на `onec_help` убран; source of truth для help runtime = structured JSONL

### Phase 2. Extractor coverage

Дальше нужно поднимать полноту именно structured полей:

- `syntax`
- `params`
- `returns`
- `availability`
- `see_also`
- owner/member/object связи

Основные источники потерь:

- статьи с inline-секциями
- property-страницы, где тип сидит в `Описание`
- chapter blocks с нестандартной HTML-структурой
- overview/query/form topics, которые ещё не уложены в structured сущности

### Phase 3. Structured completeness

Добавить или улучшить:

- object-level overview records
- query/help topics, которые нужны агенту, но не являются `member`
- official examples extraction без потери описаний
- `api_links` не только для `see_also`, но и для owner/member и type relations

### Phase 4. Runtime cleanup

Когда scorecard выйдет на целевые пороги:

- topic-layer runtime routes должны быть удалены из публичного surface
- ingest должен работать по цепочке `HBK -> temporary unpacked HTML -> structured JSONL -> Qdrant`
- Markdown и persistent unpacked HTML не должны участвовать в runtime

## Stop Metrics

Extractor считаем practically sufficient, если одновременно выполняются:

- `summary_pct >= 95`
- `syntax_pct >= 70`
- `availability_pct >= 85`
- `owner_name_pct >= 99.5`
- `method_like_params_pct >= 60`
- `method_like_returns_pct >= 60`
- `exact_top1_pct >= 95`
- `structured_sufficient_pct >= 80`

И дополнительно:

- остаток непокрытых `topic_path` должен быть понятным и осознанным
- две итерации подряд не должны давать прирост больше `1-2%`

## Practical Rule

Не пытаться выжать из extractor идеальные `100%`.

Нужный результат:

- exact API lookup идёт через structured layer
- человеку и агенту в большинстве API-кейсов хватает JSONL/Qdrant payload
- runtime ответы строятся из structured JSONL/Qdrant payload, а не из full topics
