"""Split long curated texts (standards, snippets, community references) for multi-vector indexing."""

from __future__ import annotations

import hashlib
from typing import Any

from ..shared import env_config


def stable_document_key(item: dict[str, Any], domain: str) -> str:
    """Stable id for one logical document (before chunking). Used in Qdrant point ids."""
    body = (item.get("instruction") or item.get("code_snippet") or "")[:4000]
    parts = [
        domain,
        str(item.get("detail_url") or ""),
        str(item.get("source_ref") or ""),
        str(item.get("title") or ""),
        hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()[:24],
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def split_text_with_overlap(text: str, *, max_chunk: int, overlap: int) -> list[str]:
    """Non-overlapping windows except tail overlap; skips empty input."""
    t = text.strip()
    if not t:
        return []
    if len(t) <= max_chunk:
        return [t]
    ov = min(max(0, overlap), max_chunk // 2)
    chunks: list[str] = []
    start = 0
    n = len(t)
    while start < n:
        end = min(start + max_chunk, n)
        chunks.append(t[start:end])
        if end >= n:
            break
        next_start = end - ov
        if next_start <= start:
            next_start = start + max(1, max_chunk - ov)
        start = next_start
    return chunks


def _should_chunk_domain(domain: str) -> bool:
    return domain in ("standards", "snippets", "community_help")


def expand_curated_items_for_indexing(
    items: list[dict[str, Any]], domain: str
) -> list[dict[str, Any]]:
    """One logical item → one or more rows (overlapping chunks) for embedding and Qdrant."""
    if not _should_chunk_domain(domain):
        return list(items)
    max_chunk = env_config.get_curated_chunk_body_chars()
    overlap = env_config.get_curated_chunk_overlap()
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        has_inst = bool((item.get("instruction") or "").strip())
        body = (item.get("instruction") if has_inst else item.get("code_snippet")) or ""
        body = body.strip()
        if not body:
            out.append(item)
            continue
        parts = split_text_with_overlap(body, max_chunk=max_chunk, overlap=overlap)
        total = len(parts)
        if total <= 1:
            # Один фрагмент — без parent_key: memory оставляет прежний point_id (title-hash).
            out.append(dict(item))
            continue
        parent_key = stable_document_key(item, domain)
        base_title = (item.get("title") or "").strip() or "document"
        for i, part in enumerate(parts):
            row = dict(item)
            if has_inst:
                row["instruction"] = part
                row.pop("code_snippet", None)
            else:
                row["code_snippet"] = part
            row["parent_key"] = parent_key
            row["chunk_index"] = i
            row["chunk_total"] = total
            row["title"] = f"{base_title} · {i + 1}/{total}"
            out.append(row)
    return out


def curated_point_id(domain: str, parent_key: str, chunk_index: int, chunk_total: int) -> str:
    """Deterministic Qdrant point id for a chunk (prefix matches memory domain[:8])."""
    prefix = domain[:8]
    raw = f"{prefix}|{parent_key}|{chunk_index}|{chunk_total}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{h}"
