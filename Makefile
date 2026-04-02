# 1C Help MCP — Docker commands
# По умолчанию: make up = qdrant + mcp; make ingest-up = + ingest-worker (watchdog). Full: make up-full.
# Usage: make parse-fastcode | make load-snippets | make snippets
# Pages: auto by default. Limit: ARGS="--pages 1-5 --no-fetch-detail"

# Windows: PowerShell по умолчанию для make (иначе cmd, BSL_SET не сработает)
ifeq ($(OS),Windows_NT)
  SHELL := powershell.exe
  .SHELLFLAGS := -NoProfile -Command
endif

ARGS ?=
HELP_SOURCE_PATH ?= /opt/1cv8
UNPACK_OUTPUT ?= data/unpacked
HELP_LANGS ?= ru

# -f base + overlay: merge вместо include (избегаем "conflicts with imported resource")
COMPOSE = docker compose -f docker-compose.base.yml -f docker-compose.yml
COMPOSE_FULL = docker compose -f docker-compose.base.yml -f docker-compose.full.yml
COMPOSE_BSL = docker compose -f docker-compose.bsl.yml

# BSL_HOST_PROJECTS_ROOT: PowerShell ($env:) / export (sh) / set (cmd). Docker — слэши /
BSL_ROOT = $(subst \\,/,$(CURDIR))
ifneq ($(findstring powershell,$(SHELL))$(findstring pwsh,$(SHELL)),)
  BSL_SET = $$env:BSL_HOST_PROJECTS_ROOT="$(BSL_ROOT)";
else ifneq ($(findstring sh,$(SHELL)),)
  BSL_SET = export BSL_HOST_PROJECTS_ROOT="$(BSL_ROOT)" &&
else
  BSL_SET = set "BSL_HOST_PROJECTS_ROOT=$(BSL_ROOT)" &&
endif

# По умолчанию split; для full добавлять -full к таргету
INGEST_SERVICE = ingest-worker
INDEX_STATUS_SERVICE = mcp

.PHONY: build build-nocache build-full fetch-bsl-bridge parse-fastcode parse-helpf load-snippets load-snippets-from-project load-standards snippets
.PHONY: up down ingest-up ingest-down ingest-worker up-full down-full bsl-start bsl-stop qdrant-logs ingest-logs ollama-logs qdrant-reset qdrant-backup qdrant-restore ensure-data

# bsl-bridge: локальный клон (Git URL в context не работает на Docker Windows)
deps/mcp-bsl-lsp-bridge/.git/HEAD:
	git clone --depth 1 https://github.com/SteelMorgan/mcp-bsl-lsp-bridge.git deps/mcp-bsl-lsp-bridge

fetch-bsl-bridge: deps/mcp-bsl-lsp-bridge/.git/HEAD
.PHONY: init init-full reinit reinit-full ingest ingest-full build-index build-index-full add-bm25 add-bm25-full
.PHONY: dashboard unpack-help help

WATCH_INTERVAL ?= 2

# Сборка образов (split). SERVICE=mcp|ingest-worker — только один сервис. По умолчанию образ без local-эмбеддингов.
build:
	$(COMPOSE) build $(if $(SERVICE),$(SERVICE),mcp ingest-worker)

# Сборка образов (split). SERVICE=mcp|ingest-worker — только один сервис. По умолчанию образ без local-эмбеддингов.
build-nocache:
	$(COMPOSE) build $(if $(SERVICE),$(SERVICE),mcp ingest-worker) --no-cache

# Сборка образа (full, один контейнер mcp)
build-full:
	$(COMPOSE_FULL) build mcp

# Parse FastCode.im templates → data/snippets/fastcode_snippets.json (в контейнере: /data/snippets)
parse-fastcode:
	$(COMPOSE) run --rm mcp python -m onec_help parse-fastcode $(ARGS)

