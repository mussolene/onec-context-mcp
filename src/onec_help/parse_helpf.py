"""Parse HelpF.pro FAQ (https://helpf.pro) into snippets JSON.

Listing pages show truncated content. Detail pages are fetched for full text and code.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from ._http import fetch_url, get_opener_for_base_url
from ._utils import progress_done, progress_line

_BASE_URL = "https://helpf.pro"
# Match /faq/view/ and faq/view/ (relative from /faq/N.html)
_FAQ_VIEW_RE = re.compile(r"faq/view/(\d+)\.html")
_FILE_VIEW_RE = re.compile(r"file/view/([^/]+)\.html")
_HELP_VIEW_RE = re.compile(r"help/view/(\d+)\.html")
_FREELANCE_VIEW_RE = re.compile(r"freelance/view/(\d+)\.html")
_PAGES_RE = re.compile(r"на\s+(\d+)\s+страницах", re.I)
_FAQ_PAGE_LINK_RE = re.compile(r"[/]?faq/(\d+)\.html")
_FILE_PAGE_LINK_RE = re.compile(r"[/]?file/(\d+)\.html")
_HELP_PAGE_LINK_RE = re.compile(r"[/]?help/(\d+)\.html")
_FREELANCE_PAGE_LINK_RE = re.compile(r"[/]?freelance/(\d+)\.html")


def _detect_faq_pages(opener: urllib.request.OpenerDirector) -> list[int]:
    """Fetch faq.html, parse total pages from 'на N страницах' or pagination links."""
    html = _fetch_faq_listing(1, opener)
    m = _PAGES_RE.search(html)
    if m:
        total = int(m.group(1))
        return list(range(1, total + 1))
    pages: set[int] = {1}
    for m in _FAQ_PAGE_LINK_RE.finditer(html):
        pages.add(int(m.group(1)))
    return sorted(pages) if pages else [1]


def _detect_file_pages(opener: urllib.request.OpenerDirector) -> list[int]:
    """Fetch file.html, parse total pages from text or pagination links."""
    html = _fetch_file_listing(1, opener)
    m = _PAGES_RE.search(html)
    if m:
        total = int(m.group(1))
        return list(range(1, total + 1))
    pages: set[int] = {1}
    for m in _FILE_PAGE_LINK_RE.finditer(html):
        pages.add(int(m.group(1)))
    return sorted(pages) if pages else [1]


def _detect_help_pages(opener: urllib.request.OpenerDirector) -> list[int]:
    """Fetch help.html (Forum), parse total pages."""
    html = _fetch_help_listing(1, opener)
    m = _PAGES_RE.search(html)
    if m:
        total = int(m.group(1))
        return list(range(1, total + 1))
    pages: set[int] = {1}
    for m in _HELP_PAGE_LINK_RE.finditer(html):
        pages.add(int(m.group(1)))
    return sorted(pages) if pages else [1]


def _detect_freelance_pages(opener: urllib.request.OpenerDirector) -> list[int]:
    """Fetch freelance.html, parse total pages."""
    html = _fetch_freelance_listing(1, opener)
    m = _PAGES_RE.search(html)
    if m:
        total = int(m.group(1))
        return list(range(1, total + 1))
    pages: set[int] = {1}
    for m in _FREELANCE_PAGE_LINK_RE.finditer(html):
        pages.add(int(m.group(1)))
    return sorted(pages) if pages else [1]


def _get_opener() -> urllib.request.OpenerDirector:
    """Return opener; use unverified SSL if default fails (certificate verify issues)."""
    return get_opener_for_base_url(_BASE_URL, "/faq.html", timeout=10)


def _fetch_faq_listing(page: int, opener: urllib.request.OpenerDirector) -> str:
    if page <= 1:
        url = f"{_BASE_URL}/faq.html"
    else:
        url = f"{_BASE_URL}/faq/{page}.html"
    return fetch_url(url, opener)


def _fetch_file_listing(page: int, opener: urllib.request.OpenerDirector) -> str:
    if page <= 1:
        url = f"{_BASE_URL}/file.html"
    else:
        url = f"{_BASE_URL}/file/{page}.html"
    return fetch_url(url, opener)


def _fetch_help_listing(page: int, opener: urllib.request.OpenerDirector) -> str:
    if page <= 1:
        url = f"{_BASE_URL}/help.html"
    else:
        url = f"{_BASE_URL}/help/{page}.html"
    return fetch_url(url, opener)


def _fetch_freelance_listing(page: int, opener: urllib.request.OpenerDirector) -> str:
    if page <= 1:
        url = f"{_BASE_URL}/freelance.html"
    else:
        url = f"{_BASE_URL}/freelance/{page}.html"
    return fetch_url(url, opener)


def _extract_links_regex_fallback(
    html: str, view_re: re.Pattern[str], base: str
) -> list[tuple[str, str]]:
    """Fallback: extract URLs by regex when BeautifulSoup finds nothing."""
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for m in view_re.finditer(html):
        clean = m.group(0)
        if "?" in clean.split("#")[0]:
            continue
        full_url = urljoin(base + "/", clean.lstrip("/"))
        if full_url in seen:
            continue
        seen.add(full_url)
        # Try to find title: text between > and </a> before this match
        id_part = m.group(1) if m.lastindex else ""
        title = f"HelpF #{id_part}" if id_part else "HelpF"
        result.append((title, full_url))
    return result


def _extract_faq_links(html: str) -> list[tuple[str, str]]:
    """Extract (title, url) from FAQ listing. Deduplicates by URL."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        m = _FAQ_VIEW_RE.search(href)
        if not m or "?" in href.split("#")[0]:
            continue
        clean = href.split("?")[0].split("#")[0]
        full_url = urljoin(_BASE_URL + "/", clean)
        if full_url in seen:
            continue
        seen.add(full_url)
        title = a.get_text(strip=True)
        if not title or len(title) < 3:
            continue
        result.append((title, full_url))
    if not result:
        result = _extract_links_regex_fallback(html, _FAQ_VIEW_RE, _BASE_URL)
    return result


