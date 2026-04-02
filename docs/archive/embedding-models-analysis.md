# Сравнительный анализ моделей для embedding (2026, MacBook Pro M1)

## Цель

Выбор оптимальной модели и бэкенда для эмбеддингов справки 1С: локальный запуск на MacBook Pro M1, поддержка русского языка, баланс качества и скорости.

---

## Бэкенды

| Бэкенд | Плюсы | Минусы | Рекомендация для M1 |
|--------|--------|--------|----------------------|
| **local** (sentence-transformers) | Бесплатно, без сети, данные не покидают машину, работает офлайн. На M1 можно использовать MPS (Metal). | Нагрузка на CPU/GPU и память; модель нужно скачать один раз. | **Оптимально** для личной разработки и конфиденциальных данных. |
| **openai_api** (LM Studio / Ollama / OpenAI) | Лучшее качество при использовании nomic-embed, text-embedding-3 и др.; не нагружает память приложения. | Нужен запущенный сервис; при LM Studio/Ollama — те же ресурсы M1; при облачном API — трафик и стоимость. | Имеет смысл, если уже поднят LM Studio или Ollama с эмбеддинг-моделью. |
| **deterministic** | Нулевая нагрузка, быстрый ingest. | Нет семантики, только keyword-поиск (BM25). | Только для наполнения индекса без семантического поиска. |
| **none** | Плейсхолдер при недоступности API. | Семантический поиск отключён. | Резерв при сбоях. |

**Вывод по бэкенду для M1:** предпочтительно **local** — полный контроль, офлайн, без подписки. При желании максимального качества при уже запущенном LM Studio — **openai_api** с выбранной моделью.

---

## Сравнение моделей (актуальные бенчмарки 2025–2026)

Источники: MTEB (Massive Text Embedding Benchmark), ruMTEB (русскоязычный бенчмарк), отчёты по мультиязычным моделям.

### Локальные модели (sentence-transformers, работают на M1)

| Модель | Размерность | Языки | Размер | MTEB/качество | Скорость на M1 | Примечание |
|--------|-------------|--------|--------|----------------|----------------|------------|
| **nomic-embed-text-v2-moe** | 768 | 100+ (в т.ч. RU) | ~958 MB | Мультиязычный retrieval (MIRACL, BEIR) | Средне | **Рекомендуется по умолчанию** для справки 1С (RU/EN). |
| paraphrase-multilingual-MiniLM-L12-v2 | 384 | 50+ (в т.ч. русский) | ~420 MB | Хорошо для мультиязычного retrieval | Быстро | Альтернатива при ограничениях по памяти. |
| intfloat/multilingual-e5-small | 384 | Много (в т.ч. RU) | ~120 MB | Лучше на retrieval при правильном использовании | Быстро | Для retrieval нужны префиксы `query:` / `passage:` — требуется доработка кода. |
| BAAI/bge-m3 | 1024 | 100+ | ~2.3 GB | Высокий MTEB, мультиязычный | Средне на M1 8GB | Тяжелее; на M1 16GB комфортно. Поддерживается через FlagEmbedding, не только sentence-transformers. |

### Облачные / API-модели (для справки)

| Модель | Размерность | Качество (MTEB) | Стоимость/доступ |
|--------|-------------|-----------------|-------------------|
| text-embedding-3-small | 1536 | Высокое | OpenAI API |
| text-embedding-3-large | 3072 | Очень высокое | OpenAI API |
| nomic-embed-text-v2-moe | 768 | Высокое (мультиязычный) | LM Studio, Ollama, sentence-transformers (nomic-ai/nomic-embed-text-v2-moe) |
| paraphrase-multilingual-MiniLM-L12-v2 | 384 | Хорошее (мультиязычный) | LM Studio, Ollama, sentence-transformers локально |
| mxbai-embed-large | 1024 | Высокое | LM Studio и др. |

### Модели в Ollama (API: http://localhost:11434/v1)

| Модель | Размерность | Языки | Примечание |
|--------|-------------|--------|------------|
| **nomic-embed-text** | 768 (по умолчанию) | EN-ориентирован | 274 MB, контекст 2K токенов. Для русского — не оптимален. |
| **nomic-embed-text-v2-moe** | 256–768 (Matryoshka) | 100+ (в т.ч. RU) | **Рекомендуется для русского** в Ollama. 958 MB, мультиязычный retrieval (MIRACL, BEIR). |