# Parse HelpF.pro FAQ/Files → data/snippets/helpf_snippets.json (в контейнере: /data/snippets)
parse-helpf:
	$(COMPOSE) run --rm mcp python -m onec_help parse-helpf $(ARGS)

# Load snippets from SNIPPETS_DIR into onec_help_memory
load-snippets:
	$(COMPOSE) run --rm mcp python -m onec_help load-snippets $(ARGS)

# Load snippets from 1C project
load-snippets-from-project:
	$(COMPOSE) run --rm -v "$${PROJECT_PATH:=$(CURDIR)}:/project:ro" mcp python -m onec_help load-snippets --from-project /project $(ARGS)

# Load standards into onec_help_memory. ARGS: --its-v8std to also fetch from its.1c.ru/db/v8std.
# If you get "unrecognized arguments" for new options, rebuild the image: make build
load-standards:
	$(COMPOSE) run --rm mcp python -m onec_help load-standards $(ARGS)

# Parse FastCode + HelpF (FAQ only) + load snippets
snippets: parse-fastcode parse-helpf load-snippets

# init: ingest + load-snippets + load-standards (no erase)
init:
	$(COMPOSE) exec $(INGEST_SERVICE) python -m onec_help init $(ARGS)

init-full:
	$(COMPOSE_FULL) exec mcp python -m onec_help init $(ARGS)

# reinit: erase collections + cache, then init
reinit:
	$(COMPOSE) exec $(INGEST_SERVICE) python -m onec_help reinit $(ARGS)

reinit-full:
	$(COMPOSE_FULL) exec mcp python -m onec_help reinit $(ARGS)

# Ingest .hbk (split, default) — в ingest-worker
ingest:
	$(COMPOSE) exec $(INGEST_SERVICE) python -m onec_help ingest $(ARGS)

# Ingest (full) — в mcp
ingest-full:
	$(COMPOSE_FULL) exec mcp python -m onec_help ingest $(ARGS)

# Build index from directory with .md
build-index:
	$(COMPOSE) exec $(INDEX_STATUS_SERVICE) python -m onec_help build-index $(ARGS)

build-index-full:
	$(COMPOSE_FULL) exec mcp python -m onec_help build-index $(ARGS)

# Add BM25 sparse vectors to existing collection (no re-ingest, no re-embedding)
add-bm25:
	$(COMPOSE) exec $(INDEX_STATUS_SERVICE) python -m onec_help add-bm25 $(ARGS)

add-bm25-full:
	$(COMPOSE_FULL) exec mcp python -m onec_help add-bm25 $(ARGS)

# Dashboard (Tasks, Errors, Qdrant, versions 1C). Работает пока не прервать (Ctrl+C). ARGS='--once' — один кадр и выход.
dashboard:
	@echo "Dashboard (live). Ctrl+C to exit. One shot: make dashboard ARGS='--once'"
	$(COMPOSE) exec -it $(INDEX_STATUS_SERVICE) python -m onec_help dashboard --interval $(WATCH_INTERVAL) $(ARGS)

# Unpack .hbk без индексации
unpack-help:
	$(COMPOSE) run --rm -v "$(HELP_SOURCE_PATH):/input:ro" -v "$(abspath $(UNPACK_OUTPUT)):/output" mcp python -m onec_help unpack-dir /input -o /output -l $(HELP_LANGS) $(ARGS)

# Unpack .hbk в data/unpacked с .hbk_info.json (version/stem, skip unchanged)
unpack-sync:
	$(COMPOSE) run --rm -v "$(HELP_SOURCE_PATH):/input:ro" -e DATA_UNPACKED_DIR=/output -v "$(abspath $(UNPACK_OUTPUT)):/output" mcp python -m onec_help unpack-sync /input -o /output -l $(HELP_LANGS) $(ARGS)

# Build structured JSONL and index from unpacked dir (after unpack-sync)
ingest-from-unpacked:
	$(COMPOSE) exec $(INGEST_SERVICE) python -m onec_help ingest-from-unpacked $(ARGS)

