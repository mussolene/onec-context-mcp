"""Build tree for web UI (file/folder tree with html_path)."""

import os
import re
import uuid
from pathlib import Path
from typing import Any

from ._utils import path_inside_base
from .categories import build_tree as cat_build_tree
from .categories import extract_html_title, find_categories_root, parse_content_file

_VERSION_DIR_RE = re.compile(r"^8\.\d+\.\d+\.\d+$")

# v8help:// context → stem prefix (without _ru). Used to resolve cross-refs in HTML.
_V8HELP_CONTEXT_TO_STEM: dict[str, str] = {
    "syntaxhelperqueries": "shquery",
    "syntaxhelpercontext": "shcntx",
    "syntaxhelperlanguage": "shclang",
}


def _detect_unpacked_layout(directory: Path) -> bool:
    """True if dir has version subdirs (8.x.x.xxx) with platform/stem containing __categories__."""
    if not directory.is_dir():
        return False
    for d in directory.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        if _VERSION_DIR_RE.match(d.name):
            for stem in d.iterdir():
                if stem.is_dir() and (stem / "__categories__").exists():
                    return True
    return False


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


def _build_unpacked_multiversion_tree(directory: Path) -> list[dict[str, Any]]:
    """Build tree for unpack-sync layout: version/stem with __categories__ in each stem."""
    result: list[dict[str, Any]] = []
    for version_dir in sorted(directory.iterdir()):
        if not version_dir.is_dir() or version_dir.name.startswith("."):
            continue
        if not _VERSION_DIR_RE.match(version_dir.name):
            continue
        version = version_dir.name
        version_children: list[dict[str, Any]] = []
        for stem_dir in sorted(version_dir.iterdir()):
            if not stem_dir.is_dir() or stem_dir.name.startswith("."):
                continue
            if not any(stem_dir.rglob("*.html")) and not any(stem_dir.rglob("*.htm")):
                has_content = any(
                    f.is_file() and not f.suffix and f.name != "__categories__"
                    for f in stem_dir.rglob("*")
                )
                if not has_content:
                    continue
            stem_nodes: list[dict[str, Any]] = []
            cat_file = stem_dir / "__categories__"
            if cat_file.exists():
                try:
                    struct = parse_content_file(cat_file)
                    cat_tree = cat_build_tree(stem_dir, struct, "")
                    if cat_tree:
                        stem_nodes = _categories_to_web_nodes(cat_tree)
                except Exception:
                    pass
            if not stem_nodes:
                stem_nodes = build_tree(stem_dir, max_depth=4)
            for node in stem_nodes:
                _prepend_path_prefix(node, f"{version}/{stem_dir.name}")
            if stem_nodes:
                version_children.append(
                    {
                        "id": str(uuid.uuid4()),
                        "identifier": _stem_to_label(stem_dir.name),
                        "html_path": None,
                        "is_folder": True,
                        "children": stem_nodes,
                        "parent_id": None,
                        "image_index": 0,
                    }
                )
        if version_children:
            result.append(
                {
                    "id": str(uuid.uuid4()),
                    "identifier": version,
                    "html_path": None,
                    "is_folder": True,
                    "children": version_children,
                    "parent_id": None,
                    "image_index": 0,
                }
            )
    return result


def _stem_to_label(stem: str) -> str:
    """Human-readable label from stem (1cv8_ru → 'Справка 1С:Предприятие 8', shquery_ru → 'Язык запросов')."""
    raw = os.environ.get("HBK_LABELS", "").strip()
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if ":" in part:
                key, val = part.split(":", 1)
                if stem.lower().startswith(key.lower() + "_") or stem.lower() == key.lower():
                    return val.strip()
    s = stem.lower()
    if s.startswith("1cv8"):
        return "Справка 1С:Предприятие 8"
    if s.startswith("shcntx") or "syntax" in s:
        return "Синтаксис"
    if s.startswith("shquery"):
        return "Язык запросов"
    if s.startswith("shclang"):
        return "Встроенный язык"
    if s.startswith("perform"):
        return "Выполнение кода на стороне клиента"
    if s.startswith("designer") or s.startswith("dsgn"):
        return "Конфигуратор"
    if s.startswith("mapui"):
        return "Схема компоновки данных"
    if s.startswith("accntui"):
        return "Интерфейс бухгалтерии"
    if s.startswith("basicui"):
        return "Основной интерфейс"
    if s.startswith("helpui"):
        return "Помощь"
    if s.startswith("config"):
        return "Конфигурация"
    if s.startswith("debug"):
        return "Отладка"
    if s.startswith("devtool"):
        return "Инструменты разработки"
    if s.startswith("frame"):
        return "Фрейм"
    if s.startswith("integui"):
        return "Интеграция"
    if s.startswith("mng"):
        return "Администрирование"
    if s.startswith("richui"):
        return "Управляемый интерфейс"
    if s.startswith("txtedui"):
        return "Текстовый редактор"
    return stem


