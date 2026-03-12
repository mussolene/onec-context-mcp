# Верификация код-ревью (аудит безопасности)

Проверка критических участков кода по плану аудита. Дата: 2026-03-01.

## Результаты

| Участок | Проверка | Статус |
|---------|----------|--------|
| `embedding.py` | `_is_safe_embedding_url` — только http/https | OK |
| `embedding.py` | `_mask_url_for_log` — URL не в логах полностью | OK |
| `entrypoint.sh` | EMBEDDING_API_KEY исключён из `.ingest_env` | OK |
| `web.py`, `cli.py` | `HELP_SERVE_ALLOWED_DIRS`, `_directory_allowed` до serve | OK |
| `form_metadata.py` | defusedxml при наличии (try/import) | OK |
| `memory.py` | Хранение JSONL/Qdrant, `path_inside_base` | OK |
| `standards_loader.py` | Валидация owner/repo, только https://github.com | OK |

## Дополнительные проверки для новых изменений

- При изменениях Docker/compose и env:
  - MCP и Qdrant по умолчанию не публикуются на 0.0.0.0 (только localhost или внутренняя Docker‑сеть).
  - Нет новых проброшенных портов без явного комментария о необходимости и способе защиты (reverse proxy, TLS, auth).
- При изменениях, касающихся сниппетов и памяти:
  - Логика save_1c_snippet не пишет лишних данных в логи и метрики; размер code_snippet ограничен и соответствует ожиданиям.
  - SNIPPETS_DIR и MEMORY_BASE_PATH не «утекают» в публичные сообщения об ошибках.
- При изменениях embedding API:
  - Значения EMBEDDING_API_URL и EMBEDDING_API_KEY не логируются и не попадают в исключения целиком.

## CI

- pip-audit, hadolint, trivy — в [.github/workflows/security.yml](../../.github/workflows/security.yml)
- pip обновляется до >=26 перед pip-audit (CVE-2026-1703)
