# Cursor: Skill и Rules — примеры для индексации

Примеры Skill и Rules для Cursor, используемые при работе с 1c-help и lsp-bsl-bridge MCP.

## Назначение

- **Индексация:** содержимое `docs/cursor-examples/` в репозитории и доступно для поиска по кодовой базе; папка `.cursor/` полностью исключена из git (см. `.gitignore`).
- **Синхронизация:** при изменении поведения MCP или workflow в проекте обновите эти примеры — они служат эталоном и исходником для копирования в `.cursor/skills/` и `.cursor/rules/`.
- **JSON-схемы инструментов в Cursor:** кэш дескрипторов в `~/.cursor/.../mcps/<server>/tools/*.json` может отставать от сигнатур FastMCP в `src/onec_help/interfaces/mcp_server.py`. Канон параметров — код сервера и [mcp-tools-reference.md](../reference/mcp-tools-reference.md); эталонные снимки для частых расхождений — [docs/reference/mcp-cursor-tool-schemas/](../reference/mcp-cursor-tool-schemas/README.md). При `Internal error` / validation errors сверяйте аргументы с reference (например `get_module_info` → только `uri_or_path`, `get_form_metadata` → `xml_content`, `get_1c_context_bundle` без `domains`).
- **Зависимость для доработки:** при доработке MCP, AGENTS.md или workflow разработки 1С проверьте соответствие с `docs/cursor-examples/` и при необходимости внесите правки.

## Структура

```
docs/cursor-examples/
├── README.md                 # Этот файл
├── 1c-mcp-development/       # Skill: разработка 1С с MCP
│   ├── SKILL.md
│   └── reference.md
├── 1c-mcp-tools-report/     # Skill: отчёт о полноте инструментов MCP
│   └── SKILL.md
├── 1c-explain-object/        # Skill: авто-документирование объектов конфигурации
│   └── SKILL.md
├── bsl-language-server-local/  # Skill: CLI BSL LS (analyze/format), JAR не в git
│   ├── SKILL.md
│   ├── README.md
│   └── .gitignore
├── 1c-platform-cli/          # Skill: ragent/rac/ras, ibsrv/ibcmd, SSH к автономному серверу, CREATEINFOBASE, 1cv8 (см. руководство администратора)
│   └── SKILL.md
└── rules/                    # Rules (.mdc)
    ├── 1c-bsl-standards.mdc
    ├── 1c-mcp-workflow.mdc
    ├── 1c-mcp-tools-report.mdc   # Рекомендации по отчёту (пустые ответы, URI, координаты)
    ├── 1c-explain-object.mdc     # Авто-документирование: как работает поле/кнопка/объект
    ├── 1c-project-conventions.mdc
    ├── 1c-testing-workflow.mdc
    └── 1c-sources-and-help.mdc
```

## Использование

1. **Копирование в .cursor:** при первом клонировании или настройке Cursor скопируйте:
   - `docs/cursor-examples/1c-mcp-development/` → `.cursor/skills/1c-mcp-development/`
   - `docs/cursor-examples/1c-mcp-tools-report/` → `.cursor/skills/1c-mcp-tools-report/`
   - `docs/cursor-examples/1c-explain-object/` → `.cursor/skills/1c-explain-object/`
   - `docs/cursor-examples/bsl-language-server-local/` → `.cursor/skills/bsl-language-server-local/` (и положите туда `bsl-language-server-exec.jar`, см. README в каталоге)
   - `docs/cursor-examples/1c-platform-cli/` → `.cursor/skills/1c-platform-cli/`
   - `docs/cursor-examples/rules/*.mdc` → `.cursor/rules/`

2. **Обновление после изменений:** если вы изменили skill или rules в `.cursor/` и хотите зафиксировать их в репозитории — скопируйте обратно в `docs/cursor-examples/` и закоммитьте.

3. **Инструкция по умолчанию и MCP entry point:** при открытии/редактировании `.bsl` правило **1c-mcp-workflow** подставляет краткий порядок вызовов в контекст. **В новом AI-чате по 1С:** начать с `get_1c_quick_guide(task="develop"|"refactor"|"test")`. Промпт **how_to_use_1c_help_and_bsl_bridge** оставлен как длинная human/onboarding инструкция, а не как default AI route.

4. **Самодокументируемый MCP:** если MCP запущен с путём к docs (в Docker по умолчанию `MCP_CURSOR_DOCS_PATH=/app/docs`), руководства можно получить из самого MCP. Для AI по умолчанию использовать `get_1c_quick_guide`; `get_mcp_workflow_guide`, `get_mcp_tools_tips`, `get_mcp_tools_summary`, `get_mcp_guides_bundle` нужны для human/onboarding и восстановления IDE-конфига.

5. **Использование в другом проекте (вне 1c_hbk_helper):** правила и скилл не привязаны к путям этого репозитория. В своём проекте 1С/BSL: подключите 1c-help и lsp-bsl-bridge по URL; скопируйте правила и скилл из этого каталога в свой `.cursor/` или получите их через промпты MCP (get_mcp_guides_bundle и др.). URI для LSP — `file:///projects/<ваш_путь>` (Docker) или полный file URI. Подробнее: отчёт § «Использование вне репозитория 1c_hbk_helper».

## Связь с проектом

- См. [AGENTS.md](../../AGENTS.md) — workflow разработки 1С с BSL LS, embedding и индексация.
- См. [1c-testing-guide.md](../reference/1c-testing-guide.md) — тестирование 1С: YaxUnit (unit), Vanessa-Automation (BDD, xdd, UI), где искать тесты, что применять.
- См. [embedding.md](../reference/embedding.md) — пайплайн embedding (batch/single, retry, 429), точки интеграции.
- См. [mcp-tools-cheatsheet.md](../reference/mcp-tools-cheatsheet.md) — одностраничная шпаргалка по инструментам и промптам.
- См. [mcp-tools-reference.md](../reference/mcp-tools-reference.md) — справочник MCP-инструментов 1c-help (параметры, лимиты, порядок вызовов).
- См. [mcp-1c-help-tools-report.md](../archive/mcp-1c-help-tools-report.md) — отчёт о полноте 1c-help и lsp-bsl-bridge, результаты прогона, рекомендации; оформлен как skill и правило в 1c-mcp-tools-report.
- См. [bsl-ls-mcp-setup.md](../reference/bsl-ls-mcp-setup.md) — подключение BSL LS как MCP.
