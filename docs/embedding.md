# Embedding и индексация

## Обзор

Эмбеддинги используются для семантического поиска по справке 1С, сниппетам и событиям памяти. Все точки входа используют единый пайплайн: sanitize, truncation, retry, rate limiting.

**Сравнение моделей и выбор под MacBook M1 (2026):** см. [embedding-models-analysis.md](embedding-models-analysis.md).

## Бэкенды

| Бэкенд | Описание | Размерность |
|--------|----------|-------------|
| **openai_api** | По умолчанию. Ollama (localhost:11434), модель nomic-embed-text-v2-moe (768). Работает из коробки после `ollama pull nomic-embed-text-v2-moe`. Также LM Studio (1234), любой OpenAI-совместимый API. | авто |
| **local** | sentence-transformers (HuggingFace: nomic-ai/nomic-embed-text-v2-moe, 768 dim). Размерность по модели. | авто |
| **deterministic** | Хэш без модели (NFC, токены). Размерность берётся из коллекции Qdrant, затем EMBEDDING_DIMENSION, иначе последний резерв (768). | из БД / env |
| **none** | Плейсхолдер (hash). Размерность — как у deterministic. | из БД / env |

## Размерность векторов: при старте и при работе

- **При старте (создание коллекции):** если размерность не задана в env (EMBEDDING_DIMENSION), она берётся из модели: для **local** и **openai_api** — один вызов encode/API для автоопределения; для **deterministic** и **none** — из существующей коллекции Qdrant (onec_help, onec_help_memory) или из EMBEDDING_DIMENSION; последний резорт — 768.
- **При работе (поиск, запись в память):** размерность везде берётся из БД (Qdrant), если коллекция есть: при пропадании связи с эмбеддером используется deterministic-вектор с размерностью из коллекции, чтобы запрос к базе оставался валидным.
- Хардкоженная размерность 768 используется только как последний резерв, когда ни коллекция, ни EMBEDDING_DIMENSION недоступны.

## Одна модель для индекса и поиска

**EMBEDDING_MODEL и EMBEDDING_BACKEND** при индексации (ingest, load-snippets) и при поиске (MCP, search_index) должны совпадать. Иначе запрос эмбеддится другой моделью (или плейсхолдером при несовпадении размерности с коллекцией Qdrant), и семантический поиск даёт нерелевантные результаты. В Docker в `docker-compose.base.yml` и `docker-compose.yml` для сервисов **mcp** и **ingest-worker** заданы одинаковые значения по умолчанию; при смене модели в .env меняйте их вместе.

## Точки интеграции

| Компонент | Функция | Batch/Single | Retry при mismatch |
|-----------|---------|--------------|--------------------|
| indexer.build_index | get_embedding_batch | Batch | Да (1 retry, затем skip batch) |
| memory.upsert_curated_snippets | get_embedding_batch | Batch | Да (1 retry) |
| memory.process_pending | get_embedding_batch | Batch | Да (1 retry) |
| memory._write_long_or_pending | get_embedding | Single | N/A (real-time) |

Все batch-операции (ingest, load-snippets, load-standards) используют `get_embedding_batch`; только real-time события (сохранение топика, обмен) — `get_embedding`.

## Пайплайн обработки

1. **Sanitize** — удаление управляющих символов (0x00–0x1F кроме \n, \r, \t).
2. **Truncation** — обрезка до 2000 символов (MAX_EMBEDDING_INPUT_CHARS).
3. **Batch** — для API: параллельные батчи с ThreadPoolExecutor.
4. **Retry** — при HTTP 429 используется заголовок Retry-After (1–120 с).
5. **Fallback** — при ошибке batch: retry с половинным батчем; при провале — deterministic-вектор с размерностью из Qdrant.
6. **При недоступности API** — используется deterministic-вектор (токен-хэш), размерность из коллекции Qdrant или EMBEDDING_DIMENSION, чтобы поиск по индексу оставался возможным.

## Retry при len(vectors) != len(items)

Если API возвращает меньше векторов, чем запрошено:

- **indexer** — 1 retry (тот же батч отправляется в API повторно), затем логирование и пропуск batch (данные не теряются, повторный ingest подтянет).
- **memory** — 1 retry (тот же батч отправляется повторно) в `process_pending` и `upsert_curated_snippets`, затем пропуск текущих items.

При retry один и тот же батч текстов уходит в сервис эмбеддингов дважды; в логах (уровень debug) пишется факт повторной отправки.

## Кэш эмбеддингов по тексту

При **EMBEDDING_CACHE_SIZE** > 0 (по умолчанию 10000) результаты для бэкендов **local** и **openai_api** кэшируются в памяти по хэшу текста (sanitize + truncation до 2000 символов). Повторный запрос того же текста (при повторном ingest, load-snippets, load-standards или одинаковых summary в памяти) не отправляется в API/модель. Кэш — FIFO при достижении лимита. **EMBEDDING_CACHE_SIZE=0** отключает кэш.