def _extract_file_links(html: str) -> list[tuple[str, str]]:
    """Extract (title, url) from Files listing."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "/file/view/" not in href and "file/view/" not in href:
            continue
        if "?" in href.split("#")[0]:
            continue
        clean = href.split("?")[0].split("#")[0]
        full_url = urljoin(_BASE_URL + "/", clean)
        if full_url in seen:
            continue
        seen.add(full_url)
        title = a.get_text(strip=True)
        if not title or len(title) < 3 or title in ("Подробнее", "s"):
            continue
        result.append((title, full_url))
    if not result:
        result = _extract_links_regex_fallback(html, _FILE_VIEW_RE, _BASE_URL)
    return result


def _extract_help_links(html: str) -> list[tuple[str, str]]:
    """Extract (title, url) from Forum (help) listing."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        m = _HELP_VIEW_RE.search(href)
        if not m or "?" in href.split("#")[0]:
            continue
        clean = href.split("?")[0].split("#")[0]
        full_url = urljoin(_BASE_URL + "/", clean)
        if full_url in seen:
            continue
        seen.add(full_url)
        title = a.get_text(strip=True)
        if not title or len(title) < 3 or title in ("Подробнее", "s"):
            continue
        result.append((title, full_url))
    if not result:
        result = _extract_links_regex_fallback(html, _HELP_VIEW_RE, _BASE_URL)
    return result