Ollama предоставляет OpenAI-совместимый endpoint `/v1/embeddings`. В проекте задаётся `EMBEDDING_API_URL=http://localhost:11434/v1`, модель — через `EMBEDDING_MODEL` (например `nomic-embed-text` или `nomic-embed-text-v2-moe`).

### Та же модель (nomic-embed) в LM Studio

Чтобы использовать **nomic-embed** (в т.ч. v2-moe, 768 dim) в LM Studio вместо Ollama:

1. **Скачать GGUF-модель**
   - В приложении LM Studio: вкладка поиска моделей → поиск по запросу **nomic-embed** → выбрать эмбеддинг-модель (например **nomic-embed-text-v1.5** или **nomic-embed-text-v2-moe-GGUF**) и скачать.
   - Или через CLI (если установлен `lms`):
     ```bash
     lms get nomic-ai/nomic-embed-text-v2-moe-GGUF --gguf
     ```
     Либо v1.5: `lms get nomic-ai/nomic-embed-text-v1.5`
   - Репозитории на Hugging Face: **nomic-ai/nomic-embed-text-v2-moe-GGUF** (мультиязычный, 768), **nomic-ai/nomic-embed-text-v1.5-GGUF** (или без -GGUF для v1.5).

2. **Загрузить модель в LM Studio**
   - В LM Studio: **My Models** → выбрать скачанную nomic-embed → **Load model** (тип должен определяться как embedding).
   - Запустить **Local Server** (порт 1234 по умолчанию).

3. **Настроить проект**
   - Указать бэкенд и размерность 768 (у nomic-embed выход 768):
     ```bash
     export EMBEDDING_BACKEND=openai_api
     export EMBEDDING_API_URL=http://localhost:1234/v1
     export EMBEDDING_MODEL=<имя модели в LM Studio>
     export EMBEDDING_DIMENSION=768
     ```
   - Имя модели (`EMBEDDING_MODEL`) должно совпадать с тем, что отдаёт LM Studio в списке моделей (например `nomic-embed-text-v2-moe.Q4_K_M` или полное имя файла). Точное значение видно в UI после загрузки или в ответе API `GET http://localhost:1234/v1/models`.

4. **Переиндексация**
   - При смене размерности: `python -m onec_help reinit --force`, затем `init` или `ingest`.

**Примечание:** в части спецификаций nomic-embed предполагаются префиксы `search_query:` и `search_document:`. В текущем коде проекта префиксы не добавляются; при необходимости улучшения качества для этой модели можно доработать `embedding.py` (добавление префикса по типу запроса).

---

## Практическое тестирование (скрипт benchmark)

В репозитории есть скрипт для проверки доступных бэкендов и замеров на русских текстах:

```bash
PYTHONPATH=src python3 scripts/embedding_benchmark.py
```

Скрипт проверяет по очереди:

1. **deterministic** — без внешних сервисов, размерность 768, быстрый отклик.
2. **local** — sentence-transformers (по умолчанию `EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v2-moe`, 768 dim). При отсутствии библиотеки код откатывается на deterministic.
3. **LM Studio** — `http://localhost:1234/v1` (список моделей, задержка, косинусное сходство для пары похожих русских фраз).
4. **Ollama** — `http://localhost:11434/v1` (если сервис запущен).

Для выбора конкретного API или модели можно задать переменные перед запуском:

```bash
EMBEDDING_BACKEND=openai_api EMBEDDING_API_URL=http://localhost:11434/v1 EMBEDDING_MODEL=nomic-embed-text python3 scripts/embedding_benchmark.py
```

Интерпретация: чем выше **cosine(similar)** для семантически близкой пары (при сохранении разумной задержки), тем лучше модель подходит для семантического поиска по справке. У deterministic косинус для «похожих» фраз низкий (нет реальной семантики).

---

## Результаты тестирования (пример)

На машине с запущенным **LM Studio** и без запущенного **Ollama** (дата прогона: 2026-03):

| Бэкенд | Размерность | Задержка (первый запрос) | cosine(similar) | Примечание |
|--------|-------------|---------------------------|----------------|------------|
| deterministic | 768 | ~0.2 ms | 0.06 | Нет семантики, только BM25. |
| local | 768 | ~0.2 ms | 0.06 | При отсутствии sentence_transformers — fallback на deterministic. |
| openai_api (LM Studio / Ollama) | 768 | ~60–130 ms | **0.66–0.87** | Реальная семантика; nomic-embed, paraphrase-multilingual и др. |
| openai_api (Ollama) | — | — | — | Сервис не запущен (Connection refused). |

