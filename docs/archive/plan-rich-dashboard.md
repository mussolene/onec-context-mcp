# План внедрения Rich и единого дашборда

Пошаговый план перехода на библиотеку **Rich** для отображения прогресса и введения единой команды **dashboard** (задачи, ошибки, база, при необходимости — запросы к MCP), включая тесты и обновление документации.

---

## Цели

- Использовать готовую библиотеку (Rich) для прогресса и статуса вместо кастомного вывода в терминал.
- Сохранить работу без Rich: при отсутствии зависимости или не-TTY — fallback на текущие `progress_line` / `progress_done`.
- Добавить команду `dashboard` с единым экраном (Live): задачи (ingest, standards, snippets), ошибки, Qdrant, опционально MCP.
- Покрыть изменения тестами, обновить README/AGENTS и Makefile.

---

## Этап 1. Зависимость и обёртка прогресса

### 1.1. Добавить Rich в зависимости

- **Файл:** `pyproject.toml`
- Добавить в `[project.optional-dependencies]` секцию `dashboard` (или включить `rich` в `dev`/основные deps):
  ```toml
  dashboard = [
      "rich>=13.0",
  ]
  ```
  Либо добавить `rich` в основные `dependencies`, чтобы `dashboard` и будущий `dashboard` всегда могли им пользоваться (рекомендуется для единого стека).
- В `[dependency-groups] dev` при использовании uv добавить `rich` для тестов.
- **Docker:** в `Dockerfile` или `docker-compose` при сборке образа с dashboard установить `pip install -e ".[dashboard]"` или включить rich в основной install.

### 1.2. Обёртка прогресса в _utils

- **Файл:** `src/onec_help/_utils.py`
- Оставить текущую реализацию `progress_line` и `progress_done` как fallback (без Rich).
- Добавить опциональное использование Rich:
  - При первом вызове проверять: `try: import rich.console; console = rich.console.Console(stderr=True); ... except ImportError: use_fallback`.
  - **progress_line:** при наличии Rich и TTY — `console.print(msg, end="\r")` или обновление одной строки через Live (проще — `print(msg, end="\r")` через Rich для единого стиля). При не-TTY или без Rich — текущая логика (строка + `\n` или `\r`).
  - **progress_done:** при Rich — `console.print(msg)`; иначе — текущий `stderr.write(msg + "\n")`.
- Вариант проще: не менять сигнатуры; внутри `progress_line`/`progress_done` вызывать Rich только если `rich` доступен и `sys.stderr.isatty()`, иначе текущее поведение. Так все существующие вызовы (cli, parse_fastcode, parse_helpf, memory) остаются без изменений.

### 1.3. Тесты для прогресса

- **Файл:** `tests/test_utils.py`
- Сохранить текущие тесты `test_progress_line_non_tty_no_overwrite` и `test_progress_done_writes_newline` (они проверяют поведение через mock stderr).
- Добавить тест: при замоканном `rich.console.Console` (или при `ImportError` для rich) поведение эквивалентно fallback (вызов stderr.write с ожидаемым форматом).
- Добавить тест: при установленном rich и TTY (mock) вызывается `Console.print` (проверять через patch), при не-TTY — старый путь.

Критерий приёмки: `pytest tests/test_utils.py -v` проходит; без rich в окружении поведение не ломается.

---

## Этап 2. Модуль дашборда и команда dashboard

### 2.1. Модуль сборки данных для дашборда

- **Файл:** `src/onec_help/dashboard_data.py` (новый)
- Функции без Rich (чистая логика, удобно тестировать):
  - `get_dashboard_data() -> dict`: вызывает `read_ingest_status()`, `read_last_ingest_run()`, `read_last_ingest_failed(limit=N)`, `get_index_status()`, `get_all_collections_status()`, `read_last_snippets_run()`, проверяет маркеры `load_standards.running` / `load_snippets.running`. Возвращает единую структуру (dict) с ключами: `ingest`, `collections`, `index_status`, `snippets`, `standards_loading`, `snippets_loading`, `failed_tasks`.
- Зависимости только от уже существующих модулей (ingest, indexer, snippets_cache, cli — через импорт функций чтения). Не импортировать Rich внутри этого модуля.

### 2.2. Рендер дашборда на Rich

- **Файл:** `src/onec_help/dashboard_render.py` (новый) или блок внутри `cli.py`
- Функция `render_dashboard(data: dict) -> rich.console.Group` (или `RenderableType`): по данным из `get_dashboard_data()` строит:
  - **Panel 1 — Tasks:** ingest (in progress / last run: done/total, ETA, этап), load-standards (loading… / last), load-snippets (loading… / last).
  - **Panel 2 — Errors:** таблица или список из `failed_tasks` (path, version, language, error до 1–2 строк).
  - **Panel 3 — Database:** коллекции Qdrant (имя, points, size если есть).
  - Опционально **Panel 4 — MCP:** «Запросы к MCP: N» (если позже добавим учёт).
- Использовать `rich.panel.Panel`, `rich.table.Table`, `rich.text.Text`. При отсутствии данных (например, нет Qdrant) выводить «—» или «не доступно».

### 2.3. Команда CLI dashboard

- **Файл:** `src/onec_help/cli.py`
- Новая команда `dashboard` (подкоманда в `subparsers`):
  - Опции: `--interval` (секунды обновления, по умолчанию 3), `--once` (вывести один кадр и выйти, без Live).
