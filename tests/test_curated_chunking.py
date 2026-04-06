"""Tests for curated standards/snippets chunking."""

from unittest.mock import patch

from onec_help.knowledge.curated_chunking import (
    expand_curated_items_for_indexing,
    split_text_with_overlap,
    stable_document_key,
)


def test_split_text_with_overlap_short() -> None:
    assert split_text_with_overlap("abc", max_chunk=100, overlap=20) == ["abc"]


def test_split_text_with_overlap_multi() -> None:
    parts = split_text_with_overlap("a" * 500, max_chunk=100, overlap=25)
    assert len(parts) > 1
    assert all(len(p) <= 100 for p in parts)


def test_stable_document_key_differs_by_source() -> None:
    a = {"title": "Same", "code_snippet": "x", "source_ref": "a.md"}
    b = {"title": "Same", "code_snippet": "x", "source_ref": "b.md"}
    assert stable_document_key(a, "snippets") != stable_document_key(b, "snippets")


def test_expand_creates_multiple_rows_for_long_code() -> None:
    body = "x" * 500
    item = {"title": "Doc", "description": "", "code_snippet": body, "source_ref": "f.md"}
    with patch(
        "onec_help.shared.env_config.get_curated_chunk_body_chars",
        return_value=100,
    ):
        with patch("onec_help.shared.env_config.get_curated_chunk_overlap", return_value=25):
            out = expand_curated_items_for_indexing([item], "snippets")
    assert len(out) > 1
    assert all("chunk_total" in o for o in out)
    assert all(o["chunk_total"] == len(out) for o in out)
    joined = "".join(o["code_snippet"] for o in out)
    assert "x" in joined


def test_expand_no_op_for_other_domain() -> None:
    item = {"title": "A", "code_snippet": "x" * 500}
    with patch("onec_help.shared.env_config.get_curated_chunk_body_chars", return_value=50):
        out = expand_curated_items_for_indexing([item], "user")
    assert len(out) == 1


def test_expand_instruction_chunks_community_help() -> None:
    body = "y" * 400
    item = {"title": "Ref", "instruction": body}
    with patch("onec_help.shared.env_config.get_curated_chunk_body_chars", return_value=80):
        with patch("onec_help.shared.env_config.get_curated_chunk_overlap", return_value=20):
            out = expand_curated_items_for_indexing([item], "community_help")
    assert len(out) > 1
    assert all("instruction" in o and not o.get("code_snippet") for o in out)
