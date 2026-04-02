"""Tests for snippets_loader."""

from pathlib import Path

from onec_help.knowledge.loaders.snippets_loader import collect_from_folder


def test_collect_from_folder_bsl(tmp_path: Path) -> None:
    """Collect *.bsl files."""
    (tmp_path / "a.bsl").write_text("Сообщить(1);", encoding="utf-8")
    items = collect_from_folder(tmp_path)
    assert len(items) == 1
    assert items[0]["title"] == "a"
    assert items[0]["code_snippet"] == "Сообщить(1);"


def test_collect_from_folder_1c(tmp_path: Path) -> None:
    """Collect *.1c files."""
    (tmp_path / "b.1c").write_text("Возврат Истина;", encoding="utf-8")
    items = collect_from_folder(tmp_path)
    assert len(items) == 1
    assert items[0]["title"] == "b"


def test_collect_from_folder_md_with_frontmatter(tmp_path: Path) -> None:
    """Collect *.md with YAML frontmatter and code block."""
    (tmp_path / "c.md").write_text(
        "---\ntitle: Мой пример\ndescription: Тест\n---\n\n```bsl\nСообщить(2);\n```",
        encoding="utf-8",
    )
    items = collect_from_folder(tmp_path)
    assert len(items) == 1
    assert items[0]["title"] == "Мой пример"
    assert items[0]["description"] == "Тест"
    assert "Сообщить(2)" in items[0]["code_snippet"]


def test_collect_from_folder_skips_readme(tmp_path: Path) -> None:
    """README.md is skipped."""
    (tmp_path / "README.md").write_text("```bsl\nx\n```", encoding="utf-8")
    items = collect_from_folder(tmp_path)
    assert len(items) == 0


def test_collect_from_folder_empty(tmp_path: Path) -> None:
    """Empty folder returns empty list."""
    assert collect_from_folder(tmp_path) == []


def test_collect_from_folder_md_no_frontmatter_uses_stem(tmp_path: Path) -> None:
    """*.md without frontmatter uses filename as title."""
    (tmp_path / "tip.md").write_text("```1c\nСообщить(1);\n```", encoding="utf-8")
    items = collect_from_folder(tmp_path)
    assert len(items) == 1
    assert items[0]["title"] == "tip"


def test_collect_from_folder_md_no_code_block_skipped(tmp_path: Path) -> None:
    """*.md with no bsl/1c code block is skipped."""
    (tmp_path / "doc.md").write_text("---\ntitle: Doc\n---\n\nJust text.", encoding="utf-8")
    items = collect_from_folder(tmp_path)
    assert len(items) == 0


def test_collect_from_folder_md_empty_code_block_skipped(tmp_path: Path) -> None:
    """*.md with empty code block is skipped."""
    (tmp_path / "x.md").write_text("---\ntitle: X\n---\n\n```bsl\n\n```", encoding="utf-8")
    items = collect_from_folder(tmp_path)
    assert len(items) == 0


def test_collect_from_folder_bsl_whitespace_only_skipped(tmp_path: Path) -> None:
    """*.bsl with only whitespace is skipped (line 65-66)."""
    (tmp_path / "empty.bsl").write_text("   \n\t  \n", encoding="utf-8")
    items = collect_from_folder(tmp_path)
    assert len(items) == 0


def test_collect_from_folder_bsl_read_error_skipped(tmp_path: Path) -> None:
    """OSError/UnicodeDecodeError on read is skipped."""
    (tmp_path / "good.bsl").write_text("X;", encoding="utf-8")
    bad = tmp_path / "bad.bsl"
    bad.write_text("x", encoding="utf-8")
    with open(bad, "wb") as f:
        f.write(b"\xff\xfe invalid")
    items = collect_from_folder(tmp_path)
    assert len(items) == 1
    assert items[0]["title"] == "good"


def test_collect_from_folder_md_read_error_skipped(tmp_path: Path) -> None:
    """OSError when reading .md file is skipped."""
    (tmp_path / "ok.md").write_text("---\ntitle: X\n---\n\n```bsl\nx\n```", encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text("x", encoding="utf-8")
    with open(bad, "wb") as f:
        f.write(b"\xff\xfe")
    items = collect_from_folder(tmp_path)
    assert len(items) == 1
    assert items[0]["title"] == "X"


def test_collect_from_folder_per_function(tmp_path: Path) -> None:
    """When per_function=True and file is large, split by procedures."""
    code = (
        """
Процедура П1()
    Сообщить(1);
КонецПроцедуры

Функция Ф1()
    Возврат Истина;
КонецФункции
"""
        + "\n" * 50
    )  # pad to >= 50 lines
    (tmp_path / "module.bsl").write_text(code, encoding="utf-8")
    items = collect_from_folder(tmp_path, per_function=True, per_function_min_lines=50)
    assert len(items) >= 1
    titles = [i["title"] for i in items]
    assert any("П1" in t or "Ф1" in t for t in titles)