- Логика:
  - Если `--once`: вызвать `get_dashboard_data()`, затем `render_dashboard(data)`, вывести через `rich.console.Console().print(render_dashboard(data))` и выйти.
  - Иначе: запустить `rich.live.Live(render_dashboard(get_dashboard_data()), refresh_per_second=1/interval)` в цикле с `time.sleep(interval)` и обновлением через `live.update(render_dashboard(get_dashboard_data()))`. Остановка по Ctrl+C.
- При отсутствии модуля `rich` выдать сообщение: «Установите rich: pip install rich» и вернуть код 1.

### 2.4. Тесты для дашборда

- **Файл:** `tests/test_dashboard_data.py` (новый)
  - Тесты для `get_dashboard_data()` с замоканными `read_ingest_status`, `get_index_status`, и т.д.: проверять структуру возвращаемого dict и наличие ожидаемых ключей.
  - Случай: Qdrant недоступен (get_index_status возвращает error) — в данных должен быть флаг/сообщение об ошибке.
- **Файл:** `tests/test_dashboard_render.py` (новый) или в `tests/test_cli.py`
  - При замоканных данных вызвать `render_dashboard(data)` и проверить, что возвращается объект Rich (или что вывод содержит ожидаемые подстроки при конвертации в строку через `Console.capture`).
- **Команда:** тест вызова `cmd_dashboard` с `--once` и замоканным `get_dashboard_data`: код возврата 0 и вывод не пустой (или при отсутствии rich — код 1).

Критерий приёмки: `pytest tests/test_dashboard_data.py tests/test_dashboard_render.py tests/test_cli.py -k dashboard -v` проходит.

---

## Этап 3. Перевод dashboard на Rich (опционально)

- Заменить или дополнить текущую логику `render_dashboard (Rich)` в `cli.py`:
  - Либо оставить текущий текстовый вывод (ASCII-рамки) для `dashboard` без зависимости от Rich и добавить опцию `dashboard --rich`, которая при наличии Rich рендерит через Panel/Table.
  - Либо полностью перевести rich-режим на Rich: строить `Group(Panel(...), Panel(...))` из тех же данных и выводить через `Console().print(...)`. Тогда при отсутствии Rich использовать только compact-режим или тот же ASCII-вывод как fallback.
- Тесты: существующие тесты dashboard в `tests/test_cli.py` должны по-прежнему проходить; при переходе на Rich проверять через capture вывода, что ключевые поля (ingest status, failed, collections) присутствуют в строке.

---

## Этап 4. Метрики MCP (опционально)

- В `mcp_server.py`: при каждом вызове инструмента (в обёртке или в начале каждой tool-функции) записывать строку в SQLite (например `data/ingest_cache/mcp_metrics.db`, таблица `requests`: `ts, tool_name, success`) или в JSONL. Путь к файлу — через env `MCP_METRICS_DB` или рядом с ingest cache.
- В `get_dashboard_data()` или в отдельной функции: читать последние N записей и считать total / за последний час; добавлять в структуру данных дашборда.
- В `render_dashboard()` выводить панель «MCP: N запросов (за час: K)».
- Тесты: unit-тест записи одной строки и чтения счётчика; интеграционный тест при желании.

Этот этап можно выполнить после этапов 1–3.

---

## Этап 5. Документация и Makefile

- **README.md:** в разделе команд добавить пункт про `python -m onec_help dashboard` (и при необходимости `pip install -e ".[dashboard]"` или указать, что rich входит в зависимости). Кратко: что показывает, `--once` и `--interval`, Ctrl+C для выхода.
- **AGENTS.md:** в разделе про индекс/статус упомянуть команду `dashboard` и при необходимости `dashboard --watch` / `--exit-when-done`.
- **docs/dashboard-and-resilience.md:** в конце добавить ссылку на этот план и кратко: «Реализация по плану docs/plan-rich-dashboard.md».
- **Makefile:** при необходимости цель `dashboard` (например `$(COMPOSE) exec $(INDEX_STATUS_SERVICE) python -m onec_help dashboard`) или для локального запуска `python -m onec_help dashboard`.

---

## Порядок выполнения (чек-лист)

| Шаг | Действие | Тесты |
|-----|----------|--------|
| 1.1 | Добавить `rich` в pyproject.toml (deps или optional dashboard) | — |
| 1.2 | В _utils: опционально использовать Rich в progress_line/progress_done при TTY | test_utils (patch rich, TTY) |
| 1.3 | Прогнать test_utils, убедиться в fallback без rich | pytest tests/test_utils.py |
| 2.1 | Создать dashboard_data.py, get_dashboard_data() | test_dashboard_data.py |
| 2.2 | Создать dashboard_render.py (или в cli), render_dashboard(data) | test_dashboard_render / test_cli |
| 2.3 | В cli: подкоманда dashboard, --once и Live-режим | test_cli cmd_dashboard |
| 2.4 | Полный прогон тестов дашборда | pytest -k dashboard |
| 3   | (Опционально) dashboard с Rich или --rich | test_cli dashboard |
| 4   | (Опционально) MCP metrics + панель в дашборде | unit на запись/чтение |
| 5   | README, AGENTS, Makefile, ссылка в dashboard-and-resilience | — |

---

## Зависимости между этапами

- Этапы 1 и 2 можно вести параллельно после 1.1: обёртка прогресса не блокирует дашборд.
- Этап 3 зависит от 2.2 (наличие Rich и рендера).
- Этап 4 не блокирует 2–3; дашборд без MCP-панели уже полезен.
- Этап 5 — после стабилизации 1–2 (и при необходимости 3–4).

После выполнения плана прогресс и статистика будут выводиться через Rich, дашборд даст единый экран по задачам, ошибкам и базе, с возможностью добавить учёт запросов к MCP и опционально перевести на Rich и вывод dashboard.