## Переменные окружения

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| EMBEDDING_BACKEND | openai_api (по умолчанию, Ollama), local, deterministic, none | openai_api |
| EMBEDDING_MODEL | Имя модели. По умолчанию nomic-embed-text-v2-moe (Ollama). Для local — HuggingFace id nomic-ai/nomic-embed-text-v2-moe | nomic-embed-text-v2-moe |
| EMBEDDING_API_URL | URL Ollama / LM Studio / OpenAI-совместимого API | http://localhost:11434/v1 |
| EMBEDDING_DIMENSION | Размерность при openai_api | авто |
| EMBEDDING_BATCH_SIZE | Размер батча | 32 |
| EMBEDDING_WORKERS | Одновременных HTTP-запросов (очередь на сервере); макс. 150 (только openai_api) | 6 |
| EMBEDDING_MAX_CONCURRENT | Глобальный семафор для API; ожидание слота — таймаут 300 с (избежание deadlock) | нет |
| EMBEDDING_TIMEOUT | Таймаут одиночного запроса (с) | 90 |
| EMBEDDING_BATCH_TIMEOUT | Таймаут batch-запроса (с) | max(timeout, 30 + batch/10) |
| EMBEDDING_FORCE_BATCH | 1/true — макс. батч (256) и воркеры (150) | 0 |
| EMBEDDING_CACHE_SIZE | Макс. записей кэша по хэшу текста (local/openai_api). 0 — кэш отключён. Снижает повторные отправки при повторных запусках. | 10000 |

**Очередь 100–150 одновременных запросов (LM Studio / Ollama).** В интерфейсе показывается число **одновременных HTTP-запросов**, а не текстов в одном запросе. В коде один запрос = один батч (до `EMBEDDING_BATCH_SIZE` текстов); параллельных запросов = `EMBEDDING_WORKERS` (макс. 150). Чтобы в очереди было 100–150 запросов: задайте `EMBEDDING_WORKERS=100` (или 150) и `EMBEDDING_BATCH_SIZE=5` или `10`, чтобы батчей было не меньше числа воркеров (например 500 текстов ÷ 5 = 100 батчей → 100 запросов в полёте). Пример для `.env`: `EMBEDDING_WORKERS=100` и `EMBEDDING_BATCH_SIZE=5`.

## Рекомендуемая комбинация (по тестам)

По результатам `--compare-variants` (прогрев + несколько комбинаций batch×workers): **Ollama** даёт лучшую скорость при **batch=32, workers=6** (~114 pts/s). Рекомендуемые переменные для Ollama: `EMBEDDING_BATCH_SIZE=32`, `EMBEDDING_WORKERS=6`. Для LM Studio лучшая из проверенных комбинаций: `batch=5`, `workers=50` (~70 pts/s).

## Сравнение Ollama и LM Studio (прогрев, два прохода)

Скрипт `scripts/embedding_benchmark.py` поддерживает режим **--compare-full**: один и тот же модель/размерность, прогрев большим батчем, затем тестовый батч; порядок бэкендов Ollama → LM Studio → LM Studio → Ollama (два прохода с переменой порядка). В отчёте: время, pts/s, CPU (клиентский процесс), dim и cosine для одной пары текстов (качество воспроизводимости).

Запуск с прогреванием в несколько сотен/тысяч запросов и тестовым батчем:

```bash
PYTHONPATH=src python scripts/embedding_benchmark.py --compare-full
PYTHONPATH=src python scripts/embedding_benchmark.py --compare-full --warmup 1000 --test 300
```

Сравнение нескольких комбинаций batch×workers и выбор победителя (одна серия на бэкенд):

```bash
PYTHONPATH=src python scripts/embedding_benchmark.py --compare-variants --warmup 300 --test 300
```

CPU в таблице — время процесса клиента (resource.getrusage). Нагрузку на процессор сервера (Ollama / LM Studio) смотрите отдельно (например, `top`, `docker stats`).

## Stemming и BM25

**Стемминг не используется при эмбеддинге.** Текст в модель/API передаётся как есть (после sanitize и truncation). Стемминг (Snowball Russian) применяется только в **BM25** (sparse vectors для keyword-поиска) — см. `sparse_bm25.py`, переменная окружения `BM25_STEMMING=1`. Для эмбеддингов стемминг не нужен и ухудшил бы качество семантического поиска.

## Ingest: статус бэкенда

При `ingest` или `dashboard` backend отображается как `local`, `openai_api`, `deterministic` или `none`. Раньше deterministic показывался как `none` — исправлено в ingest.py (проверка `"deterministic"` в имени бэкенда).

## Документация

- `src/onec_help/embedding.py` — основная логика
- `src/onec_help/indexer.py` — build_index, retry при mismatch
- `env.example` — полный список переменных
