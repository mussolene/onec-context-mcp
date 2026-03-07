# Ingest: диагностика зависания и «0 done»

Если **dashboard** показывает операцию **embedding** с прогрессом вроде `4500/25503 pts (17%)` и **Summary: 13 tasks │ 0 done** в течение многих минут без изменений — ingest либо завис на API эмбеддингов, либо процесс завершился (краш/OOM/kill), а статус в кэше не обновился.

---

## 0. Где узкое место (медленность): логи Docker и LM Studio

Чтобы понять, тормозит ли **запись в Qdrant**, **API эмбеддингов (LM Studio)** или что-то ещё:

1. **Лог ingest (основной источник):**
   ```bash
   docker exec <ingest-worker-container> tail -300 /app/var/log/ingest.log
   ```
   - **`[embedding] embedding API batch error (...), retrying with smaller batches: TimeoutError`** — узкое место **LM Studio** (не успевает ответить за таймаут). Запись в Qdrant идёт только после получения векторов, поэтому до Qdrant запросы даже не доходят. Действия: увеличить `EMBEDDING_TIMEOUT` (например 90–120), уменьшить `EMBEDDING_BATCH_SIZE` (32 или 16), уменьшить `EMBEDDING_WORKERS` (1–2).
   - **`429`** — rate limit LM Studio; уменьшить батч и воркеры.
   - **`Qdrant 500`** / **`upsert`** / **`connection refused`** к Qdrant — проблема **Qdrant** (нагрузка, память, сеть). Смотреть логи: `docker logs <qdrant-container> --tail 200`.
   - **`Redis`** / **`connection refused`** к Redis — проблема Redis; проверить контейнер redis и REDIS_URL.

2. **Лог watchdog (если ingest запускается из watchdog):**
   ```bash
   docker exec <ingest-worker-container> tail -100 /app/var/log/watchdog.log
   ```

3. **LM Studio:** в интерфейсе LM Studio смотреть вкладку с логами/запросами. Если запросы висят долго или идут пачками и не успевают — это подтверждает, что узкое место на стороне эмбеддингов, а не Qdrant.

Итог: если в `ingest.log` есть **TimeoutError** или **retrying with smaller batches** — медленность со стороны **API эмбеддингов (LM Studio)**. Запись в Qdrant в таком случае не является узким местом.

### Результат самостоятельной проверки (по логам и конфигу)

- **ingest.log:** последняя строка — `[embedding] embedding API batch error (64 texts), retrying with smaller batches: TimeoutError`. Узкое место — запрос к LM Studio (батч 64 не укладывается в таймаут).
- **Qdrant логи:** только GET /collections, GET /collections/…, POST …/scroll, все ответы 200 за 0.0001–0.07 с. Записей (PUT/upsert) в последних строках нет — дашборд только опрашивает коллекции; ingest не доходит до записи, т.к. ждёт векторы от API.
- **Контейнер ingest-worker:** по умолчанию Ollama (host.docker.internal:11434). При таймаутах увеличьте `EMBEDDING_TIMEOUT` или уменьшите `EMBEDDING_BATCH_SIZE`/`EMBEDDING_WORKERS`.

**Вывод:** проблема не в Qdrant и не в Redis; задержка из‑за **API эмбеддингов (LM Studio)**. По умолчанию в коде и compose уже заданы `EMBEDDING_TIMEOUT=90`, `EMBEDDING_BATCH_SIZE=32`, `EMBEDDING_WORKERS=2`; при необходимости можно увеличить таймаут до 120 в `.env`.

---

## 1. Почему «0 done» при 4500 pts

- **done** — это число **завершённых задач** (файлов .hbk), а не точек.
- Пока первая задача (например `8.3.27.1719/shcntx_ru`) не закончится полностью (build_index вернётся), `done_tasks` остаётся 0.
- 4500 pts — это точки, уже проиндексированные **в рамках текущей** задачи; всего в ней может быть 25503.

