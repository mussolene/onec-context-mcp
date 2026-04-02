"""Structured API snapshot built from indexed 1C platform help topics."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..shared import env_config

API_OBJECTS_FILE = "api_objects.jsonl"
API_MEMBERS_FILE = "api_members.jsonl"
API_EXAMPLES_FILE = "api_examples.jsonl"
API_LINKS_FILE = "api_links.jsonl"

API_OBJECTS_COLLECTION_NAME = "onec_help_api_objects"
API_MEMBERS_COLLECTION_NAME = "onec_help_api_members"
API_EXAMPLES_COLLECTION_NAME = "onec_help_examples"
API_LINKS_COLLECTION_NAME = "onec_help_api_links"

# Backward-compatible alias used by callers/tests from the previous structured layer.
API_COLLECTION_NAME = API_MEMBERS_COLLECTION_NAME

_SECTION_ALIASES: dict[str, str] = {
    "Синтаксис": "syntax",
    "Параметры": "params",
    "Возвращаемое значение": "returns",
    "Пример": "example",
    "Доступность": "availability",
    "Использование в версии": "availability",
    "См. также": "see_also",
}
_GENERIC_BREADCRUMB = {
    "объекты",
    "типы",
    "методы",
    "свойства",
    "конструкторы",
    "события",
    "functions",
    "methods",
    "properties",
    "types",
    "events",
    "constructors",
}
_CODE_BLOCK_RE = re.compile(r"```(?:\w+)?\s*\n(.*?)```", re.DOTALL)
_STRUCTURED_MEMBER_KINDS = {"method", "property", "event", "constructor", "function"}
_STRUCTURED_OBJECT_KINDS = {"type", "manager", "global_context", "metadata_object", "collection", "enum"}


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


def _infer_member_kind(topic_path: str, title: str, entity_type: str) -> str:
    entity = (entity_type or "").strip().lower()
    if entity in _STRUCTURED_MEMBER_KINDS:
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
    if "/ctors/" in path or ".По умолчанию" in title_clean:
        return "constructor"
    return "topic"


def _infer_object_kind(topic_path: str, title: str) -> str:
    path = (topic_path or "").replace("\\", "/").lower()
    title_base = _strip_title_suffix(title)
    if title_base.startswith("Глобальный контекст"):
        return "global_context"
    if title_base.startswith("ОбъектМетаданных:"):
        return "metadata_object"
    if "менеджер" in title_base.lower():
        return "manager"
    if path.endswith("/global context.html"):
        return "global_context"
    if "/enums/" in path or "перечислен" in title_base.lower():
        return "enum"
    if "/collections/" in path or "коллекц" in title_base.lower():
        return "collection"
    if "/objects/" in path:
        return "type"
    return "topic"


def _has_structured_api_sections(sections: dict[str, str]) -> bool:
    return any(sections.get(key) for key in ("syntax", "params", "returns", "availability"))


def _should_index_object_topic(topic_path: str, title: str, sections: dict[str, str], kind: str) -> bool:
    if kind in _STRUCTURED_OBJECT_KINDS:
        return True
    if not _has_structured_api_sections(sections):
        return False
    path = (topic_path or "").replace("\\", "/").lower()
    title_base = _strip_title_suffix(title)
    if title_base.startswith("ОбъектМетаданных:"):
        return True
    return "/objects/" in path and not any(
        marker in path for marker in ("/methods/", "/properties/", "/events/", "/ctors/")
    )


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
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("-"):
            line = line.lstrip("- ").strip()
        if line.startswith("<") and ">" in line:
            name = line
            type_value = ""
            description = ""
            if idx + 1 < len(lines) and lines[idx + 1].startswith("Тип:"):
                type_value = lines[idx + 1].removeprefix("Тип:").strip()
                idx += 1
            if idx + 1 < len(lines):
                description = lines[idx + 1]
                idx += 1
            params.append({"name": name, "type": type_value or "—", "description": description})
        else:
            m = re.match(r"\*\*(.+?)\*\*\s+\((.+?)\)\s*$", line)
            if m:
                params.append({"name": m.group(1).strip(), "type": m.group(2).strip(), "description": ""})
            elif line:
                params.append({"name": line, "type": "", "description": ""})
        idx += 1
    return params


def _extract_code_blocks(md_text: str) -> list[str]:
    return [block.strip() for block in _CODE_BLOCK_RE.findall(md_text or "") if block.strip()]


def _extract_see_also(section_text: str) -> list[str]:
    if not section_text:
        return []
    values: list[str] = []
    for raw in section_text.splitlines():
        line = raw.strip().strip("-").strip()
        if not line:
            continue
        values.append(line)
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _split_full_name(name: str) -> tuple[str, str]:
    value = (name or "").strip()
    if "." in value:
        owner, member = value.rsplit(".", 1)
        return owner.strip(), member.strip()
    return "", value


def _make_object_stub(
    owner_name: str,
    *,
    version: str,
    language: str,
    topic_path: str = "",
    breadcrumb: list[str] | None = None,
    owner_kind: str = "type",
) -> dict[str, Any]:
    return {
        "id": _topic_point_id(f"object:{owner_name}", version, language),
        "object_name": owner_name,
        "full_name": owner_name,
        "kind": owner_kind,
        "title": owner_name,
        "summary": "",
        "availability": "",
        "version": version,
        "language": language,
        "topic_path": topic_path,
        "breadcrumb": breadcrumb or [],
        "aliases": [],
        "see_also": [],
    }


def extract_structured_records_from_topic(
    topic: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract structured object/member records, official examples and related links from indexed topic payload."""
    text = _normalize_text(str(topic.get("text") or ""))
    payload_title = str(topic.get("title") or "").strip()
    title, intro, sections = _split_markdown_sections(text)
    title = title or payload_title or str(topic.get("path") or "").strip()
    version = str(topic.get("version") or "")
    language = str(topic.get("language") or "")
    path = str(topic.get("path") or "")
    entity_type = str(topic.get("entity_type") or "topic").strip() or "topic"
    breadcrumb = list(topic.get("breadcrumb") or [])
    member_kind = _infer_member_kind(path, title, entity_type)
    object_kind = _infer_object_kind(path, title)
    if member_kind == "topic" and "." in _strip_title_suffix(title) and (
        sections.get("syntax") or sections.get("params") or sections.get("returns")
    ):
        member_kind = "method"
    summary_source = intro or sections.get("returns") or sections.get("syntax") or text
    summary = _compact_summary(summary_source, 500)
    see_also = _extract_see_also(sections.get("see_also", ""))

    object_record: dict[str, Any] | None = None
    member_record: dict[str, Any] | None = None

    if member_kind in _STRUCTURED_MEMBER_KINDS:
        full_name = _normalize_api_name(title, member_kind, breadcrumb)
        owner_name, member_name = _split_full_name(full_name)
        owner_kind = _infer_object_kind(path.rsplit("/", 2)[0] if "/" in path else path, owner_name) if owner_name else "type"
        member_record = {
            "id": _topic_point_id(path, version, language),
            "owner_name": owner_name,
            "owner_kind": owner_kind,
            "member_name": member_name,
            "full_name": full_name,
            "kind": member_kind,
            "title": title,
            "summary": summary,
            "syntax": sections.get("syntax", ""),
            "params": _parse_param_lines(sections.get("params", "")),
            "returns": sections.get("returns", ""),
            "availability": sections.get("availability", ""),
            "version": version,
            "language": language,
            "topic_path": path,
            "breadcrumb": breadcrumb,
            "aliases": [title] if title and title != full_name else [],
            "see_also": see_also,
        }
        if owner_name:
            object_record = _make_object_stub(
                owner_name,
                version=version,
                language=language,
                breadcrumb=breadcrumb[:-1] if breadcrumb else [],
                owner_kind=owner_kind if owner_kind in _STRUCTURED_OBJECT_KINDS else "type",
            )
    elif _should_index_object_topic(
        path,
        title,
        {
            "syntax": sections.get("syntax", ""),
            "params": "1" if sections.get("params") else "",
            "returns": sections.get("returns", ""),
            "availability": sections.get("availability", ""),
        },
        object_kind,
    ):
        full_name = _strip_title_suffix(title)
        object_record = {
            "id": _topic_point_id(path, version, language),
            "object_name": full_name,
            "full_name": full_name,
            "kind": object_kind if object_kind in _STRUCTURED_OBJECT_KINDS else "type",
            "title": title,
            "summary": summary,
            "availability": sections.get("availability", ""),
            "version": version,
            "language": language,
            "topic_path": path,
            "breadcrumb": breadcrumb,
            "aliases": [title] if title and title != full_name else [],
            "see_also": see_also,
        }

    examples: list[dict[str, Any]] = []
    example_section = sections.get("example", "")
    code_blocks = _extract_code_blocks(example_section)
    if code_blocks and member_record is not None:
        description = _compact_summary(_CODE_BLOCK_RE.sub("", example_section).strip(), 300)
        for idx, code in enumerate(code_blocks, 1):
            examples.append(
                {
                    "id": _topic_point_id(f"{path}#example-{idx}", version, language),
                    "owner_name": member_record.get("owner_name") or "",
                    "member_name": member_record.get("member_name") or "",
                    "full_name": member_record.get("full_name") or "",
                    "kind": member_record.get("kind") or "example",
                    "example_title": f"{title} — пример {idx}",
                    "title": f"{title} — пример {idx}",
                    "description": description,
                    "code": code,
                    "topic_path": path,
                    "version": version,
                    "language": language,
                }
            )

    links: list[dict[str, Any]] = []
    source_full_name = (
        (member_record or object_record or {}).get("full_name")
        or (member_record or object_record or {}).get("object_name")
        or ""
    )
    if source_full_name:
        for idx, target_name in enumerate(see_also, 1):
            links.append(
                {
                    "id": _topic_point_id(f"{path}#see-also-{idx}", version, language),
                    "source_full_name": source_full_name,
                    "target_name": target_name,
                    "link_kind": "see_also",
                    "topic_path": path,
                    "version": version,
                    "language": language,
                    "text": f"{source_full_name} -> {target_name}",
                }
            )

    return object_record, member_record, examples, links


