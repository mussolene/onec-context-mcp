"""Scorecard for the deterministic 1C knowledge mesh runtime."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from math import ceil
from pathlib import Path
from statistics import median
from typing import Any

from ..runtime.mcp_metrics import get_metrics as get_mcp_metrics
from ..shared import env_config
from .help_structured import (
    get_api_member,
    get_api_object,
    search_api_members,
    search_api_objects,
    search_api_topics,
)
from .metadata_graph import (
    METADATA_FIELDS_COLLECTION_NAME,
    search_metadata_exact,
    search_metadata_fields,
)
from .orchestrator.task_orchestrator import plan_1c_query
from .platform_graph.qdrant_mesh_store import get_qdrant_mesh_status, get_workflow_path

_DEFAULT_TARGETS: dict[str, float] = {
    "overall_case_pass_pct": 85.0,
    "route_hit_pct": 95.0,
    "help_hit_pct": 85.0,
    "metadata_hit_pct": 85.0,
    "workflow_hit_pct": 80.0,
    "field_hit_pct": 95.0,
    "median_plan_ms": 50.0,
    "median_context_ms": 1200.0,
}

_PROFILE_TITLES = {
    "exact_api_surface": "Exact API Surface",
    "metadata_navigation": "Metadata Navigation",
    "workflow_context": "Workflow Context",
}
_RUNNER_TITLES = {
    "task_context": "Task Context",
    "metadata_field": "Metadata Field",
    "exact_member": "Exact Member",
    "exact_object": "Exact Object",
    "metadata_exact": "Metadata Exact",
}
_VALID_RUNNERS = frozenset(_RUNNER_TITLES)
_DEFAULT_TOTAL_CASES = 120
_DEFAULT_BULK_CASE_TARGETS: tuple[tuple[str, int], ...] = (
    ("exact_member", 40),
    ("exact_object", 20),
    ("metadata_exact", 30),
    ("metadata_field", 30),
)


def get_default_mesh_benchmark_path() -> Path:
    return Path(__file__).with_name("mesh_scorecard_benchmark.json")


def get_default_mesh_external_path() -> Path:
    return Path(__file__).with_name("mesh_external_tasks.json")


def load_mesh_benchmark(path: Path | None = None) -> list[dict[str, Any]]:
    target = (path or get_default_mesh_benchmark_path()).expanduser().resolve()
    if not target.is_file():
        return []
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Mesh benchmark must be a JSON array")
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        runner = str(item.get("runner") or "").strip()
        profile = str(item.get("profile") or "").strip()
        if runner not in _VALID_RUNNERS or not profile:
            continue
        out.append(item)
    return out


def _append_unique_cases(
    target: list[dict[str, Any]],
    items: list[dict[str, Any]],
    *,
    seen_ids: set[str],
) -> None:
    for item in items:
        case_id = str(item.get("id") or "").strip()
        if not case_id or case_id in seen_ids:
            continue
        seen_ids.add(case_id)
        target.append(item)


def _scroll_payloads(
    collection_name: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    from qdrant_client import QdrantClient

    client = QdrantClient(
        host=env_config.get_qdrant_host(),
        port=env_config.get_qdrant_port(),
        check_compatibility=False,
    )
    try:
        if not client.collection_exists(collection_name):
            return []
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    offset = None
    while len(out) < limit:
        batch, offset = client.scroll(
            collection_name=collection_name,
            limit=min(500, max(1, limit - len(out))),
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not batch:
            break
        for point in batch:
            payload = dict(getattr(point, "payload", None) or {})
            if payload:
                out.append(payload)
                if len(out) >= limit:
                    break
        if offset is None:
            break
    return out


def _generate_runtime_benchmark_cases(total_target: int) -> list[dict[str, Any]]:
    if total_target <= 0:
        return []
    remaining = total_target
    out: list[dict[str, Any]] = []

    quota_map = dict(_DEFAULT_BULK_CASE_TARGETS)
    member_rows = _scroll_payloads("onec_help_api_members", limit=quota_map["exact_member"] * 2)
    seen_members: set[str] = set()
    for row in member_rows:
        name = str(row.get("full_name") or "").strip()
        if not name:
            continue
        if name in seen_members:
            continue
        seen_members.add(name)
        out.append(
            {
                "id": f"bulk_member_{len(seen_members):03d}",
                "suite": "bulk_runtime",
                "profile": "exact_api_surface",
                "runner": "exact_member",
                "query": name,
                "expected_help_contains": [name],
            }
        )
        remaining -= 1
        if remaining <= 0 or len(seen_members) >= quota_map["exact_member"]:
            return out

    object_rows = _scroll_payloads("onec_help_api_objects", limit=quota_map["exact_object"] * 2)
    seen_objects: set[str] = set()
    for row in object_rows:
        name = str(row.get("full_name") or "").strip()
        if not name:
            continue
        if name in seen_objects:
            continue
        seen_objects.add(name)
        out.append(
            {
                "id": f"bulk_object_{len(seen_objects):03d}",
                "suite": "bulk_runtime",
                "profile": "exact_api_surface",
                "runner": "exact_object",
                "query": name,
                "expected_help_contains": [name],
            }
        )
        remaining -= 1
        if remaining <= 0 or len(seen_objects) >= quota_map["exact_object"]:
            return out

    metadata_rows = _scroll_payloads("onec_config_metadata", limit=quota_map["metadata_exact"] * 2)
    seen_metadata: set[tuple[str, str]] = set()
    for row in metadata_rows:
        object_id = str(row.get("id") or "").strip()
        config_version = str(row.get("config_version") or "").strip()
        if not object_id or not config_version:
            continue
        key = (object_id, config_version)
        if key in seen_metadata:
            continue
        seen_metadata.add(key)
        out.append(
            {
                "id": f"bulk_metadata_{len(seen_metadata):03d}",
                "suite": "bulk_runtime",
                "profile": "metadata_navigation",
                "runner": "metadata_exact",
                "query": object_id,
                "config_version": config_version,
                "expected_metadata_contains": [object_id],
            }
        )
        remaining -= 1
        if remaining <= 0 or len(seen_metadata) >= quota_map["metadata_exact"]:
            return out

    field_rows = _scroll_payloads(
        METADATA_FIELDS_COLLECTION_NAME, limit=quota_map["metadata_field"] * 2
    )
    seen_fields: set[tuple[str, str, str]] = set()
    for row in field_rows:
        object_id = str(row.get("object_id") or "").strip()
        field_name = str(row.get("field_name") or "").strip()
        config_version = str(row.get("config_version") or "").strip()
        if not object_id or not field_name or not config_version:
            continue
        key = (object_id, field_name, config_version)
        if key in seen_fields:
            continue
        seen_fields.add(key)
        out.append(
            {
                "id": f"bulk_field_{len(seen_fields):03d}",
                "suite": "bulk_runtime",
                "profile": "metadata_navigation",
                "runner": "metadata_field",
                "object_query": object_id,
                "field_query": field_name,
                "config_version": config_version,
                "expected_field_contains": [field_name],
            }
        )
        remaining -= 1
        if remaining <= 0 or len(seen_fields) >= quota_map["metadata_field"]:
            return out
    return out


def compose_mesh_benchmark(
    *,
    benchmark_path: Path | None = None,
    external_path: Path | None = None,
    total_target: int = _DEFAULT_TOTAL_CASES,
) -> list[dict[str, Any]]:
    benchmark = load_mesh_benchmark(benchmark_path)
    external = load_mesh_benchmark(external_path or get_default_mesh_external_path())
    seen_ids: set[str] = set()
    out: list[dict[str, Any]] = []
    _append_unique_cases(out, benchmark, seen_ids=seen_ids)
    _append_unique_cases(out, external, seen_ids=seen_ids)
    generated_target = max(0, total_target - len(out))
    _append_unique_cases(
        out,
        _generate_runtime_benchmark_cases(generated_target),
        seen_ids=seen_ids,
    )
    return out


def _norm(value: str) -> str:
    return " ".join((value or "").strip().split()).lower()


def _contains_any(haystack: list[str], needles: list[str]) -> bool:
    values = [_norm(item) for item in haystack if _norm(item)]
    for needle in needles:
        n = _norm(needle)
        if n and any(n in value for value in values):
            return True
    return False


def _percent(numerator: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(numerator * 100.0 / total, 1)


def _ms(values: list[float]) -> dict[str, float]:
    if not values:
        return {"median_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, ceil(len(ordered) * 0.95) - 1))
    return {
        "median_ms": round(median(ordered), 1),
        "p95_ms": round(ordered[idx], 1),
        "max_ms": round(max(ordered), 1),
    }


def _profile_card(
    profile: str,
    rows: list[dict[str, Any]],
    *,
    title: str | None = None,
) -> dict[str, Any]:
    total = len(rows)
    case_pass = sum(1 for row in rows if row.get("case_pass"))
    plan_lat = [float(row.get("plan_ms") or 0.0) for row in rows if row.get("plan_ms") is not None]
    ctx_lat = [
        float(row.get("context_ms") or 0.0) for row in rows if row.get("context_ms") is not None
    ]
    card = {
        "profile": profile,
        "title": title or _PROFILE_TITLES.get(profile, profile),
        "total": total,
        "case_pass_pct": _percent(case_pass, total),
        "route_hit_pct": _metric_pct(rows, "route_expected", "route_ok"),
        "help_hit_pct": _metric_pct(rows, "help_expected", "help_ok"),
        "metadata_hit_pct": _metric_pct(rows, "metadata_expected", "metadata_ok"),
        "workflow_hit_pct": _metric_pct(rows, "workflow_expected", "workflow_ok"),
        "field_hit_pct": _metric_pct(rows, "field_expected", "field_ok"),
        "plan_latency": _ms(plan_lat),
        "context_latency": _ms(ctx_lat),
    }
    return card


def _metric_pct(rows: list[dict[str, Any]], expected_key: str, ok_key: str) -> float:
    applicable = [row for row in rows if row.get(expected_key)]
    if not applicable:
        return 0.0
    return _percent(sum(1 for row in applicable if row.get(ok_key)), len(applicable))


def _fast_help_hits(plan: dict[str, Any], query: str, *, limit: int = 2) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()

    def add_name(name: str) -> None:
        clean = str(name or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            titles.append(clean)

    for candidate in plan.get("candidate_nodes") or []:
        lookup = str(candidate.get("lookup") or "").strip()
        name = str(candidate.get("name") or "").strip()
        if lookup == "member":
            for item in get_api_member(name):
                add_name(str(item.get("full_name") or item.get("title") or item.get("name") or ""))
        elif lookup == "object":
            for item in get_api_object(name):
                add_name(
                    str(item.get("full_name") or item.get("title") or item.get("object_name") or "")
                )
        if len(titles) >= limit:
            return titles[:limit]

    for source in (search_api_members, search_api_objects, search_api_topics):
        for item in source(query, limit=limit):
            add_name(str(item.get("full_name") or item.get("title") or item.get("name") or ""))
            if len(titles) >= limit:
                return titles[:limit]
    return titles[:limit]


def build_mesh_scorecard(
    *,
    benchmark_path: Path | None = None,
    external_path: Path | None = None,
    total_target: int = _DEFAULT_TOTAL_CASES,
) -> dict[str, Any]:
    benchmark = compose_mesh_benchmark(
        benchmark_path=benchmark_path,
        external_path=external_path,
        total_target=total_target,
    )
    cases: list[dict[str, Any]] = []

    for item in benchmark:
        runner = str(item.get("runner") or "").strip()
        case_id = str(item.get("id") or "").strip()
        profile = str(item.get("profile") or "").strip()
        route_ok = False
        help_ok = False
        metadata_ok = False
        workflow_ok = False
        field_ok = False
        candidate_ok = False
        plan_ms: float | None = None
        context_ms: float | None = None
        route_kind = ""
        resolver_kind = ""
        top_help = ""
        top_metadata = ""
        top_workflow = ""
        top_field = ""
        top_candidate = ""

        if runner == "task_context":
            query = str(item.get("query") or "").strip()
            cfg = str(item.get("config_version") or "").strip() or None
            t0 = time.perf_counter()
            plan = plan_1c_query(query, config_version=cfg)
            plan_ms = (time.perf_counter() - t0) * 1000.0
            t1 = time.perf_counter()
            help_titles = _fast_help_hits(plan, query, limit=2)
            metadata_titles: list[str] = []
            if cfg:
                for hit in search_metadata_exact(query, None, cfg, limit=2):
                    metadata_titles.append(
                        str(hit.get("id") or hit.get("full_name") or hit.get("name") or "")
                    )
            workflow_titles: list[str] = []
            workflow_seed = str(plan.get("workflow_seed") or "").strip()
            if workflow_seed:
                for hit in get_workflow_path(workflow_seed, max_steps=6):
                    workflow_titles.append(str(hit.get("full_name") or hit.get("title") or ""))
            context_ms = (time.perf_counter() - t1) * 1000.0

            route_kind = str(plan.get("route_kind") or "")
            resolver_kind = str(plan.get("resolver_kind") or "")
            route_ok = not item.get("expected_route_kind") or route_kind == str(
                item.get("expected_route_kind") or ""
            )

            candidates = [str(x.get("name") or "") for x in (plan.get("candidate_nodes") or [])]
            top_candidate = candidates[0] if candidates else ""
            candidate_ok = _contains_any(
                candidates, [str(x) for x in item.get("expected_candidate_contains") or []]
            )

            top_help = help_titles[0] if help_titles else ""
            help_ok = _contains_any(
                help_titles, [str(x) for x in item.get("expected_help_contains") or []]
            )

            top_metadata = metadata_titles[0] if metadata_titles else ""
            metadata_ok = _contains_any(
                metadata_titles, [str(x) for x in item.get("expected_metadata_contains") or []]
            )

            top_workflow = workflow_titles[0] if workflow_titles else ""
            workflow_ok = _contains_any(
                workflow_titles, [str(x) for x in item.get("expected_workflow_contains") or []]
            )

        elif runner == "exact_member":
            query = str(item.get("query") or "").strip()
            t0 = time.perf_counter()
            help_titles = [
                str(row.get("full_name") or row.get("title") or row.get("name") or "")
                for row in get_api_member(query)
            ]
            context_ms = (time.perf_counter() - t0) * 1000.0
            top_help = help_titles[0] if help_titles else ""
            help_ok = _contains_any(
                help_titles, [str(x) for x in item.get("expected_help_contains") or []]
            )

        elif runner == "exact_object":
            query = str(item.get("query") or "").strip()
            t0 = time.perf_counter()
            help_titles = [
                str(row.get("full_name") or row.get("title") or row.get("object_name") or "")
                for row in get_api_object(query)
            ]
            context_ms = (time.perf_counter() - t0) * 1000.0
            top_help = help_titles[0] if help_titles else ""
            help_ok = _contains_any(
                help_titles, [str(x) for x in item.get("expected_help_contains") or []]
            )

        elif runner == "metadata_exact":
            query = str(item.get("query") or "").strip()
            cfg = str(item.get("config_version") or "").strip()
            t0 = time.perf_counter()
            metadata_titles = [
                str(row.get("id") or row.get("full_name") or row.get("name") or "")
                for row in search_metadata_exact(query, None, cfg, limit=3)
            ]
            context_ms = (time.perf_counter() - t0) * 1000.0
            top_metadata = metadata_titles[0] if metadata_titles else ""
            metadata_ok = _contains_any(
                metadata_titles, [str(x) for x in item.get("expected_metadata_contains") or []]
            )

        elif runner == "metadata_field":
            object_query = str(item.get("object_query") or "").strip()
            field_query = str(item.get("field_query") or "").strip()
            cfg = str(item.get("config_version") or "").strip()
            t0 = time.perf_counter()
            rows = search_metadata_fields(
                object_query,
                field_query,
                config_version=cfg,
                type_filter=str(item.get("object_type") or "").strip() or None,
                limit=3,
            )
            context_ms = (time.perf_counter() - t0) * 1000.0
            field_titles = [
                str(x.get("name") or "") for x in rows if str(x.get("name") or "").strip()
            ]
            if not field_titles:
                field_titles = [
                    str(x.get("field_name") or "")
                    for x in rows
                    if str(x.get("field_name") or "").strip()
                ]
            top_field = field_titles[0] if field_titles else ""
            field_ok = _contains_any(
                field_titles, [str(x) for x in item.get("expected_field_contains") or []]
            )

        checks = [
            route_ok if item.get("expected_route_kind") else True,
            candidate_ok if item.get("expected_candidate_contains") else True,
            help_ok if item.get("expected_help_contains") else True,
            metadata_ok if item.get("expected_metadata_contains") else True,
            workflow_ok if item.get("expected_workflow_contains") else True,
            field_ok if item.get("expected_field_contains") else True,
        ]
        case_pass = all(checks)
        cases.append(
            {
                "id": case_id,
                "suite": str(item.get("suite") or "golden_local"),
                "profile": profile,
                "runner": runner,
                "query": item.get("query") or item.get("field_query") or "",
                "route_kind": route_kind,
                "resolver_kind": resolver_kind,
                "route_expected": bool(item.get("expected_route_kind")),
                "route_ok": route_ok,
                "candidate_expected": bool(item.get("expected_candidate_contains")),
                "candidate_ok": candidate_ok,
                "help_expected": bool(item.get("expected_help_contains")),
                "help_ok": help_ok,
                "metadata_expected": bool(item.get("expected_metadata_contains")),
                "metadata_ok": metadata_ok,
                "workflow_expected": bool(item.get("expected_workflow_contains")),
                "workflow_ok": workflow_ok,
                "field_expected": bool(item.get("expected_field_contains")),
                "field_ok": field_ok,
                "case_pass": case_pass,
                "plan_ms": round(plan_ms, 1) if plan_ms is not None else None,
                "context_ms": round(context_ms, 1) if context_ms is not None else None,
                "top_candidate": top_candidate,
                "top_help": top_help,
                "top_metadata": top_metadata,
                "top_workflow": top_workflow,
                "top_field": top_field,
                "source_title": str(item.get("source_title") or ""),
                "source_url": str(item.get("source_url") or ""),
            }
        )

    profiles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    suites: dict[str, list[dict[str, Any]]] = defaultdict(list)
    runners: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        profiles[str(case.get("profile") or "other")].append(case)
        suites[str(case.get("suite") or "other")].append(case)
        runners[str(case.get("runner") or "other")].append(case)

    cards = {name: _profile_card(name, rows) for name, rows in profiles.items()}
    suite_cards = {
        name: _profile_card(name, rows, title=f"Suite: {name}") for name, rows in suites.items()
    }
    runner_cards = {
        name: _profile_card(name, rows, title=_RUNNER_TITLES.get(name, name))
        for name, rows in runners.items()
    }
    total = len(cases) or 1
    route_cases = [x for x in cases if x.get("route_expected")]
    help_cases = [x for x in cases if x.get("help_expected")]
    metadata_cases = [x for x in cases if x.get("metadata_expected")]
    workflow_cases = [x for x in cases if x.get("workflow_expected")]
    field_cases = [x for x in cases if x.get("field_expected")]
    summary = {
        "total_cases": len(cases),
        "suite_counts": {name: len(rows) for name, rows in sorted(suites.items())},
        "runner_counts": {name: len(rows) for name, rows in sorted(runners.items())},
        "overall_case_pass_pct": _percent(sum(1 for x in cases if x.get("case_pass")), total),
        "route_hit_pct": _percent(
            sum(1 for x in route_cases if x.get("route_ok")), len(route_cases)
        ),
        "help_hit_pct": _percent(sum(1 for x in help_cases if x.get("help_ok")), len(help_cases)),
        "metadata_hit_pct": _percent(
            sum(1 for x in metadata_cases if x.get("metadata_ok")), len(metadata_cases)
        ),
        "workflow_hit_pct": _percent(
            sum(1 for x in workflow_cases if x.get("workflow_ok")), len(workflow_cases)
        ),
        "field_hit_pct": _percent(
            sum(1 for x in field_cases if x.get("field_ok")), len(field_cases)
        ),
        "latency": {
            "plan": _ms([float(x["plan_ms"]) for x in cases if x.get("plan_ms") is not None]),
            "context": _ms(
                [float(x["context_ms"]) for x in cases if x.get("context_ms") is not None]
            ),
        },
    }

    mesh_store = get_qdrant_mesh_status()
    mcp_metrics = get_mcp_metrics()
    targets = {
        key: {
            "target": value,
            "actual": summary["latency"]["plan"]["median_ms"]
            if key == "median_plan_ms"
            else summary["latency"]["context"]["median_ms"]
            if key == "median_context_ms"
            else summary.get(key, 0.0),
            "met": summary["latency"]["plan"]["median_ms"] <= value
            if key == "median_plan_ms"
            else summary["latency"]["context"]["median_ms"] <= value
            if key == "median_context_ms"
            else summary.get(key, 0.0) >= value,
        }
        for key, value in _DEFAULT_TARGETS.items()
    }
    return {
        "format": "onec_help_mesh_scorecard_v1",
        "benchmark_path": str((benchmark_path or get_default_mesh_benchmark_path()).resolve()),
        "external_path": str((external_path or get_default_mesh_external_path()).resolve()),
        "summary": summary,
        "cards": cards,
        "suite_cards": suite_cards,
        "runner_cards": runner_cards,
        "mesh_store": mesh_store,
        "mcp_metrics": mcp_metrics,
        "targets": targets,
        "cases": cases,
    }