**Вывод по прогону:** по умолчанию используется **nomic-embed-text-v2-moe** (768 dim). При наличии LM Studio или Ollama — **openai_api** с соответствующим URL; при отсутствии API — **deterministic** (768 dim, поиск опирается на BM25).

---

## Рекомендация для MacBook Pro M1 (2026)

### Оптимальная конфигурация (локально, без API)

- **Бэкенд:** `EMBEDDING_BACKEND=local`
- **Модель:** `EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v2-moe` (по умолчанию)

Почему:

1. **Русский язык** — справка 1С в основном на русском; модель мультиязычная (100+ языков), русский поддерживается.
2. **Размерность 768** — единый стандарт проекта (deterministic, local, openai_api).
3. **Качество** — nomic-embed-text-v2-moe даёт лучшую семантику на тестах (cosine для похожих фраз выше, чем у paraphrase).
4. **Совместимость** — sentence-transformers из коробки; для API (Ollama/LM Studio) используется короткое имя nomic-embed-text-v2-moe.
5. **Скорость на M1** — приемлемая; при нехватке ресурсов можно перейти на paraphrase (384) или deterministic.

### Ускорение на M1 (Metal / MPS)

По желанию можно включить использование GPU через Metal:

```bash
export PYTORCH_ENABLE_MPS_FALLBACK=1
```

В коде при необходимости можно явно задать устройство для `SentenceTransformer` (например, `device="mps"` при доступности MPS). При нестабильности MPS для части операций используется fallback на CPU.

### Если используете Ollama (по умолчанию) или LM Studio

- **По умолчанию:** Ollama на `http://localhost:11434/v1`, модель `nomic-embed-text-v2-moe`. Ничего задавать не нужно после `ollama pull nomic-embed-text-v2-moe`.
- **LM Studio:** задайте `EMBEDDING_API_URL=http://localhost:1234/v1`; модель по умолчанию nomic-embed-text-v2-moe.
- **Модель:** при необходимости задайте `EMBEDDING_MODEL` и `EMBEDDING_DIMENSION=768`.

Размерность задаётся через `EMBEDDING_DIMENSION` или определяется по первому ответу API.

---

## Как применить в проекте

Локальная мультиязычная модель (по умолчанию nomic-embed, 768 dim):

```bash
pip install -e ".[mcp,embed]"
export EMBEDDING_BACKEND=local
# EMBEDDING_MODEL по умолчанию nomic-ai/nomic-embed-text-v2-moe
python -m onec_help ingest
```

Для Ollama или LM Studio задайте `EMBEDDING_API_URL` и при необходимости `EMBEDDING_MODEL=nomic-embed-text-v2-moe`, `EMBEDDING_DIMENSION=768`. Для экономии ресурсов можно использовать `EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2` (384 dim) и переиндексировать с `EMBEDDING_DIMENSION=384`.

---

## Итоговая рекомендация по выбору бэкенда

| Ситуация | Рекомендация |
|----------|--------------|
| Нет внешнего API, нужна только скорость ingest | **deterministic** — семантический поиск отключён, работает BM25. |
| Нет внешнего API, нужен семантический поиск по русскому | **local** (по умолчанию `nomic-ai/nomic-embed-text-v2-moe`, 768 dim). Требуется `pip install sentence-transformers`. |
| **Ollama (по умолчанию)** | **openai_api** + `EMBEDDING_API_URL=http://localhost:11434/v1` (дефолт). Модель `nomic-embed-text-v2-moe`, 768 dim. Работает из коробки. |
| Запущен **LM Studio** | **openai_api** + `EMBEDDING_API_URL=http://localhost:1234/v1`. Модель nomic-embed-text-v2-moe; размерность 768. |

Для наших целей (справка 1С, русский текст) по умолчанию везде **nomic-embed** (768 dim): local, openai_api (Ollama/LM Studio), deterministic. При недоступности API код переходит на deterministic-векторы 768 dim, поиск продолжает работать за счёт BM25.

### Смена размерности (переиндексация)

При смене размерности (например с 768 на 384 при переходе на paraphrase) нужно пересоздать коллекцию и переиндексировать:

```bash
export EMBEDDING_BACKEND=openai_api
export EMBEDDING_API_URL=http://localhost:11434/v1
export EMBEDDING_MODEL=nomic-embed-text-v2-moe
export EMBEDDING_DIMENSION=768
python -m onec_help reinit --force   # очистка коллекций и кэша
python -m onec_help init              # ingest + load-snippets + load-standards
```

Либо только пересборка индекса из уже распакованной справки: `build-index` с теми же переменными (коллекция пересоздаётся автоматически с новой размерностью).
