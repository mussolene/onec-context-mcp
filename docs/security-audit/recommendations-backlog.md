# Рекомендации по результатам аудита безопасности

Приоритизированный backlog исправлений по [findings-report.md](findings-report.md).

**Статус (2026-02):** пункты 1–10 и инфраструктура реализованы.

---

## Критичный приоритет

| # | AUDIT | Действие | Статус |
|---|-------|----------|--------|
| 1 | AUDIT-013 | Проверять `directory` в `cmd_serve` против `HELP_SERVE_ALLOWED_DIRS` до `app.run` | done |
| 2 | AUDIT-014 | Документировать отсутствие auth в README/AGENTS.md | done |

---

## Высокий приоритет

| # | AUDIT | Действие | Статус |
|---|-------|----------|--------|
| 3 | AUDIT-015 | defusedxml в form_metadata.py | done |
| 4 | AUDIT-016 | Rate limiting на MCP (MCP_RATE_LIMIT_PER_MIN) | done |
| 5 | AUDIT-005 | Валидация owner/repo в standards_loader.py | done |
| 6 | AUDIT-004 | Валидация URL (http/https) в embedding.py | done |

---

## Средний приоритет

| # | AUDIT | Действие | Статус |
|---|-------|----------|--------|
| 7 | AUDIT-001 | pip>=26 в security.yml | done |
| 8 | AUDIT-002 | HELP_SERVE_HOST (default 127.0.0.1) | done |
| 9 | AUDIT-003 | tempfile.gettempdir() для INGEST_TEMP_DIR | done |
| 10 | AUDIT-017 | Лимиты query/code_snippet (64 KB) в MCP | done |

---

## Низкий приоритет / принятые риски

| # | AUDIT | Действие | Статус |
|---|-------|----------|--------|
| 11 | AUDIT-007–012 | try/except pass: добавить логирование | done |
| 12 | Subprocess (unpack, mcp, watchdog) | Оставить как есть | list-аргументы, без shell |
| 13 | FastCode URL | Валидировать href (относительные vs //evil.com) | done |

---

## Инфраструктура и процессы

| Действие | Статус |
|----------|--------|
| trivy fs в CI | done (.github/workflows/security.yml) |
| hadolint в CI | done (.github/workflows/security.yml) |
| pip-audit | test.yml + security.yml |
| pip>=26 | security.yml |

---

## Оценки

- **S** — small (до 2 ч)
- **M** — medium (2–8 ч)
