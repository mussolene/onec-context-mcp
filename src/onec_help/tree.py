"""Build tree for web UI (file/folder tree with html_path)."""

import re
import uuid
from pathlib import Path
from typing import Any

from ._utils import path_inside_base
from .categories import build_tree as cat_build_tree
from .categories import find_categories_root, parse_content_file


def _categories_to_web_nodes(cat_nodes: list, parent_id: str | None = None) -> list[dict[str, Any]]:
    """Convert categories tree {title, path, children} to web format {id, identifier, html_path, ...}."""
    result: list[dict[str, Any]] = []
    for node in cat_nodes or []:
        nid = str(uuid.uuid4())
        has_path = bool(node.get("path"))
        children = node.get("children", [])
        result.append(
            {
                "id": nid,
                "identifier": node.get("title", ""),
                "html_path": node.get("path") or None,
                "is_folder": not has_path,
                "children": _categories_to_web_nodes(children, nid) if children else [],
                "parent_id": parent_id,
                "image_index": 0 if not has_path else 2,
            }
        )
    return result


def build_tree_for_web(directory: str | Path) -> list[dict[str, Any]]:
    """Build tree for web viewer. Uses __categories__ (semantic TOC) when present, else file walk."""
    directory = Path(directory).resolve()
    root = find_categories_root(directory)
    if root and (root / "__categories__").exists():
        try:
            struct = parse_content_file(root / "__categories__")
            cat_tree = cat_build_tree(root, struct, "")
            if cat_tree:
                return _categories_to_web_nodes(cat_tree)
        except Exception:
            pass
    return build_tree(directory)


def build_tree(directory):
    """
    Build a tree structure from directory contents for the web viewer.
    Each node: id, identifier, html_path, is_folder, children, parent_id, image_index.
    """
    directory = Path(directory).resolve()
    flat: list[dict[str, Any]] = []

    def walk_dir(dir_path: Path, parent_id=None) -> None:
        for item in sorted(dir_path.iterdir()):
            node_id = str(uuid.uuid4())
            html_path = None
            if item.is_file() and item.suffix == ".html":
                html_path = str(item.relative_to(directory))
            element = {
                "id": node_id,
                "identifier": item.name,
                "html_path": html_path,
                "is_folder": item.is_dir(),
                "children": [],
                "parent_id": parent_id,
                "image_index": 0 if item.is_dir() else 2,
            }
            if parent_id:
                parent = next((e for e in flat if e["id"] == parent_id), None)
                if parent:
                    parent["children"].append(element)
            else:
                flat.append(element)
            if item.is_file() and item.suffix == ".html":
                folder_path = item.parent / item.stem
                if folder_path.is_dir():
                    walk_dir(folder_path, node_id)
            if item.is_dir():
                walk_dir(item, node_id)

    walk_dir(directory)
    return flat


def _rewrite_content_links(content: str, base: Path, current_file: Path) -> str:
    """Rewrite relative href/src in HTML for web serving. Resolves paths correctly."""
    current_dir = current_file.parent

    def replace_href(m: re.Match) -> str:
        href = m.group(1)
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            return m.group(0)
        if href.startswith(("http://", "https://", "//")):
            return m.group(0)
        try:
            resolved = (current_dir / href).resolve()
            if path_inside_base(resolved, base) and (
                resolved.is_file() or (resolved / "index.html").exists()
            ):
                rel = resolved.relative_to(base)
                if resolved.is_dir():
                    rel = rel / "index.html" if (resolved / "index.html").exists() else rel
                return f'href="/content/{str(rel).replace(chr(92), "/")}"'
        except (ValueError, OSError):
            pass
        return f'href="/content/{href}"'

    def replace_src(m: re.Match) -> str:
        src = m.group(1)
        if not src or src.startswith(("data:", "http://", "https://")):
            return m.group(0)
        try:
            resolved = (current_dir / src).resolve()
            if path_inside_base(resolved, base) and resolved.exists():
                rel = resolved.relative_to(base)
                return f'src="/download/{str(rel).replace(chr(92), "/")}"'
        except (ValueError, OSError):
            pass
        return f'src="/download/{src}"'

    content = re.sub(r'href="([^"]*)"', replace_href, content)
    content = re.sub(r'src="([^"]*)"', replace_src, content)
    return content


def get_html_content(html_path: str, base_dir) -> str:
    """Read HTML file and adjust links for web serving (href -> /content/, src -> /download/)."""
    base = Path(base_dir).resolve()
    file_path = (base / html_path).resolve()
    if not path_inside_base(file_path, base):
        return "<html><body>No content available</body></html>"
    if not file_path.exists() or file_path.suffix not in (".html", ".htm"):
        return "<html><body>No content available</body></html>"
    from .html2md import read_file_with_encoding_fallback

    content = read_file_with_encoding_fallback(file_path)
    return _rewrite_content_links(content, base, file_path)
