"""Compact context builder for AI-oriented 1C tasks.

This module intentionally keeps the returned context small:
- classify the request (api / metadata / mixed / review);
- derive local hints from file/module path when available;
- fetch only the top 1-2 items per source;
- avoid broad "search everywhere" behaviour by default.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import unquote, urlparse

from .. import env_config, indexer

_OBJECT_DIRS = {
    "Catalogs": "Catalog",
    "Documents": "Document",
    "DataProcessors": "DataProcessor",
    "Reports": "Report",
    "InformationRegisters": "InformationRegister",
    "AccumulationRegisters": "AccumulationRegister",
    "AccountingRegisters": "AccountingRegister",
    "CalculationRegisters": "CalculationRegister",
    "BusinessProcesses": "BusinessProcess",
    "Tasks": "Task",
    "Enumerations": "Enumeration",
    "Constants": "Constant",
}


@dataclass(slots=True)
class ContextRequest:
    query: str
    config_version: str | None = None
    file_uri: str | None = None
    symbol_name: str | None = None
    limit: int = 5


def _path_parts(uri_or_path: str | None) -> tuple[str, ...]:
    if not uri_or_path:
        return ()
    value = uri_or_path.strip()
    if value.startswith("file://"):
        value = unquote(urlparse(value).path)
    value = value.replace("\\", "/").strip("/")
    return tuple(part for part in value.split("/") if part)


def _infer_local_context(file_uri: str | None, symbol_name: str | None) -> dict[str, Any]:
    parts = _path_parts(file_uri)
    file_name = parts[-1] if parts else ""
    module_type = "Unknown"
    if file_name == "ObjectModule.bsl":
        module_type = "ObjectModule"
    elif file_name == "Module.bsl":
        module_type = "FormModule"
    elif file_name.endswith("Module.bsl"):
        module_type = file_name.removesuffix(".bsl")

    form_name = ""
    if "Forms" in parts:
        idx = parts.index("Forms")
        if idx + 1 < len(parts):
            form_name = parts[idx + 1]

    object_type = ""
    object_name = ""
    for directory, normalized in _OBJECT_DIRS.items():
        if directory in parts:
            idx = parts.index(directory)
            if idx + 1 < len(parts):
                object_type = normalized
                object_name = parts[idx + 1]
            break

    return {
        "file_uri": file_uri,
        "symbol_name": symbol_name,
        "module_type": module_type,
        "form_name": form_name,
        "object_type": object_type,
        "object_name": object_name,
    }


def _classify_query(query: str, local_context: dict[str, Any]) -> str:
    q = (query or "").strip().lower()
    if "." in q and " " not in q:
        return "api"
    if any(token in q for token in ("ошиб", "diagnostic", "warning", "review", "рефактор")):
        return "review"
    if local_context.get("object_type"):
        return "metadata"
    if any(token in q for token in ("документ", "справочник", "регистр", "catalog", "document")):
        return "metadata"
    return "mixed"


def _auto_config_version(explicit: str | None, need_metadata: bool) -> str:
    cfg_ver = (explicit or "").strip()
    if cfg_ver or not need_metadata:
        return cfg_ver
    try:
        from ..metadata_graph import get_metadata_config_versions

        versions = get_metadata_config_versions()
        if len(versions) == 1:
            return versions[0]
    except Exception:
        return ""
    return ""


def build_context(req: ContextRequest) -> dict[str, Any]:
    q = (req.query or "").strip()
    host = env_config.get_qdrant_host()
    port = env_config.get_qdrant_port()
    local_context = _infer_local_context(req.file_uri, req.symbol_name)
    query_type = _classify_query(q, local_context)

    help_query = (req.symbol_name or q).strip()
    metadata_query = (local_context.get("object_name") or q).strip()
    need_metadata = query_type in {"metadata", "mixed", "review"} or bool(local_context.get("object_name"))
    cfg_ver = _auto_config_version(req.config_version, need_metadata)

    help_limit = 1 if query_type == "api" else 2 if query_type in {"mixed", "review"} else 0
    memory_limit = 1 if query_type in {"api", "mixed", "review"} else 0
    metadata_limit = 2 if need_metadata else 0
    per_source_limit = max(1, min(req.limit, 2))

    help_topics: list[dict[str, Any]] = []
    if help_limit and help_query:
        try:
            help_limit_effective = min(per_source_limit, help_limit)
            if query_type == "api":
                help_topics = indexer.search_index_keyword(
                    help_query,
                    limit=help_limit_effective,
                    qdrant_host=host,
                    qdrant_port=port,
                )
            else:
                help_topics = indexer.search_hybrid(
                    help_query,
                    limit=help_limit_effective,
                    qdrant_host=host,
                    qdrant_port=port,
                )
        except Exception:
            help_topics = []

    memory_items: list[dict[str, Any]] = []
    if memory_limit and q:
        try:
            from ..memory import get_memory_store

            memory_items = get_memory_store().search_long(q, limit=min(per_source_limit, memory_limit))
        except Exception:
            memory_items = []

    metadata_objects: list[dict[str, Any]] = []
    if metadata_limit and metadata_query and cfg_ver:
        try:
            from ..metadata_graph import search_metadata_exact, search_metadata_semantic

            metadata_limit_effective = min(per_source_limit, metadata_limit)
            object_type = local_context.get("object_type") or None
            prefer_exact = bool(local_context.get("object_name")) or (" " not in metadata_query.strip())

            if prefer_exact:
                metadata_objects = search_metadata_exact(
                    metadata_query,
                    object_type,
                    cfg_ver,
                    limit=metadata_limit_effective,
                )
                if not metadata_objects and query_type in {"metadata", "mixed", "review"}:
                    metadata_objects = search_metadata_semantic(
                        metadata_query,
                        object_type,
                        cfg_ver,
                        limit=metadata_limit_effective,
                    )
            else:
                metadata_objects = search_metadata_semantic(
                    metadata_query,
                    object_type,
                    cfg_ver,
                    limit=metadata_limit_effective,
                )
                if not metadata_objects:
                    metadata_objects = search_metadata_exact(
                        metadata_query,
                        object_type,
                        cfg_ver,
                        limit=metadata_limit_effective,
                    )
        except Exception:
            metadata_objects = []

    return {
        "request": asdict(req),
        "query_type": query_type,
        "local_context": local_context,
        "help_topics": help_topics,
        "memory": memory_items,
        "metadata_objects": metadata_objects,
    }