def _extract_freelance_links(html: str) -> list[tuple[str, str]]:
    """Extract (title, url) from Freelance listing."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        m = _FREELANCE_VIEW_RE.search(href)
        if not m or "?" in href.split("#")[0]:
            continue
        clean = href.split("?")[0].split("#")[0]
        full_url = urljoin(_BASE_URL + "/", clean)
        if full_url in seen:
            continue
        seen.add(full_url)
        title = a.get_text(strip=True)
        if not title or len(title) < 3 or title in ("Подробнее", "s"):
            continue
        result.append((title, full_url))
    if not result:
        result = _extract_links_regex_fallback(html, _FREELANCE_VIEW_RE, _BASE_URL)
    return result


def _is_title_plus_noise(desc: str, title: str) -> bool:
    """Проверяет, что описание = заголовок + мусор (теги, категория без пробела)."""
    if not desc or not title or desc == title:
        return desc == title
    if not desc.startswith(title) or len(desc) - len(title) > 60:
        return False
    rest = desc[len(title) :].strip()
    return bool(rest and len(rest) < 50)  # короткий хвост — вероятно теги


# Фразы, после которых контент не считается основной инструкцией (подвал, сайдбар, спам)
_HELPF_SKIP_PATTERNS = (
    "Разместил:",
    "Подробнее",
    "Слова упорядочены по частоте",
    "Только текст:",
    "Возможно, вас также заинтересует",
    "Похожие FAQ",
    "Ключевые слова",
    "Комментарии",
    "Еще в этой же категории",
    "FAQ1855",
    "Forum19350",
    "Freelance15",
    "Добавить FAQ",
    "Задать Вопрос",
    "Добавить Проект",
    "О портале",
    "Портал в лицах",
    "Реклама на портале",
    "Ваши предложения",
    "Мы ищем хорошие сайты",
    "рассматриваю его к приобретению",
)


def parse_faq_detail(html: str, title: str) -> tuple[str, str]:
    """Extract description and code from FAQ detail page. Returns (desc, code).
    Максимум инструкции: h1, span.break-word, параграфы, списки — для quality MCP ответов."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    desc_parts: list[str] = []
    h1 = soup.find("h1")
    if h1:
        h1_text = h1.get_text(strip=True)
        if h1_text:
            desc_parts.append(h1_text)

    # span.break-word — краткое описание (как в FastCode)
    for span in soup.find_all("span", class_=lambda c: c and "break-word" in str(c)):
        t = span.get_text(strip=True)
        if t and len(t) > 20 and t not in desc_parts:
            desc_parts.append(t)
            break

    # h2/h3 — заголовки секций (Код 1C v 8.3, Подготовка и т.д.)
    for tag in soup.find_all(["h2", "h3"]):
        t = tag.get_text(strip=True)
        if t and len(t) > 5 and t not in desc_parts:
            if not any(s in t for s in _HELPF_SKIP_PATTERNS):
                desc_parts.append(t)

    for p in soup.find_all("p"):
        t = p.get_text(strip=True)
        if not t or len(t) <= 20:
            continue
        if any(s in t for s in _HELPF_SKIP_PATTERNS):
            continue
        desc_parts.append(t)

    # Списки (ul/ol) — пошаговые инструкции; len>30 отсекает навигацию
    for li in soup.find_all("li"):
        t = li.get_text(strip=True)
        if t and len(t) > 30 and t not in desc_parts:
            if not any(s in t for s in _HELPF_SKIP_PATTERNS):
                desc_parts.append(t)

    # Full text for references (instruction) — без обрезки, сохраняем весь контекст
    desc = " ".join(desc_parts).strip() or title
    if _is_title_plus_noise(desc, title):
        desc = title  # оставляем только заголовок, детали — по ссылке

    blocks: list[str] = []
    for pre in soup.find_all("pre"):
        code = pre.get_text().strip()
        if code and len(code) > 15:
            code = re.sub(r"<br\s*/?>", "\n", code, flags=re.I)
            blocks.append(code)
    # code в <code> — иногда доп. сниппет
    for code_tag in soup.find_all("code"):
        t = code_tag.get_text().strip()
        if t and len(t) > 40 and t not in blocks:
            if any(kw in t for kw in ("Процедура", "Функция", "Новый ", "Запрос")):
                blocks.append(t)
    code = "\n\n".join(blocks) if blocks else ""
    return (desc, code)


