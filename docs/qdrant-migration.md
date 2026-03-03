# Миграция индекса Qdrant между хостами

Копирование `data/qdrant` между Mac и Windows приводит к повреждению WAL («missing segment(s)»). Используйте **снапшоты** через `make qdrant-backup` и `make qdrant-restore`.

---

## 1. На исходном хосте (Mac / Linux)

```bash
make up          # если ещё не запущено
make qdrant-backup
```

Снапшот сохраняется в `data/backup/onec_help-{timestamp}.snapshot`.

Скопируйте папку `data/backup/` на целевой хост (флешка, сеть, облако).

---

## 2. На целевом хосте (Windows)

```powershell
make qdrant-reset   # очистить повреждённые данные
make up             # запустить сервисы
make qdrant-restore # восстановить из последнего снапшота в data/backup/
```

---

## CLI (локально или в контейнере)

```bash
# Backup
python -m onec_help qdrant-backup -o data/backup

# Restore (последний снапшот)
python -m onec_help qdrant-restore

# Restore из конкретного файла
python -m onec_help qdrant-restore -f data/backup/onec_help-20260302-120000.snapshot
```

---

## Миграция на TOC (новый payload)

После перехода на разбор по TOC (распаковка через HBK binary container или ручное добавление `.toc.json`) нужно переиндексировать справку, чтобы в payload попали `breadcrumb`, `section_path`, `title` из TOC и корректный `entity_type`.

1. Очистить коллекции и кэш: **`reinit --force`** (локально или в контейнере).
2. Запустить загрузку: **init** или **ingest** / **ingest-from-unpacked** (при использовании `data/unpacked`).
3. Проверить MCP: вызовы `get_1c_help_topic`, `search_1c_help_*` возвращают в payload поля `breadcrumb`, `entity_type` при наличии .toc.json в каталоге справки.

Без переиндексации старые точки останутся с прежним payload (без breadcrumb из TOC).

---

## Версии Qdrant

Исходный и целевой Qdrant должны совпадать по минорной версии (например, оба 1.12.x).
