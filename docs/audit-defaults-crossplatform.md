# Аудит: умолчания, переменные, папки, кроссплатформенность

Цель: работа «из коробки», минимум настроек для ассистента, единые умолчания и кроссплатформенный запуск.

## 1. Переменные окружения и папки

### 1.1 Корень данных — `data/`

| Переменная | Назначение | Текущее умолчание | Рекомендация |
|------------|------------|-------------------|--------------|
| **DATA_UNPACKED_DIR** | Распакованная справка (ingest) | `data/unpacked` | Оставить. Единый корень `data/`. |
| **INGEST_CACHE_FILE** | SQLite-кэш ingest | `data/ingest_cache/ingest_cache.db` (локально), в Docker — `/app/var/...` | Локально: относительный путь от cwd (Path.resolve()). В Docker — env в compose. |
| **DATA_DIR** | BM25 vocab (sparse_bm25) | `data` | Оставить; единый корень. Добавить в env.example. |
| **HELP_PATH** | Каталог справки для MCP (get_1c_help_topic с диска) | Нет умолчания → RuntimeError | **Умолчание: `data`** (или каталог, переданный в `mcp <dir>`). |

Итог: все рабочие каталоги под `data/` (unpacked, ingest_cache, snippets, standards, qdrant, backup, bm25_vocab). Один корень — проще бэкапы и переносимость.

### 1.2 HELP_PATH и MCP

- Сейчас: при запуске `mcp <directory>` путь задаётся аргументом; внутри MCP при обращении к `_get_help_path()` без предварительного вызова `run_mcp(help_path=...)` читается **HELP_PATH**; если не задан — **RuntimeError**.
- В Docker: `command: ["...", "mcp", "/data"]` — каталог передаётся, но **тома `/data` в base compose нет** → в контейнере mcp папка `/data` пустая; контент после ingest лежит в ingest-worker в `/app/data/unpacked`, в mcp не смонтирован.
- Рекомендации:
  - Дать **умолчание HELP_PATH**: например `data` (от cwd), чтобы без env не падать.
  - В CLI для `mcp`: сделать аргумент каталога **опциональным** с умолчанием `data` → `python -m onec_help mcp` без аргументов работает из корня проекта.
  - В **docker-compose.base.yml** для сервиса **mcp** добавить том `./data/unpacked:/data`, чтобы после ingest контент был доступен MCP для чтения топиков с диска.

### 1.3 Источники справки (ingest)

| Переменная | Описание | Умолчание в compose | Кроссплатформенность |
|------------|----------|---------------------|----------------------|
| **HELP_SOURCE_BASE** | Корень каталогов с версиями 1С (.hbk) | `/opt/1cv8` | Linux/macOS. На Windows: `C:\Program Files\1cv8` или свой путь; задаётся в .env. |
| **HELP_SOURCE_DIRS** | Список путей через запятую | — | Гибко для любой ОС. |

Рекомендация: в **env.example** и README явно указать для Windows пример: `HELP_SOURCE_BASE=C:\Program Files\1cv8` (в .env без кавычек или с учётом экранирования). В Docker на Windows монтировать этот путь в volume.

### 1.4 Дублирование и синонимы

- **HELP_SOURCE_BASE** — единственная переменная для корня каталогов с .hbk.
- **DATA_DIR** (BM25) и корень для остального — по смыслу один «корень данных»; логично считать им `data/`, **DATA_DIR** только для BM25 (путь к `data` или аналог).

## 2. Упрощения для «из коробки»

### 2.1 Запуск без конфигурации