Итого: процесс либо ещё работает над первой задачей (медленно или в долгом retry), либо уже не работает, но последний записанный статус был «в процессе».

---

## 2. Что проверить

### 2.1. Жив ли процесс ingest

Если дашборд показывает «всё стоит» (цифры не меняются, Standards/Snippets «loading» без прогресса) — в первую очередь проверьте, запущен ли контейнер **ingest-worker**. Без него статус в кэше и маркеры load_standards/load_snippets не обновляются.

- **Docker:**  
  `docker compose -f docker-compose.base.yml -f docker-compose.yml ps`  
  `docker compose -f docker-compose.base.yml -f docker-compose.yml logs ingest-worker --tail 200`  
  (или сервис, в котором запущен ingest/watchdog.)

- **Локальный запуск:**  
  Проверить, что процесс `python -m onec_help ingest` (или watchdog) ещё запущен.

Если процесса нет — статус в `ingest_current` «заморожен»; при следующем запуске ingest он будет перезаписан новым прогрессом.

### 2.2. Standards / Snippets «стоят», справка (ingest) уже в эмбеддинге

Если в дашборде **Standards** и **Snippets** показывают «embed → Qdrant» без роста счётчика, а **Ingest** при этом идёт по эмбеддингу — все три процесса делят один и тот же **Ollama** (или другой API эмбеддингов). Запросы обрабатываются по очереди, поэтому load_standards и load_snippets могут почти не продвигаться, пока ingest занял API.

**Что проверить:**

1. **Логи контейнера ingest-worker** — ошибки load_standards/load_snippets (watchdog запускает их как подпроцессы):
   ```bash
   docker compose -f docker-compose.base.yml -f docker-compose.yml logs ingest-worker --tail 300
   ```
   Ищите строки вида: `[watchdog] load-standards exited 1: ...`, `load-snippets │ Embedding not available`, таймауты, `connection refused` к Ollama.

2. **Один каталог маркеров** — дашборд должен читать тот же каталог, куда пишет worker. Локальный дашборд: по умолчанию `data/ingest_cache` (или `INGEST_CACHE_FILE` → родительский каталог). В Docker у worker путь `/app/var/ingest_cache` (volume `./data/ingest_cache`). Если дашборд запущен на хосте без этого каталога/volume — маркеры `load_standards.running`, `load_snippets.status.json` он не увидит.

3. **Ollama** — при нехватке ресурсов или перегрузке возможны таймауты. Логи Ollama на хосте (если запущена как сервис): `journalctl -u ollama -n 100` или вывод в консоль. Увеличить `EMBEDDING_TIMEOUT` в .env для ingest-worker.

4. **Устаревший маркер** — если процесс load_standards/load_snippets упал (kill, OOM), файлы `load_*.running` могли остаться. Через 10 минут дашборд считает их устаревшими и перестаёт показывать «loading». Вручную удалить: `data/ingest_cache/load_standards.running`, `load_snippets.running`.

### 2.3. Обработка прекратилась: таймаут watchdog, Ollama и сон Mac

**В логах Docker:** `[watchdog] ingest failed: timeout, will retry on next poll` — значит подпроцесс **ingest** был убит по таймауту watchdog. По умолчанию **таймаут 10800 с (3 ч)**. Если справка большая (десятки тысяч pts), ingest не успевает завершиться за час, watchdog убивает процесс и при следующем опросе снова запускает ingest (он продолжит с кэша, но снова упрётся в 1 ч).

**Что сделать:** при необходимости задать **`INGEST_WATCHDOG_TIMEOUT`** (секунды). По умолчанию 10800 (3 ч). Для отключения таймаута: `INGEST_WATCHDOG_TIMEOUT=0`. Перезапустить контейнер ingest-worker.

**Логи Ollama** (на хосте): `~/.ollama/logs/server.log` (macOS/Linux).

