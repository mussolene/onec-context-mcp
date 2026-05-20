"""Parse 1C ITS v8std (https://its.1c.ru/db/v8std) for load-standards.

Crawls browse TOC, collects content/*/hdoc URLs, fetches each page and extracts
title + body as markdown-like text. Optional auth via ITS_AUTH_COOKIE env.
Encoding: detects charset from Content-Type or HTML meta, falls back to windows-1251 for Russian.
"""

from __future__ import annotations

import re
import time
import unicodedata
import urllib.request
from typing import Any
from urllib.parse import urljoin

from ...shared._http import get_ssl_context

_BASE = "https://its.1c.ru"
_V8STD_MAIN = _BASE + "/db/v8std"
_V8STD_BROWSE = _BASE + "/db/v8std/browse/13/-1"
_CONTENT_RE = re.compile(r"/db/v8std/content/(\d+)/hdoc")
_BROWSE_RE = re.compile(r"/db/v8std/browse/13/-1(?:/\d+)*")


# 0 = без лимита (все страницы оглавления и все статьи)
def _get_its_max_browse_pages() -> int:
    from ...shared import env_config

    return env_config.get_its_v8std_max_browse_pages()


def _get_its_delay_sec() -> float:
    from ...shared import env_config

    return env_config.get_its_v8std_delay()


_USER_AGENT = "Mozilla/5.0 (compatible; onec-context-mcp-its-v8std-parser/1.0)"
# Строки навигации/футера ITS — выкидываем из контента
_NAV_NOISE = re.compile(
    r"^(Вход|Об 1С:ИТС|Тест-драйв|Заказать ИТС|Задать вопрос|Обновить ПО|"
    r"Оценить 1С|Купить кассу|Подбор КБК|Последние результаты|Подписаться на рассылку|"
    r"Мы используем файлы cookie|Принимаю|Назад|Результаты поиска|Содержание|Документ|"
    r"Тематические подборки|Календарь бухгалтера|Калькуляторы|"
    r"Главная|Инструкции по разработке на 1С|Методические материалы|"
    r"© Фирма|Все права защищены|Информационная система 1С:ИТС|"
    r"Инструкции по учету|Консультации по законодательству|Книги и периодика|"
    r"Справочная информация|База нормативных документов|Новости|1С:Лекторий|"
    r"Акции и конкурсы|Курсы и экзамены|Отзывы об ИТС|1С:Напарник|Партнер года|Вконтакте)$",
    re.I,
)
# Хлебные крошки и пункты меню (короткие или только ссылки)
_BREADCRUMB_RE = re.compile(r"^\d+\.\s+\[.+\]\(.+\)\s*$")
_MIN_REAL_CONTENT_CHARS = 150


def _make_opener() -> urllib.request.OpenerDirector:
    from ...shared import env_config

    cookie = env_config.get_its_auth_cookie()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=get_ssl_context()))
    if cookie:
        opener.addheaders.append(("Cookie", cookie))
    opener.addheaders.append(("User-Agent", _USER_AGENT))
    return opener


def _detect_charset(resp: urllib.response.addinfourl, raw: bytes) -> str:
    """Infer charset from Content-Type, then HTML meta, then try UTF-8 / windows-1251."""
    ct = resp.headers.get("Content-Type", "") or ""
    for part in ct.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            enc = part.split("=", 1)[1].strip().strip("'\"").lower()
            if enc in ("utf-8", "utf8"):
                return "utf-8"
            if enc in ("windows-1251", "cp1251"):
                return "windows-1251"
            return enc
    head = raw[:8192].decode("ascii", errors="ignore")
    m = re.search(r'<meta[^>]+charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', head, re.I)
    if m:
        enc = m.group(1).lower()
        if "1251" in enc or enc == "cp1251":
            return "windows-1251"
        if "utf" in enc:
            return "utf-8"
    # No charset: try UTF-8 first; if many replacement chars, use windows-1251
    try:
        raw.decode("utf-8", errors="strict")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("windows-1251", errors="strict")
        return "windows-1251"
    except UnicodeDecodeError:
        pass
    return "utf-8"