- **MCP:** `python -m onec_help mcp` без аргументов → использовать каталог `data` по умолчанию; при отсутствии папки не падать при старте, а только при первом обращении к диску (или создавать `data`).
- **HELP_PATH:** если не задан в env и MCP запущен с явным `help_path` из CLI — env не нужен. Если где-то вызывается `_get_help_path()` без инициализации — дать default `data` (Path от cwd).
- **Ingest без источников:** при отсутствии HELP_SOURCE_BASE и без `--sources`: не обязательно падать с exit 1; можно выйти 0 с сообщением «No sources configured; set HELP_SOURCE_BASE or use --sources». Тогда `make up` + `make ingest` на чистом клоне дают поднятый MCP + Qdrant и пустой индекс без ошибки.

### 2.2 Единая точка входа и документация

- **Единая точка входа:** ingest (и при необходимости reinit --force) — уже описано в README; оставить акцент на этом.
- В **env.example** в начале файла добавить блок «Минимальный набор для быстрого старта» с 3–5 переменными (QDRANT_*, HELP_SOURCE_BASE, при необходимости HELP_PATH), остальное — комментарии с умолчаниями.

## 3. Кроссплатформенность

### 3.1 Пути в коде

- Использование **pathlib.Path** и `Path("data/unpacked")` и т.п. — корректно; разрешение через `.resolve()` от cwd — нормально для любой ОС.
- Избегать жёстко прописанных `/opt/1cv8`, `C:\...` в коде — только через env и примеры в документации.

### 3.2 Makefile

- **ensure-data (Make):** текущая реализация `mkdir -p data/...` остаётся; reinit, backup, restore уже покрывают сценарии. На Windows при необходимости пользователь создаёт каталоги вручную или задаёт SHELL.
- **HELP_SOURCE_PATH** в Make (unpack-help): по умолчанию `/opt/1cv8`; на Windows пользователь задаёт в env или переопределяет: `make unpack-help HELP_SOURCE_PATH="C:/Program Files/1cv8"`.

### 3.3 Docker

- Volumes: `./data/...` — кросс-платформенно в Docker (Docker Desktop подставляет корректный путь).
- Монтирование хоста: Linux/macOS `/opt/1cv8`, Windows — свой путь; документировать в README и env.example.
- Healthcheck в base: `exec 3<>/dev/tcp/...` — bash-специфично; образ с bash — ок.

## 4. Итоговый список изменений (в коде/конфиге)

1. **mcp_server:** при отсутствии HELP_PATH в env использовать умолчание `Path("data").resolve()` (или от cwd), не бросать RuntimeError.
2. **cli mcp:** аргумент `directory` сделать опциональным с default `"data"`.
3. **docker-compose.base.yml:** для сервиса mcp добавить volume `./data/unpacked:/data`.
4. **env.example:** блок «Quick start»; HELP_PATH по умолчанию `data`; пример для Windows HELP_SOURCE_BASE; добавить DATA_DIR=data (для BM25).
5. **Makefile ensure-data:** оставить текущую реализацию (mkdir -p); reinit/backup/restore уже покрывают сценарии.
6. **Ingest при отсутствии источников (опционально):** exit 0 с сообщением вместо exit 1 — по желанию продукта.

## 5. Документация

- **README:** обновлён: быстрый старт; команда mcp с опциональным каталогом (по умолчанию data).
- **docs/run.md:** при обновлении добавить подраздел «Windows» с путём к 1С и примером монтирования в Docker.
- **AGENTS.md:** при обновлении путей/умолчаний синхронизировать с env.example и этим аудитом.

---

## 6. Выполненные изменения (итог)

- **mcp_server:** при отсутствии HELP_PATH используется умолчание `Path("data").resolve()`.
- **cli mcp:** аргумент directory опциональный (nargs='?'), по умолчанию HELP_PATH или `data`.
- **docker-compose.base.yml:** для mcp добавлен volume `./data/unpacked:/data`.
- **env.example:** блок «Быстрый старт», HELP_PATH по умолчанию data (в комментарии), пример для Windows (HELP_SOURCE_BASE), DATA_DIR.
- **Тесты:** test_get_help_path_default_when_unset. Команда ensure-data не вводилась — в проекте уже есть reinit, backup, restore и make ensure-data (mkdir).
