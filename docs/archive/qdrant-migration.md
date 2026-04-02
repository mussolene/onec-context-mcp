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

## Переиндексация (новый payload, TOC)

Чтобы обновить payload (breadcrumb, section_path, title, entity_type из TOC): выполните **`reinit --force`** — очистка коллекций и кэша, затем ingest и загрузка сниппетов/стандартов. Отдельные шаги не требуются.

---

## Версии Qdrant

Исходный и целевой Qdrant должны совпадать по минорной версии (например, оба 1.12.x).