def _fetch(url: str, opener: urllib.request.OpenerDirector) -> str:
    req = urllib.request.Request(url)
    with opener.open(req, timeout=30) as resp:
        raw = resp.read()
    charset = _detect_charset(resp, raw)
    try:
        text = raw.decode(charset, errors="replace")
    except (LookupError, ValueError):
        text = raw.decode("utf-8", errors="replace")
    return _sanitize_text(text)


def _fetch_bytes(url: str, opener: urllib.request.OpenerDirector) -> tuple[bytes, str]:
    """Fetch URL, return (raw_bytes, decoded_text). Used when we need to re-detect charset."""
    req = urllib.request.Request(url)
    with opener.open(req, timeout=30) as resp:
        raw = resp.read()
    charset = _detect_charset(resp, raw)
    try:
        text = raw.decode(charset, errors="replace")
    except (LookupError, ValueError):
        text = raw.decode("utf-8", errors="replace")
    return raw, text


def _get_iframe_doc_url(html: str, base_url: str) -> str | None:
    """Из страницы hdoc извлечь src iframe с контентом документа (печатная версия). ITS использует iframe id=w_metadata_doc_frame."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    iframe = soup.find("iframe", id="w_metadata_doc_frame")
    if not iframe:
        iframe = soup.find("iframe", src=re.compile(r"/db/content/v8std/"))
    if not iframe or not iframe.get("src"):
        return None
    src = iframe["src"].strip()
    if not src.startswith("http"):
        src = urljoin(base_url, src)
    return src.split("#")[0] or None


def _sanitize_text(s: str) -> str:
    """Normalize and strip control chars so embedding gets clean UTF-8 text. Keeps newlines."""
    if not s or not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", s)
    return s.strip()


def _extract_content_links(html: str, base_url: str) -> set[str]:
    """Collect unique /db/v8std/content/<id>/hdoc links from page."""
    out: set[str] = set()
    for m in _CONTENT_RE.finditer(html):
        path = m.group(0)
        full = urljoin(base_url, path)
        out.add(full.split("?")[0].split("#")[0])
    return out


def _extract_browse_links(html: str, base_url: str) -> set[str]:
    """Collect /db/v8std/browse/13/-1[/<id>] links for recursive crawl."""
    out: set[str] = set()
    for m in _BROWSE_RE.finditer(html):
        path = m.group(0)
        full = urljoin(base_url, path)
        out.add(full.split("?")[0].split("#")[0])
    return out


def _browse_path_from_url(url: str) -> list[str]:
    """Extract path ids from browse URL: .../browse/13/-1/26/28 -> ['26', '28']. Main page /db/v8std -> []."""
    url_clean = url.split("?")[0].rstrip("/")
    if "/browse/13/-1/" not in url_clean:
        return []
    suffix = url_clean.split("/browse/13/-1/")[-1].strip("/")
    if not suffix:
        return []
    return [p for p in suffix.split("/") if p.isdigit()]


def _path_cache_key(path_ids: list[str]) -> str:
    """'26' or '26/28' for cache key."""
    return "/".join(path_ids) if path_ids else ""


def _crawl_content_with_paths(
    opener: urllib.request.OpenerDirector,
    start_url: str = _V8STD_BROWSE,
    max_pages: int | None = None,
) -> list[tuple[str, list[str]]]:
    """BFS over browse pages (включая главную /db/v8std). Returns [(content_url, section_titles), ...].
    Меню многоуровневое: главная -> разделы -> подразделы -> статьи. Обходим все уровни."""
    from bs4 import BeautifulSoup

    if max_pages is None:
        max_pages = _get_its_max_browse_pages()
    path_title_cache: dict[str, str] = {}
    result: list[tuple[str, list[str]]] = []
    to_visit: set[str] = {_V8STD_MAIN, start_url}
    visited: set[str] = set()
    while to_visit and (max_pages <= 0 or len(visited) < max_pages):
        url = to_visit.pop()
        if url in visited:
            continue
        visited.add(url)
        time.sleep(_get_its_delay_sec())
        try:
            html = _fetch(url, opener)
        except Exception:
            continue
        soup = BeautifulSoup(html, "html.parser")
        path_ids = _browse_path_from_url(url)
        path_key = _path_cache_key(path_ids)
        h1 = soup.find("h1")
        title = (
            (h1.get_text(separator=" ", strip=True) if h1 else "").strip() or path_key or "v8std"
        )
        if path_key:
            path_title_cache[path_key] = _sanitize_text(title)
        elif not path_ids and (_V8STD_MAIN in url or url.rstrip("/").endswith("/db/v8std")):
            path_title_cache[""] = _sanitize_text(title) or "v8std"
        current_path_titles: list[str] = []
        for i in range(len(path_ids)):
            part_key = _path_cache_key(path_ids[: i + 1])
            current_path_titles.append(path_title_cache.get(part_key, part_key))
        if not current_path_titles and not path_ids:
            current_path_titles = ["v8std"]
        for content_url in _extract_content_links(html, url):
            result.append((content_url, list(current_path_titles)))
        for link in _extract_browse_links(html, url):
            if link not in visited:
                to_visit.add(link)
    return result


def _parse_print_page(html: str, url: str, title: str) -> str | None:
    """Парсинг страницы печатной версии (iframe src). Возвращает текст тела статьи или None."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("body")
    if not body:
        body = soup
    text = body.get_text(separator="\n", strip=True) if body else ""
    text = _sanitize_text(text)
    if not text or len(text) < _MIN_REAL_CONTENT_CHARS:
        return None
    return text


