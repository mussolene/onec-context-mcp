# Тесты: БД, изоляция и производительность

## 1. Затрагивает ли тестовый прогон реальную БД (Qdrant)?

**Кратко: при обычном запуске `pytest tests` реальная БД не затрагивается** — все обращения к Qdrant и к индексации закрыты моками.

### Как это устроено

| Область | Механизм изоляции |
|--------|--------------------|
| **indexer** (build_index, search, get_topic_content, compare_1c_help, …) | В `tests/test_indexer.py` везде, где вызывается код, работающий с Qdrant, стоит `@patch("onec_help.indexer.QdrantClient")` или `patch.object(indexer_mod, "QdrantClient", None)`. Реальный `QdrantClient` не создаётся. |
| **ingest** (run_ingest, run_ingest_from_unpacked) | В `tests/test_ingest.py` либо мокается `onec_help.indexer.build_index`, либо `_unpack_build_and_index`, либо `qdrant_client.QdrantClient`. В тестах CLI (`test_cli.py`) мокаются `run_ingest` / `run_ingest_from_unpacked` или `build_index`. Цепочка до реального Qdrant не доходит. |
| **memory** (MemoryStore, upsert в onec_help_memory) | В `tests/test_memory.py` при вызовах, которые приводят к `_upsert_long` / `upsert_curated_snippets` с включённым embedding, используется `patch("qdrant_client.QdrantClient")`. Qdrant создаётся внутри `memory.py` через `from qdrant_client import QdrantClient` — подмена в `qdrant_client` перехватывает его. |
| **CLI** (load-snippets, load-standards, …) | В `tests/test_cli.py` мокается **`onec_help.cli._get_memory_store`** (нет записи в Qdrant). В **conftest** для **test_cli** включён **redis_mock_for_ingest**: используется fakeredis, чтобы cmd_load_snippets/cmd_load_standards не писали в реальный Redis (snippets_cache, standards_run_record). |
| **MCP server** | В `tests/test_mcp_server.py` вызовы, требующие memory/indexer, закрыты моками (`get_memory_store`, `indexer.compare_1c_help` и т.д.). |
| **Watchdog** | В `tests/test_watchdog.py` мокается `_run_ingest` и при необходимости `get_memory_store`. |

### Интеграционные тесты (исключение)

- **`tests/test_mcp_integration.py`** — помечен как интеграционный: запускается только при `MCP_INTEGRATION=1` и обращается к реальному MCP (и при его настройке — к реальному Qdrant). Это только **чтение** (get_1c_help_index_status, search_1c_help_keyword и т.п.), не запись в индекс.
- **`tests/test_mcp_functional_crypto.py`** — вызывает MCP по HTTP; при поднятом сервере может читать из реального индекса. Запись в БД в этих сценариях не делается.

Итого: при стандартном запуске без `MCP_INTEGRATION=1` тесты в БД не пишут.

---

## 2. Почему в БД могли «писаться новые индексы»?

Возможные причины, если такое наблюдалось:

1. **Запуск не тестов, а приложения**  
   Запуск `python -m onec_help ingest` (или `make ingest`) без моков действительно вызывает `build_index` и пишет в Qdrant. К тестам это не относится.

2. **Интеграционные тесты с MCP**  
   При `MCP_INTEGRATION=1` тесты ходят в живой MCP; сам MCP при вызовах типа `get_1c_help_index_status` только читает. Но если параллельно запущен другой процесс (ingest/watchdog), он может писать в ту же БД.

3. **Сбой или отсутствие мока**  
   Если в одном из тестов забыли замокать `QdrantClient` или `build_index`, и при этом сработал код пути до Qdrant (например, из-за изменения логики), возможна запись в localhost:6333. В текущем коде такие пути перекрыты моками (см. выше).

4. **Redis**  
   Кэш ингеста и маркеры — в Redis. В тестах `test_ingest`, `test_watchdog`, `test_snippets_cache` используется `redis_mock_for_ingest` (fakeredis), реальный Redis тестами не используется.

Рекомендация: для полной уверенности при локальном прогоне не поднимать Qdrant/Redis или поднимать их на тестовых портах и не использовать те же инстансы, что и для продакшена.

---

## 3. Почему тесты работают долго?

