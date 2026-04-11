# Language Graph Resolver Plan

Цель: сделать основной runtime route по справке 1С deterministic-first:

1. разобрать пользовательский BSL/accessor query;
2. зарезолвить его в канонические placeholder-имена structured help;
3. выполнить exact/lexical lookup;
4. только потом использовать semantic fallback.

## Why

Текущий MCP уже хорошо работает на exact `Тип.Метод`, но разработчики часто пишут:

- `Документы.РеализацияТоваровУслуг.СоздатьДокумент`
- `Константы.ИспользоватьСкидки.Получить`
- `Метаданные.Документы.РеализацияТоваровУслуг`
- `Метаданные.СвойстваОбъектов.РежимСовместимости`

Справка платформы хранит эти знания в другой канонической форме:

- `ДокументыМенеджер`
- `ДокументМенеджер.<Имя документа>`
- `КонстантыМенеджер`
- `КонстантаМенеджер.<Имя константы>`
- `ПеречислимыеСвойстваОбъектовМетаданных`
- `ОбъектМетаданныхКонфигурация`

Поэтому основная сложность не в retrieval, а в resolution.

## Target Architecture

### 1. Resolver-first route

Новый первый слой: `language_resolver`.

Он классифицирует запрос как один из:

- `platform_api_exact`
- `platform_surface_chain`
- `metadata_exact`
- `metadata_surface_chain`
- `conceptual_help`

### 2. Typed language graph

Нужны relation types:

- `global_property_returns_type`
- `collection_property_returns_item_manager`
- `manager_method_returns_type`
- `metadata_property_returns_metadata_collection`
- `metadata_collection_contains_object_type`
- `metadata_enumerated_property_returns_system_enum`
- `html_link_resolved_to_topic`

### 3. Retrieval order

1. Resolver
2. Exact lookup
3. Stemmed / FTS lookup
4. Semantic fallback

## Surface Families

Первый обязательный набор platform surface families:

- `Документы`
- `Справочники`
- `Перечисления`
- `Константы`
- `РегистрыСведений`
- `РегистрыНакопления`
- `РегистрыБухгалтерии`
- `РегистрыРасчета`
- `ПланыСчетов`
- `ПланыВидовХарактеристик`
- `ПланыВидовРасчета`
- `ПланыОбмена`
- `БизнесПроцессы`
- `Задачи`
- `Отчеты`
- `Обработки`
- `ХранилищаНастроек`

## Metadata-Specific Families

Отдельный graph layer для metadata:

- `Метаданные.<Коллекция>.<Имя>`
- `ОбъектМетаданныхКонфигурация.<Коллекция>`
- `ОбъектМетаданныхКонфигурация.СвойстваОбъектов`
- `ПеречислимыеСвойстваОбъектовМетаданных.<Имя свойства>`

Системные перечисления свойств метаданных нужно моделировать как relation graph, а не только как тексты:

- `ПеречислимыеСвойстваОбъектовМетаданных.РежимСовместимости -> РежимСовместимости`
- `ПеречислимыеСвойстваОбъектовМетаданных.HTTPМетод -> HTTPМетод`
- `ПеречислимыеСвойстваОбъектовМетаданных.Индексирование -> Индексирование`

## Index / Storage Plan

Primary route должен опираться не только на Qdrant payload, а на нормализованный structured layer.

Рекомендуемый состав:

- structured JSONL snapshot
- relational/FTS store для aliases + relations
- Qdrant vectors только как fallback layer

Минимальные поля snapshot:

- `value_types`
- `surface_aliases`
- `resolver_family`
- `resolver_kind`
- `relation_kind`
- `relation_target`

## html2md / Links

`see_also` в текущем виде слишком шумный.

Нужно использовать:

- `help_core.html2md.extract_outgoing_links`
- `help_core.html2md.resolve_href`

как источник typed topic-to-topic links, а не полагаться только на текстовый блок `См. также`.

## Tool Audit

### Keep as exact-first core tools

- `get_1c_api_answer`
- `get_1c_api_object`
- `search_1c_metadata_exact`
- `get_1c_metadata_object`
- `get_1c_task_context`

### Retune

- `answer_1c_help_question`
  - использовать resolver до broad search
- `search_1c_api`
  - сначала lexical/exact expansion, потом semantic fallback
- `compare_1c_help`
  - сравнение через canonical node id, не через loose query fallback
- `get_1c_task_context`
  - подмешивать resolved surface-chain hints и metadata/system-enum hints

### New helper tool

- `resolve_1c_api_name`
  - явный дебаг/AI-tool для surface chain -> canonical candidate names

## Expected Outcome

Для большинства инженерных запросов по языку 1С ответ должен собираться без vector search:

- быстрый resolver
- 1-3 exact lookup hop
- краткий ответ из structured payload

Embeddings остаются только для prose, концептуальных статей, стандартов и community snippets.
