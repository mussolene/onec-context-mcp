"""Structured API snapshot built from indexed 1C platform help topics."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..shared import env_config

API_OBJECTS_FILE = "api_objects.jsonl"
API_EXAMPLES_FILE = "api_examples.jsonl"
API_COLLECTION_NAME = "onec_help_api"
API_EXAMPLES_COLLECTION_NAME = "onec_help_examples"

_SECTION_ALIASES: dict[str, str] = {
    "Синтаксис": "syntax",
    "Параметры": "params",
    "Возвращаемое значение": "returns",
    "Пример": "example",
    "Доступность": "availability",
    "Использование в версии": "availability",
}
_GENERIC_BREADCRUMB = {
    "объекты",
    "типы",
    "методы",
    "свойства",
    "functions",
    "methods",
    "properties",
    "types",
}
_CODE_BLOCK_RE = re.compile(r"```(?:\w+)?\s*\n(.*?)```", re.DOTALL)
_STRUCTURED_API_KINDS = {"method", "property", "event", "constructor", "function", "type"}


def get_help_structured_dir() -> Path:
    """Derived structured help snapshot directory."""
    return Path(env_config.get_help_structured_dir()).expanduser().resolve()


def _topic_point_id(path: str, version: str = "", language: str = "") -> int:
    import hashlib

    key = f"{version}|{language}|{path}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:14], 16) % (2**63)


def _normalize_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in (value or "").replace("\r\n", "\n").splitlines()).strip()


def _compact_summary(value: str, max_chars: int = 500) -> str:
    text = " ".join((value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _strip_title_suffix(title: str) -> str:
    base = (title or "").strip()
    if " (" in base:
        base = base.split(" (", 1)[0].strip()
    return base


def _member_parent_from_breadcrumb(title: str, breadcrumb: list[str] | None) -> str:
    title_lower = (title or "").strip().lower()
    for item in reversed(breadcrumb or []):
        raw = str(item or "").strip()
        if not raw:
            continue
        lowered = raw.lower()
        if lowered == title_lower or lowered in _GENERIC_BREADCRUMB:
            continue
        return raw
    return ""


def _normalize_api_name(title: str, entity_type: str, breadcrumb: list[str] | None) -> str:
    base = _strip_title_suffix(title)
    if "." in base or entity_type not in {"method", "property", "event", "constructor"}:
        return base
    parent = _member_parent_from_breadcrumb(base, breadcrumb)
    if not parent or "." in parent:
        return base
    return f"{parent}.{base}"


def _infer_api_kind(topic_path: str, title: str, entity_type: str) -> str:
    entity = (entity_type or "").strip().lower()
    if entity in _STRUCTURED_API_KINDS:
        return entity
    path = (topic_path or "").replace("\\", "/").lower()
    title_clean = (title or "").strip()
    if "/methods/" in path:
        if "/script functions/" in path or title_clean.startswith("Встроенные функции языка."):
            return "function"
        return "method"
    if "/properties/" in path:
        return "property"
    if "/events/" in path:
        return "event"
    if "/construct" in path or ".По умолчанию" in title_clean:
        return "constructor"
    if "/types/" in path:
        return "type"
    return "topic"


def _has_structured_api_sections(sections: dict[str, str]) -> bool:
    return any(sections.get(key) for key in ("syntax", "params", "returns", "availability"))


def _should_index_api_topic(topic_path: str, title: str, sections: dict[str, str], kind: str) -> bool:
    if kind in _STRUCTURED_API_KINDS:
        return True
    if not _has_structured_api_sections(sections):
        return False
    title_base = _strip_title_suffix(title)
    if "." in title_base:
        return True
    if title_base.startswith("ОбъектМетаданных:"):
        return True
    if title_base.startswith("Встроенные функции языка."):
        return True
    path = (topic_path or "").replace("\\", "/").lower()
    return "/objects/" in path


def _split_markdown_sections(text: str) -> tuple[str, str, dict[str, str]]:
    lines = _normalize_text(text).splitlines()
    title = ""
    intro: list[str] = []
    sections: dict[str, list[str]] = {}
    current_key: str | None = None
    in_code = False
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
            continue
        if not in_code and stripped.startswith("## "):
            heading = stripped[3:].strip()
            current_key = _SECTION_ALIASES.get(heading)
            if current_key:
                sections.setdefault(current_key, [])
            else:
                current_key = None
            continue
        if current_key:
            sections[current_key].append(line)
        elif title:
            intro.append(line)
    intro_text = _normalize_text("\n".join(intro))
    return title, intro_text, {key: _normalize_text("\n".join(value)) for key, value in sections.items()}


def _parse_param_lines(text: str) -> list[dict[str, str]]:
    params: list[dict[str, str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line.startswith("-"):
            continue
        m = re.match(r"-\s+\*\*(.+?)\*\*\s+\((.+?)\)\s*$", line)
        if m:
            params.append({"name": m.group(1).strip(), "type": m.group(2).strip(), "description": ""})
        else:
            params.append({"name": line.lstrip("- ").strip(), "type": "", "description": ""})
    return params


def _extract_code_blocks(md_text: str) -> list[str]:
    return [block.strip() for block in _CODE_BLOCK_RE.findall(md_text or "") if block.strip()]


def extract_api_records_from_topic(topic: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Extract one structured API object and zero or more official examples from indexed topic payload."""
    text = _normalize_text(str(topic.get("text") or ""))
    payload_title = str(topic.get("title") or "").strip()
    title, intro, sections = _split_markdown_sections(text)
    title = title or payload_title or str(topic.get("path") or "").strip()
    entity_type = str(topic.get("entity_type") or "topic").strip() or "topic"
    kind = _infer_api_kind(str(topic.get("path") or ""), title, entity_type)
    breadcrumb = list(topic.get("breadcrumb") or [])
    name = _normalize_api_name(title, kind, breadcrumb)
    summary_source = intro or sections.get("returns") or sections.get("syntax") or text
    summary = _compact_summary(summary_source, 500)
    api_object = {
        "id": _topic_point_id(
            str(topic.get("path") or ""),
            str(topic.get("version") or ""),
            str(topic.get("language") or ""),
        ),
        "name": name,
        "kind": kind,
        "title": title,
        "summary": summary,
        "syntax": sections.get("syntax", ""),
        "params": _parse_param_lines(sections.get("params", "")),
        "returns": sections.get("returns", ""),
        "availability": sections.get("availability", ""),
        "version": topic.get("version") or "",
        "language": topic.get("language") or "",
        "topic_path": topic.get("path") or "",
        "breadcrumb": breadcrumb,
        "entity_type": kind,
    }
    examples: list[dict[str, Any]] = []
    example_section = sections.get("example", "")
    code_blocks = _extract_code_blocks(example_section)
    if code_blocks:
        description = _compact_summary(_CODE_BLOCK_RE.sub("", example_section).strip(), 300)
        for idx, code in enumerate(code_blocks, 1):
            examples.append(
                {
                    "id": _topic_point_id(
                        f"{topic.get('path', '')}#example-{idx}",
                        str(topic.get("version") or ""),
                        str(topic.get("language") or ""),
                    ),
                    "api_name": name,
                    "title": f"{title} — пример {idx}",
                    "code": code,
                    "description": description,
                    "topic_path": topic.get("path") or "",
                    "version": topic.get("version") or "",
                    "language": topic.get("language") or "",
                    "entity_type": kind,
                }
            )
    return api_object, examples


