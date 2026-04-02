# JSONL-First Help Plan

Цель: сделать `structured help` основным runtime-слоем для справки 1С, а `onec_help` оставить только как cold fallback и источник для редких полнотекстовых сценариев.

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

Cold fallback:

- `onec_help` с полными topic texts
- `get_1c_help_topic` и редкие general-topic сценарии

## Why HTML-First

Для structured слоя важнее исходный HTML, а не Markdown:

- в HTML уже есть секции `Синтаксис`, `Параметры`, `Возвращаемое значение`, `Доступность`, `Пример`
- в Markdown часть этой структуры уже теряется или схлопывается
- HTML-first extraction даёт более полный `jsonl` и требует меньше эвристик

Markdown остаётся полезным:

- для человека
- для cold fallback
- для общего topic reading

## Migration Phases

### Phase 1. HTML-first snapshot

Сделано:

- `build-api-structured` читает `data/unpacked`
- использует `.toc.json` и `.hbk_info.json`
- строит `api_objects.jsonl`, `api_members.jsonl`, `api_examples.jsonl`, `api_links.jsonl`
- fallback на `onec_help` оставлен только если `data/unpacked` недоступен

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

### Phase 4. Cold fallback

Когда scorecard выйдет на целевые пороги:

- перестать использовать `onec_help` как first-line exact route
- оставить `onec_help` только для:
  - `get_1c_help_topic`
  - редких general-topic запросов
  - повторного extraction / forensic reading

Полностью удалять `onec_help` не требуется.

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
- full topics читаются только по требованию
