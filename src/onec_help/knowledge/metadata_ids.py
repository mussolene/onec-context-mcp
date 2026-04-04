"""Canonical string ids for configuration metadata (KD2 graph, Qdrant payload ``id``)."""

from __future__ import annotations


def make_metadata_object_id(object_type: str, name: str) -> str:
    """Build canonical id: ``EnglishType.ObjectName`` (single dot between type and technical name).

    1C metadata object names normally do not contain ``.``; dotted BSL paths after the first
    segment are handled in query normalization, not in this id.
    """
    ot = (object_type or "").strip()
    nm = (name or "").strip()
    return f"{ot}.{nm}"


def legacy_slash_metadata_id_to_dot(object_id: str) -> str | None:
    """If ``object_id`` is legacy ``Type/Name`` (exactly one slash), return ``Type.Name``."""
    s = (object_id or "").strip()
    if s.count("/") != 1:
        return None
    a, b = s.split("/", 1)
    if not a or not b or "/" in b:
        return None
    return f"{a}.{b}"