def iter_help_topics_from_index(
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = "onec_help",
) -> list[dict[str, Any]]:
    """Read unique topic payloads from help index, preferring latest version for duplicate paths."""
    from qdrant_client import QdrantClient

    from ..search_store.indexer import _get_default_qdrant_client, _version_sort_key

    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    if QdrantClient is None:
        return []
    client = _get_default_qdrant_client(host, port)
    if not client.collection_exists(collection):
        return []
    by_path: dict[str, dict[str, Any]] = {}
    offset = None
    while True:
        batch, next_offset = client.scroll(
            collection_name=collection,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not batch:
            break
        for point in batch:
            payload = getattr(point, "payload", None) or {}
            path = str(payload.get("path") or "").strip()
            if not path:
                continue
            current = {
                "path": path,
                "title": payload.get("title") or "",
                "text": payload.get("text") or "",
                "version": payload.get("version") or "",
                "language": payload.get("language") or "",
                "entity_type": payload.get("entity_type") or "topic",
                "breadcrumb": payload.get("breadcrumb") or [],
            }
            prev = by_path.get(path)
            if prev is None or _version_sort_key(str(current["version"])) > _version_sort_key(str(prev["version"])):
                by_path[path] = current
        if next_offset is None:
            break
        offset = next_offset
    return list(by_path.values())


def build_structured_api_snapshot(
    output_dir: Path | None = None,
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = "onec_help",
) -> dict[str, Any]:
    """Build structured API snapshot from indexed help topics."""
    out_dir = (output_dir or get_help_structured_dir()).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    objects_path = out_dir / API_OBJECTS_FILE
    examples_path = out_dir / API_EXAMPLES_FILE
    topics = iter_help_topics_from_index(
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        collection=collection,
    )
    api_objects: list[dict[str, Any]] = []
    api_examples: list[dict[str, Any]] = []
    for topic in topics:
        api_object, examples = extract_api_records_from_topic(topic)
        if not _should_index_api_topic(
            str(topic.get("path") or ""),
            str(api_object.get("title") or ""),
            {
                "syntax": str(api_object.get("syntax") or ""),
                "params": "1" if api_object.get("params") else "",
                "returns": str(api_object.get("returns") or ""),
                "availability": str(api_object.get("availability") or ""),
            },
            str(api_object.get("kind") or "topic"),
        ):
            continue
        api_objects.append(api_object)
        api_examples.extend(examples)
    with objects_path.open("w", encoding="utf-8") as fh:
        for item in api_objects:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    with examples_path.open("w", encoding="utf-8") as fh:
        for item in api_examples:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    manifest = {
        "format": "onec_help_structured_api_v1",
        "objects": len(api_objects),
        "examples": len(api_examples),
        "source_collection": collection,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not path.is_file():
        return items
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        items.append(json.loads(line))
    return items


def load_api_objects(snapshot_dir: Path | None = None) -> list[dict[str, Any]]:
    base = (snapshot_dir or get_help_structured_dir()).expanduser().resolve()
    return _read_jsonl(base / API_OBJECTS_FILE)


def load_api_examples(snapshot_dir: Path | None = None) -> list[dict[str, Any]]:
    base = (snapshot_dir or get_help_structured_dir()).expanduser().resolve()
    return _read_jsonl(base / API_EXAMPLES_FILE)


def _api_object_embedding_text(item: dict[str, Any]) -> str:
    params = item.get("params") or []
    params_text = "\n".join(
        f"- {param.get('name', '')}: {param.get('type', '')}".strip(": ")
        for param in params
        if isinstance(param, dict)
    )
    parts = [
        item.get("name") or "",
        item.get("title") or "",
        item.get("summary") or "",
        item.get("syntax") or "",
        params_text,
        item.get("returns") or "",
        item.get("availability") or "",
        " > ".join(str(x) for x in (item.get("breadcrumb") or [])),
    ]
    return "\n".join(part for part in parts if part).strip()


def index_structured_api_objects(
    snapshot_dir: Path | None = None,
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = API_COLLECTION_NAME,
    recreate: bool = True,
    batch_size: int = 200,
) -> int:
    """Index structured API objects into dedicated Qdrant collection."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    items = load_api_objects(snapshot_dir)
    if not items:
        return 0
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    client = QdrantClient(
        host=host,
        port=port,
        timeout=env_config.get_qdrant_timeout(),
        check_compatibility=False,
    )
    dim = 1
    if recreate:
        client.recreate_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
    elif not client.collection_exists(collection):
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )

    inserted = 0
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        points = []
        for item in batch:
            payload = {
                "name": item.get("name") or "",
                "kind": item.get("kind") or "topic",
                "title": item.get("title") or "",
                "summary": item.get("summary") or "",
                "syntax": item.get("syntax") or "",
                "params": item.get("params") or [],
                "returns": item.get("returns") or "",
                "availability": item.get("availability") or "",
                "version": item.get("version") or "",
                "language": item.get("language") or "",
                "topic_path": item.get("topic_path") or "",
                "path": item.get("topic_path") or "",
                "entity_type": item.get("entity_type") or (item.get("kind") or "topic"),
                "breadcrumb": item.get("breadcrumb") or [],
                "text": _api_object_embedding_text(item),
            }
            points.append(
                PointStruct(
                    id=int(item.get("id") or _topic_point_id(payload["path"], payload["version"], payload["language"])),
                    vector=[0.0],
                    payload=payload,
                )
            )
        client.upsert(collection_name=collection, points=points)
        inserted += len(points)
    return inserted


def index_structured_api_examples(
    snapshot_dir: Path | None = None,
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = API_EXAMPLES_COLLECTION_NAME,
    recreate: bool = True,
    batch_size: int = 200,
) -> int:
    """Index official examples into dedicated Qdrant collection."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    items = load_api_examples(snapshot_dir)
    if not items:
        return 0
    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    client = QdrantClient(
        host=host,
        port=port,
        timeout=env_config.get_qdrant_timeout(),
        check_compatibility=False,
    )
    dim = 1
    if recreate:
        client.recreate_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
    elif not client.collection_exists(collection):
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )

    inserted = 0
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        points = []
        for item in batch:
            payload = {
                "api_name": item.get("api_name") or "",
                "title": item.get("title") or "",
                "code": item.get("code") or "",
                "description": item.get("description") or "",
                "version": item.get("version") or "",
                "language": item.get("language") or "",
                "topic_path": item.get("topic_path") or "",
                "path": item.get("topic_path") or "",
                "entity_type": item.get("entity_type") or "example",
                "text": "\n".join(
                    part
                    for part in (
                        item.get("api_name") or "",
                        item.get("title") or "",
                        item.get("description") or "",
                        item.get("code") or "",
                    )
                    if part
                ),
            }
            points.append(
                PointStruct(
                    id=int(
                        item.get("id")
                        or _topic_point_id(
                            f"{payload['path']}#example",
                            payload["version"],
                            payload["language"],
                        )
                    ),
                    vector=[0.0],
                    payload=payload,
                )
            )
        client.upsert(collection_name=collection, points=points)
        inserted += len(points)
    return inserted


def search_official_examples(
    query: str,
    *,
    snapshot_dir: Path | None = None,
    limit: int = 5,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Qdrant-backed search over official examples extracted from help topics."""
    from qdrant_client import QdrantClient

    q = (query or "").strip().lower()
    if not q:
        return []
    host = env_config.get_qdrant_host()
    port = env_config.get_qdrant_port()
    client = QdrantClient(host=host, port=port, check_compatibility=False)
    items: list[dict[str, Any]] = []
    if client.collection_exists(API_EXAMPLES_COLLECTION_NAME):
        offset = None
        while True:
            points, next_offset = client.scroll(
                collection_name=API_EXAMPLES_COLLECTION_NAME,
                limit=500,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break
            for point in points:
                payload = getattr(point, "payload", None) or {}
                items.append(payload)
            if next_offset is None:
                break
            offset = next_offset
    elif snapshot_dir is not None:
        items = load_api_examples(snapshot_dir)
    else:
        return []

    tokens = [token.lower() for token in re.findall(r"[А-Яа-яA-Za-z0-9_.-]+", q) if len(token) >= 2]
    results: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        if version and str(item.get("version") or "") != version:
            continue
        if language and str(item.get("language") or "") != language:
            continue
        haystack = " ".join(
            [
                str(item.get("api_name") or ""),
                str(item.get("title") or ""),
                str(item.get("description") or ""),
                str(item.get("code") or ""),
            ]
        ).lower()
        score = 0
        api_name = str(item.get("api_name") or "").lower()
        if q == api_name:
            score += 100
        elif q in api_name:
            score += 40
        for token in tokens:
            if token in haystack:
                score += 5
        if score > 0:
            results.append((score, item))
    results.sort(key=lambda item: (-item[0], str(item[1].get("api_name") or ""), str(item[1].get("title") or "")))
    return [item for _, item in results[:limit]]


def search_api_objects(
    query: str,
    *,
    limit: int = 10,
    version: str | None = None,
    language: str | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
) -> list[dict[str, Any]]:
    """Keyword search over structured API collection."""
    from ..search_store.indexer import search_index_keyword

    return search_index_keyword(
        query,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        collection=API_COLLECTION_NAME,
        limit=limit,
        version=version,
        language=language,
    )


def get_api_object(
    name: str,
    *,
    version: str | None = None,
    language: str | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
) -> list[dict[str, Any]]:
    """Exact-first lookup in structured API collection."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    client = QdrantClient(host=host, port=port, check_compatibility=False)
    if not client.collection_exists(API_COLLECTION_NAME):
        return []
    name_clean = (name or "").strip()
    if not name_clean:
        return []
    must = [FieldCondition(key="name", match=MatchValue(value=name_clean))]
    if version:
        must.append(FieldCondition(key="version", match=MatchValue(value=version)))
    if language:
        must.append(FieldCondition(key="language", match=MatchValue(value=language)))
    results: list[dict[str, Any]] = []
    try:
        points, _ = client.scroll(
            collection_name=API_COLLECTION_NAME,
            scroll_filter=Filter(must=must),
            limit=10,
            with_payload=True,
            with_vectors=False,
        )
        for point in points or []:
            payload = getattr(point, "payload", None) or {}
            results.append(payload)
    except Exception:
        results = []
    if results:
        return results
    return search_api_objects(
        name_clean,
        limit=10,
        version=version,
        language=language,
        qdrant_host=host,
        qdrant_port=port,
    )
