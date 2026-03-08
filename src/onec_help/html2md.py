"""Convert 1C help HTML to Markdown (one .md per article).
Supports: (1) V8SH_* schema (Syntax Helper), (2) Legacy schema (H1–H6, tables, STRONG sections).
See docs/help_formats.md for formal spec."""

import html
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


def resolve_href(current_path: Path, href: str, base_dir: Path) -> str | None:
    """Resolve relative href to a path within base_dir. Returns normalized path string or None.
    href="#" (anchor) returns None."""
    href = (href or "").strip()
    if not href or href.startswith("#"):
        return None
    try:
        resolved = (current_path.parent / href).resolve()
        rel = resolved.relative_to(base_dir.resolve())
    except (ValueError, OSError):
        return None
    rel_str = str(rel).replace("\\", "/")
    candidates = [
        base_dir / rel_str,
        base_dir / Path(rel_str).with_suffix(".md"),
        base_dir / Path(rel_str).with_suffix(".html"),
    ]
    if not rel_str.endswith((".md", ".html", ".htm")):
        candidates.extend([base_dir / (rel_str + ".md"), base_dir / (rel_str + ".html")])
    for c in candidates:
        if c.exists() and c.is_file():
            try:
                r = c.relative_to(base_dir)
                return str(r).replace("\\", "/")
            except ValueError:
                pass
    return None


def extract_outgoing_links(html_path: Path, base_dir: Path) -> list[dict[str, Any]]:
    """Parse HTML, find all <a href>, resolve each, return [{href, resolved_path, target_title, link_text}]."""
    result: list[dict[str, Any]] = []
    try:
        text = _read_html_file(html_path)
    except Exception:
        return result
    soup = BeautifulSoup(text, "html.parser")
    current = Path(html_path)
    seen: set[tuple[str, str]] = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        link_text = a.get_text(strip=True) or ""
        if not href:
            continue
        key = (href, link_text)
        if key in seen:
            continue
        seen.add(key)
        resolved = resolve_href(current, href, base_dir)
        result.append(
            {
                "href": href,
                "resolved_path": resolved,
                "target_title": link_text,
                "link_text": link_text,
            }
        )
    return result


# Regex for Markdown links [text](url)
_MD_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")