# Start (split: qdrant + mcp + ingest-worker)
# Каталоги data/* создаются Docker при volume mount — кросс-платформенно
# По умолчанию только qdrant + mcp
up:
	$(COMPOSE) up -d --remove-orphans

# Запустить ingest-worker (watchdog): нужен после make up, если нужна индексация/стандарты/сниппеты
ingest-up:
	$(COMPOSE) --profile ingest up -d --remove-orphans

# Остановить только ingest-worker (qdrant и mcp остаются)
ingest-down:
	$(COMPOSE) stop ingest-worker

# Алиас: make ingest-worker = make ingest-up (поднять с профилем ingest)
ingest-worker: ingest-up

# Start full (один контейнер mcp)
up-full:
	$(COMPOSE_FULL) up -d

# Stop
down:
	$(COMPOSE) down

down-full:
	$(COMPOSE_FULL) down

# BSL LS bridge only (отдельный compose, не с up)
bsl-start: deps/mcp-bsl-lsp-bridge/.git/HEAD
	$(BSL_SET) $(COMPOSE_BSL) up -d

bsl-stop:
	$(COMPOSE_BSL) stop

# Создать каталоги data/ для bind-mount. После потери data/qdrant: make ensure-data && make up; для индекса: make ingest-up
ensure-data:
	@mkdir -p data/qdrant data/unpacked data/help_structured data/ingest_cache data/snippets data/backup data/bm25_vocab data/standards data/config data/kd2 data/kd2_snapshot data/redis
	@echo "data/qdrant и остальные каталоги созданы."

# При qdrant exit 101: логи и сброс данных. Использовать оба -f!
qdrant-logs:
	docker compose -f docker-compose.base.yml -f docker-compose.yml logs qdrant

# Логи ingest-worker (эмбеддинги, fallback, ошибки API). Ищите [embedding] и «Внешний сервис недоступен»
ingest-logs:
	$(COMPOSE) logs ingest-worker --tail 200

# Сбросить состояние watchdog для config metadata и сразу запустить metadata-graph-build (без ожидания следующего цикла опроса).
# Для primary route используйте data/kd2: кладите туда KD2 XML, watchdog/metadata-graph-build обновят snapshot автоматически.
reset-metadata-watchdog:
	@echo "Сброс watchdog:state:metadata в Redis..."
	@$(COMPOSE) exec redis redis-cli DEL "watchdog:state:metadata" || true
	@echo "Запуск metadata-graph-build в ingest-worker (источник: ONEC_CONFIG_SOURCE_DIR)..."
	$(COMPOSE) exec $(INGEST_SERVICE) python -m onec_help metadata-graph-build

# Только сбросить ключ (без запуска build). Следующий запуск metadata — при следующем опросе watchdog (до 10 мин).
reset-metadata-watchdog-only:
	@$(COMPOSE) exec redis redis-cli DEL "watchdog:state:metadata" || true
	@echo "Ключ сброшен. Ждите следующий цикл watchdog (WATCHDOG_POLL_INTERVAL сек) или выполните: make metadata-build"

# Очистить в Redis ошибки, которые отображаются в dashboard (ingest + MCP).
clear-dashboard-errors:
	@echo "Очистка ошибок дашборда в Redis (ingest:errors, mcp:errors_total, mcp:errors_recent)..."
	@$(COMPOSE) exec redis redis-cli DEL "ingest:errors" "mcp:errors_total" "mcp:errors_recent" || true
	@echo "Готово. Панели Errors и MCP requests в дашборде будут пустыми по ошибкам."

