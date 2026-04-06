"""Scorecard for structured help extraction quality and stopping metrics."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .help_structured import (
    API_EXAMPLES_FILE,
    API_LINKS_FILE,
    API_MEMBERS_FILE,
    API_OBJECTS_FILE,
    canonical_topic_path,
    get_help_structured_dir,
    iter_help_topics_from_index,
    iter_help_topics_from_unpacked,
)

_METHOD_LIKE_KINDS = {"method", "function", "constructor"}
_DEFAULT_TARGETS: dict[str, float] = {
    "summary_pct": 95.0,
    "syntax_pct": 70.0,
    "availability_pct": 85.0,
    "owner_name_pct": 99.5,
    "method_like_params_pct": 60.0,
    "method_like_returns_pct": 60.0,
    "exact_top1_pct": 95.0,
    "structured_sufficient_pct": 80.0,
}


def _classify_help_only_topic(path: str) -> str:
    normalized = (path or "").replace("\\", "/").lower()
    if "/shclang_" in normalized or "/embedlang" in normalized or "/shlang_ru/" in normalized:
        return "language"
    if "/tables/" in normalized:
        return "tables"
    if "/forms/" in normalized:
        return "forms"
    if "/objects/" in normalized and all(
        marker not in normalized for marker in ("/methods/", "/properties/", "/events/", "/ctors/")
    ):
        return "object_overview"
    if "/query/" in normalized or "queries" in normalized or "/shquery_ru/" in normalized:
        return "query"
    if "/lang/" in normalized:
        return "language"
    return "other_topic"


def get_default_benchmark_path() -> Path:
    """Return packaged benchmark fixture path for structured help scorecard."""
    return Path(__file__).with_name("help_structured_benchmark.json")


def load_structured_benchmark(path: Path | None = None) -> list[dict[str, Any]]:
    """Load exact-match benchmark cases for structured help."""
    target = (path or get_default_benchmark_path()).expanduser().resolve()
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Structured help benchmark must be a JSON array")
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        entity = str(item.get("entity") or "member").strip().lower()
        expected = str(item.get("expected_full_name") or "").strip()
        if not query or entity not in {"member", "object"} or not expected:
            continue
        out.append(
            {
                "query": query,
                "entity": entity,
                "expected_full_name": expected,
                "expected_kind": str(item.get("expected_kind") or "").strip(),
            }
        )
    return out


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not path.exists():
        return items
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                items.append(json.loads(line))
    return items


def _normalize_name(value: str) -> str:
    return " ".join((value or "").strip().split()).lower()


def _matches_expected_name(expected: str, item: dict[str, Any]) -> bool:
    expected_norm = _normalize_name(expected)
    if not expected_norm:
        return False
    full_name = _normalize_name(str(item.get("full_name") or ""))
    member_name = _normalize_name(str(item.get("member_name") or ""))
    owner_name = _normalize_name(str(item.get("owner_name") or ""))
    if full_name == expected_norm or member_name == expected_norm:
        return True
    if (
        owner_name in {"глобальный контекст", "встроенные функции языка"}
        and member_name == expected_norm
        and full_name.endswith("." + expected_norm)
    ):
        return True
    return False


def _score_case(query: str, item: dict[str, Any]) -> int:
    query_norm = _normalize_name(query)
    full_name = _normalize_name(str(item.get("full_name") or ""))
    member_name = _normalize_name(str(item.get("member_name") or ""))
    title = _normalize_name(str(item.get("title") or ""))
    summary = _normalize_name(str(item.get("summary") or ""))
    score = 0
    if full_name == query_norm:
        score += 100
    elif member_name == query_norm:
        score += 90
    elif full_name.startswith(query_norm):
        score += 70
    elif query_norm in full_name:
        score += 55
    if title == query_norm:
        score += 40
    elif title.startswith(query_norm):
        score += 25
    elif query_norm in title:
        score += 10
    if query_norm and query_norm in summary:
        score += 5
    owner_name = _normalize_name(str(item.get("owner_name") or ""))
    if owner_name in {"глобальный контекст", "встроенные функции языка"}:
        score += 3
    return score


def _case_sort_key(query: str, item: dict[str, Any]) -> tuple[int, int, int, str]:
    query_norm = _normalize_name(query)
    full_name = _normalize_name(str(item.get("full_name") or ""))
    member_name = _normalize_name(str(item.get("member_name") or ""))
    owner_name = _normalize_name(str(item.get("owner_name") or ""))
    owner_priority = 0 if owner_name in {"глобальный контекст", "встроенные функции языка"} else 1
    if full_name == query_norm:
        priority = 0
    elif member_name == query_norm:
        priority = 1
    elif full_name.endswith("." + query_norm):
        priority = 2
    else:
        priority = 3
    return (
        priority,
        owner_priority,
        -_score_case(query, item),
        _normalize_name(str(item.get("full_name") or item.get("title") or "")),
    )


def _rank_cases(query: str, items: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    ranked = sorted(
        items,
        key=lambda item: _case_sort_key(query, item),
    )
    return [item for item in ranked if _score_case(query, item) > 0][:limit]


def _field_pct(items: list[dict[str, Any]], field: str) -> float:
    if not items:
        return 0.0
    present = 0
    for item in items:
        value = item.get(field)
        if isinstance(value, list):
            if value:
                present += 1
        elif str(value or "").strip():
            present += 1
    return round(present * 100.0 / len(items), 1)


def _is_structured_sufficient(item: dict[str, Any], entity: str) -> bool:
    if entity == "object":
        return bool(str(item.get("summary") or "").strip())
    kind = str(item.get("kind") or "")
    summary = bool(str(item.get("summary") or "").strip())
    syntax = bool(str(item.get("syntax") or "").strip())
    params = bool(item.get("params"))
    returns = bool(str(item.get("returns") or "").strip())
    availability = bool(str(item.get("availability") or "").strip())
    signals = sum([summary, syntax, params, returns, availability])
    if kind in _METHOD_LIKE_KINDS:
        return summary and signals >= 3
    return summary and signals >= 2


def build_structured_help_scorecard(
    *,
    snapshot_dir: Path | None = None,
    benchmark_path: Path | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = "onec_help",
) -> dict[str, Any]:
    """Build scorecard for structured help extraction quality."""
    base = (snapshot_dir or get_help_structured_dir()).expanduser().resolve()
    objects = _load_jsonl(base / API_OBJECTS_FILE)
    members = _load_jsonl(base / API_MEMBERS_FILE)
    examples = _load_jsonl(base / API_EXAMPLES_FILE)
    links = _load_jsonl(base / API_LINKS_FILE)
    benchmark = load_structured_benchmark(benchmark_path)

    method_like = [item for item in members if str(item.get("kind") or "") in _METHOD_LIKE_KINDS]
    member_kinds = Counter(str(item.get("kind") or "") for item in members)
    object_kinds = Counter(str(item.get("kind") or "") for item in objects)
    structured_paths = {
        str(item.get("topic_path") or "")
        for item in [*objects, *members, *examples]
        if str(item.get("topic_path") or "").strip()
    }

    unpacked_topics = iter_help_topics_from_unpacked()
    help_topics = unpacked_topics or iter_help_topics_from_index(
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        collection=collection,
    )
    help_paths = {
        canonical_topic_path(str(item.get("path") or ""), str(item.get("version") or ""))
        for item in help_topics
        if str(item.get("path") or "").strip()
    }
    help_only = [
        item
        for item in help_topics
        if canonical_topic_path(str(item.get("path") or ""), str(item.get("version") or ""))
        not in structured_paths
    ]
    help_only_types = Counter(str(item.get("entity_type") or "topic") for item in help_only)
    help_only_buckets = Counter(
        _classify_help_only_topic(
            canonical_topic_path(str(item.get("path") or ""), str(item.get("version") or ""))
        )
        for item in help_only
    )

    cases: list[dict[str, Any]] = []
    top1 = 0
    top3 = 0
    sufficient = 0
    for case in benchmark:
        haystack = members if case["entity"] == "member" else objects
        hits = _rank_cases(case["query"], haystack, limit=3)
        matched_index = -1
        for idx, hit in enumerate(hits):
            if _matches_expected_name(case["expected_full_name"], hit):
                matched_index = idx
                break
        if matched_index == 0:
            top1 += 1
        if matched_index >= 0:
            top3 += 1
            if _is_structured_sufficient(hits[matched_index], case["entity"]):
                sufficient += 1
        cases.append(
            {
                **case,
                "top1": matched_index == 0,
                "top3": matched_index >= 0,
                "structured_sufficient": matched_index >= 0
                and _is_structured_sufficient(hits[matched_index], case["entity"]),
                "top_hit_full_name": str(hits[0].get("full_name") or "") if hits else "",
                "top_hit_kind": str(hits[0].get("kind") or "") if hits else "",
                "top_hit_path": str(hits[0].get("topic_path") or "") if hits else "",
            }
        )

    benchmark_total = len(benchmark) or 1
    coverage = {
        "summary_pct": _field_pct(members, "summary"),
        "syntax_pct": _field_pct(members, "syntax"),
        "params_pct": _field_pct(members, "params"),
        "returns_pct": _field_pct(members, "returns"),
        "availability_pct": _field_pct(members, "availability"),
        "owner_name_pct": _field_pct(members, "owner_name"),
        "method_like_params_pct": _field_pct(method_like, "params"),
        "method_like_returns_pct": _field_pct(method_like, "returns"),
        "kind_topic_pct": round(member_kinds.get("topic", 0) * 100.0 / len(members), 3)
        if members
        else 0.0,
    }
    benchmark_metrics = {
        "total": len(benchmark),
        "exact_top1_pct": round(top1 * 100.0 / benchmark_total, 1),
        "exact_top3_pct": round(top3 * 100.0 / benchmark_total, 1),
        "structured_sufficient_pct": round(sufficient * 100.0 / benchmark_total, 1),
    }
    path_metrics = {
        "help_topics_total": len(help_paths),
        "structured_paths_total": len(structured_paths),
        "path_coverage_pct": round(len(structured_paths) * 100.0 / len(help_paths), 1)
        if help_paths
        else 0.0,
        "help_only_total": len(help_only),
        "help_only_entity_types": dict(help_only_types.most_common(10)),
        "help_only_buckets": dict(help_only_buckets.most_common(10)),
        "source": "unpacked_html" if unpacked_topics else "indexed_topics",
    }
    targets = {
        key: {
            "target": value,
            "actual": coverage.get(key, benchmark_metrics.get(key, 0.0)),
            "met": (coverage.get(key, benchmark_metrics.get(key, 0.0)) >= value),
        }
        for key, value in _DEFAULT_TARGETS.items()
    }
    return {
        "format": "onec_help_structured_scorecard_v1",
        "snapshot_dir": str(base),
        "benchmark_path": str(
            (benchmark_path or get_default_benchmark_path()).expanduser().resolve()
        ),
        "counts": {
            "objects": len(objects),
            "members": len(members),
            "examples": len(examples),
            "links": len(links),
        },
        "kinds": {
            "objects": dict(object_kinds.most_common()),
            "members": dict(member_kinds.most_common()),
        },
        "coverage": coverage,
        "path_coverage": path_metrics,
        "benchmark": benchmark_metrics,
        "targets": targets,
        "cases": cases,
    }
