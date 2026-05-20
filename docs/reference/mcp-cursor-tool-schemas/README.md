# Снимки схем инструментов для Cursor MCP

Cursor кэширует JSON-дескрипторы инструментов в `~/.cursor/projects/<project>/mcps/user-onec-context-mcp/tools/`. После обновления `mcp_server.py` или смены версии FastMCP дескрипторы могут отставать до переподключения к серверу.

**Источник правды:** сигнатуры в [`mcp_server.py`](../../../src/onec_help/interfaces/mcp_server.py) и таблица в [`mcp-tools-reference.md`](../mcp-tools-reference.md).

В этой папке — эталонные копии схем для инструментов, которые чаще всего расходились с кэшем клиента (имена параметров `uri_or_path`, `xml_content`). Их можно сравнить с локальным кэшем или использовать как ориентир при ручной правке.
