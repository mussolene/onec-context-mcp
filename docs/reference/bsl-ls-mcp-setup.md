# BSL Language Server: CLI, IDE и опционально Docker

Читайте этот файл, если нужно проверять и форматировать `.bsl` рядом с MCP **1c-help**. Справка платформы — только через 1c-help; статический анализ BSL — через **BSL Language Server** (не через второй MCP в этом репозитории).

## Рекомендуемый путь: exec-JAR (`analyze` / `format`)

Пошагово и команды: [../cursor-examples/bsl-language-server-local/SKILL.md](../cursor-examples/bsl-language-server-local/SKILL.md).

Кратко:

```bash
JAR="${BSL_LS_JAR:-docs/cursor-examples/bsl-language-server-local/bsl-language-server-exec.jar}"
mkdir -p /path/to/report-dir
java -jar "$JAR" analyze -s /path/to/bsl/sources -r json -o /path/to/report-dir -q
java -jar "$JAR" format -s /path/to/File.bsl -q
```

## IDE

Расширение **1C (BSL)** / BSL Language Server в VS Code или Cursor даёт диагностики и навигацию по открытому проекту без отдельного MCP-сервера.

## Опционально: Docker в этом репозитории

Отдельный compose поднимает контейнер с BSL LS и смонтированным проектом (`.:/projects:ro`):

```bash
make fetch-bsl-ls-docker-deps   # один раз: клон в deps/ для build context
make bsl-start                  # docker compose -f docker-compose.bsl.yml up -d
```

Остановка: `make bsl-stop`. Переменные см. в `docker-compose.bsl.yml` и `.env`.

Это **не** MCP **1c-help** (он на порту 8050). Подключение второго MCP в Cursor для обёртки LSP в этом документе не описывается: для агентов достаточно CLI `analyze` и инструментов IDE.

## См. также

- [mcp-tools-reference.md](mcp-tools-reference.md) — инструменты только 1c-help.
- [run.md](run.md) — запуск Qdrant и MCP 1c-help.
