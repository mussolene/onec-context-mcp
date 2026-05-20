"""Task-oriented orchestration for deterministic 1C knowledge retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import unquote, urlparse

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

_CONCEPTUAL_QUERY_RULES: tuple[dict[str, Any], ...] = (
    {
        "name": "http_request",
        "all": ("http",),
        "any": ("запрос", "соединен", "соединение", "получить", "сохран"),
        "candidate_nodes": (
            {
                "name": "HTTPСоединение.Получить",
                "lookup": "member",
                "reason": "curated workflow: execute HTTP GET request",
            },
            {
                "name": "HTTPСоединение",
                "lookup": "object",
                "reason": "curated workflow: HTTP connection object",
            },
        ),
        "guidance_queries": ("HTTP запрос сохранить файл",),
    },
    {
        "name": "temp_tables",
        "all": ("временн", "таблиц"),
        "candidate_nodes": (
            {
                "name": "МенеджерВременныхТаблиц",
                "lookup": "object",
                "reason": "curated workflow: temporary table manager",
            },
            {
                "name": "МенеджерВременныхТаблиц.Закрыть",
                "lookup": "member",
                "reason": "curated workflow: close/drop temporary tables",
            },
            {
                "name": "Запрос.МенеджерВременныхТаблиц",
                "lookup": "member",
                "reason": "curated workflow: query temporary table manager",
            },
        ),
        "guidance_queries": ("временные таблицы менеджер временных таблиц",),
    },
    {
        "name": "dcs_table_values",
        "all": ("таблиц",),
        "any": ("скд", "компонов"),
        "extra": ("значен", "коллекц"),
        "workflow_seed": "СхемаКомпоновкиДанных",
        "candidate_nodes": (
            {
                "name": "ПроцессорВыводаРезультатаКомпоновкиДанныхВКоллекциюЗначений.Вывести",
                "lookup": "member",
                "reason": "curated workflow: output DCS result into ТаблицаЗначений",
            },
            {
                "name": "ПроцессорВыводаРезультатаКомпоновкиДанныхВКоллекциюЗначений",
                "lookup": "object",
                "reason": "curated workflow: output processor for value collection",
            },
            {
                "name": "СхемаКомпоновкиДанных",
                "lookup": "object",
                "reason": "curated workflow: data composition schema root",
            },
        ),
        "guidance_queries": (
            "СКД таблица значений",
            "Временные таблицы в отчетах СКД",
        ),
    },
    {
        "name": "dcs_cell_breakdown",
        "all": ("расшифров",),
        "any": ("скд", "ячейк"),
        "candidate_nodes": (
            {
                "name": "Глобальный контекст.ПолучитьИзВременногоХранилища",
                "lookup": "member",
                "reason": "curated workflow: DCS cell breakdown stored in temporary storage",
            },
        ),
        "guidance_queries": ("расшифровка ячейки СКД временное хранилище",),
    },
    {
        "name": "excel_to_value_table",
        "all": ("excel",),
        "any": ("таблиц", "таблицазначений"),
        "candidate_nodes": (
            {
                "name": "ТаблицаЗначений",
                "lookup": "object",
                "reason": "curated workflow: Excel rows loaded into value table",
            },
        ),
        "guidance_queries": ("Excel ТаблицаЗначений",),
    },
    {
        "name": "copy_value_table",
        "all": ("скопир",),
        "any": ("таблиц", "таблицазначений"),
        "candidate_nodes": (
            {
                "name": "ТаблицаЗначений.Скопировать",
                "lookup": "member",
                "reason": "curated workflow: copy value table rows",
            },
            {
                "name": "ТаблицаЗначений",
                "lookup": "object",
                "reason": "curated workflow: value table object",
            },
        ),
        "guidance_queries": ("ТаблицаЗначений скопировать",),
    },
    {
        "name": "join_value_tables",
        "all": ("соедин",),
        "any": ("таблиц", "таблицазначений"),
        "candidate_nodes": (
            {
                "name": "ТаблицаЗначений",
                "lookup": "object",
                "reason": "curated workflow: join value table rows by key fields",
            },
        ),
        "guidance_queries": ("соединить таблицы значений",),
    },
)


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
    if not q:
        return "mixed_task"
    if q.startswith(("метаданные.", "metadata.", "глобальный контекст.метаданные.")):
        return "metadata_surface_chain"
    if any(token in q for token in ("snippet", "сниппет", "стандарт", "standard", "v8std")):
        return "standards_or_snippets"
    if "." in q and " " not in q:
        return "platform_surface_chain" if q.count(".") >= 1 else "platform_api_exact"
    if any(token in q for token in ("как", "чем", "зачем", "workflow", "сценар", "получить")):
        return "conceptual_help"
    if local_context.get("object_type"):
        return "metadata_exact"
    return "mixed_task"


def _match_conceptual_rule(query: str) -> dict[str, Any] | None:
    q = (query or "").strip().lower()
    if not q:
        return None
    for rule in _CONCEPTUAL_QUERY_RULES:
        required_all = tuple(str(item) for item in (rule.get("all") or ()))
        if required_all and not all(token in q for token in required_all):
            continue
        required_any = tuple(str(item) for item in (rule.get("any") or ()))
        if required_any and not any(token in q for token in required_any):
            continue
        extra = tuple(str(item) for item in (rule.get("extra") or ()))
        if extra and not any(token in q for token in extra):
            continue
        return rule
    return None


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


def _normalize_help_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title") or item.get("full_name") or item.get("object_name") or "",
        "path": item.get("topic_path") or item.get("path") or "",
        "text": item.get("summary") or item.get("description") or item.get("text") or "",
        "entity_type": item.get("kind") or item.get("entity_type") or "topic",
        "breadcrumb": item.get("breadcrumb") or [],
        "full_name": item.get("full_name") or item.get("object_name") or "",
    }


def _guidance_for_query(
    query: str,
    *,
    limit: int,
    resolved_names: list[str],
    extra_queries: list[str] | None = None,
) -> list[dict[str, Any]]:
    from ..platform_graph.qdrant_mesh_store import search_guidance_lexical

    for candidate in [*(extra_queries or []), *resolved_names, query]:
        items = search_guidance_lexical(candidate, limit=limit)
        if items:
            return items[:limit]
    return []


def _help_for_plan(
    *,
    query: str,
    resolved_surface: dict[str, Any],
    route_kind: str,
    limit: int,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    from ..help_structured import (
        get_api_member,
        get_api_object,
        search_api_members,
        search_api_objects,
        search_api_topics,
    )
    from ..platform_graph.qdrant_mesh_store import get_workflow_path

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(items: list[dict[str, Any]]) -> None:
        for item in items:
            norm = _normalize_help_item(item)
            key = (
                str(norm.get("full_name") or norm.get("title") or ""),
                str(norm.get("path") or ""),
            )
            if not key[0] or key in seen:
                continue
            seen.add(key)
            out.append(norm)
            if len(out) >= limit:
                return

    candidates = resolved_surface.get("candidate_nodes") or []
    for candidate in candidates:
        lookup = str(candidate.get("lookup") or "").strip()
        name = str(candidate.get("name") or "").strip()
        if lookup == "member":
            add(get_api_member(name, version=version, language=language))
        elif lookup == "object":
            add(get_api_object(name, version=version, language=language))
        if len(out) >= limit:
            return out[:limit]

    workflow_seed = str(resolved_surface.get("workflow_seed") or "").strip()
    if route_kind == "conceptual_help" and workflow_seed:
        for item in get_workflow_path(workflow_seed, max_steps=6):
            add([item])
            if len(out) >= limit:
                return out[:limit]

    if route_kind in {"platform_api_exact", "platform_surface_chain"}:
        add(search_api_members(query, limit=limit, version=version, language=language))
        if len(out) < limit:
            add(search_api_objects(query, limit=limit, version=version, language=language))
    else:
        add(search_api_members(query, limit=limit, version=version, language=language))
        if len(out) < limit:
            add(search_api_objects(query, limit=limit, version=version, language=language))
        if len(out) < limit:
            add(search_api_topics(query, limit=limit, version=version, language=language))
    return out[:limit]


def _metadata_for_plan(
    *,
    query: str,
    route_kind: str,
    resolved_surface: dict[str, Any],
    local_context: dict[str, Any],
    config_version: str,
    limit: int,
) -> list[dict[str, Any]]:
    if not config_version:
        return []
    from ..metadata_graph import (
        search_metadata_exact,
        search_metadata_fields,
        search_metadata_semantic,
    )

    object_type = local_context.get("object_type") or None
    candidates = resolved_surface.get("candidate_nodes") or []
    metadata_candidate = ""
    for candidate in candidates:
        if str(candidate.get("lookup") or "").strip() == "metadata_graph":
            metadata_candidate = str(candidate.get("name") or "").strip()
            break
    metadata_query = metadata_candidate or str(local_context.get("object_name") or query).strip()
    if not metadata_query:
        return []
    if route_kind in {"metadata_exact", "metadata_surface_chain", "mixed_task"} or object_type:
        exact = search_metadata_exact(
            metadata_query,
            object_type,
            config_version,
            limit=limit,
        )
        if exact:
            return exact[:limit]
        field_hits = search_metadata_fields(
            metadata_query,
            metadata_query.split(".")[-1],
            config_version=config_version,
            type_filter=object_type,
            limit=limit,
        )
        if field_hits:
            return field_hits[:limit]
    return search_metadata_semantic(
        metadata_query,
        object_type,
        config_version,
        limit=limit,
    )[:limit]


def plan_1c_query(
    query: str,
    *,
    file_uri: str | None = None,
    symbol_name: str | None = None,
    config_version: str | None = None,
) -> dict[str, Any]:
    from ..language_resolver import resolve_1c_language_query

    q = (query or "").strip()
    local_context = _infer_local_context(file_uri, symbol_name)
    route_kind = _classify_query(q, local_context)
    resolved = resolve_1c_language_query(q) if q else {}
    candidate_nodes = list(resolved.get("candidates") or [])
    conceptual_rule = _match_conceptual_rule(q) if route_kind == "conceptual_help" else None
    if conceptual_rule:
        for item in conceptual_rule.get("candidate_nodes") or ():
            if item not in candidate_nodes:
                candidate_nodes.append(dict(item))
    confidence = 0.85 if candidate_nodes else 0.35
    if route_kind == "conceptual_help" and candidate_nodes:
        confidence = 0.7
    elif route_kind == "mixed_task":
        confidence = 0.5 if candidate_nodes else 0.25
    need_metadata = route_kind in {
        "metadata_exact",
        "metadata_surface_chain",
        "mixed_task",
    } or bool(local_context.get("object_name"))
    cfg_ver = _auto_config_version(config_version, need_metadata)
    route_plan: list[str] = ["resolver"]
    if route_kind in {"platform_api_exact", "platform_surface_chain"}:
        route_plan.extend(["platform_graph_exact", "guidance_optional"])
    elif route_kind in {"metadata_exact", "metadata_surface_chain"}:
        route_plan.extend(["metadata_exact", "platform_graph_optional", "guidance_optional"])
    elif route_kind == "standards_or_snippets":
        route_plan.extend(["platform_graph_exact_optional", "guidance"])
    elif route_kind == "conceptual_help":
        route_plan.extend(["platform_graph_lexical", "guidance", "semantic_fallback"])
    else:
        route_plan.extend(["platform_graph_exact_optional", "metadata_optional", "guidance"])
    return {
        "query": q,
        "canonical_query": str(resolved.get("normalized_query") or q).strip(),
        "resolver_kind": str(resolved.get("resolver_kind") or route_kind).strip(),
        "route_kind": route_kind,
        "candidate_nodes": candidate_nodes,
        "confidence": confidence,
        "route_plan": route_plan,
        "resolved_surface": resolved,
        "workflow_seed": str(conceptual_rule.get("workflow_seed") or "").strip()
        if conceptual_rule
        else "",
        "guidance_queries": list(conceptual_rule.get("guidance_queries") or ())
        if conceptual_rule
        else [],
        "local_context": local_context,
        "config_version": cfg_ver,
    }


def resolve_1c_task_context(req: ContextRequest) -> dict[str, Any]:
    plan = plan_1c_query(
        req.query,
        file_uri=req.file_uri,
        symbol_name=req.symbol_name,
        config_version=req.config_version,
    )
    per_source_limit = max(1, min(req.limit, 2))
    resolved_names = [
        str(item.get("name") or "").strip()
        for item in (plan.get("candidate_nodes") or [])
        if str(item.get("name") or "").strip()
    ]
    help_topics = _help_for_plan(
        query=plan["canonical_query"] or req.query,
        resolved_surface=plan,
        route_kind=str(plan.get("route_kind") or ""),
        limit=per_source_limit,
    )
    metadata_objects = _metadata_for_plan(
        query=req.query,
        route_kind=str(plan.get("route_kind") or ""),
        resolved_surface=plan,
        local_context=plan.get("local_context") or {},
        config_version=str(plan.get("config_version") or ""),
        limit=per_source_limit,
    )
    memory_items: list[dict[str, Any]] = []
    try:
        from ..memory import get_memory_store

        if req.query:
            memory_items = get_memory_store().search_long(req.query, limit=1)
    except Exception:
        memory_items = []
    workflow_items: list[dict[str, Any]] = []
    workflow_seed = str(plan.get("workflow_seed") or "").strip()
    if workflow_seed:
        try:
            from ..platform_graph.qdrant_mesh_store import get_workflow_path

            workflow_items = get_workflow_path(workflow_seed, max_steps=6)
        except Exception:
            workflow_items = []
    guidance_items = _guidance_for_query(
        req.query,
        limit=1,
        resolved_names=resolved_names,
        extra_queries=list(plan.get("guidance_queries") or []),
    )
    route_kind = str(plan.get("route_kind") or "")
    if route_kind.startswith("metadata"):
        query_type = "metadata"
    elif route_kind.startswith("platform"):
        query_type = "api"
    elif route_kind == "mixed_task":
        query_type = "mixed"
    else:
        query_type = route_kind or "mixed"
    return {
        "request": asdict(req),
        "query_type": query_type,
        "route_kind": route_kind,
        "resolved_surface": plan.get("resolved_surface") or {},
        "route_plan": plan.get("route_plan") or [],
        "workflow": workflow_items,
        "local_context": plan.get("local_context") or {},
        "help_topics": help_topics,
        "memory": memory_items,
        "guidance": guidance_items,
        "metadata_objects": metadata_objects,
    }


def build_context(req: ContextRequest) -> dict[str, Any]:
    return resolve_1c_task_context(req)


def resolve_1c_answer(
    query: str,
    *,
    version: str | None = None,
    language: str | None = None,
) -> dict[str, Any] | None:
    """Return orchestrated answer candidates before semantic fallback."""
    plan = plan_1c_query(query)
    route_kind = str(plan.get("route_kind") or "")
    help_topics = _help_for_plan(
        query=plan["canonical_query"] or query,
        resolved_surface=plan,
        route_kind=route_kind,
        limit=3,
        version=version,
        language=language,
    )
    guidance = _guidance_for_query(
        query,
        limit=2,
        resolved_names=[
            str(item.get("name") or "").strip()
            for item in (plan.get("candidate_nodes") or [])
            if str(item.get("name") or "").strip()
        ],
        extra_queries=list(plan.get("guidance_queries") or []),
    )
    if not help_topics and not guidance:
        return None
    return {
        "plan": plan,
        "help_topics": help_topics,
        "guidance": guidance,
        "version": version,
        "language": language,
    }
