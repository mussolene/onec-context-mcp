"""Curated JSONL snapshot writes."""

from pathlib import Path

from onec_help.knowledge.curated_jsonl import write_curated_snapshot


def test_write_curated_snapshot_standards(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    items = [
        {
            "title": "T",
            "description": "d",
            "code_snippet": "body",
            "source_ref": "x.md",
        }
    ]
    p = write_curated_snapshot("standards", items)
    assert p is not None
    assert p.exists()
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "body" in lines[0]
    assert "standards" in lines[0]