def _prepend_path_prefix(node: dict[str, Any], prefix: str) -> None:
    """Mutate node and children: prepend prefix to html_path."""
    if node.get("html_path"):
        node["html_path"] = f"{prefix}/{node['html_path']}"
    for ch in node.get("children", []):
        _prepend_path_prefix(ch, prefix)


def build_tree_for_web(directory: str | Path) -> list[dict[str, Any]]:
    """Build tree for web viewer. Multi-version layout > __categories__ > file walk."""
    directory = Path(directory).resolve()
    if _detect_unpacked_layout(directory):
        tree = _build_unpacked_multiversion_tree(directory)
        if tree:
            return tree
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


def build_tree(directory, max_depth: int | None = None) -> list[dict[str, Any]]:
    """
    Build a tree structure from directory contents for the web viewer.
    Each node: id, identifier, html_path, is_folder, children, parent_id, image_index.
    max_depth: limit recursion depth (None = unlimited).
    """
    directory = Path(directory).resolve()
    flat: list[dict[str, Any]] = []

    def walk_dir(dir_path: Path, parent_id: str | None = None, depth: int = 0) -> None:
        if max_depth is not None and depth >= max_depth:
            return
        try:
            items = sorted(dir_path.iterdir())
        except OSError:
            return
        for item in items:
            if item.name.startswith(".") or item.name == "__categories__":
                continue
            if item.is_file():
                if item.suffix not in (".html", ".htm") and item.suffix != "":
                    continue
            node_id = str(uuid.uuid4())
            html_path = None
            if item.is_file() and (item.suffix in (".html", ".htm") or item.suffix == ""):
                html_path = str(item.relative_to(directory))
            identifier = item.name
            if item.is_file() and html_path and depth < 1:
                try:
                    title = extract_html_title(item)
                    if title and title != "Untitled" and len(title) > 2:
                        identifier = title
                except Exception:
                    pass
            element = {
                "id": node_id,
                "identifier": identifier,
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
            if item.is_file() and (item.suffix in (".html", ".htm") or item.suffix == ""):
                folder_path = item.parent / item.stem
                if folder_path.is_dir():
                    walk_dir(folder_path, node_id, depth + 1)
            if item.is_dir():
                walk_dir(item, node_id, depth + 1)

    walk_dir(directory)
    return flat


def _resolve_v8help(v8help_uri: str, base: Path, current_file: Path) -> str | None:
    """Resolve v8help:// URI to relative path within base. Returns path str or None."""
    if not v8help_uri.lower().startswith("v8help://"):
        return None
    try:
        rest = v8help_uri[9:].strip()  # after v8help://
        if "/" in rest:
            context, path_part = rest.split("/", 1)
        else:
            return None
        context_key = context.lower()
        rel_current = current_file.relative_to(base)
        parts = rel_current.parts
        version, stem = "", ""
        if len(parts) >= 2:
            version, stem = parts[0], parts[1]
        lang_suffix = "_ru"
        if "_" in stem and len(stem.split("_")[-1]) == 2:
            lang_suffix = "_" + stem.split("_")[-1]
        stem_prefix = _V8HELP_CONTEXT_TO_STEM.get(context_key)
        if stem_prefix:
            cand_stem = stem_prefix + lang_suffix
            cand = base / version / cand_stem / path_part
            for p in [cand, base / version / cand_stem / (path_part + ".html")]:
                if p.exists() and p.is_file() and path_inside_base(p, base):
                    return str(p.relative_to(base)).replace("\\", "/")
        for version_dir in base.iterdir():
            if not version_dir.is_dir() or not _VERSION_DIR_RE.match(version_dir.name):
                continue
            fn = Path(path_part).name
            if not fn.endswith(".html"):
                fn = fn + ".html"
            for f in version_dir.rglob(fn):
                if f.is_file() and path_inside_base(f, base):
                    return str(f.relative_to(base)).replace("\\", "/")
    except (ValueError, OSError):
        pass
    return None


def _rewrite_content_links(content: str, base: Path, current_file: Path) -> str:
    """Rewrite relative href/src and v8help:// in HTML for web serving."""
    current_dir = current_file.parent

    def replace_href(m: re.Match) -> str:
        href = m.group(1)
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            return m.group(0)
        if href.startswith(("http://", "https://", "//")):
            return m.group(0)
        if href.lower().startswith("v8help://"):
            resolved = _resolve_v8help(href, base, current_file)
            if resolved:
                return f'href="/content/{resolved}"'
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
    if not file_path.exists():
        return "<html><body>No content available</body></html>"
    if file_path.is_dir():
        idx = file_path / "index.html"
        if idx.exists():
            file_path = idx
        else:
            return "<html><body>No content available</body></html>"
    if file_path.suffix not in (".html", ".htm") and file_path.suffix != "":
        return "<html><body>No content available</body></html>"
    from .html2md import read_file_with_encoding_fallback

    content = read_file_with_encoding_fallback(file_path)
    return _rewrite_content_links(content, base, file_path)
