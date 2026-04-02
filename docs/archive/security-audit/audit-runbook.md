# Runbook: аудит безопасности и NDA

Пошаговый сценарий проведения аудита по плану «Security Audit and NDA» (см. [security-audit-prompt.md](../security-audit-prompt.md)).

## Фаза 1: Подготовка

1. **NDA и договорённости**
   - [ ] Подписать [nda-executor-template.md](nda-executor-template.md) до начала работы
   - [ ] Определить круг лиц с доступом к результатам
   - [ ] Выделить защищённое хранилище для артефактов
   - [ ] Зафиксировать политику хранения и удаления

2. **Окружение**
   - [ ] Запускать аудит в изолированной среде (локальная машина / VPN)
   - [ ] Не выносить код и данные за пределы доверенной зоны

3. **Чеклист**
   - [ ] Пройти [nda-checklist.md](nda-checklist.md) перед началом

## Фаза 2: Анализ

1. **Зависимости**
   ```bash
   pip-audit
   bandit -r src/onec_help
   ```

2. **Код-ревью** — проверить участки:
   - `src/onec_help/embedding.py` — `_is_safe_embedding_url`, `_mask_url_for_log`
   - `entrypoint.sh` — исключение EMBEDDING_API_KEY из `.ingest_env`
   - `src/onec_help/web.py`, `src/onec_help/cli.py` — HELP_SERVE_ALLOWED_DIRS, path traversal
   - `src/onec_help/form_metadata.py` — defusedxml
   - `src/onec_help/memory.py` — права на каталоги, JSONL/Qdrant
   - `src/onec_help/standards_loader.py` — валидация owner/repo

3. **Конфигурация**
   - [ ] EMBEDDING_API_KEY не в репо
   - [ ] PRODUCTION=1 маскирует детали в логах
   - [ ] SAVE_SNIPPET_TO_FILES=0 в production‑среде или SNIPPETS_DIR указывает на защищённый том
   - [ ] STANDARDS_DIR и ONEC_CONFIG_SOURCE_DIR (`data/config`) расположены на защищённых томах (NDA‑периметр)

## Фаза 3: Тестирование

1. **Веб и MCP**
   - [ ] Path traversal: `serve /etc` при пустом allowlist — отказ
   - [ ] MCP rate limit и лимиты query/code_snippet (64 KB)

2. **Docker**
   - В CI: [.github/workflows/security.yml](../../../.github/workflows/security.yml) — hadolint, trivy fs
   - Локально (если установлены): `trivy fs .`, `hadolint Dockerfile`

## Фаза 4: Отчёт

1. Оформить находки по шаблону [findings-report.md](findings-report.md)
2. Сохранить отчёт в защищённом хранилище
3. При NDA: обезличить пути, токены, сниппеты; не включать SNIPPETS_DIR, MEMORY_BASE_PATH, EMBEDDING_API_URL
4. Пройти [nda-checklist.md](nda-checklist.md) после завершения
