# План: Веб-справка и pipeline (unpack → ingest → serve)

**Дата:** март 2025  
**Статус:** единый план

---

## 1. Выполнено

- **Serve: путь только из конфига** — HELP_SERVE_DATA_DIR → HELP_PATH → data/; Docker: serve без аргументов.
- **2.1 Структурированное дерево** — `categories.build_tree` при `__categories__`, иначе file tree.
- **2.2 Кросс-ссылки** — `_rewrite_content_links` для href/img.
- **2.3 Поиск Qdrant** — `/api/search`, hybrid RRF, UI блок «По индексу Qdrant».

---

## 2. План работ (чеклист)

### 2.1 Структурированное отображение
- [x] categories.build_tree вместо file tree
- [x] Заголовки из HTML, иерархия разделов
- [x] Fallback на file tree

### 2.2 Кросс-ссылки и навигация
- [x] Внутренние ссылки → loadContent
- [ ] Breadcrumb по section_path
- [ ] «См. также» из outgoing_links
- [ ] Навигация вверх/вниз по иерархии

### 2.3 Поиск
- [x] API search, hybrid RRF
- [x] Результаты в сайдбаре, клик → контент
- [ ] Режим «только в текущем разделе» (фильтр section_path)

### 2.4 Поведение как у справки
- [ ] Стилизация V8SH_*, MkDocs-style layout
- [ ] Подсветка BSL (highlight.js/Prism)
- [ ] Разворачиваемые секции (Синтаксис, Параметры)
- [ ] Метаданные: Доступность, Использование в версии

### 2.5 entity_type
- [ ] entity_type в payload (method/property/type/function)
- [ ] Фильтр в поиске по entity_type
- [ ] В вебе: вкладки «Методы», «Свойства», «Типы»

### 2.6 Pipeline (unpack, ingest, watchdog)
- [ ] unpack-sync → data/unpacked, .hbk_info.json
- [ ] ingest-from-unpacked, path `version/platform_lang/rel_path`
- [ ] Watchdog: unpack-sync + ingest-from-unpacked при изменении .hbk
- [ ] INGEST_USE_UNPACKED=1 — режим без temp

---

## 3. Разрешения и коммиты

**Разрешения** (запросить до начала): `git_write`, `network`, `all` (при необходимости).

**Коммиты по фазам:**

| Фаза | Сообщение |
|------|-----------|
| 1 | `feat(unpack): unpack-sync в data/unpacked, .hbk_info.json` |
| 2 | `feat(ingest): ingest-from-unpacked, path version/platform_lang` |
| 3 | `feat(indexer): entity_type в payload, фильтр поиска` |
| 4 | `feat(watchdog): unpack-sync + ingest-from-unpacked при изменении hbk` |
| 5 | `feat(web): breadcrumb, См. также, API метаданных` |
| 6 | `feat(web): MkDocs-style UI, подсветка BSL, сворачиваемые секции` |
| 7 | `docs: CHANGELOG и описания изменений` |

---

## 4. Структура данных и entity_type

**Каталог распаковки:**
```
data/unpacked/<version>/<platform>_<lang>/
  .hbk_info.json   # {source_file, label, version, language}
  (содержимое hbk) # __categories__, HTML — без изменений
```

**entity_type** (из section_path/breadcrumb):
- Методы/Methods → method
- Свойства/Properties → property
- Типы/Types → type
- Функции/Functions → function
- иначе → topic

---

## 5. UI: стиль MkDocs Material

- Боковая навигация, сворачиваемые узлы
- Breadcrumb над контентом
- Поиск в шапке
- «См. также» внизу контента
- Подсветка BSL в `.V8SH_codesample`, `pre`
- Сворачиваемые секции (Синтаксис, Параметры)
- Подсказка «Источник: 1cv8_ru.hbk» (из .hbk_info.json)

---

## 6. Инструменты проверки

**После каждой фазы:**
1. `uv run ruff check src tests && uv run ruff format src tests`
2. `uv run pytest tests -q --tb=short`
3. `make build && make up-serve`
4. Проверка http://localhost:8000 (mcp_web_fetch или браузер)

**Критерий готовности:** новичок может найти тему, открыть по дереву, перейти по «См. также» без инструкций.

---

## 7. Документирование

- `docs/CHANGELOG-serve.md` — лог изменений
- Обновить AGENTS.md, README.md
- Отмечать выполненные пункты в этом плане

---

## 8. Порядок реализации (фазы)

1. **unpack-sync** — run_unpack_sync, CLI, .hbk_info.json
2. **ingest-from-unpacked** — run_ingest_from_unpacked, path в индексе
3. **entity_type** — _infer_entity_type, payload, фильтр search
4. **watchdog** — unpack-sync + ingest-from-unpacked
5. **веб breadcrumb + См. также** — API ?meta=1, UI
6. **MkDocs-style UI** — стилизация, подсветка, секции
7. **документация** — CHANGELOG, опции (фильтр раздела, entity_type в UI)
