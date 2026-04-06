"""Write curated snapshots (standards / snippets) to JSONL under DATA_DIR/curated_memory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..shared import env_config

_SNAPSHOT_NAMES = {
    "standards": "standards_snapshot.jsonl",
    "snippets": "snippets_snapshot.jsonl",
    "community_help": "community_help_snapshot.jsonl",
}


def write_curated_snapshot(domain: str, items: list[dict[str, Any]]) -> Path | None:
    """Append-free snapshot: one JSON object per line (full document text, before chunking)."""
    name = _SNAPSHOT_NAMES.get(domain)
    if not name or not items:
        return None
    base = Path(env_config.get_curated_memory_dir()).expanduser().resolve()
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    path = base / name
    try:
        with path.open("w", encoding="utf-8") as f:
            for it in items:
                if not isinstance(it, dict):
                    continue
                text = (it.get("instruction") or it.get("code_snippet") or "").strip()
                rec: dict[str, Any] = {
                    "schema_version": 1,
                    "domain": domain,
                    "source_ref": it.get("source_ref"),
                    "title": it.get("title"),
                    "description": it.get("description"),
                    "text": text,
                    "detail_url": it.get("detail_url"),
                    "source_site": it.get("source_site"),
                    "source": it.get("source"),
                    "type": it.get("type"),
                    "content_id": it.get("content_id"),
                    "section_path": it.get("section_path"),
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        return None
    return path