- **«aborting embedding request due to client closing the connection»** — клиент (ingest из Docker) закрыл соединение. Причины: (1) **таймаут запроса** — ingest ждёт ответ не дольше `EMBEDDING_TIMEOUT` (по умолчанию 90 с); если Ollama долго обрабатывает батч (нагрузка, сон Mac), клиент разрывает соединение и Ollama логирует отмену; (2) **Mac ушёл в сон** — сеть/процессы приостанавливаются, соединения рвутся; после пробуждения ingest может упасть по таймауту или connection reset.
- **Медленный батчинг** — в `server.log` видно время каждого `POST /v1/embeddings`: обычно **0.5–3 с на один батч** (зависит от размера батча и железа). Это нормально для локальной модели (nomic-embed). Ускорить: уменьшить `EMBEDDING_BATCH_SIZE` (меньше время на батч, но больше запросов) или оставить как есть; главное — не давать Mac засыпать во время индексации (Настройки → Энергосбережение → отключить сон при питании от сети или `caffeinate`).

**Итог:** если обработка «заглохла» — проверьте (1) лог Docker на `ingest failed: timeout` и при необходимости увеличьте `INGEST_WATCHDOG_TIMEOUT`; (2) лог Ollama на «client closing the connection» и при необходимости увеличьте `EMBEDDING_TIMEOUT` или не давайте Mac засыпать.

### 2.4. Где смотреть логи (Docker)

У контейнера **ingest-worker** основной вывод идёт **не** в `docker logs`, а в файлы внутри контейнера (entrypoint перенаправляет фоновые процессы):

- **ingest:** `/app/var/log/ingest.log`
- **watchdog:** `/app/var/log/watchdog.log`
- **При запуске ingest из watchdog** полный stderr/stdout каждого запуска дописывается в каталог маркеров: `ingest_stderr.log` (каталог из INGEST_CACHE_FILE). Файл ротируется по размеру (при превышении 2 MiB создаётся `ingest_stderr.log.old`). В контейнере путь: `/app/var/ingest_cache/ingest_stderr.log` (volume `./data/ingest_cache`).

При любом падении в первую очередь смотрите лог ingest:
```bash
docker exec <ingest-worker-container> tail -500 /app/var/log/ingest.log
```
Дополнительно при падении, запущенном из watchdog, проверьте:
```bash
docker exec <ingest-worker-container> tail -500 /app/var/ingest_cache/ingest_stderr.log
```

### 2.5. Ошибки в логах

В логах ищите:

- **429** — rate limit API эмбеддингов; в коде есть retry с Retry-After (до 3 попыток), затем fallback на deterministic.
- **timeout** / **TimeoutError** — таймаут запроса к API; увеличить `EMBEDDING_TIMEOUT` или уменьшить батч.
- **connection refused** / **ECONNREFUSED** — API недоступен; проверить `EMBEDDING_API_URL` и что сервис эмбеддингов запущен.
- **slot not available within 300s** — семафор `EMBEDDING_MAX_CONCURRENT`: один из запросов не освободил слот (завис или краш).
- **Bus error** — падение процесса; возможные причины см. раздел **7. Причины SIGBUS (exit -7)** ниже.
- **exit -7** (в логе watchdog: `ingest failed (exit -7)`) — процесс ingest убит сигналом **SIGBUS (7)**. Это не обязательно нагрузка/OOM; см. раздел **7**.
- **Redis** — кэш и статус хранятся только в Redis; при недоступности Redis (connection refused) ingest и дашборд не смогут читать/писать статус. Убедитесь, что контейнер redis запущен и REDIS_URL задан.
- **TimeoutError** (embedding API batch error, retrying with smaller batches) — LM Studio или API не успевает ответить. Увеличить `EMBEDDING_TIMEOUT` или уменьшить `EMBEDDING_BATCH_SIZE`; проверить, что LM Studio запущен и модель загружена.

### 2.6. Дашборд не обновляется

**Кэш и статус — только Redis.** Живой статус ингеста и история запусков хранятся в Redis (ключи `ingest:current`, `ingest:runs`, `ingest:failed:*`). Дашборд и ingest-worker используют один и тот же Redis (REDIS_URL в docker-compose задаётся для mcp и ingest-worker). Если Redis недоступен — проверьте, что контейнер redis запущен и REDIS_URL=redis://redis:6379/0.