# Построить compact snapshot из KD2 XML выгрузки.
# По умолчанию snapshot пишется в ту же рабочую папку data/kd2.
# Пример: make kd2-snapshot-build XML_PATH=/data/kd2/ВыгрузкаБП30.xml OUT=data/kd2
# XML рекомендуется получать через tools/1c/MetadataExport.epf, а не через выгрузку конфигурации в файлы.
kd2-snapshot-build:
	@test -n "$(XML_PATH)" || (echo "Usage: make kd2-snapshot-build XML_PATH=/path/export.xml OUT=data/kd2" && exit 1)
	$(COMPOSE) exec $(INGEST_SERVICE) python -m onec_help kd2-snapshot-build "$(XML_PATH)" -o "$(or $(OUT),data/kd2)"

# Запустить сборку графа метаданных вручную.
# Primary route: data/kd2 (KD2 XML + in-place snapshot) or direct KD2 XML/KD2 snapshot.
# Deprecated fallback: exported configuration in files (data/config / ONEC_CONFIG_SOURCE_DIR).
# Требует: make ingest-up (ingest-worker запущен). Если в списке команд нет metadata-graph-build — пересоберите образ: make build.
# Для больших конфигов (тысячи объектов) эмбеддинг и запись в Qdrant могут занять 10+ мин.
# При таймауте после «embedding N/N» (запись в Qdrant): QDRANT_TIMEOUT=600 make metadata-build
METADATA_EXEC_ENV = $(if $(QDRANT_TIMEOUT),-e QDRANT_TIMEOUT=$(QDRANT_TIMEOUT),)
metadata-build:
	$(COMPOSE) exec $(METADATA_EXEC_ENV) $(INGEST_SERVICE) python -m onec_help metadata-graph-build $(ARGS)
metadata-graph-build: metadata-build

# Диагностика: почему watchdog не запускает metadata-graph-build. Показывает путь конфигурации, find_config_root и число файлов .xml/.bsl.
metadata-watchdog-debug:
	@echo "Диагностика config dir и watchdog (в контейнере ingest-worker)..."
	$(COMPOSE) exec $(INGEST_SERVICE) python -c "\
from pathlib import Path; \
from onec_help.shared import env_config; \
from onec_help.runtime.watchdog import _scan_metadata_source_stable; \
from onec_help.knowledge.config_crawler import find_config_root; \
d = env_config.get_config_source_dir(); \
p = Path(d).resolve() if d else None; \
print('ONEC_CONFIG_SOURCE_DIR (effective):', repr(d)); \
print('resolved path:', p, '| exists:', p.exists() if p else False); \
root = find_config_root(p) if p and p.exists() else None; \
print('find_config_root:', root); \
scan = _scan_metadata_source_stable(p) if p and p.exists() else {}; \
print('scan metadata source files count:', len(scan)); \
"
	@echo "--- Redis: ключ watchdog:state:metadata ---"
	@$(COMPOSE) exec redis redis-cli EXISTS "watchdog:state:metadata" 2>/dev/null || echo "redis недоступен или ключ не найден"

# Логи Ollama на хосте (macOS: ~/.ollama/logs/server.log). Ищите «aborting embedding request due to client closing»
ollama-logs:
	@tail -100 ~/.ollama/logs/server.log 2>/dev/null || echo "Ollama не установлен или логи не найдены (macOS: ~/.ollama/logs/)"

# Удалить data/qdrant и перезапустить (если qdrant падает с 101 — повреждённые данные). Индекс будет потерян — затем make ingest
qdrant-reset:
	-$(COMPOSE) stop qdrant
	docker run --rm -v "$(CURDIR)/data:/data" alpine rm -rf /data/qdrant
	@echo "data/qdrant удалён. Запустите: make up; для индексации: make ingest-up"

# Снапшоты всех коллекций onec_* → data/backup/{collection}-{timestamp}.snapshot (для миграции между хостами)
qdrant-backup:
	$(COMPOSE) exec mcp python -m onec_help qdrant-backup -o /data/backup

# Восстановить все коллекции onec_* из последних снапшотов в data/backup/ (в контейнере: /data/backup)
qdrant-restore:
	$(COMPOSE) exec mcp python -m onec_help qdrant-restore --backup-dir /data/backup