- **Около 720 тестов** — один прогон даёт много вызовов.
- **Перезагрузка модуля embedding**  
  В `conftest.py` фикстура `embedding_backend_none_for_network_tests` для каждого теста в `test_indexer` и `test_embedding` делает:
  - `importlib.reload(emb)` (модуль `onec_help.embedding`);
  - повторный вызов `_ensure_onec_help_submodules()`.
  Это нужно, чтобы при `EMBEDDING_BACKEND=none` не тянуть HuggingFace и не ходить в сеть, но даёт заметные накладные расходы на каждый такой тест.
- **Много reload в test_embedding.py**  
  В `test_embedding.py` десятки раз вызывается `importlib.reload(embedding_mod)` для смены окружения (env) и проверки поведения. Каждый reload — повторная инициализация модуля.
- **Файловый I/O**  
  Тесты активно используют `tmp_path`, чтение фикстур (`help_sample`, распакованные каталоги), запись во временные файлы и каталоги. Для сотен тестов это суммируется.
- **Покрытие (coverage)**  
  Включён сбор покрытия (`--cov=src/onec_help`), что замедляет выполнение.

Итого: долгое выполнение связано с количеством тестов, частыми reload модуля embedding и сбором покрытия, а не с обращением к реальной БД.

---

## 4. Рекомендации

- **Не запускать интеграционные тесты с реальным MCP/Qdrant** без явной необходимости; не задавать `MCP_INTEGRATION=1` в обычном прогоне CI/локально.
- **Локально** при желании можно поднимать Qdrant/Redis на отдельных портах и не использовать прод-данные.
- **Ускорение прогона** (при необходимости):
  - запуск по маске, например только `tests/test_indexer.py` или без `test_embedding`;
  - временно отключить coverage для быстрой проверки;
  - рассмотреть уменьшение количества `reload` в `test_embedding.py` (группировка сценариев по одному reload на группу) — с осторожностью, чтобы не сломать изоляцию по env.

---

## 5. Где что мокается (справочно)

| Файл/модуль | Что мокается | Цель |
|-------------|--------------|------|
| test_indexer.py | `onec_help.indexer.QdrantClient` | Нет реального Qdrant |
| test_indexer.py | `onec_help.embedding.get_embedding`, `get_embedding_batch` (часть тестов) | Нет вызовов API эмбеддингов |
| test_ingest.py | `onec_help.indexer.build_index`, `_unpack_build_and_index`, `qdrant_client.QdrantClient` | Нет реального индекса и распаковки |
| test_cli.py | `onec_help.indexer.build_index`, `onec_help.runtime.ingest.run_ingest`, `run_ingest_from_unpacked`, `onec_help.memory.get_memory_store` | Нет реального ингеста и memory |
| test_memory.py | `qdrant_client.QdrantClient`, `onec_help.embedding.*` | Нет реального Qdrant и embedding API |
| test_mcp_server.py | `onec_help.memory.get_memory_store`, `onec_help.indexer.*` (где нужно) | Нет реального memory/indexer при вызове инструментов |
| conftest.py | `EMBEDDING_BACKEND=none` + reload для test_indexer/test_embedding; `DATA_DIR` → tmp_path для test_indexer; `INGEST_CACHE_FILE` → temp для всех; `get_redis` → fakeredis для test_ingest, test_watchdog, snippets_cache | Изоляция окружения и кэша, без сети и без записи в прод-каталоги |

---

## 6. Неполный вывод в терминале (test_cli и др.)

При большом числе тестов буфер терминала может обрезать вывод — видно только часть списка и не видно итога (X passed / N failed).

**Варианты:**

- Увидеть конец вывода (последние тесты + итог):
  ```bash
  PYTHONPATH=src pytest tests/test_cli.py -v --tb=short 2>&1 | tail -50
  ```
- Полный лог в файл, затем итог:
  ```bash
  PYTHONPATH=src pytest tests/test_cli.py -v --tb=short > /tmp/test_cli.txt 2>&1; tail -45 /tmp/test_cli.txt
  ```
- Только итог без списка:
  ```bash
  PYTHONPATH=src pytest tests/test_cli.py -q
  ```

---

## 7. Под капотом: что загружает standards и snippets

Обе команды в итоге пишут в **коллекцию Qdrant `onec_help_memory`** через `memory.MemoryStore.upsert_curated_snippets()`: эмбеддинги текста (title + description + code_snippet/instruction) и payload с `domain` (snippets / community_help / standards).

### load-snippets (`cmd_load_snippets` в cli.py)