### 2.7. Ошибки в кэше (ingest_failed)

Ошибки завершённых задач пишутся в Redis (списки `ingest:failed:{run_id}`). После завершения run их можно посмотреть через последний run. Пока run в статусе `in_progress`, в failed могут быть только уже упавшие задачи; текущая «зависшая» задача туда не попадёт, пока не упадёт по исключению.

---

## 3. Что делать

### 3.1. Перезапустить ingest

Если процесс мёртв или решено начать заново:

- **Docker:**  
  `make ingest` (разовый запуск) или поднять воркер заново и дать ему отработать: `make ingest-up`.

- **Локально:**  
  Запустить `python -m onec_help ingest` ещё раз.

Новый запуск создаёт новый run и при первой же записи статуса перезаписывает `ingest_current`. В dashboard появится актуальный прогресс (или новый «0 done», если ингест только стартовал). Уже проиндексированные точки в Qdrant остаются; при включённом инкрементальном режиме повторная индексация тех же файлов по кэшу может быть пропущена или обновлена.

### 3.2. Снизить нагрузку на API (429 / таймауты)

В `.env` или в переменных окружения контейнера:

- `EMBEDDING_BATCH_SIZE=32` (или меньше) — меньше точек за запрос.
- `EMBEDDING_WORKERS=1` или `2` — меньше параллельных запросов.
- `EMBEDDING_TIMEOUT=120` — больше времени на один запрос (если API медленный).

Перезапустить ingest после изменений.

### 3.3. Проверить доступность API

- Убедиться, что сервис по `EMBEDDING_API_URL` запущен и отвечает (браузер или curl на `/v1/models` и т.п.).
- Для OpenAI-совместимого API проверить квоты и лимиты (rate limit).

---

## 4. Краткий чеклист

1. Логи: `docker compose logs ingest-worker --tail 200` (или аналог) — есть ли 429, timeout, connection errors.
2. Процесс: контейнер/процесс ingest ещё запущен?
3. Перезапуск: при необходимости снова запустить ingest; статус в dashboard обновится после первой записи нового run.
4. При повторяющихся 429/таймаутах — уменьшить `EMBEDDING_BATCH_SIZE` и `EMBEDDING_WORKERS`, при необходимости увеличить `EMBEDDING_TIMEOUT`.

См. также: `docs/embedding.md`, раздел «Ingest: переиндексация при перезапуске» в AGENTS.md.

---

## 4a. Быстрый чеклист при падении

1. **Контейнер жив?** `docker compose ps`
2. **Лог ingest:**  
   `docker exec <ingest-worker-container> tail -200 /app/var/log/ingest.log`  
   Искать: Bus error, exit -7, 429, timeout, connection refused, slot not available.
3. **При exit -7 (SIGBUS):** проверить место на диске (`df -h`), целостность кэша (`sqlite3 .../ingest_cache.db "PRAGMA integrity_check;"`), не использовать NFS для `data/`.
4. **При 429/таймаутах:** снизить `EMBEDDING_BATCH_SIZE`, `EMBEDDING_WORKERS`, задать `EMBEDDING_MAX_CONCURRENT`, увеличить `EMBEDDING_TIMEOUT`.
5. **При подозрении на OOM:** смотреть `docker stats` во время индексации; добавить лимит памяти контейнеру и/или уменьшить воркеры и батчи.
6. **Доп. лог (ingest из watchdog):** `docker exec <ingest-worker-container> tail -500 /app/var/ingest_cache/ingest_stderr.log`

---

## 4b. Стабильность SQLite и диска

- Каталог кэша (`./data/ingest_cache`) должен быть на **локальном диске**, не на нестабильном NFS.
- Периодически проверять целостность:  
  `sqlite3 ./data/ingest_cache/ingest_cache.db "PRAGMA integrity_check;"`