help:
	@echo "1C Help MCP — Docker (по умолчанию split)"
	@echo ""
	@echo "  make build            Сборка образов mcp+ingest-worker (split). SERVICE=mcp|ingest-worker"
	@echo "  make build-nocache    Сборка образов mcp+ingest-worker (split). SERVICE=mcp|ingest-worker" --no-cache
	@echo "  make build-full       Сборка образа mcp (full)"
	@echo "  make parse-fastcode   Parse FastCode.im → fastcode_snippets.json"
	@echo "  make parse-helpf      Parse HelpF.pro FAQ/Files → helpf_snippets.json"
	@echo "  make load-snippets    Load snippets from SNIPPETS_DIR"
	@echo "  make load-snippets-from-project  Load from 1C project"
	@echo "  make load-standards   Load standards (STANDARDS_REPOS)"
	@echo "  make snippets         parse-fastcode + parse-helpf (FAQ) + load-snippets"
	@echo "  make init             ingest + load-snippets + load-standards (не стирает)"
	@echo "  make reinit           init (если индекс есть — без стирания). reinit ARGS='--force' — стереть и init"
	@echo "  make unpack-help      Распаковка .hbk без индексации"
	@echo "  make ingest           Индексация .hbk (требует make ingest-up)"
	@echo "  make ingest-full      Индексация (full, mcp)"
	@echo "  make build-index      Построение structured help из unpacked HTML (ARGS=путь)"
	@echo "  make add-bm25         Добавить BM25 sparse. ARGS='--collection onec_config_metadata' — только эта коллекция"
	@echo "  make dashboard        Дашборд (Tasks, Errors, Qdrant). ARGS='--once' — один кадр"
	@echo "  make fetch-bsl-bridge  Клонировать mcp-bsl-lsp-bridge (для Windows)"
	@echo "  make up               Start qdrant + mcp (по умолчанию только эти два)"
	@echo "  make ingest-up        Start + ingest-worker (watchdog, индексация)"
	@echo "  make ingest-down      Stop ingest-worker"
	@echo "  make up-full          Start full (один контейнер mcp)"
	@echo "  make down             Stop все сервисы"
	@echo "  make bsl-start        BSL LS bridge only (отдельно от up)"
	@echo "  make bsl-stop         Stop BSL bridge"
	@echo "  make ensure-data      Создать data/qdrant и др. (после потери базы)"
	@echo "  make qdrant-logs      Логи qdrant (при exit 101)"
	@echo "  make ingest-logs     Логи ingest-worker (эмбеддинги, fallback)"
	@echo "  make reset-metadata-watchdog  Сбросить metadata в watchdog и сразу запустить metadata-graph-build (нужен make ingest-up)"
	@echo "  make kd2-snapshot-build      Построить/обновить snapshot из KD2 XML (по умолчанию в data/kd2)"
	@echo "  make metadata-build          Запустить metadata-graph-build вручную (primary: data/kd2; files route deprecated)"
	@echo "  make metadata-watchdog-debug Диагностика: путь конфигурации, find_config_root, число файлов, ключ Redis"
	@echo "  make ollama-logs      Последние 100 строк лога Ollama (~/.ollama/logs/server.log)"
	@echo "  make qdrant-reset     Удалить data/qdrant, перезапустить с пустым индексом"
	@echo "  make qdrant-backup    Снапшот → data/backup/ (для миграции)"
	@echo "  make qdrant-restore   Восстановить из data/backup/"
	@echo ""
	@echo "При qdrant exit 101: make qdrant-logs, затем make qdrant-reset && make up && make ingest"
	@echo "Миграция индекса с другого хоста: docs/qdrant-migration.md"
	@echo "Compose требует оба файла: -f docker-compose.base.yml -f docker-compose.yml"
	@echo ""
	@echo "Args: ARGS=...  make ingest ARGS='--dry-run'"
