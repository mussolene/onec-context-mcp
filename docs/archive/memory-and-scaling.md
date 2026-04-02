# Память и масштабирование

## Трёхуровневая память (triple-write)

При `MEMORY_ENABLED=1` каждое событие (get_topic, save_snippet) записывается в три уровня:

| Уровень | Хранилище | Содержимое |
|---------|-----------|------------|
| **Short** | Память процесса (deque) | Сырые данные: topic_path, title, query, timestamp |
| **Medium** | JSONL-файл `session_memory.jsonl` | Саммари по шаблону; TTL 7 дней |
| **Long** | Qdrant `onec_help_memory` | Краткое саммари + embedding для семантического поиска |

Если embedding недоступен — запись идёт в pending (`pending_memory.json`). Watchdog периодически обрабатывает pending при появлении API.

## Watchdog и Cron

- **Cron (3:00)** — полная индексация по расписанию
- **Watchdog** (по умолчанию включён, `WATCHDOG_ENABLED=1`) — мониторинг .hbk, STANDARDS_DIR и SNIPPETS_DIR; при изменении — ingest / load-standards / load-snippets; каждые N минут — обработка pending memory. Отключить: `WATCHDOG_ENABLED=0`.

Переменные: `WATCHDOG_ENABLED`, `WATCHDOG_POLL_INTERVAL`, `WATCHDOG_PENDING_INTERVAL`.

## Задел под масштабирование

Будущие домены для индексации:

| Домен | Коллекция | Источник |
|-------|-----------|----------|
| Справка | onec_help | .hbk, ingest |
| Память | onec_help_memory | MCP, save_snippet |
| Код 1С | onec_help_code | Разбор .bsl |
| Метаданные | onec_help_metadata | XML конфигурации |

Единая модель MemoryStore с полем `domain`; при поиске — опция `domains`.