- При повторяющихся SIGBUS можно перенести `INGEST_CACHE_FILE` на том с более предсказуемым I/O (например, отдельный локальный каталог на хосте).

---

## 4c. LM Studio и сеть

- Убедиться, что **Ollama запущен** на хосте (по умолчанию порт 11434). В контейнере используется `EMBEDDING_API_URL=http://host.docker.internal:11434/v1`. Для LM Studio задайте `EMBEDDING_API_URL=http://host.docker.internal:1234/v1`.
- При нестабильном ответе или 429: уменьшить батч/воркеры и задать `EMBEDDING_MAX_CONCURRENT`; проверить логи LM Studio на хосте на предмет перегрузки и ограничений.

---

## 4d. Коллекция onec_help_memory не появляется (standards/snippets не загрузились)

**Симптомы:** в дашборде Qdrant только коллекция `onec_help`, нет `onec_help_memory`; Standards и Snippets показывают «нет данных» после запуска watchdog.

**Причина:** load_standards и load_snippets пишут в коллекцию **onec_help_memory** только при **доступном embedding API**. Если при старте подпроцесса embedding недоступен (EMBEDDING_API_URL не отвечает, таймаут, LM Studio не запущен), команды завершаются с кодом 1 и ничего не записывают в Qdrant.

**Что проверить:**

1. **Лог watchdog** — при ненулевом коде выхода load_standards/load_snippets теперь пишется сообщение:
   ```bash
   docker exec <ingest-worker-container> tail -300 /app/var/log/watchdog.log
   ```
   Искать: `[watchdog] load-standards exited 1:` или `load-snippets exited 1:` и текст после (например «Embedding not available»).

2. **Доступность API эмбеддингов** из контейнера ingest-worker: по умолчанию `EMBEDDING_API_URL=http://host.docker.internal:11434/v1` (Ollama). Убедиться, что Ollama запущен на хосте и слушает порт 11434; при использовании LM Studio задайте порт 1234 в .env.

3. **Запуск вручную** для проверки:
   ```bash
   docker exec -it <ingest-worker-container> python -m onec_help load-standards /data/standards
   ```
   Если в stderr появится «Embedding not available (check EMBEDDING_BACKEND and EMBEDDING_API_URL)» — исправить доступ к API и перезапустить watchdog.

4. **STANDARDS_DIR / SNIPPETS_DIR** — в контейнере это `/data/standards` и `/data/snippets` (volume из `./data/standards`, `./data/snippets`). Если каталоги пусты или не смонтированы, load завершится без ошибки с «0 loaded» и коллекция не создаётся.

---

## 4e. Мало точек в onec_help_memory (например 730)

**Коллекция onec_help_memory** объединяет: стандарты (v8-code-style, v8std), сниппеты (fastcode, helpf, локальные), а также точки, сохранённые через MCP (`save_1c_snippet`). Число точек в дашборде — это сумма всего этого.

Если отображается, например, **730 pts** — это нормально, если загружена только часть источников, загрузка ещё не завершилась или в каталогах мало файлов. Чтобы увеличить: убедиться, что load-standards и load-snippets успешно отработали (в дашборде не «нет данных»), проверить объём в `./data/standards` и `./data/snippets`, при необходимости увеличить `EMBEDDING_TIMEOUT` и перезапустить загрузку.

---

## 5. Сброс базы Qdrant при сохранённом кэше (справка пропала, сниппеты подгрузились снова)

**Симптомы:** в поиске нет разделов справки (onec_help пустой), при этом сниппеты и стандарты снова загрузились и есть в выдаче. Кэш ingest при этом не очищался.

**Причина:** данные хранятся в двух местах:

- **Qdrant** (каталог `./data/qdrant` в docker-compose) — сами векторы и коллекции. Если этот каталог очистили, пересоздали volume или контейнер Qdrant — данные в БД пропадают.
- **Кэш ingest** (файл `./data/ingest_cache/ingest_cache.db`) — список уже проиндексированных .hbk (version, language, hash). Ingest **не** проверяет наличие данных в Qdrant, только кэш. Если кэш не трогали, при следующем запуске ingest считает «всё уже проиндексировано» и ничего не переиндексирует.

