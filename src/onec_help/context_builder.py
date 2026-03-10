"""Context builder: combine HBK help, memory, and configuration metadata.

This module is a thin orchestration layer that:
- Runs hybrid search over help index (Qdrant collection `onec_help`).
- Fetches curated snippets/standards from long-term memory.
- Optionally fetches configuration objects from metadata graph for a given config_version.

It intentionally does **not** know anything about MCP or BSL LS transport —
MCP tools and Cursor rules call this module with an already prepared request.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from . import env_config, indexer


@dataclass(slots=True)
class ContextRequest:
    """Input for context building.

    Only `query` is required; остальные поля — подсказка для будущих доработок
    (учёт позиции в модуле, конкретного объекта конфигурации и т.п.).
    """

    query: str
    config_version: str | None = None
    file_uri: str | None = None
    symbol_name: str | None = None
    limit: int = 5


def build_context(req: ContextRequest) -> dict[str, Any]:
    """Build combined context from help index, memory and metadata graph.

    Returns a JSON-serializable dict:
    {
        "request": { ... },
        "help_topics": [ ... ],
        "memory": [ ... ],
        "metadata_objects": [ ... ],
    }
    """

    q = (req.query or "").strip()
    host = env_config.get_qdrant_host()
    port = env_config.get_qdrant_port()

    # 1. HBK help via hybrid search
    help_topics: list[dict[str, Any]] = []
    if q:
        try:
            help_topics = indexer.search_hybrid(
                q,
                limit=req.limit,
                qdrant_host=host,
                qdrant_port=port,
            )
        except Exception:
            help_topics = []

    # 2. Memory (snippets + standards + community_help)
    memory_items: list[dict[str, Any]] = []
    if q:
        try:
            from .memory import get_memory_store

            memory_items = get_memory_store().search_long(q, limit=req.limit)
        except Exception:
            memory_items = []

    # 3. Metadata graph (configuration objects)
    metadata_objects: list[dict[str, Any]] = []
    cfg_ver = (req.config_version or "").strip()
    if not cfg_ver and q:
        try:
            from .metadata_graph import get_metadata_config_versions

            versions = get_metadata_config_versions()
            if len(versions) == 1:
                cfg_ver = versions[0]
        except Exception:
            pass
    if cfg_ver and q:
        try:
            from .metadata_graph import search_metadata_by_name

            metadata_objects = search_metadata_by_name(
                q,
                type_filter=None,
                config_version=cfg_ver,
            )
        except Exception:
            metadata_objects = []

    return {
        "request": asdict(req),
        "help_topics": help_topics,
        "memory": memory_items,
        "metadata_objects": metadata_objects,
    }
