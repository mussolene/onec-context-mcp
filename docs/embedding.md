# Embedding и индексация

## Обзор

Эмбеддинги используются для семантического поиска по справке 1С, сниппетам и событиям памяти. Все точки входа используют единый пайплайн: sanitize, truncation, retry, rate limiting.

**Сравнение моделей и выбор под MacBook M1 (2026):** см. [embedding-models-analysis.md](embedding-models-analysis.md).

## Бэкенды

| Бэкенд | Описание | Размерность |
|--------|----------|-------------|
| **local** | По умолчанию. sentence-transformers, модель **paraphrase-multilingual-MiniLM-L12-v2** (50+ языков, RU). Размерность определяется автоматически по модели. | авто |
| **openai_api** | LM Studio (localhost:1234), Ollama, OpenAI-совместимый API. Размерность определяется автоматически по ответу API; при недоступности API используется EMBEDDING_DIMENSION. | авто (fallback: EMBEDDING_DIMENSION) |
| **deterministic** | 384-dim хэш без модели — только для наполнения БД, keyword-поиск | 384 |
| **none** | Плейсхолдер, только keyword-поиск | 384 |

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
5. **Fallback** — при ошибке batch: retry с половинным батчем; при провале — по одному.
6. **Placeholder** — при недоступности API: хэш-вектор для сохранения индекса.

## Retry при len(vectors) != len(items)

Если API возвращает меньше векторов, чем запрошено:

- **indexer** — 1 retry, затем логирование и пропуск batch (данные не теряются, повторный ingest подтянет).
- **memory** — 1 retry, затем пропуск текущих items.

## Переменные окружения

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| EMBEDDING_BACKEND | local (по умолчанию), openai_api, deterministic, none | local |
| EMBEDDING_MODEL | Имя модели. Для local — HuggingFace (по умолчанию paraphrase-multilingual-MiniLM-L12-v2); для openai_api — id в LM Studio | paraphrase-multilingual-MiniLM-L12-v2 |
| EMBEDDING_API_URL | URL LM Studio / OpenAI-совместимого API | http://localhost:1234/v1 |
| EMBEDDING_DIMENSION | Размерность при openai_api | авто |
| EMBEDDING_BATCH_SIZE | Размер батча | 64 |
| EMBEDDING_WORKERS | Параллельных воркеров (только openai_api) | 4 |
| EMBEDDING_MAX_CONCURRENT | Глобальный семафор для API; ожидание слота — таймаут 300 с (избежание deadlock) | нет |
| EMBEDDING_TIMEOUT | Таймаут одиночного запроса (с) | 60 |
| EMBEDDING_BATCH_TIMEOUT | Таймаут batch-запроса (с) | max(timeout, 30 + batch/10) |
| EMBEDDING_FORCE_BATCH | 1/true — макс. батч (256) и воркеры (16) | 0 |

## Ingest: статус бэкенда

При `ingest` или `index-status` backend отображается как `local`, `openai_api`, `deterministic` или `none`. Раньше deterministic показывался как `none` — исправлено в ingest.py (проверка `"deterministic"` в имени бэкенда).

## Документация

- `src/onec_help/embedding.py` — основная логика
- `src/onec_help/indexer.py` — build_index, retry при mismatch
- `env.example` — полный список переменных
