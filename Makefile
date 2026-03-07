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

.PHONY: build build-full fetch-bsl-bridge parse-fastcode parse-helpf load-snippets load-snippets-from-project load-standards snippets
.PHONY: up down ingest-up ingest-down ingest-worker up-full down-full bsl-start bsl-stop qdrant-logs qdrant-reset qdrant-backup qdrant-restore ensure-data

# bsl-bridge: локальный клон (Git URL в context не работает на Docker Windows)
deps/mcp-bsl-lsp-bridge/.git/HEAD:
	git clone --depth 1 https://github.com/SteelMorgan/mcp-bsl-lsp-bridge.git deps/mcp-bsl-lsp-bridge

fetch-bsl-bridge: deps/mcp-bsl-lsp-bridge/.git/HEAD
.PHONY: init init-full reinit reinit-full ingest ingest-full build-index build-index-full add-bm25 add-bm25-full
.PHONY: dashboard unpack-help help

WATCH_INTERVAL ?= 2

# Сборка образов (split). SERVICE=mcp|ingest-worker — только один сервис
build:
	$(COMPOSE) build $(if $(SERVICE),$(SERVICE),mcp ingest-worker)

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

# Index from unpacked dir (after unpack-sync)
ingest-from-unpacked:
	$(COMPOSE) exec $(INGEST_SERVICE) python -m onec_help ingest-from-unpacked $(ARGS)

# Start (split: qdrant + mcp + ingest-worker)
# Каталоги data/* создаются Docker при volume mount — кросс-платформенно
# По умолчанию только qdrant + mcp
up:
	$(COMPOSE) up -d

# Запустить ingest-worker (watchdog): нужен после make up, если нужна индексация/стандарты/сниппеты
ingest-up:
	$(COMPOSE) --profile ingest up -d

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
	@mkdir -p data/qdrant data/unpacked data/ingest_cache data/snippets data/backup data/bm25_vocab data/standards
	@echo "data/qdrant и остальные каталоги созданы."

# При qdrant exit 101: логи и сброс данных. Использовать оба -f!
qdrant-logs:
	docker compose -f docker-compose.base.yml -f docker-compose.yml logs qdrant

# Удалить data/qdrant и перезапустить (если qdrant падает с 101 — повреждённые данные). Индекс будет потерян — затем make ingest
qdrant-reset:
	-$(COMPOSE) stop qdrant
	docker run --rm -v "$(CURDIR)/data:/data" alpine rm -rf /data/qdrant
	@echo "data/qdrant удалён. Запустите: make up; для индексации: make ingest-up"

# Снапшот коллекции → data/backup/onec_help-{timestamp}.snapshot (для миграции между хостами)
qdrant-backup:
	$(COMPOSE) exec mcp python -m onec_help qdrant-backup -o /data/backup

# Восстановить коллекцию из последнего снапшота в data/backup/ (в контейнере: /data/backup)
qdrant-restore:
	$(COMPOSE) exec mcp python -m onec_help qdrant-restore --backup-dir /data/backup

help:
	@echo "1C Help MCP — Docker (по умолчанию split)"
	@echo ""
	@echo "  make build            Сборка образов mcp+ingest-worker (split). SERVICE=mcp|ingest-worker"
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
	@echo "  make build-index      Индексация из папки (ARGS=путь)"
	@echo "  make add-bm25         Добавить BM25 sparse vectors (без re-ingest)"
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
	@echo "  make qdrant-reset     Удалить data/qdrant, перезапустить с пустым индексом"
	@echo "  make qdrant-backup    Снапшот → data/backup/ (для миграции)"
	@echo "  make qdrant-restore   Восстановить из data/backup/"
	@echo ""
	@echo "При qdrant exit 101: make qdrant-logs, затем make qdrant-reset && make up && make ingest"
	@echo "Миграция индекса с другого хоста: docs/qdrant-migration.md"
	@echo "Compose требует оба файла: -f docker-compose.base.yml -f docker-compose.yml"
	@echo ""
	@echo "Args: ARGS=...  make ingest ARGS='--dry-run'"
