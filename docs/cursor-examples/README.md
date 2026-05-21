# Cursor: skills и rules (эталон в репозитории)

Каталог **`docs/cursor-examples/`** — единственная копия в git. Папка **`.cursor/`** не коммитится (см. `.gitignore`); после клонирования или обновления скиллов скопируйте отсюда в свой `.cursor/`.

## Синхронизация в локальный `.cursor/skills/`

Из корня репозитория:

```bash
for d in 1c-explain-object 1c-mcp-development 1c-mcp-token-budget 1c-mcp-tools-report 1c-platform-cli bsl-language-server-local; do
  mkdir -p .cursor/skills/$d
  rsync -a --delete "docs/cursor-examples/$d/" ".cursor/skills/$d/"
done
```

Правила (`.mdc`):

```bash
mkdir -p .cursor/rules
cp docs/cursor-examples/rules/*.mdc .cursor/rules/
```

Обратное копирование (если правили только локально): скопируйте изменённый файл в `docs/cursor-examples/...` и закоммитьте.

## Skills

| Каталог | Назначение |
|---------|------------|
| `1c-mcp-development/` | Основной workflow: MCP onec-context-mcp, BSL LS, тесты Python, метаданные. См. `reference.md`. |
| `1c-mcp-token-budget/` | Порядок вызовов MCP, экономия контекста, шпаргалки по СКД. |
| `1c-mcp-tools-report/` | Как читать отчёт о полноте инструментов MCP. |
| `1c-explain-object/` | Авто-документирование объектов конфигурации. |
| `1c-platform-cli/` | ragent/rac, ibcmd, временная ИБ, epf и т.д. |
| `bsl-language-server-local/` | CLI `analyze` / `format`; JAR не в git — см. `README.md` в каталоге. |

## Rules (`rules/*.mdc`)

Краткие правила для контекста: конвенции проекта, workflow MCP, тесты, BSL и источники справки. Копируйте в `.cursor/rules/` (см. выше).

## Связь с документацией проекта

- [AGENTS.md](../../AGENTS.md) — полный workflow агента и MCP.
- [mcp-tools-reference.md](../reference/mcp-tools-reference.md) — параметры инструментов (канон при расхождении с кэшем Cursor).
- [mcp-cursor-tool-schemas/](../reference/mcp-cursor-tool-schemas/README.md) — снимки схем для частых ошибок валидации.
- [bsl-ls-mcp-setup.md](../reference/bsl-ls-mcp-setup.md) — BSL Language Server.

## Зависимость для разработчиков репозитория

При изменении MCP, `AGENTS.md` или этих скиллов — обновляйте **`docs/cursor-examples/`** и при необходимости выполняйте синхронизацию у себя в `.cursor/`.