def _parse_content_page(html: str, url: str) -> dict[str, Any] | None:
    """Extract title and body from ITS v8std content page. Returns None if only nav/cookie (no real article)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    content_id = ""
    if "/content/" in url:
        content_id = url.split("/content/")[-1].split("/")[0]

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(separator=" ", strip=True)
    if not title and soup.title:
        raw_title = soup.title.get_text(separator=" ", strip=True)
        if "::" in raw_title:
            title = raw_title.split("::")[0].strip()
        else:
            title = raw_title
    if not title:
        title = content_id or "ITS v8std"
    title = _sanitize_text(title)

    # 1) Блок по id/data с content_id (ITS может рендерить контент в content-637, hdoc-637 и т.д.)
    body_parts: list[str] = []
    if content_id:
        for candidate in (
            soup.find(
                id=re.compile(
                    rf"content[-_]?{re.escape(content_id)}|hdoc[-_]?{re.escape(content_id)}|doc[-_]?{re.escape(content_id)}",
                    re.I,
                )
            ),
            soup.find(attrs={"data-content-id": content_id}),
            soup.find(attrs={"data-doc-id": content_id}),
            soup.find(attrs={"data-id": content_id}),
        ):
            if candidate and candidate.get_text(strip=True):
                body_parts.append(candidate.get_text(separator="\n", strip=True))
                break
    # 2) Обычные контейнеры основного контента
    if not body_parts:
        for candidate in (
            soup.find("main"),
            soup.find("article"),
            soup.find(id=re.compile(r"content|document|article|body", re.I)),
            soup.find(
                class_=re.compile(
                    r"document-body|article-body|hdoc-content|content-body|text-body", re.I
                )
            ),
            soup.find(class_=re.compile(r"content|body|text|doc", re.I)),
        ):
            if candidate and candidate.get_text(strip=True):
                body_parts.append(candidate.get_text(separator="\n", strip=True))
                break
    # 3) Эвристика: самый большой блок, содержащий заголовок статьи (не навбар)
    if not body_parts and title:
        best = None
        best_len = 0
        for tag in soup.find_all(["div", "section", "article"]):
            if tag.find_parent(["nav", "header", "footer", "aside"]):
                continue
            text = tag.get_text(separator="\n", strip=True)
            if len(text) < _MIN_REAL_CONTENT_CHARS:
                continue
            if title and title in text:
                if len(text) > best_len:
                    best_len = len(text)
                    best = text
        if best:
            body_parts.append(best)
    if not body_parts:
        body = soup.find("body")
        if body:
            for tag in body.find_all(["nav", "header", "footer", "aside", "script", "style"]):
                tag.decompose()
            body_parts.append(body.get_text(separator="\n", strip=True))

    lines = []
    for p in body_parts:
        for line in p.splitlines():
            line = line.strip()
            if not line or len(line) < 3:
                continue
            if _NAV_NOISE.match(line):
                continue
            if _BREADCRUMB_RE.match(line):
                continue
            if re.match(r"^\[.+\]\(https?://", line) and len(line) < 120:
                continue
            lines.append(line)
    text = "\n\n".join(lines).strip()
    text = _sanitize_text(text)
    if not text:
        return None
    if title and text.strip() == title:
        return None
    real_len = len(text.replace(title, "").strip())
    if real_len < _MIN_REAL_CONTENT_CHARS:
        return None

    first_para = text.split("\n\n")[0][:500].strip() if text else ""
    first_para = _sanitize_text(first_para)

    return {
        "title": title,
        "description": first_para,
        "code_snippet": _sanitize_text(f"# {title}\n\n{text}"),
        "detail_url": url,
        "source_ref": url,
        "source": "its.1c.ru",
        "source_site": "its.1c.ru",
    }


def _safe_folder_name(s: str, max_len: int = 60) -> str:
    """Safe directory name: alphanumeric, dash, underscore; fallback hash."""
    s = (s or "").strip()
    out: list[str] = []
    for c in s:
        if c.isalnum() or c in "-_ ":
            out.append(c if c != " " else "_")
    name = "".join(out).strip("_")
    if not name:
        import hashlib

        name = hashlib.md5(s.encode("utf-8")).hexdigest()[:12]
    return name[:max_len]


def fetch_its_v8std_items(
    opener: urllib.request.OpenerDirector | None = None,
    start_url: str = _V8STD_BROWSE,
    max_content: int | None = None,
) -> list[dict[str, Any]]:
    """Crawl ITS v8std with section paths, fetch content pages. Returns items with section_path, content_id.

    Each item: title, description, code_snippet, detail_url, source, source_site, section_path (list), content_id (str).
    Pages that are only nav/cookie are skipped. set ITS_AUTH_COOKIE if you have subscription.
    max_content: None или 0 = без лимита (все статьи).
    """
    op = opener or _make_opener()
    content_with_paths = _crawl_content_with_paths(op, start_url=start_url, max_pages=None)
    seen_ids: set[str] = set()
    deduped: list[tuple[str, list[str]]] = []
    for url, path_titles in content_with_paths:
        mid = url.split("/content/")[-1].split("/")[0] if "/content/" in url else ""
        if mid and mid not in seen_ids:
            seen_ids.add(mid)
            deduped.append((url, path_titles))
    if max_content and max_content > 0:
        deduped = deduped[:max_content]
    items: list[dict[str, Any]] = []
    for url, path_titles in deduped:
        time.sleep(_get_its_delay_sec())
        try:
            html = _fetch(url, op)
        except Exception:
            continue
        # Контент статьи на ITS в iframe (печатная версия). Сначала пробуем загрузить её.
        title_from_hdoc = ""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            h1 = soup.find("h1")
            if h1:
                title_from_hdoc = _sanitize_text(h1.get_text(separator=" ", strip=True))
            if not title_from_hdoc and soup.title:
                raw_title = soup.title.get_text(separator=" ", strip=True)
                title_from_hdoc = _sanitize_text(
                    raw_title.split("::")[0].strip() if "::" in raw_title else raw_title
                )
        except Exception:
            pass
        if not title_from_hdoc and "/content/" in url:
            title_from_hdoc = url.split("/content/")[-1].split("/")[0]

        iframe_url = _get_iframe_doc_url(html, url)
        body_text: str | None = None
        if iframe_url:
            time.sleep(_get_its_delay_sec())
            try:
                _, html_print = _fetch_bytes(iframe_url, op)
                body_text = _parse_print_page(html_print, iframe_url, title_from_hdoc)
            except Exception:
                pass

        if body_text:
            first_para = body_text.split("\n\n")[0][:500].strip() if body_text else ""
            mid = url.split("/content/")[-1].split("/")[0] if "/content/" in url else ""
            items.append(
                {
                    "title": title_from_hdoc or "ITS v8std",
                    "description": _sanitize_text(first_para),
                    "code_snippet": _sanitize_text(
                        f"# {title_from_hdoc or 'Стандарт'}\n\n{body_text}"
                    ),
                    "detail_url": url,
                    "source_ref": url,
                    "source": "its.1c.ru",
                    "source_site": "its.1c.ru",
                    "content_id": mid,
                    "section_path": path_titles,
                }
            )
            continue

        item = _parse_content_page(html, url)
        if item:
            mid = url.split("/content/")[-1].split("/")[0] if "/content/" in url else ""
            item["content_id"] = mid
            item["section_path"] = path_titles
            items.append(item)
    return items