def extract_api_records_from_topic(topic: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Backward-compatible wrapper that returns member record + examples for API topics."""
    object_record, member_record, examples, _links = extract_structured_records_from_topic(topic)
    if member_record is not None:
        return (
            {
                "id": member_record.get("id"),
                "name": member_record.get("full_name") or member_record.get("member_name") or "",
                "kind": member_record.get("kind") or "topic",
                "title": member_record.get("title") or "",
                "summary": member_record.get("summary") or "",
                "syntax": member_record.get("syntax") or "",
                "params": member_record.get("params") or [],
                "returns": member_record.get("returns") or "",
                "availability": member_record.get("availability") or "",
                "version": member_record.get("version") or "",
                "language": member_record.get("language") or "",
                "topic_path": member_record.get("topic_path") or "",
                "breadcrumb": member_record.get("breadcrumb") or [],
                "entity_type": member_record.get("kind") or "topic",
            },
            examples,
        )
    if object_record is not None:
        return (
            {
                "id": object_record.get("id"),
                "name": object_record.get("full_name") or object_record.get("object_name") or "",
                "kind": object_record.get("kind") or "topic",
                "title": object_record.get("title") or "",
                "summary": object_record.get("summary") or "",
                "syntax": "",
                "params": [],
                "returns": "",
                "availability": object_record.get("availability") or "",
                "version": object_record.get("version") or "",
                "language": object_record.get("language") or "",
                "topic_path": object_record.get("topic_path") or "",
                "breadcrumb": object_record.get("breadcrumb") or [],
                "entity_type": object_record.get("kind") or "topic",
            },
            examples,
        )
    return (
        {
            "id": _topic_point_id(str(topic.get("path") or ""), str(topic.get("version") or ""), str(topic.get("language") or "")),
            "name": _strip_title_suffix(str(topic.get("title") or "")),
            "kind": "topic",
            "title": str(topic.get("title") or ""),
            "summary": _compact_summary(str(topic.get("text") or ""), 500),
            "syntax": "",
            "params": [],
            "returns": "",
            "availability": "",
            "version": topic.get("version") or "",
            "language": topic.get("language") or "",
            "topic_path": topic.get("path") or "",
            "breadcrumb": list(topic.get("breadcrumb") or []),
            "entity_type": "topic",
        },
        [],
    )


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


def _write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")


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
    topics = iter_help_topics_from_index(
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        collection=collection,
    )

    objects_by_name: dict[str, dict[str, Any]] = {}
    members: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []

    for topic in topics:
        object_record, member_record, topic_examples, topic_links = extract_structured_records_from_topic(topic)
        if object_record is not None:
            key = str(object_record.get("full_name") or object_record.get("object_name") or "")
            prev = objects_by_name.get(key)
            if prev is None or (not prev.get("topic_path") and object_record.get("topic_path")):
                objects_by_name[key] = object_record
        if member_record is not None:
            members.append(member_record)
        examples.extend(topic_examples)
        links.extend(topic_links)

    object_items = sorted(objects_by_name.values(), key=lambda item: str(item.get("full_name") or ""))
    members.sort(key=lambda item: str(item.get("full_name") or ""))
    examples.sort(key=lambda item: str(item.get("full_name") or ""))
    links.sort(key=lambda item: (str(item.get("source_full_name") or ""), str(item.get("target_name") or "")))

    _write_jsonl(out_dir / API_OBJECTS_FILE, object_items)
    _write_jsonl(out_dir / API_MEMBERS_FILE, members)
    _write_jsonl(out_dir / API_EXAMPLES_FILE, examples)
    _write_jsonl(out_dir / API_LINKS_FILE, links)

    manifest = {
        "format": "onec_help_structured_api_v2",
        "objects": len(object_items),
        "members": len(members),
        "examples": len(examples),
        "links": len(links),
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
        if line:
            items.append(json.loads(line))
    return items


def load_api_objects(snapshot_dir: Path | None = None) -> list[dict[str, Any]]:
    base = (snapshot_dir or get_help_structured_dir()).expanduser().resolve()
    return _read_jsonl(base / API_OBJECTS_FILE)


def load_api_members(snapshot_dir: Path | None = None) -> list[dict[str, Any]]:
    base = (snapshot_dir or get_help_structured_dir()).expanduser().resolve()
    return _read_jsonl(base / API_MEMBERS_FILE)


def load_api_examples(snapshot_dir: Path | None = None) -> list[dict[str, Any]]:
    base = (snapshot_dir or get_help_structured_dir()).expanduser().resolve()
    return _read_jsonl(base / API_EXAMPLES_FILE)


def load_api_links(snapshot_dir: Path | None = None) -> list[dict[str, Any]]:
    base = (snapshot_dir or get_help_structured_dir()).expanduser().resolve()
    return _read_jsonl(base / API_LINKS_FILE)


def _record_embedding_text(item: dict[str, Any], *, kind: str) -> str:
    params = item.get("params") or []
    params_text = "\n".join(
        f"- {param.get('name', '')}: {param.get('type', '')}".strip(": ")
        for param in params
        if isinstance(param, dict)
    )
    parts = [
        item.get("full_name") or item.get("object_name") or "",
        item.get("title") or "",
        item.get("summary") or "",
        item.get("syntax") or "",
        params_text,
        item.get("returns") or "",
        item.get("availability") or "",
        " > ".join(str(x) for x in (item.get("breadcrumb") or [])),
        kind,
    ]
    return "\n".join(part for part in parts if part).strip()


def _index_records(
    items: list[dict[str, Any]],
    *,
    collection: str,
    recreate: bool,
    batch_size: int,
    qdrant_host: str | None,
    qdrant_port: int | None,
    payload_builder,
) -> int:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

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
            payload = payload_builder(item)
            points.append(
                PointStruct(
                    id=int(item.get("id") or _topic_point_id(payload.get("path", ""), payload.get("version", ""), payload.get("language", ""))),
                    vector=[0.0],
                    payload=payload,
                )
            )
        client.upsert(collection_name=collection, points=points)
        inserted += len(points)
    return inserted


def index_structured_api_objects(
    snapshot_dir: Path | None = None,
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = API_OBJECTS_COLLECTION_NAME,
    recreate: bool = True,
    batch_size: int = 200,
) -> int:
    """Index structured API objects into dedicated object collection."""
    items = load_api_objects(snapshot_dir)
    return _index_records(
        items,
        collection=collection,
        recreate=recreate,
        batch_size=batch_size,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        payload_builder=lambda item: {
            "object_name": item.get("object_name") or "",
            "full_name": item.get("full_name") or item.get("object_name") or "",
            "name": item.get("full_name") or item.get("object_name") or "",
            "kind": item.get("kind") or "type",
            "title": item.get("title") or "",
            "summary": item.get("summary") or "",
            "availability": item.get("availability") or "",
            "version": item.get("version") or "",
            "language": item.get("language") or "",
            "topic_path": item.get("topic_path") or "",
            "path": item.get("topic_path") or "",
            "entity_type": item.get("kind") or "type",
            "breadcrumb": item.get("breadcrumb") or [],
            "see_also": item.get("see_also") or [],
            "aliases": item.get("aliases") or [],
            "text": _record_embedding_text(item, kind="object"),
        },
    )


def index_structured_api_members(
    snapshot_dir: Path | None = None,
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = API_MEMBERS_COLLECTION_NAME,
    recreate: bool = True,
    batch_size: int = 200,
) -> int:
    """Index structured API members into dedicated member collection."""
    items = load_api_members(snapshot_dir)
    return _index_records(
        items,
        collection=collection,
        recreate=recreate,
        batch_size=batch_size,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        payload_builder=lambda item: {
            "owner_name": item.get("owner_name") or "",
            "owner_kind": item.get("owner_kind") or "type",
            "member_name": item.get("member_name") or "",
            "full_name": item.get("full_name") or "",
            "name": item.get("full_name") or "",
            "kind": item.get("kind") or "method",
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
            "entity_type": item.get("kind") or "method",
            "breadcrumb": item.get("breadcrumb") or [],
            "see_also": item.get("see_also") or [],
            "aliases": item.get("aliases") or [],
            "text": _record_embedding_text(item, kind="member"),
        },
    )


def index_structured_api_examples(
    snapshot_dir: Path | None = None,
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = API_EXAMPLES_COLLECTION_NAME,
    recreate: bool = True,
    batch_size: int = 200,
) -> int:
    """Index official examples into dedicated example collection."""
    items = load_api_examples(snapshot_dir)
    return _index_records(
        items,
        collection=collection,
        recreate=recreate,
        batch_size=batch_size,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        payload_builder=lambda item: {
            "owner_name": item.get("owner_name") or "",
            "member_name": item.get("member_name") or "",
            "full_name": item.get("full_name") or "",
            "api_name": item.get("full_name") or "",
            "kind": item.get("kind") or "example",
            "title": item.get("title") or item.get("example_title") or "",
            "description": item.get("description") or "",
            "code": item.get("code") or "",
            "version": item.get("version") or "",
            "language": item.get("language") or "",
            "topic_path": item.get("topic_path") or "",
            "path": item.get("topic_path") or "",
            "entity_type": "example",
            "text": "\n".join(
                part
                for part in (
                    item.get("full_name") or "",
                    item.get("title") or "",
                    item.get("description") or "",
                    item.get("code") or "",
                )
                if part
            ),
        },
    )


def index_structured_api_links(
    snapshot_dir: Path | None = None,
    *,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
    collection: str = API_LINKS_COLLECTION_NAME,
    recreate: bool = True,
    batch_size: int = 200,
) -> int:
    """Index API links into dedicated relation collection."""
    items = load_api_links(snapshot_dir)
    return _index_records(
        items,
        collection=collection,
        recreate=recreate,
        batch_size=batch_size,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        payload_builder=lambda item: {
            "source_full_name": item.get("source_full_name") or "",
            "target_name": item.get("target_name") or "",
            "link_kind": item.get("link_kind") or "see_also",
            "version": item.get("version") or "",
            "language": item.get("language") or "",
            "topic_path": item.get("topic_path") or "",
            "path": item.get("topic_path") or "",
            "entity_type": "link",
            "text": item.get("text") or "",
        },
    )


def _score_text_match(query: str, item: dict[str, Any], fields: list[str]) -> int:
    q = (query or "").strip().lower()
    if not q:
        return 0
    tokens = [token.lower() for token in re.findall(r"[А-Яа-яA-Za-z0-9_.-]+", q) if len(token) >= 2]
    haystack_parts = [str(item.get(field) or "") for field in fields]
    haystack = " ".join(haystack_parts).lower()
    primary = str(item.get(fields[0]) or "").lower() if fields else ""
    score = 0
    if q == primary:
        score += 100
    elif q in primary:
        score += 40
    for token in tokens:
        if token in haystack:
            score += 5
    return score


def _scroll_payloads(collection: str) -> list[dict[str, Any]]:
    from qdrant_client import QdrantClient

    host = env_config.get_qdrant_host()
    port = env_config.get_qdrant_port()
    client = QdrantClient(host=host, port=port, check_compatibility=False)
    if not client.collection_exists(collection):
        return []
    offset = None
    items: list[dict[str, Any]] = []
    while True:
        points, next_offset = client.scroll(
            collection_name=collection,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            break
        for point in points:
            items.append(getattr(point, "payload", None) or {})
        if next_offset is None:
            break
        offset = next_offset
    return items


def search_official_examples(
    query: str,
    *,
    snapshot_dir: Path | None = None,
    limit: int = 5,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Qdrant-backed search over official examples extracted from help topics."""
    items = _scroll_payloads(API_EXAMPLES_COLLECTION_NAME) if snapshot_dir is None else []
    if not items:
        items = load_api_examples(snapshot_dir) if snapshot_dir is not None else []
    results: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        if version and str(item.get("version") or "") != version:
            continue
        if language and str(item.get("language") or "") != language:
            continue
        score = _score_text_match(query, item, ["full_name", "title", "description", "code"])
        if score > 0:
            results.append((score, item))
    results.sort(key=lambda item: (-item[0], str(item[1].get("full_name") or ""), str(item[1].get("title") or "")))
    return [item for _, item in results[:limit]]


def search_api_members(
    query: str,
    *,
    limit: int = 10,
    version: str | None = None,
    language: str | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
) -> list[dict[str, Any]]:
    """Keyword search over structured API member collection."""
    from ..search_store.indexer import search_index_keyword

    return search_index_keyword(
        query,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        collection=API_MEMBERS_COLLECTION_NAME,
        limit=limit,
        version=version,
        language=language,
    )


def search_api_objects(
    query: str,
    *,
    limit: int = 10,
    version: str | None = None,
    language: str | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
) -> list[dict[str, Any]]:
    """Keyword search over structured API object collection."""
    from ..search_store.indexer import search_index_keyword

    return search_index_keyword(
        query,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        collection=API_OBJECTS_COLLECTION_NAME,
        limit=limit,
        version=version,
        language=language,
    )


def get_api_member(
    name: str,
    *,
    version: str | None = None,
    language: str | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
) -> list[dict[str, Any]]:
    """Exact-first lookup in structured API member collection."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    client = QdrantClient(host=host, port=port, check_compatibility=False)
    if not client.collection_exists(API_MEMBERS_COLLECTION_NAME):
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
            collection_name=API_MEMBERS_COLLECTION_NAME,
            scroll_filter=Filter(must=must),
            limit=10,
            with_payload=True,
            with_vectors=False,
        )
        results = [getattr(point, "payload", None) or {} for point in points or []]
    except Exception:
        results = []
    if results:
        return results
    return search_api_members(
        name_clean,
        limit=10,
        version=version,
        language=language,
        qdrant_host=host,
        qdrant_port=port,
    )


def get_api_object(
    name: str,
    *,
    version: str | None = None,
    language: str | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
) -> list[dict[str, Any]]:
    """Exact-first lookup in structured API object collection."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    host = qdrant_host or env_config.get_qdrant_host()
    port = qdrant_port or env_config.get_qdrant_port()
    client = QdrantClient(host=host, port=port, check_compatibility=False)
    if not client.collection_exists(API_OBJECTS_COLLECTION_NAME):
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
            collection_name=API_OBJECTS_COLLECTION_NAME,
            scroll_filter=Filter(must=must),
            limit=10,
            with_payload=True,
            with_vectors=False,
        )
        results = [getattr(point, "payload", None) or {} for point in points or []]
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


def get_api_related(
    name: str,
    *,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Exact-first lookup of related API links by source name."""
    items = _scroll_payloads(API_LINKS_COLLECTION_NAME)
    name_clean = (name or "").strip()
    if not name_clean:
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if version and str(item.get("version") or "") != version:
            continue
        if language and str(item.get("language") or "") != language:
            continue
        if str(item.get("source_full_name") or "") == name_clean:
            out.append(item)
    return out


# Backward-compatible wrappers used by the old MCP route/tests.
def get_api_object_legacy(
    name: str,
    *,
    version: str | None = None,
    language: str | None = None,
    qdrant_host: str | None = None,
    qdrant_port: int | None = None,
) -> list[dict[str, Any]]:
    return get_api_member(
        name,
        version=version,
        language=language,
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
    )