def extract_links_from_markdown(
    md_text: str, current_path: Path, base_dir: Path
) -> list[dict[str, Any]]:
    """Parse Markdown [text](url) links, resolve each to base_dir, return [{href, resolved_path, target_title, link_text}]."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for m in _MD_LINK_PATTERN.finditer(md_text):
        link_text = (m.group(1) or "").strip()
        href = (m.group(2) or "").strip()
        if not href:
            continue
        key = (href, link_text)
        if key in seen:
            continue
        seen.add(key)
        resolved = resolve_href(current_path, href, base_dir)
        result.append(
            {
                "href": href,
                "resolved_path": resolved,
                "target_title": link_text,
                "link_text": link_text,
            }
        )
    return result


def _normalize_md_text(s: str) -> str:
    """Replace HTML entities with Unicode and normalize composite characters for consistent search."""
    if not s:
        return s
    s = html.unescape(s)  # &nbsp; &amp; &lt; &#160; etc. → real characters
    s = unicodedata.normalize("NFC", s)  # canonical composition (é as one codepoint)
    return s


def _table_to_md(table) -> str:
    """Convert a <table> to Markdown table."""
    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["td", "th"])]
        if cells:
            rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return ""
    if len(rows) >= 2:
        rows.insert(1, "|" + "|".join([" --- " for _ in rows[0].split("|")[1:-1]]) + "|")
    return "\n".join(rows) + "\n\n"


def _legacy_body_to_md(body) -> str:
    """Convert legacy article body (H1–H6, P, TABLE, STRONG) to Markdown."""
    lines = []
    for elem in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "pre"]):
        tag = elem.name.lower()
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            lines.append(
                "\n" + "#" * level + " " + elem.get_text(separator=" ", strip=True) + "\n\n"
            )
        elif tag == "table":
            tbl = _table_to_md(elem)
            if tbl:
                lines.append(tbl)
        elif tag == "pre":
            lines.append("```\n" + elem.get_text(separator="\n", strip=True) + "\n```\n\n")
        elif tag == "p":
            text = elem.get_text(separator=" ", strip=True)
            if text:
                # Inline links: keep [text](url)
                for a in elem.find_all("a", href=True):
                    a.replace_with("[" + a.get_text(strip=True) + "](" + a["href"] + ")")
                text = elem.get_text(separator=" ", strip=True)
                lines.append(text + "\n\n")
    return "\n".join(lines).strip()


# Справка 1С: пробуем UTF-8, затем CP1251 (при ошибке декода UTF-8 для 1251-файлов)
_ENCODINGS_UTF8_FIRST = ("utf-8", "cp1251", "cp866", "latin-1")


# Макс. размер HTML (байты). From env_config.
def _html_max_bytes() -> int:
    from . import env_config

    return env_config.get_help_html_max_bytes()


def _looks_like_utf8_mojibake(text: str) -> bool:
    """True, если текст похож на кракозябры: UTF-8 байты прочитаны как однобайтовая кодировка.
    Признак 1: много символов Р (U+0420), С (U+0421) — байты 0xD0, 0xD1 в UTF-8 русских букв.
    Признак 2: псевдографика (╨ ╤ и т.п. U+2500–U+257F) вперемешку с кириллицей."""
    if len(text) < 20:
        return False
    cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
    if cyrillic < 10:
        return False
    # Р и С как первый байт UTF-8 русских букв
    bad = sum(1 for c in text if c in "\u0420\u0421")  # Р, С
    if (bad / cyrillic) > 0.25:
        return True
    # Псевдографика (типично при неверной кодировке) вместе с кириллицей
    box = sum(1 for c in text if "\u2500" <= c <= "\u257f")
    return box > 5 and cyrillic > 5


def _file_encodings() -> tuple[str, ...]:
    from . import env_config

    order = env_config.get_help_file_encoding()
    # HELP_FILE_ENCODING=cp1251 — сначала CP1251 (если точно знаете, что все файлы в 1251)
    if order == "cp1251":
        return ("cp1251", "utf-8", "cp866", "latin-1")
    return _ENCODINGS_UTF8_FIRST


def _try_fix_mojibake(text: str, raw: bytes) -> str | None:
    """Если текст похож на кракозябры — перекодировать или перечитать raw в другой кодировке."""
    if not _looks_like_utf8_mojibake(text):
        return None
    # Случай: файл в UTF-8, но прочитан как CP1251 → перечитаем как UTF-8
    try:
        u8 = raw.decode("utf-8")
        if not _looks_like_utf8_mojibake(u8):
            return u8
    except UnicodeDecodeError:
        pass
    # Случай: строка — UTF-8 байты, прочитанные как Latin-1 (двойная кодировка)
    try:
        fixed = text.encode("latin-1").decode("utf-8")
        if not _looks_like_utf8_mojibake(fixed):
            return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    for alt in ("cp1251", "cp866"):
        try:
            alt_text = raw.decode(alt)
            if not _looks_like_utf8_mojibake(alt_text):
                return alt_text
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def read_file_with_encoding_fallback(path: Path, encodings: tuple[str, ...] | None = None) -> str:
    """Читает файл, пробуя кодировки по порядку. При признаках кракозябр пробует альтернативу."""
    if encodings is None:
        encodings = _file_encodings()
    raw = path.read_bytes()
    for enc in encodings:
        try:
            text = raw.decode(enc)
            fixed = _try_fix_mojibake(text, raw)
            if fixed is not None:
                return fixed
            return text
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _read_html_file(path: Path) -> str:
    """Read file content; try utf-8, then cp1251/cp866/latin-1. Skip files over HELP_HTML_MAX_BYTES."""
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size > _html_max_bytes():
        print(
            f"[html2md] skip {path.name} ({size} bytes > {_html_max_bytes()}): too large",
            file=sys.stderr,
            flush=True,
        )
        return ""
    return read_file_with_encoding_fallback(path)


def html_to_md_content(html_path) -> str:
    """
    Extract help article from HTML and return Markdown string.
    Sections: title, description, syntax, parameters, return value, examples, see also.
    Skips files over HELP_HTML_MAX_BYTES to avoid BeautifulSoup hang on huge HTML.
    """
    path = Path(html_path)
    if not path.exists():
        return ""
    text = _read_html_file(path)
    soup = BeautifulSoup(text, "html.parser")

    # Legacy schema: no V8SH_pagetitle → structured body (H1→#, H2–H6, tables)
    title_tag = soup.find("h1", class_="V8SH_pagetitle")
    if not title_tag:
        body = soup.find("body")
        if body:
            md_body = _legacy_body_to_md(body)
            if md_body.strip():
                return _normalize_md_text(md_body.strip())
        title = "Untitled"
    else:
        title = title_tag.get_text(strip=True)

    lines: list[str] = []
    lines.append(f"# {title}\n")

    # Description
    desc_tag = soup.find(
        "p",
        class_="V8SH_chapter",
        string=lambda t: t and "Описание:" in (t if isinstance(t, str) else t),
    )
    if not desc_tag and soup.find("p", class_="V8SH_chapter"):
        for p in soup.find_all("p", class_="V8SH_chapter"):
            if p.get_text(strip=True) == "Описание:":
                desc_tag = p
                break
    if desc_tag:
        next_p = desc_tag.find_next_sibling()
        if next_p and next_p.name == "p":
            lines.append("## Описание\n\n")
            lines.append(next_p.get_text(separator=" ", strip=True) + "\n\n")
        else:
            n = desc_tag.find_next()
            if n and getattr(n, "get_text", None):
                lines.append("## Описание\n\n")
                lines.append(n.get_text(separator=" ", strip=True) + "\n\n")

    # Syntax
    syntax_heading = soup.find(
        "p",
        class_="V8SH_chapter",
        string=lambda t: t and "Синтаксис:" in (t if isinstance(t, str) else t),
    )
    if not syntax_heading:
        for p in soup.find_all("p", class_="V8SH_chapter"):
            if p.get_text(strip=True) == "Синтаксис:":
                syntax_heading = p
                break
    if syntax_heading:
        lines.append("## Синтаксис\n\n```\n")
        pre = syntax_heading.find_next("pre")
        if pre:
            lines.append(pre.get_text(separator="\n", strip=True) + "\n")
        else:
            next_ = syntax_heading.find_next(string=True)
            if next_:
                syntax_text = str(next_).strip()
                if syntax_text and syntax_text != "Синтаксис:":
                    lines.append(syntax_text + "\n")
        lines.append("```\n\n")

    # Parameters
    params_heading = soup.find(
        "p",
        class_="V8SH_chapter",
        string=lambda t: t and "Параметры:" in (t if isinstance(t, str) else t),
    )
    if not params_heading:
        for p in soup.find_all("p", class_="V8SH_chapter"):
            if p.get_text(strip=True) == "Параметры:":
                params_heading = p
                break
    if params_heading:
        lines.append("## Параметры\n\n")
        for div in params_heading.find_all_next("div", class_="V8SH_rubric"):
            if div.find_previous("p", class_="V8SH_chapter") != params_heading:
                break
            p_tag = div.find("p")
            a_tag = div.find("a")
            name = p_tag.get_text(strip=True) if p_tag else "—"
            typ = a_tag.get_text(strip=True) if a_tag else "—"
            lines.append(f"- **{name}** ({typ})\n")
        lines.append("\n")

    # Return value
    ret_heading = soup.find(
        "p",
        class_="V8SH_chapter",
        string=lambda t: t and "Возвращаемое значение:" in (t if isinstance(t, str) else t),
    )
    if not ret_heading:
        for p in soup.find_all("p", class_="V8SH_chapter"):
            if p.get_text(strip=True) == "Возвращаемое значение:":
                ret_heading = p
                break
    if ret_heading:
        next_p = ret_heading.find_next_sibling("p")
        if next_p:
            ret_text = next_p.get_text(separator=" ", strip=True)
            if ret_text:
                lines.append("## Возвращаемое значение\n\n")
                lines.append(ret_text + "\n\n")
        else:
            next_ = ret_heading.find_next(string=True)
            if next_:
                ret_text = str(next_).strip()
                if ret_text and "Возвращаемое значение" not in ret_text:
                    lines.append("## Возвращаемое значение\n\n")
                    lines.append(ret_text + "\n\n")

    # Examples
    ex_heading = soup.find(
        "p",
        class_="V8SH_chapter",
        string=lambda t: t and "Пример:" in (t if isinstance(t, str) else t),
    )
    if not ex_heading:
        for p in soup.find_all("p", class_="V8SH_chapter"):
            if p.get_text(strip=True) == "Пример:":
                ex_heading = p
                break
    if ex_heading:
        code_block = ex_heading.find_next("pre") or ex_heading.find_next("table")
        if code_block:
            lines.append("## Пример\n\n```\n")
            if code_block.name == "table":
                rows = code_block.find_all("tr")
                text = "\n".join(
                    " ".join(cell.get_text(strip=True) for cell in row.find_all(["td", "th"]))
                    for row in rows
                )
                lines.append(text + "\n")
            else:
                lines.append(code_block.get_text(separator="\n", strip=True) + "\n")
            lines.append("```\n\n")

    # See also
    see_heading = soup.find(
        "p",
        class_="V8SH_chapter",
        string=lambda t: t and "См. также:" in (t if isinstance(t, str) else t),
    )
    if not see_heading:
        for p in soup.find_all("p", class_="V8SH_chapter"):
            if p.get_text(strip=True) == "См. также:":
                see_heading = p
                break
    if see_heading:
        links = see_heading.find_all_next("a", limit=20)
        if links:
            lines.append("## См. также\n\n")
            for a in links:
                lines.append(f"- {a.get_text(strip=True)}\n")
            lines.append("\n")

    # Примечание
    note_heading = soup.find(
        "p",
        class_="V8SH_chapter",
        string=lambda t: t and "Примечание:" in (t if isinstance(t, str) else t),
    )
    if not note_heading:
        for p in soup.find_all("p", class_="V8SH_chapter"):
            if p.get_text(strip=True) == "Примечание:":
                note_heading = p
                break
    if note_heading:
        next_p = note_heading.find_next_sibling("p") or note_heading.find_next(string=True)
        if next_p:
            note_text = (
                next_p.get_text(separator=" ", strip=True)
                if hasattr(next_p, "get_text")
                else str(next_p).strip()
            )
            if note_text and "Примечание" not in note_text:
                lines.append("## Примечание\n\n")
                lines.append(note_text + "\n\n")

    # Использование в версии — в справке 1С контент в p.V8SH_versionInfo (следующие за заголовком)
    version_heading = None
    for p in soup.find_all("p", class_="V8SH_chapter"):
        raw = p.get_text(separator=" ", strip=True) or ""
        if raw.startswith("Использование в версии"):
            version_heading = p
            break
    if version_heading:
        parts = []
        for sib in version_heading.find_next_siblings():
            if sib.name == "p" and "V8SH_versionInfo" in (sib.get("class") or []):
                t = sib.get_text(separator=" ", strip=True)
                if t:
                    parts.append(t)
            elif sib.name == "p" and "V8SH_chapter" in (sib.get("class") or []):
                break
        if parts:
            lines.append("## Использование в версии\n\n")
            lines.append("\n\n".join(parts) + "\n\n")

    # Доступность
    avail_heading = soup.find(
        "p",
        class_="V8SH_chapter",
        string=lambda t: t and "Доступность:" in (t if isinstance(t, str) else t),
    )
    if not avail_heading:
        for p in soup.find_all("p", class_="V8SH_chapter"):
            if "Доступность:" in (p.get_text(strip=True) or ""):
                avail_heading = p
                break
    if avail_heading:
        next_p = avail_heading.find_next_sibling("p") or avail_heading.find_next(string=True)
        if next_p:
            avail_text = (
                next_p.get_text(separator=" ", strip=True)
                if hasattr(next_p, "get_text")
                else str(next_p).strip()
            )
            if avail_text and "Доступность" not in avail_text:
                lines.append("## Доступность\n\n")
                lines.append(avail_text + "\n\n")

    out = "".join(lines).strip()
    if not out or out.strip() == (f"# {title}").strip():
        # Fallback: title + body text (catalog pages with only title)
        body = soup.find("body")
        if body:
            out = f"# {title}\n\n" + body.get_text(separator="\n", strip=True)[:8000]
    return _normalize_md_text(out)


def _looks_like_html(path: Path) -> bool:
    """True if file has no extension and content starts like HTML (e.g. unpacked .hbk)."""
    try:
        head = _read_html_file(path)[:1024].lower()
        return "<html" in head or "<!doctype" in head
    except Exception:
        return False


# Extensions we never treat as HTML (binary or non-content)
_SKIP_EXTENSIONS = frozenset(
    {
        ".hbk",
        ".zip",
        ".7z",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".css",
        ".js",
        ".json",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".png",
        ".gif",
        ".jpg",
        ".jpeg",
        ".ico",
        ".bmp",
        ".webp",
        ".svg",
        ".db",
        ".dat",
        ".bin",
        ".idx",
    }
)


def build_docs(project_dir, output_dir):
    """
    Walk project_dir recursively (all subdirs, including PayloadData and any name).
    Process: .html, .htm, extension-less files that look like HTML, and any other
    file that _looks_like_html (e.g. .xml XHTML). Binary/non-content extensions are skipped.
    Convert each to .md in output_dir preserving structure.
    Returns list of created .md paths.
    """
    project_dir = Path(project_dir).resolve()
    output_dir = Path(output_dir).resolve()
    created: list[Path] = []
    for root, _, files in os.walk(project_dir):
        for name in files:
            if name.startswith("."):
                continue
            html_path = Path(root) / name
            ext = html_path.suffix.lower() if html_path.suffix else ""
            if ext in _SKIP_EXTENSIONS:
                continue
            is_html = ext in (".html", ".htm") or (
                ext in ("", ".xml", ".xhtml", ".st") and _looks_like_html(html_path)
            )
            if not is_html:
                continue
            try:
                rel = html_path.relative_to(project_dir)
            except ValueError:
                rel = html_path.name
            out_sub = output_dir / rel.parent
            out_sub.mkdir(parents=True, exist_ok=True)
            stem = rel.stem if rel.suffix else rel.name
            md_path = out_sub / (stem + ".md")
            content = html_to_md_content(html_path)
            if content:
                md_path.write_text(content, encoding="utf-8")
                created.append(md_path)
    return created
