"""Qdrant-only deterministic mesh helpers.

JSONL snapshots remain the source of truth; Qdrant is the only persistent runtime store.
This module provides a small exact/graph/guidance adapter for orchestrator and scorecards.
"""

from __future__ import annotations

from typing import Any

_WORKFLOW_RELATIONS: tuple[tuple[str, str], ...] = (
    ("СхемаКомпоновкиДанных", "ИсточникДоступныхНастроекКомпоновкиДанных"),
    ("ИсточникДоступныхНастроекКомпоновкиДанных", "КомпоновщикНастроекКомпоновкиДанных"),
    ("КомпоновщикНастроекКомпоновкиДанных", "КомпоновщикМакетаКомпоновкиДанных"),
    ("КомпоновщикМакетаКомпоновкиДанных", "ПроцессорКомпоновкиДанных"),
    (
        "ПроцессорКомпоновкиДанных",
        "ПроцессорВыводаРезультатаКомпоновкиДанныхВКоллекциюЗначений",
    ),
)
_WORKFLOW_NEXT_BY_NAME = {source: target for source, target in _WORKFLOW_RELATIONS}


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


def _collection_counts() -> dict[str, int]:
    from ...search_store.indexer import get_all_collections_status

    counts: dict[str, int] = {}
    for item in get_all_collections_status():
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        counts[name] = int(item.get("points_count") or 0)
    return counts


def get_qdrant_mesh_status() -> dict[str, Any]:
    from ..metadata_graph import METADATA_FIELDS_COLLECTION_NAME

    try:
        counts = _collection_counts()
    except Exception as exc:
        return {"exists": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "exists": True,
        "api_members": counts.get("onec_help_api_members", 0),
        "api_objects": counts.get("onec_help_api_objects", 0),
        "api_examples": counts.get("onec_help_examples", 0),
        "api_edges": counts.get("onec_help_api_links", 0),
        "metadata_nodes": counts.get("onec_config_metadata", 0),
        "metadata_fields": counts.get(METADATA_FIELDS_COLLECTION_NAME, 0),
        "guidance": counts.get("onec_help_memory", 0),
        "topic_fallback": counts.get("onec_help_topics", 0),
        "collections": counts,
    }


def search_guidance_lexical(
    query: str,
    *,
    limit: int = 5,
    domain: str | None = None,
) -> list[dict[str, Any]]:
    from ..memory import get_memory_store

    rows = get_memory_store().search_long(query, limit=limit, domain=domain)
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row.get("payload") or {})
        if not payload:
            continue
        payload["score"] = row.get("score")
        out.append(payload)
    return out[:limit]


def get_workflow_path(
    name: str,
    *,
    version: str | None = None,
    language: str | None = None,
    max_steps: int = 8,
) -> list[dict[str, Any]]:
    from ..help_structured import get_api_member, get_api_object

    current_hits = get_api_object(name, version=version, language=language)
    if not current_hits:
        current_hits = get_api_member(name, version=version, language=language)
    if not current_hits:
        return []

    out: list[dict[str, Any]] = [current_hits[0]]
    seen: set[str] = {
        str(current_hits[0].get("full_name") or current_hits[0].get("object_name") or "").strip()
    }
    current_name = next(iter(seen))

    while len(out) < max_steps:
        next_name = _WORKFLOW_NEXT_BY_NAME.get(current_name)
        if not next_name or next_name in seen:
            break
        next_hits = get_api_object(next_name, version=version, language=language)
        if not next_hits:
            next_hits = get_api_member(next_name, version=version, language=language)
        if not next_hits:
            break
        out.append(next_hits[0])
        current_name = str(
            next_hits[0].get("full_name") or next_hits[0].get("object_name") or next_name
        ).strip()
        seen.add(current_name)
    return out
