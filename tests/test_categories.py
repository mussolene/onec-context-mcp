"""Tests for categories module."""

from pathlib import Path

from onec_help.help_core.categories import (
    build_tree,
    extract_html_title,
    find_categories_root,
    parse_content_file,
)


def test_parse_content_file(categories_file: Path) -> None:
    structure = parse_content_file(categories_file)
    assert isinstance(structure, list)
    assert "field626.html" in structure
    assert "Node573.html" in structure


def test_parse_content_file_missing() -> None:
    assert parse_content_file(Path("/nonexistent")) == []


def test_extract_html_title(sample_html: Path) -> None:
    title = extract_html_title(sample_html)
    assert "Имя общего реквизита" in title or "Common attribute" in title or title


def test_extract_html_title_missing() -> None:
    assert extract_html_title(Path("/nonexistent")) == "Untitled"


def test_extract_html_title_from_title_tag(tmp_path: Path) -> None:
    """When no h1, extract from <title>."""
    f = tmp_path / "page.html"
    f.write_text(
        "<html><head><title>Page Title Here</title></head><body></body></html>", encoding="utf-8"
    )
    assert extract_html_title(f) == "Page Title Here"


def test_build_tree(help_sample_dir: Path) -> None:
    structure = parse_content_file(help_sample_dir / "__categories__")
    tree = build_tree(help_sample_dir, structure)
    assert isinstance(tree, list)
    for node in tree:
        assert "title" in node
        assert "path" in node
        assert "children" in node


def test_find_categories_root(help_sample_dir: Path) -> None:
    root = find_categories_root(help_sample_dir)
    assert root is not None
    assert (root / "__categories__").exists()


def test_find_categories_root_not_found(tmp_path: Path) -> None:
    assert find_categories_root(tmp_path) is None


def test_find_categories_root_not_found_after_common_subdirs(tmp_path: Path) -> None:
    """find_categories_root returns None when common subdirs exist but have no __categories__."""
    (tmp_path / "source").mkdir()
    (tmp_path / "objects").mkdir()
    assert find_categories_root(tmp_path) is None
    assert find_categories_root(tmp_path / "source") is None


def test_find_categories_root_via_objects_subdir(tmp_path: Path) -> None:
    """find_categories_root finds __categories__ in objects/ subdir."""
    (tmp_path / "objects").mkdir()
    (tmp_path / "objects" / "__categories__").write_text("{}")
    root = find_categories_root(tmp_path)
    assert root is not None
    assert (root / "__categories__").exists()


def test_build_tree_dir_without_categories(tmp_path: Path) -> None:
    """Directory without __categories__ uses iterdir() for sub structure."""
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "a.html").write_text("<html><body></body></html>", encoding="utf-8")
    structure = ["subdir"]
    tree = build_tree(tmp_path, structure)
    assert len(tree) == 1
    assert tree[0]["title"] == "subdir"
    assert "children" in tree[0]
    # One child for a.html
    assert len(tree[0]["children"]) == 1
    assert tree[0]["children"][0]["path"] == "subdir/a.html"


def test_find_categories_root_via_common_subdir(tmp_path: Path) -> None:
    """find_categories_root finds __categories__ in source/FileStorage/objects."""
    objects_dir = tmp_path / "source" / "FileStorage" / "objects"
    objects_dir.mkdir(parents=True)
    (objects_dir / "__categories__").write_text("item.html\n", encoding="utf-8")
    deep = tmp_path / "source" / "FileStorage" / "objects" / "deep"
    deep.mkdir()
    root = find_categories_root(deep)
    assert root is not None
    assert (root / "__categories__").exists()


def test_build_tree_nested_categories(tmp_path: Path) -> None:
    """Subdirectory with __categories__ uses parse_content_file for children."""
    (tmp_path / "__categories__").write_text('{1,"subdir"}', encoding="utf-8")
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "__categories__").write_text('{1,"nested.html"}', encoding="utf-8")
    (sub / "nested.html").write_text(
        "<html><head><title>Nested</title></head><body></body></html>", encoding="utf-8"
    )
    structure = parse_content_file(tmp_path / "__categories__")
    tree = build_tree(tmp_path, structure)
    assert len(tree) == 1
    assert tree[0]["title"] == "subdir"
    assert len(tree[0]["children"]) == 1
    assert tree[0]["children"][0]["path"] == "subdir/nested.html"