def parse_file_detail(html: str, title: str) -> tuple[str, str]:
    """Extract description from File detail page. Files usually have no code inline."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    desc_parts: list[str] = []
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(strip=True)
        if t:
            desc_parts.append(t)
    if not desc_parts:
        desc_parts.append(title)
    for p in soup.find_all("p"):
        t = p.get_text(strip=True)
        if t and len(t) > 20 and not any(s in t for s in _HELPF_SKIP_PATTERNS):
            desc_parts.append(t)
    for li in soup.find_all("li"):
        t = li.get_text(strip=True)
        if t and len(t) > 30 and not any(s in t for s in _HELPF_SKIP_PATTERNS):
            desc_parts.append(t)
    desc = " ".join(desc_parts).strip()
    if _is_title_plus_noise(desc, title):
        desc = title
    blocks: list[str] = []
    for pre in soup.find_all("pre"):
        code = pre.get_text().strip()
        if code and len(code) > 15:
            blocks.append(code)
    for code_tag in soup.find_all("code"):
        t = code_tag.get_text().strip()
        if t and len(t) > 40 and t not in blocks:
            if any(kw in t for kw in ("Процедура", "Функция", "Новый ", "Запрос")):
                blocks.append(t)
    code = "\n\n".join(blocks) if blocks else ""
    return (desc, code)


def parse_help_detail(html: str, title: str) -> tuple[str, str]:
    """Extract description and code from Forum (help) question page."""
    return parse_faq_detail(html, title)


def parse_freelance_detail(html: str, title: str) -> tuple[str, str]:
    """Extract description from Freelance project page."""
    return parse_file_detail(html, title)


_SOURCE_CONFIG = {
    "faq": (
        _fetch_faq_listing,
        _extract_faq_links,
        "FAQ",
        parse_faq_detail,
    ),
    "file": (
        _fetch_file_listing,
        _extract_file_links,
        "Files",
        parse_file_detail,
    ),
    "help": (
        _fetch_help_listing,
        _extract_help_links,
        "Forum",
        parse_help_detail,
    ),
    "freelance": (
        _fetch_freelance_listing,
        _extract_freelance_links,
        "Freelance",
        parse_freelance_detail,
    ),
}


def run_parse(
    out: Path,
    source: str = "faq",
    pages: list[int] | None = None,
    max_items: int = 0,
    delay: float = 1.0,
    fetch_detail: bool = True,
    skip_minimal: bool = False,
) -> int:
    """Fetch HelpF.pro FAQ, Files, Forum, Freelance into snippets JSON.

    source: 'faq' | 'file' | 'help' | 'freelance' | 'all'
    pages: listing pages to fetch (default: detect from site)
    max_items: max items to fetch detail for (0 = all)
    fetch_detail: fetch each detail page for full content
    """
    opener = _get_opener()
    all_items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    list_err = 0
    detail_err = 0

    sources = ["faq", "file", "help", "freelance"] if source == "all" else [source]
    if pages is None or not pages:
        progress_line("parse-helpf │ Detecting total pages...")
        try:
            if source == "all":
                pages_by_src = {}
                for src in sources:
                    det = (
                        _detect_faq_pages
                        if src == "faq"
                        else _detect_file_pages
                        if src == "file"
                        else _detect_help_pages
                        if src == "help"
                        else _detect_freelance_pages
                    )
                    pages_by_src[src] = det(opener)
                    time.sleep(delay)
            else:
                det = (
                    _detect_faq_pages
                    if source == "faq"
                    else _detect_file_pages
                    if source == "file"
                    else _detect_help_pages
                    if source == "help"
                    else _detect_freelance_pages
                )
                pages_by_src = {source: det(opener)}
        except Exception:
            pages_by_src = {src: [1] for src in sources}
        total = sum(len(p) for p in pages_by_src.values())
        progress_done(f"parse-helpf │ detected {total} pages total")
        time.sleep(delay)
    else:
        pages_by_src = {src: pages for src in sources}

    for src in sources:
        cfg = _SOURCE_CONFIG.get(src)
        if not cfg:
            continue
        fetch_listing, extract_links, label, _ = cfg
        src_pages = pages_by_src.get(src, [1])

        progress_line(f"parse-helpf │ {label} listing 0/{len(src_pages)} │ 0 items │ 0 err")

        for i, page in enumerate(src_pages):
            try:
                html = fetch_listing(page, opener)
            except Exception:
                list_err += 1
                progress_done(f"parse-helpf │ {label} page {page} fetch error")
                continue
            links = extract_links(html)
            for title, url in links:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                all_items.append(
                    {
                        "title": title,
                        "description": "",
                        "code_snippet": "",
                        "source_url": url,
                        "source": src,
                    }
                )
            progress_line(
                f"parse-helpf │ {label} listing {i + 1}/{len(src_pages)} │ {len(all_items)} items │ {list_err} err"
            )
            if i < len(src_pages) - 1:
                time.sleep(delay)

    if fetch_detail and all_items:
        to_fetch = [(idx, it) for idx, it in enumerate(all_items) if it.get("source_url")]
        if max_items > 0:
            to_fetch = to_fetch[:max_items]
        total_detail = len(to_fetch)
        progress_done(f"parse-helpf │ Detail 0/{total_detail} │ fetching...")
        for di, (idx, it) in enumerate(to_fetch):
            url = it.get("source_url", "")
            if not url:
                continue
            parse_fn = _SOURCE_CONFIG.get(it.get("source"), (None, None, None, parse_faq_detail))[3]
            try:
                detail_html = fetch_url(url, opener)
                desc, code = parse_fn(detail_html, it.get("title", ""))
                if desc:
                    all_items[idx]["description"] = desc
                    # Full text for references (instruction); snippets keep code_snippet
                    all_items[idx]["instruction"] = desc
                if code:
                    all_items[idx]["code_snippet"] = code
            except Exception:
                detail_err += 1
            progress_line(
                f"parse-helpf │ Detail {di + 1}/{total_detail} │ {di + 1 - detail_err} ok │ {detail_err} err"
            )
            time.sleep(delay)

    for it in all_items:
        if it.get("source_url"):
            it["detail_url"] = it.pop("source_url")
        it["source_site"] = "helpf.pro"
        # source (faq/file/help/freelance) оставляем для атрибуции
        if not it.get("code_snippet") and not it.get("description"):
            it["description"] = it.get("title", "") or ""
        # instruction — полный текст локально; без detail fetch — хотя бы description
        if not it.get("instruction") and (it.get("description") or "").strip():
            it["instruction"] = it["description"]

    if skip_minimal:
        before = len(all_items)
        all_items = [
            it
            for it in all_items
            if it.get("code_snippet")
            or it.get("instruction")
            or (it.get("description") or "").strip() != (it.get("title") or "").strip()
        ]
        dropped = before - len(all_items)
        if dropped:
            progress_done(f"parse-helpf │ Dropped {dropped} minimal (title-only) items")

    from .snippet_classifier import classify_snippet_vs_reference

    snippets_n = 0
    for it in all_items:
        it["type"] = classify_snippet_vs_reference(
            it.get("title", ""),
            it.get("description", ""),
            it.get("code_snippet", ""),
        )
        if it["type"] == "snippet":
            snippets_n += 1
        # instruction храним и для snippets, и для references — полный текст локально

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")

    ref_n = len(all_items) - snippets_n
    summary = (
        f"parse-helpf │ ✓ {len(all_items)} items ({snippets_n} snippets, {ref_n} ref) → {out.name}"
    )
    if list_err or detail_err:
        summary += f" │ {list_err} list err, {detail_err} detail err"
    progress_done(summary)
    return 0
