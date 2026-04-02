# Поиск по справке 1С и MCP

Читайте этот файл, если нужно улучшать качество поиска, разбираться с нерелевантной выдачей или понять рекомендации по MCP-маршрутам.

## Публикация tools в Cursor

При транспорте **streamable-http** (FastMCP 3.x) Cursor иногда не показывает tools или обрывает соединение (ECONNRESET, «No server info found»). **Обходной вариант:** запустить MCP в режиме **SSE** — в `.env` или в переменных окружения контейнера задать `MCP_TRANSPORT=sse`, перезапустить сервис `mcp`. URL в `.cursor/mcp.json` оставить `http://localhost:8050/mcp`. Транспорт в команде контейнера не передаётся — берётся из `MCP_TRANSPORT`.

## BM25 sparse vectors (по умолчанию)

Structured help search (`search_1c_api`, hybrid retrieval в `api_members|api_objects|api_examples`) использует BM25 sparse vectors для ранжирования результатов. По умолчанию BM25 включён (BM25_ENABLED=1).

- **Новый ingest:** BM25 добавляется автоматически при build_index (при `--no-bm25` или BM25_ENABLED=0 — отключено).
- **Существующий индекс:** запустите `add-bm25` для миграции **без re-ingest** и без пересчёта эмбеддингов:
  ```bash
  make add-bm25
  # или
  docker compose exec mcp python -m onec_help add-bm25
  ```
- Vocab BM25 сохраняется в `data/bm25_vocab/onec_help.json` для поиска. Папка монтируется в контейнер. Если словарь потерян, а коллекция уже содержит BM25 — повторный вызов `make add-bm25` сохранит vocab на хост.
- **Стемминг** (Snowball Russian): включён по умолчанию (`BM25_STEMMING=1`). Улучшает recall: «документы» → «документ», «подключение» → «подключ». Смена `BM25_STEMMING` требует повторного `make add-bm25`.

## Structured JSONL-first route

Старый topic-layer больше не является публичным search/read surface. Runtime route теперь такой:

- exact API: `get_1c_api_answer`
- natural-language factual question: `answer_1c_help_question`
- broad structured lookup: `search_1c_api`
- official examples: `search_1c_official_examples`

### 3. Skill 1c-mcp-development

Добавлена секция «Типичные промахи семантики» с таблицей частых синонимов API и порядком действий при нерелевантных результатах. См. `.cursor/skills/1c-mcp-development/SKILL.md` и `docs/cursor-examples/1c-mcp-development/SKILL.md`.

---

## Оптимизация результата поиска

- Для **точных имён** (`Тип.Метод`) — используйте **get_1c_api_answer**.
- Для **общих вопросов по API** — **answer_1c_help_question**.
- Для **широкого поиска по API и объектам** — **search_1c_api**.
- Для **примеров** — **search_1c_official_examples** или **search_1c_snippets**.

---

## Проверка MCP справки: скорость, полнота, рабочий код

### Быстрая проверка (когда MCP доступен)

1. **Статус индекса** — `get_1c_help_index_status`: число топиков, версии, языки, размер БД. Если индекс пуст — запустить ingest.
2. **Natural-language question** — `answer_1c_help_question("как прочитать JSON в Соответствие")`.
3. **Точное имя** — `get_1c_api_answer("Формат")` или `get_1c_function_info("ПрочитатьJSON")`.

### Скорость

- **Семантический поиск:** размерность запроса берётся из коллекции Qdrant; при несовпадении с текущей моделью используется placeholder (без вызова API) — запрос быстрый.
- **Qdrant:** локальный поиск обычно &lt; 100 мс.
- **answer_1c_help_question / search_1c_api:** hybrid structured retrieval + форматирование enriched payload. В типичном случае ответ за 1–3 с (зависит от embedding API, если используется).

### Полнота

- Зависит от **ingest**: какие .hbk проиндексированы (HELP_SOURCE_BASE, версии, HELP_LANGUAGES).
- В ответах structured route используются enriched JSONL records (`summary`, `description`, `notes`, `restrictions`, `syntax`, `params`, `returns`, `availability`, `source_sections`).
- При малой релевантности нужно уточнить `version`, exact API name или использовать `search_1c_api`.

### Рабочий код за несколько вызовов

- **Один вызов:** `answer_1c_help_question(query)` — часто достаточно для factual API-вопросов.
- **Два вызова:** `get_1c_api_answer("Тип.Метод", detail="full")` + `search_1c_official_examples("Тип.Метод")`.
- **Третий вызов (по желанию):** `save_1c_snippet(code, description, title)` — сохранить рабочий пример в память, чтобы в следующих сессиях он попадал в «Из памяти» в get_1c_code_answer.

Итого: рабочий API-контекст теперь получается за 1–3 вызова по structured DB-first route без topic fallback.
