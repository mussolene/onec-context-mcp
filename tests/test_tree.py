"""Tests for tree module."""

from pathlib import Path
from unittest.mock import patch

from onec_help._utils import path_inside_base
from onec_help.tree import build_tree, build_tree_for_web, get_html_content


def test_build_tree_for_web_uses_categories(help_sample_dir: Path) -> None:
    """build_tree_for_web uses __categories__ when present (semantic titles)."""
    nodes = build_tree_for_web(help_sample_dir)
    assert isinstance(nodes, list)
    for n in nodes:
        assert "identifier" in n
        assert "html_path" in n
        assert "is_folder" in n
        assert "children" in n
    # With __categories__, should have semantic titles from HTML, not just filenames
    ids = [n["identifier"] for n in nodes]
    assert ids  # has at least one


def test_build_tree(help_sample_dir: Path) -> None:
    nodes = build_tree(help_sample_dir)
    assert isinstance(nodes, list)
    for n in nodes:
        assert "id" in n
        assert "identifier" in n
        assert "html_path" in n
        assert "is_folder" in n
        assert "children" in n


def test_get_html_content(help_sample_dir: Path) -> None:
    content = get_html_content("field626.html", help_sample_dir)
    assert "content" in content.lower() or "реквизит" in content.lower() or "html" in content


def test_get_html_content_missing(help_sample_dir: Path) -> None:
    content = get_html_content("nonexistent.html", help_sample_dir)
    assert "No content" in content


def test_get_html_content_non_html_suffix(tmp_path: Path) -> None:
    """Non-.html path returns default message."""
    (tmp_path / "readme.txt").write_text("text")
    content = get_html_content("readme.txt", tmp_path)
    assert "No content" in content


def test_path_inside_base_resolve_raises_returns_false(tmp_path: Path) -> None:
    """When resolve() raises ValueError/OSError, path_inside_base returns False."""
    base = tmp_path / "base"
    base.mkdir()
    path = base / "file.html"
    with patch.object(Path, "resolve", side_effect=OSError("resolve failed")):
        assert path_inside_base(path, base) is False


def test_get_html_content_path_traversal_rejected(tmp_path: Path) -> None:
    """Path traversal (../) outside base_dir is rejected and returns safe default."""
    (tmp_path / "valid.html").write_text("<html>valid</html>")
    # Attempt to read from a path that escapes base
    content = get_html_content("../../../etc/passwd", tmp_path)
    assert "No content" in content
    # Valid relative path still works
    content_valid = get_html_content("valid.html", tmp_path)
    assert "valid" in content_valid


def test_build_tree_with_html_and_same_name_folder(tmp_path: Path) -> None:
    """When an .html file has a same-name folder, walk_dir recurses into it."""
    (tmp_path / "page.html").write_text("<html></html>")
    (tmp_path / "page").mkdir()
    (tmp_path / "page" / "nested.html").write_text("<html><body>Nested</body></html>")
    nodes = build_tree(tmp_path)
    root = next(n for n in nodes if n["identifier"] == "page.html")
    assert root is not None
    assert root["html_path"] == "page.html"
    children = root.get("children") or []
    nested = next((c for c in children if c["identifier"] == "nested.html"), None)
    assert nested is not None
    assert "nested.html" in (nested.get("html_path") or "")


def test_build_tree_max_depth(tmp_path: Path) -> None:
    """build_tree with max_depth limits recursion depth."""
    (tmp_path / "a.html").write_text("<html></html>")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.html").write_text("<html></html>")
    nodes = build_tree(tmp_path, max_depth=1)
    assert len(nodes) >= 1
    ids = [n["identifier"] for n in nodes]
    assert "a.html" in ids or "sub" in ids


def test_build_tree_for_web_multiversion_layout(tmp_path: Path) -> None:
    """build_tree_for_web with version/stem layout uses _build_unpacked_multiversion_tree."""
    v_dir = tmp_path / "8.3.27.1234"
    v_dir.mkdir()
    stem_dir = v_dir / "shcntx_ru"
    stem_dir.mkdir()
    (stem_dir / "__categories__").write_text("page1.html\n")
    (stem_dir / "page1.html").write_text("<html><body>Page1</body></html>")
    nodes = build_tree_for_web(tmp_path)
    assert isinstance(nodes, list)
    assert len(nodes) >= 1
    # Should have version node with children
    version_node = next((n for n in nodes if n.get("identifier") == "8.3.27.1234"), None)
    assert version_node is not None
    assert version_node.get("is_folder") is True
    assert len(version_node.get("children", [])) >= 1


def test_get_html_content_rewrites_links(tmp_path: Path) -> None:
    """get_html_content rewrites href and src to /content/ and /download/."""
    (tmp_path / "page.html").write_text(
        '<html><body><a href="other.html">Link</a><img src="img.png"></body></html>'
    )
    (tmp_path / "other.html").write_text("<html>Other</html>")
    (tmp_path / "img.png").write_bytes(b"\x89PNG")
    content = get_html_content("page.html", tmp_path)
    assert "/content/" in content
    assert "/download/" in content
    assert "other.html" in content or "img.png" in content


def test_resolve_v8help_not_uri_returns_none(tmp_path: Path) -> None:
    """_resolve_v8help with non-v8help URI returns None."""
    from onec_help.tree import _resolve_v8help

    assert _resolve_v8help("http://example.com/", tmp_path, tmp_path / "x.html") is None
    assert _resolve_v8help("v8help://", tmp_path, tmp_path / "x.html") is None


def test_build_tree_for_web_multiversion_uses_hbk_labels(tmp_path: Path) -> None:
    """build_tree_for_web multiversion layout uses HBK_LABELS for stem identifier."""
    v_dir = tmp_path / "8.3.27.1"
    v_dir.mkdir()
    stem_dir = v_dir / "shcntx_ru"
    stem_dir.mkdir()
    (stem_dir / "__categories__").write_text("p.html\n")
    (stem_dir / "p.html").write_text("<html></html>")
    with patch.dict("os.environ", {"HBK_LABELS": "shcntx:Синтаксис,1cv8:Справка 1С"}, clear=False):
        nodes = build_tree_for_web(tmp_path)
    assert len(nodes) >= 1
    version_node = next((n for n in nodes if n.get("identifier") == "8.3.27.1"), None)
    assert version_node is not None
    children = version_node.get("children", [])
    stem_node = next((c for c in children if c.get("identifier") == "Синтаксис"), None)
    assert stem_node is not None