В итоге: справка (onec_help) не восстанавливается, а load-snippets и load-standards при следующем запуске снова пишут в Qdrant — поэтому сниппеты/стандарты появляются.

**Что делать:**

1. **Полная перезагрузка (рекомендуется):**  
   `make reinit ARGS='--force'`  
   (или `python -m onec_help reinit --force` локально).  
   Это очистит коллекции и кэш, затем заново выполнит ingest, load-snippets и load-standards.

2. **Только справка:** очистить кэш ingest и заново запустить ingest:
   - Удалить или переименовать файл кэша (в Docker: volume `./data/ingest_cache`, файл `ingest_cache.db`).
   - Запустить `make ingest` (или `python -m onec_help ingest`).  
   Сниппеты и стандарты при этом не трогаются (уже в Qdrant).

При каждом запуске, когда **все** задачи пропущены по кэшу, ingest проверяет коллекцию в Qdrant. Если коллекции нет или в ней 0 точек — в лог пишется предупреждение с подсказкой выполнить `reinit --force` или очистить кэш.

---

## 6. Кто стирает кэш ingest при перезапуске

**В коде кэш не очищается при перезапуске.** Удаление файла `ingest_cache.db` выполняется только в одном месте: **`reinit --force`** (функция `clear_ingest_cache()`). Ни init, ни watchdog, ни ingest при старте кэш не трогают.

Если после перезапуска контейнеров снова идёт полная переиндексация (Standards: loading…, Snippets: loading…, ingest с нуля), возможные причины:

1. **Запускали `reinit --force`** — кэш и коллекции были очищены по вашей команде.
2. **Каталог кэша не сохранился** — путь к кэшу задаётся через `INGEST_CACHE_FILE`. В Docker это `/app/var/ingest_cache/ingest_cache.db`, том `./data/ingest_cache`. Если при `docker compose down`/пересоздании контейнеров этот каталог на хосте удаляли или проект копировали без `data/`, кэш будет пустым.
3. **Другой рабочий каталог** — при запуске без `INGEST_CACHE_FILE` путь к кэшу считается от текущей директории (`data/ingest_cache/ingest_cache.db`). Если compose поднимается из другой папки, кэш может читаться из другого (пустого) места.
4. **Состояние watchdog** — хранится в той же SQLite-базе. Если файл кэша пропал, при первом опросе watchdog считает все каталоги «изменившимися» и запускает ingest, load-standards и load-snippets.

При полной переиндексации из-за пустого кэша в лог ingest выводится:  
`[ingest] Cache empty or missing; full re-index. If you did not run reinit --force, check INGEST_CACHE_FILE and that data/ingest_cache is persisted.`

**Проверка целостности кэша:** если на хосте выполнить `file data/ingest_cache/ingest_cache.db`, должно быть `SQLite 3.x database`. Если там `data` или ошибка — файл повреждён или перезаписан не-SQLite данными; приложение при чтении получит ошибку и будет считать кэш пустым. В этом случае удалите или переименуйте файл и заново запустите ingest (или `reinit --force`), чтобы создался новый кэш.

---

## 7. Причины SIGBUS (exit -7)

**SIGBUS (код 7)** — «bus error»: ядро прерывает процесс при обращении к памяти, которое не может быть выполнено. Часто считают, что это только из‑за нехватки памяти (OOM), но это не так.

### 7.1. Не только нагрузка

- **OOM / нехватка памяти** — да, возможная причина: при нехватке RAM ядро может убить процесс (OOM killer иногда шлёт SIGKILL, но в ряде сценариев бывает SIGBUS). Если хост/контейнер не перегружен по памяти, эта причина маловероятна.
- **mmap и файлы** — основная альтернатива:
  - Обращение к области memory-mapped файла **за пределами реального размера файла** (например файл урезали или он пустой, а код читает страницу).
  - Файл **изменён или перезаписан** во время активного mmap (в т.ч. другой процесс пишет в тот же файл).
  - **Нулевой или почти пустой файл**: mmap создаёт отображение на целую страницу, чтение за концом файла → SIGBUS.
