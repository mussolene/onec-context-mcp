# Отчёт о находках аудита безопасности 1C Help MCP

**Дата:** 2026-02-27  
**Последнее обновление:** 2026-03-01  
**Инструменты:** pip-audit, bandit, ruff  
**CI:** trivy, hadolint — [.github/workflows/security.yml](../../.github/workflows/security.yml)

---

## Последний прогон сканов (2026-03-01)

| Инструмент | Результат |
|------------|-----------|
| pip-audit | 1 уязвимость: pip 25.3 (CVE-2026-1703) → remediated в CI (upgrade pip>=26) |
| bandit | 24 Medium, 33 Low — большая часть в backlog (AUDIT-001–017 исправлены или приняты) |
| ruff | 0 находок |

---

## Резюме

| Severity | Количество |
|----------|------------|
| Critical | 2 |
| High     | 2 |
| Medium   | 6 |
| Low      | 7 |

---

## Находки (шаблон)

### AUDIT-001: CVE в pip (dependency)

| Поле | Значение |
|------|----------|
| **Severity** | Medium |
| **Область** | Dependencies |
| **Описание** | pip 25.3 содержит уязвимость CVE-2026-1703. Требуется обновление до 26.0. |
| **Воспроизведение** | `pip-audit` |
| **Remediation** | Обновить pip: `pip install --upgrade pip` |
| **Ссылки** | CVE-2026-1703 |

---

### AUDIT-002: Binding to all interfaces (Flask serve)

| Поле | Значение |
|------|----------|
| **Severity** | Medium |
| **Область** | Web |
| **Описание** | `app.run(host="0.0.0.0", port=port)` — привязка ко всем интерфейсам. По design для Docker, но при локальном запуске может открыть доступ из сети. |
| **Воспроизведение** | bandit B104, `cli.py:58` |
| **Remediation** | Документировать; при необходимости добавить `HELP_SERVE_HOST` (default 127.0.0.1 для локального запуска) |
| **Ссылки** | CWE-605 |

---

### AUDIT-003: Hardcoded temp directory

| Поле | Значение |
|------|----------|
| **Severity** | Medium |
| **Область** | Secrets / Config |
| **Описание** | Дефолт `INGEST_TEMP_DIR=/tmp/help_ingest` — возможна race при shared /tmp. |
| **Воспроизведение** | bandit B108, `cli.py:291` |
| **Remediation** | Использовать `tempfile.mkdtemp()` или `TMPDIR`; документировать override через env |
| **Ссылки** | CWE-377 |

---

### AUDIT-004: urlopen — audit for permitted schemes (embedding)

| Поле | Значение |
|------|----------|
| **Severity** | Medium |
| **Область** | External Services |
| **Описание** | `urllib.request.urlopen` в embedding.py — может допускать file:/ или custom schemes при контроле EMBEDDING_API_URL. |
| **Воспроизведение** | bandit B310, `embedding.py:162` |
| **Remediation** | Валидировать схему URL (только http/https) перед вызовом |
| **Ссылки** | CWE-22 |

---

### AUDIT-005: urlopen — SSRF / scheme validation (standards_loader)

| Поле | Значение |
|------|----------|
| **Severity** | Medium |
| **Область** | External Services |
| **Описание** | `urlopen` к `github.com/{owner}/{repo}/archive/...`. owner/repo из STANDARDS_REPOS — при контроле env возможен SSRF; urlopen допускает file:/ и custom schemes. |
| **Воспроизведение** | bandit B310, `standards_loader.py:70` |
| **Remediation** | Валидировать owner/repo (только github.com); разрешить только https:// |
| **Ссылки** | CWE-22 |

---

### AUDIT-007–AUDIT-012: Bandit LOW (информационные)

| ID | Файл | Тест | Описание |
|----|------|------|----------|
| AUDIT-007 | embedding.py | B110 | try/except pass |
| AUDIT-008 | form_metadata.py | — | xml.etree — см. AUDIT-015 |
| AUDIT-009 | indexer.py | B110 | try/except pass |
| AUDIT-010 | mcp_server.py | B404, B603 | subprocess — фиксированные аргументы, low risk |
| AUDIT-011 | memory.py | B110 | try/except pass |
| AUDIT-012 | unpack.py, watchdog.py | B404, B603, B607 | subprocess — list-аргументы, принятый риск |

**Remediation (общая):** try/except pass — добавить логирование. subprocess — list-аргументы без shell, принятый риск.

---

## Ручной анализ (по плану аудита)

### AUDIT-013 (manual): Обход allowlist при serve через CLI

| Поле | Значение |
|------|----------|
| **Severity** | Critical |
| **Область** | Web |
| **Описание** | `serve <directory>` из CLI устанавливает BASE_DIR без проверки HELP_SERVE_ALLOWED_DIRS. Позволяет раздавать произвольный каталог. |
| **Воспроизведение** | `python -m onec_help serve /etc` при пустом allowlist |
| **Remediation** | Проверять directory против allowlist в cmd_serve до app.run |
| **Ссылки** | — |

### AUDIT-014 (manual): Отсутствие аутентификации на MCP и serve

| Поле | Значение |
|------|----------|
| **Severity** | Critical (при доступе из ненадёжной сети) |
| **Область** | Web, MCP |
| **Описание** | Нет auth на Flask и MCP. По design для доверенной сети; при экспозиции в интернет — полный доступ. |
| **Remediation** | Документировать; при необходимости — reverse proxy с auth |
| **Ссылки** | — |

### AUDIT-015 (manual): XML parsing без defusedxml

| Поле | Значение |
|------|----------|
| **Severity** | High |
| **Область** | Parsing |
| **Описание** | form_metadata.py использует ET.fromstring на XML. XXE/entity expansion при недоверенном вводе. |
| **Remediation** | defusedxml для XML от пользователя или внешних источников |
| **Ссылки** | CWE-611 |

### AUDIT-016 (manual): Отсутствие rate limiting на MCP

| Поле | Значение |
|------|----------|
| **Severity** | High |
| **Область** | MCP |
| **Описание** | DoS при массовых запросах; нагрузка на embedding API. |
| **Remediation** | Rate limiting на уровне MCP или reverse proxy |
| **Ссылки** | — |

### AUDIT-017 (manual): Нет лимитов на размер query/code_snippet

| Поле | Значение |
|------|----------|
| **Severity** | Medium |
| **Область** | MCP |
| **Описание** | Длинные query и code_snippet могут вызвать DoS или переполнение. |
| **Remediation** | Ограничить длину (например, 64 KB) |
| **Ссылки** | — |

---

## Результаты ruff

Ruff check (с учётом pyproject.toml ignores): 0 находок.

---

## Дополнительные находки bandit (информационно)

- **B108** (cli.py): `unpack-diag` default `--output-dir /tmp/unpack_diag` — диагностическая утилита, низкий риск.
- **B323** (parse_helpf.py): `ssl._create_unverified_context()` — fallback при отсутствии CA bundle (Mac); помечено `# noqa: S323`.

## Запуск сканов

- **Локально:** см. [README.md](README.md) и [audit-runbook.md](audit-runbook.md).
- **CI:** hadolint, trivy fs — автоматически при push/PR.
