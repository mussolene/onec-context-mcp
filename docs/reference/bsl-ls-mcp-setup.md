# Подключение BSL LS как MCP-сервера в Cursor

Читайте этот файл, если нужно подключить внешний `lsp-bsl-bridge` и использовать диагностику и навигацию по BSL-коду вместе с 1c-help.

Инструкция по настройке **mcp-bsl-lsp-bridge** — MCP-сервера, дающего AI-агентам (Cursor, Claude Code) доступ к BSL Language Server: навигация, поиск, диагностика, рефакторинг для кода 1С и OneScript.

## Интегрированный вариант (этот проект)

BSL LS — отдельный compose (`docker-compose.bsl.yml`), запускается командой `make bsl-start`. Проект 1С монтируется в volume `.:/projects`; код обычно в `src` или в корне.

```bash
# Основные сервисы (qdrant + mcp)
make up

# BSL LS bridge отдельно
make bsl-start

# Или напрямую
docker compose -f docker-compose.bsl.yml up -d
```

Сервис `bsl-bridge` собирается из [mcp-bsl-lsp-bridge](https://github.com/SteelMorgan/mcp-bsl-lsp-bridge) (локальный клон в `deps/`, нужен `make fetch-bsl-bridge`). В `.cursor/mcp.json` добавлен `lsp-bsl-bridge`. Контейнер: `mcp-lsp-1c-hbk-helper`. Проверка: tool `lsp_status`.

**Skill и Rules для Cursor:** см. [docs/cursor-examples/](../cursor-examples/README.md) — примеры для индексации; при изменении workflow обновляйте `docs/cursor-examples/` как зависимость.

Переменные в `.env` (опционально): `BSL_CONTAINER_MEMORY`, `BSL_LS_VERSION`, `MCP_LSP_BSL_JAVA_XMX` и др.

## Требования

- Docker и Docker Compose
- Cursor (или другая IDE с поддержкой MCP)
- 8+ ГБ RAM (BSL LS требователен к памяти на крупных проектах)

## Варианты подключения

### Вариант 1: mcp-bsl-lsp-bridge (рекомендуется)

Специализированный MCP-сервер для BSL LS. Работает в Docker, включает BSL LS, file watcher и полный набор инструментов.

### Вариант 2: mcp-language-server (универсальный)

Универсальный MCP, оборачивающий любой language server. Поддерживает BSL LS при наличии установленного [BSL Language Server](https://1c-syntax.github.io/bsl-language-server/). Конфигурация сложнее, требует ручной установки BSL LS.

---

## Подключение mcp-bsl-lsp-bridge (пошагово)

### 1. Клонирование репозитория

```bash
git clone https://github.com/SteelMorgan/mcp-bsl-lsp-bridge.git
cd mcp-bsl-lsp-bridge
```

### 2. Настройка окружения

```bash
cp env.example .env
```

Отредактируйте `.env`. Минимально обязательны:

| Переменная | Описание |
|------------|----------|
| `MCP_PROJECT_NAME` | Имя проекта (часть имени контейнера) |
| `HOST_PROJECTS_ROOT` | Путь к каталогу с кодом 1С на хосте |
| `WORKSPACE_ROOT` | Путь к workspace внутри контейнера |

**Примеры `WORKSPACE_ROOT`:**

- Один каталог с конфигурацией:
  ```bash
  WORKSPACE_ROOT=/projects/main-config
  ```

- Конфигурация + расширения (общий родитель):
  ```bash
  # Структура:
  # /projects/main-config/
  # /projects/extension1/
  WORKSPACE_ROOT=/projects
  ```

**Важно:** `HOST_PROJECTS_ROOT` — путь на вашей машине. `WORKSPACE_ROOT` — путь внутри контейнера (подкаталог от `/projects` или сам `/projects`). Docker монтирует `HOST_PROJECTS_ROOT` в `/projects`.

### 3. Запуск контейнера

```bash
docker compose build
docker compose up -d
```

Имя контейнера: `${MCP_CONTAINER_PREFIX}-${MCP_PROJECT_NAME}` (по умолчанию, например, `mcp-lsp-demo`).

### 4. Конфигурация Cursor

Создайте или отредактируйте **`.cursor/mcp.json`** в корне проекта:

```json
{
  "mcpServers": {
    "1c-help": {
      "url": "http://localhost:8050/mcp"
    },
    "lsp-bsl-bridge": {
      "command": "docker",
      "args": [
        "exec",
        "-i",
        "mcp-lsp-1c-hbk-helper",
        "mcp-lsp-bridge"
      ]
    }
  }
}
```

Имя контейнера: `mcp-lsp-1c-hbk-helper` (в этом проекте зафиксировано).

### 5. Перезапуск Cursor

После изменений в `.cursor/mcp.json` перезапустите Cursor, чтобы подхватить новый MCP-сервер.

### 6. Проверка

В Cursor (через Composer или чат) вызовите tool `lsp_status` — он покажет статус подключения и прогресс индексации BSL LS.

---

## URI для document_diagnostics

Пути к файлам в контейнере bsl-bridge отличаются от путей на хосте. Volume: `.:/projects`.

| Путь на хосте | URI для document_diagnostics |
|---------------|------------------------------|
| `./src/DataProcessors/.../Module.bsl` | `file:///projects/src/DataProcessors/.../Module.bsl` |
| `./DataProcessors/X/Forms/MyForm/Ext/Form/Module.bsl` | `file:///projects/DataProcessors/X/Forms/MyForm/Ext/Form/Module.bsl` |

**Правило:** замените корень проекта на `/projects` и добавьте префикс `file://`.

**Пример вызова:**
```
document_diagnostics(uri="file:///projects/src/DataProcessors/.../Forms/.../Ext/Form/Module.bsl")
```

---

## Основные инструменты (tools)

| Tool | Назначение |
|------|------------|
| `project_analysis` | Поиск символов, файлов, текста по проекту |
| `symbol_explore` | Детальная информация о символе с кодом и документацией |
| `definition` | Перейти к определению |
| `hover` | Документация и сигнатура по курсору |
| `call_hierarchy` | Кто вызывает / что вызывает (1 уровень) |
| `call_graph` | Полный граф вызовов |
| `document_diagnostics` | Ошибки, предупреждения, стилистика BSL LS |
| `code_actions` | Автоматические исправления (quick-fix) |
| `prepare_rename` / `rename` | Переименование символа |
| `lsp_status` | Статус LSP и прогресс индексации |
| `did_change_watched_files` | Уведомление об изменении файлов (после git pull) |

---

## Совместная работа с 1c-help

В AGENTS.md рекомендуется использовать **оба** MCP:

- **1c-help** — справка 1С, сниппеты, память
- **lsp-bsl-bridge** — навигация, диагностика, рефакторинг

Пример `.cursor/mcp.json` для обоих серверов:

```json
{
  "mcpServers": {
    "1c-help": {
      "url": "http://localhost:8050/mcp"
    },
    "lsp-bsl-bridge": {
      "command": "docker",
      "args": ["exec", "-i", "mcp-lsp-1c-hbk-helper", "mcp-lsp-bridge"]
    }
  }
}
```

---

## Batch diagnostics (workspace-wide)

`document_diagnostics` проверяет один файл. Для проверки нескольких модулей вызывайте его для каждого URI. После массовых правок вызывайте `did_change_watched_files`, чтобы BSL LS обновил индекс.

Batch/workspace diagnostics (одна операция «проверить всё») зависят от mcp-bsl-lsp-bridge — при необходимости откройте issue в [репозитории](https://github.com/SteelMorgan/mcp-bsl-lsp-bridge).

---

## Устранение неполадок

- **Медленная индексация** — на проектах 40k+ файлов может занимать 10+ минут. Рекомендуется 8+ ГБ RAM для BSL LS.
- **Контейнер не запускается** — проверьте `docker compose logs`, доступность Java (BSL LS на Java).
- **MCP не подключается** — убедитесь, что контейнер запущен (`docker ps`), имя в `mcp.json` совпадает с именем контейнера.
- **Пути** — проект монтируется в `/projects` (volume `.:/projects`). Код 1С обычно в `src` или в корне; укажите BSL_WORKSPACE_ROOT на каталог с Configuration.xml (EDT/XML).

---

## Ссылки

- [mcp-bsl-lsp-bridge](https://github.com/SteelMorgan/mcp-bsl-lsp-bridge) — репозиторий MCP-сервера
- [BSL Language Server](https://1c-syntax.github.io/bsl-language-server/) — официальная документация BSL LS
- [Документация mcp-bsl-lsp-bridge](https://github.com/SteelMorgan/mcp-bsl-lsp-bridge/tree/main/docs) — конфигурация, tools, архитектура