- **SQLite** — использует память и файлы (основной .db, иногда -shm, -wal). При нехватке места на диске, обрезании файла, сбое I/O или доступе к БД с NFS/проблемного тома возможен SIGBUS.
- **Docker volumes / диск** — том `./data/ingest_cache` (и другие) смонтированы с хоста. Если том на NFS, виртуализированном диске (Docker Desktop для Mac/Windows) или при сбое/обрыве I/O ядро может вернуть SIGBUS при чтении страницы.
- **Нативные библиотеки** — зависимости (numpy, модели эмбеддингов и т.д.) могут использовать mmap для больших данных; те же правила: обрезка файла, сбой диска, NFS.

### 7.2. Что проверить, если машина не перегружена

1. **Диск и тома**
   - Место: `df -h` в контейнере и на хосте (каталог с `./data`).
   - Ошибки ядра: на хосте `dmesg | grep -iE 'error|I/O|bus'` (при наличии прав).
2. **Файловая система**
   - Том `./data` не на NFS с нестабильным соединением. Если NFS — попробовать перенести `data/ingest_cache` (и при необходимости весь `data`) на локальный диск.
   - После сбоев питания/принудительного выключения — проверка ФС: `fsck` (при размонтированном разделе).
3. **SQLite и кэш**
   - Целостность: `sqlite3 data/ingest_cache/ingest_cache.db "PRAGMA integrity_check;"` на хосте.
   - Нет ли параллельной записи в тот же файл (два процесса ingest, скрипты бэкапа и т.д.).
4. **Снижение нагрузки (если подозреваете OOM)**
   - Уменьшить `EMBEDDING_BATCH_SIZE`, `EMBEDDING_WORKERS`, `INGEST_MAX_WORKERS`; при необходимости увеличить лимит памяти контейнера.
5. **Docker Mac: отключить WAL и VACUUM**
   - Задать `INGEST_SQLITE_WAL=0` (режим журнала DELETE вместо WAL — меньше mmap/ I/O на виртуализированном томе).
   - В Docker для ingest-worker уже по умолчанию `INGEST_VACUUM_CACHE=0` и `INGEST_SQLITE_WAL=0`. Если падения после «Cache hit» продолжаются — см. п. 3 (целостность, NFS).

Итог: при стабильной машине без нехватки памяти SIGBUS чаще связан с **mmap/файлами** (размер файла, усечение, конкурентная запись) или с **I/O тома** (NFS, сбой диска), а не с «перегрузкой» в смысле CPU/RAM.

### 7.3. Синхронность кода и «одновременное чтение одного файла»

Проект написан **синхронно** (без asyncio). Параллелизм — через **потоки** (`ThreadPoolExecutor`, `threading.Lock`). Переход на полностью асинхронный код (asyncio) **не устраняет SIGBUS**: сигнал выдаёт ядро при некорректном доступе к памяти (mmap, диск и т.д.), а не из-за модели concurrency в приложении.

**Один ли файл читается из разных потоков?** В текущей схеме — **нет**. Каждый воркер ingest обрабатывает **одну** задачу (один .hbk) и работает в **своей** временной директории (`temp_base/version/language/safe_name`). Файлы справки (.md/.html) из каталога одной задачи читает только один поток; другие воркеры читают файлы из своих каталогов. Общий ресурс — только SQLite (кэш/статус); запись в него идёт из одного потока статуса и из главного потока при завершении. Поэтому падения вряд ли вызваны «двумя потоками читают один и тот же файл справки». Возможные источники — SQLite или зависимости (numpy, клиент Qdrant, библиотеки эмбеддингов) на проблемном томе или при mmap. Переписывание на asyncio не избавит от этого и добавит сложность (например, работа с SQLite из async).
