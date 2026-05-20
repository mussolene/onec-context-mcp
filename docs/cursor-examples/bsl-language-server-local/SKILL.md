---
name: bsl-language-server-local
description: Локальный CLI BSL Language Server (диагностика и форматирование .bsl без MCP LSP). Применять при правках BSL вне Docker, офлайн-проверке модулей, скриптах в репозитории.
---

# BSL Language Server (локальный JAR)

## Назначение

Запуск **bsl-language-server** в режимах `analyze` и `format` из **exec-JAR** рядом со скиллом (или по `BSL_LS_JAR`). Сочетается с MCP **onec-context-mcp**: справка и API — **onec-context-mcp**; статический анализ и стиль — **BSL LS** (этот скилл).

## Расположение JAR

- Репозиторий (пример пути после копирования): `docs/cursor-examples/bsl-language-server-local/bsl-language-server-exec.jar` — **не коммитится** (большой бинарник). Скопируйте сборку из проекта BSL LS, например:
  - `…/bsl-language-server/build/libs/bsl-language-server-*-exec.jar` → переименуйте в `bsl-language-server-exec.jar`.
- Локально в Cursor (часто gitignored): `.cursor/skills/bsl-language-server-local/bsl-language-server-exec.jar`.
- Переменная: `BSL_LS_JAR` — явный путь к JAR, если не используется путь по умолчанию.

## Как устроен `analyze`

- Режим **не LSP**: однократный обход **`--srcDir`** (файл или каталог `.bsl`), применяются встроенные диагностики BSL Language Server (стиль, устаревшие методы, пустые `Исключение`, «недопустимые» символы в комментариях и т.д.).
- **`-o` / `--outputDir`**: каталог должен **уже существовать**, иначе запись `bsl-json.json` падает с `FileNotFoundException`.
- **`-r json`**: отчёт в **`bsl-json.json`** внутри `outputDir` (массив `diagnostics` с полями `severity`, `code`, `message`, `range`).
- Уровни: **`Error`** — исправлять в первую очередь; `Warning` / `Information` / `Hint` — по политике проекта.

## Команды

```bash
JAR="${BSL_LS_JAR:-docs/cursor-examples/bsl-language-server-local/bsl-language-server-exec.jar}"

# Диагностика каталога (JSON-отчёт: в outputDir появляется bsl-json.json)
mkdir -p /path/to/report-dir
java -jar "$JAR" analyze -s /path/to/bsl/sources -r json -o /path/to/report-dir -q

# Консольный вывод
java -jar "$JAR" analyze -s /path/to/dir -r console -q

# Форматирование (in-place по файлу или каталогу)
java -jar "$JAR" format -s /path/to/File.bsl -q
java -jar "$JAR" format -s /path/to/modules/dir -q
```

Опции: `-c` путь к конфигурации BSL LS; `analyze --help` / `format --help` — полный список.

## Согласование со справкой 1С (onec-context-mcp)

BSL LS проверяет **стиль и типовые диагностики**; **семантику платформы** (доступность методов, поведение в тонком/толстом клиенте, точные сигнатуры) при спорных случаях сверяйте через MCP **onec-context-mcp**: `get_1c_api_answer`, `search_1c_api`, `answer_1c_help_question`. Диагностика «ошибка» от LS не отменяет ограничений справки и режима исполнения.

## Workflow для агента

1. После правок `.bsl` — при необходимости `format -s <файл или каталог>`.
2. `analyze -s … -r json -o …` — разбор отчёта; критичные замечания устранить.
3. По смыслу API/ограничениям платформы — **onec-context-mcp**, не только LS.

## Версия

В скилле зафиксирована проверенная сборка: **0.29.0-rc.1.12-SNAPSHOT** (exec). При обновлении JAR обновите эту строку и прогоните `analyze` на тестовом каталоге.