1. **Источники** — `_build_snippets_sources(args)`: аргумент пути, `SNIPPETS_DIR` или `--from-project`; файлы: `.json` (массив сниппетов), каталоги с `.bsl`, `.1c`, `.md`.
2. **Кэш** — при `--use-cache` / без явного отключения: `snippets_cache.get_snippets_sources_to_load()` отфильтровывает «неизменённые» по подписи (`_file_signature` для JSON, `_folder_signature` для папки по path+size). Остальное — только изменённые источники.
3. **Парсинг:**
   - **JSON:** `_load_json_items(path)` — читает массив `[{title, description, code_snippet, type?}]`; при `type=reference` элемент пойдёт в домен `community_help`, иначе `snippets`.
   - **Папка:** `snippets_loader.collect_from_folder(path, per_function=...)` — рекурсивно обходит `*.bsl`, `*.1c`, `*.md`; из .md вытаскивает YAML frontmatter и первый блок ` ```bsl `; при `per_function` и большом .bsl режет по процедурам/функциям (`bsl_utils.extract_procedures_and_functions`).
4. **Запись:** разбивка по доменам `snippets` / `community_help` → для каждого домена вызов `get_memory_store().upsert_curated_snippets(domain_items, progress_callback=..., domain=domain)`.
5. **Маркеры:** создаётся `load_snippets.running` и `load_snippets.status.json` (phase: parsing → embedding; loaded/total для дашборда); по окончании удаляются.

### load-standards (`cmd_load_standards` в cli.py)

1. **Источники:** аргумент `standards_path`, иначе `STANDARDS_DIR`, иначе `STANDARDS_REPOS` (по умолчанию `1C-Company/v8-code-style:master,zeegin/v8std:main`). Если заданы репо — каталог используется только как **место копирования** после загрузки.
2. **Загрузка репо:** для каждого элемента из `STANDARDS_REPOS` вызывается `standards_loader.fetch_repo_archive(repo_url, subpath=STANDARDS_SUBPATH, branch)` — скачивается ZIP с GitHub (`/archive/refs/heads/{branch}.zip`), распаковка во временный каталог, возврат пути к `subpath` (обычно `docs`). Временные каталоги потом удаляются в `finally`; при необходимости содержимое копируется в `STANDARDS_DIR`.
3. **Сбор .md:** для каждого каталога (локальный путь или распакованный репо) — `standards_loader.collect_from_folder(d)`: рекурсивно все `*.md` кроме `readme.md`; заголовок — первая `#` строка, описание — первый абзац до 300 символов; в items попадает `{title, description, code_snippet: full_md}`.
4. **ITS v8std (опционально):** при `STANDARDS_ITS_V8STD=1` или `--its-v8std` — `parse_its_v8std.fetch_its_v8std_items()`: обход its.1c.ru/db/v8std (browse TOC, страницы content/*/hdoc), извлечение заголовка и тела; статьи сохраняются в `STANDARDS_DIR/its-v8std/...` и добавляются в общий список items. Если папка `its-v8std` уже есть, можно подгружать с диска без повторного fetch (`collect_from_folder(its_dir)`).
5. **Запись:** один вызов `get_memory_store().upsert_curated_snippets(items, progress_callback=..., domain="standards")`. Записывается в ту же коллекцию `onec_help_memory` с `domain=standards`.
6. **Маркеры:** `load_standards.running`, `load_standards.status.json` (phase: parsing → embedding); `redis_cache.standards_run_record(n, started_at)` для дашборда.

### Общая точка записи: `memory.MemoryStore.upsert_curated_snippets`

- Проверка `embedding.is_embedding_available()`; при недоступности возврат 0 (ничего не пишется).
- Для каждого item: формируется текст для эмбеддинга (`title | description | code_snippet` или для reference — `instruction`), payload с `domain`, `title`, `description`, `code_snippet`, и т.д.
- Обработка батчами (chunk 32–256); для каждого батча `embedding.get_embedding_batch(texts)` → векторы; затем для каждой точки `_upsert_long(point_id, vector, payload)`.
- `_upsert_long`: внутри создаётся `QdrantClient(host, port)`, при отсутствии коллекции `onec_help_memory` — создаётся, затем `client.upsert(collection_name=_MEMORY_COLLECTION, points=[PointStruct(...)])`.

Итого: и standards, и snippets в итоге попадают в **Qdrant, коллекция onec_help_memory**, с разными `domain` в payload; источник данных — файлы/репо/ITS, парсеры в `standards_loader`, `snippets_loader`, `parse_its_v8std`, кэш сниппетов — в `snippets_cache`.

---

## 8. Docker: что вызывает загрузку snippets/standards

Загрузку **load-snippets** и **load-standards** в Docker запускает **watchdog**, а не cron и не entrypoint напрямую.

| Где | Что происходит |
|-----|----------------|
| **ingest-worker** (профиль `ingest`) | `command: ... python -m onec_help watchdog` — при `WATCHDOG_ENABLED=1` контейнер крутит только watchdog. |
| **Watchdog** | Раз в `WATCHDOG_POLL_INTERVAL` (по умолчанию 600 с) сравнивает состояние каталогов **STANDARDS_DIR** и **SNIPPETS_DIR** (path → size) с тем, что сохранено в Redis. Если состояние изменилось или при первом запуске в Redis пусто — запускает подпроцессы: `python -m onec_help load-standards <STANDARDS_DIR>` и/или `python -m onec_help load-snippets <SNIPPETS_DIR>`. |
| **Первый запуск / пустой Redis** | `last_standards` и `last_snippets` из Redis пустые, а каталоги `/data/standards` и `/data/snippets` уже смонтированы и могут содержать файлы → watchdog считает это «изменением» и **один раз** запускает load-standards и load-snippets. |

**Где смотреть логи:**

- Контейнер watchdog (ingest-worker):  
  `docker compose logs ingest-worker` или `docker compose -f docker-compose.base.yml -f docker-compose.yml --profile ingest logs ingest-worker`
- В логах будут строки вида:  
  `[watchdog] standards dir changed, running load-standards`  
  `[watchdog] snippets dir changed, running load-snippets`  
  и вывод самих команд load-standards/load-snippets (эмбеддинги, запись в onec_help_memory).

**Где смотреть, что загрузка идёт прямо сейчас:**

- На хосте (если каталог смонтирован): `data/ingest_cache/load_snippets.running`, `data/ingest_cache/load_snippets.status.json` (например `{"loaded": 176, "total": 2973, "phase": "embedding"}`) — значит **load-snippets** в процессе. Аналогично `load_standards.running` и `load_standards.status.json` для standards.
- В контейнере: `docker exec <ingest-worker> cat /app/var/ingest_cache/load_snippets.status.json` (путь к кэшу задаётся через `INGEST_CACHE_FILE` / `_ingest_cache_path()`; в compose это часто `./data/ingest_cache` → `/app/var/ingest_cache`).
- Вывод самого watchdog в контейнере может уходить в stdout (тогда `docker logs ingest-worker`) или в `/app/var/log/watchdog.log` — в зависимости от того, как запущен процесс (entrypoint поднимает фоновый watchdog в `watchdog.log`, а `command` в compose может запускать второй watchdog как главный процесс).

**Почему тесты могли запустить загрузку в контейнере:**

Если тесты запускаются на **хосте**, а Redis в Docker проброшен на `localhost:6379`, то тесты и контейнер используют **один и тот же Redis**. По умолчанию при отсутствии `REDIS_URL` код подключается к `localhost:6379`.

Цепочка:

1. В тесте вызывается код, который дергает **redis_cache** (например `clear_ingest_cache()` → `clear_all()`), при этом **без мока Redis** (тест из файла, для которого раньше не включался `redis_mock_for_ingest`).
2. `clear_all()` удаляет в Redis ключи `ingest:*`, `snippets:*`, **`watchdog:*`**, `mcp:*`.
3. В контейнере **watchdog** при следующем опросе читает `_load_watchdog_state("snippets")` / `"standards"` из Redis и получает **пустой словарь** (ключи стёрты).
4. Watchdog сравнивает `last_snippets` (пусто) с `current_snip` (файлы в `/data/snippets`) и решает, что каталог «изменился» → запускает подпроцесс **load-snippets** (и при необходимости load-standards).

Исправление: в **conftest** Redis мокается теперь для **всех** тестов (любой файл под `tests/`), чтобы ни один тест не обращался к реальному Redis и не мог обнулить состояние watchdog.

**Как отключить автозагрузку по watchdog:**

- Выключить watchdog: в `docker-compose` для ingest-worker задать `WATCHDOG_ENABLED: "0"`. Тогда контейнер просто спит (`sleep infinity`), load-snippets/load-standards из контейнера не запускаются; загрузку можно вызывать вручную (`make load-snippets`, `make load-standards`).
- Либо не монтировать/оставить пустыми каталоги `SNIPPETS_DIR` и `STANDARDS_DIR`, чтобы watchdog не видел файлов и не запускал загрузку.
