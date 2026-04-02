# Аудит безопасности 1C Help MCP

Артефакты аудита безопасности проекта onec_help.

## Содержимое

| Файл | Описание |
|------|----------|
| [nda-checklist.md](nda-checklist.md) | Чеклист NDA при работе с конфиденциальным кодом |
| [nda-executor-template.md](nda-executor-template.md) | Шаблон соглашения о неразглашении для исполнителя аудита |
| [audit-runbook.md](audit-runbook.md) | Runbook: пошаговый сценарий аудита (4 фазы) |
| [code-review-verification.md](code-review-verification.md) | Верификация критических участков кода |
| [findings-report.md](findings-report.md) | Отчёт о находках (pip-audit, bandit, ручной анализ) |
| [recommendations-backlog.md](recommendations-backlog.md) | Приоритизированный backlog исправлений |

## План аудита

Полный план — `docs/security-audit-prompt.md` (промпт), [audit-runbook.md](audit-runbook.md) (сценарий выполнения).

## Использование в code review и CI

- При ревью изменений, затрагивающих безопасность (Docker/compose, env, MCP, embedding, Qdrant, Redis, snippets, metadata), используйте:
  - [code-review-verification.md](code-review-verification.md) — чек‑лист по критическим участкам и дополнительным проверкам (порты, логи, сниппеты, embedding).
  - [nda-checklist.md](nda-checklist.md) — при работе с конфиденциальным кодом/конфигурацией 1С.
- В CI дополнительно к pip-audit, hadolint и trivy запускается `scripts/ci_security_checks.py`, который:
  - запрещает появление закоммиченных `.env`‑файлов (кроме `env.example`);
  - проверяет, что в docker-compose по умолчанию нет привязок `0.0.0.0:PORT` (используется localhost или внутренняя сеть).

## Запуск сканов

```bash
# Зависимости
pip-audit

# SAST
bandit -r src/onec_help

# Docker (если установлены)
trivy image python:3.14-slim
hadolint Dockerfile
```
