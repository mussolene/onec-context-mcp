"""Parse FastCode templates (https://fastcode.im/Templates) into snippets JSON.

Listing pages show truncated code. Items with detail links are fetched for full code.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from ._http import fetch_url, get_opener_for_base_url
from ._utils import progress_done, progress_line

_DETAIL_LINK_RE = re.compile(r"/Templates/(\d+)/")
_PAGE_RE = re.compile(r"[?&]Page=(\d+)")

# Теги FastCode, которые могут склеиваться с заголовком в span.break-word
_FASTCODE_KNOWN_TAGS = frozenset(
    "TurboConf ИР БСП 1С Скрипты Starter Стартер Executor OneScript Powershell Инструменты Данные".split()
)


def _strip_tag_suffix(desc: str, title: str) -> str:
    """Убирает из описания хвост из тегов (TurboConf ИР и т.п.), если описание = заголовок + теги."""
    if not desc or not title:
        return desc
    desc = desc.strip()
    # Описание = заголовок + теги без пробела (ИР Найти в спискеTurboConf ИР)
    if desc == title:
        return ""
    if not desc.startswith(title):
        return desc
    rest = desc[len(title) :].strip()
    if not rest or len(rest) > 80:
        return desc
    # Проверяем: rest выглядит как теги (слова из известного набора или короткие токены)
    words = rest.replace(",", " ").split()
    if not words:
        return ""
    for w in words:
        w_clean = w.strip("#")
        if len(w_clean) > 25:
            return desc  # длинное слово — не тег, оставляем как есть
        if w_clean not in _FASTCODE_KNOWN_TAGS and not re.match(r"^[А-Яа-яA-Za-z0-9#]+$", w_clean):
            return desc
    return ""  # rest — только теги, реального описания нет


_FASTCODE_TAG_PATTERN = re.compile(
    r"\s+(?:TurboConf|ИР|БСП|1С|Скрипты|Starter|Стартер|Executor|OneScript|Powershell|Инструменты|Данные)(?:\s+[А-Яа-яA-Za-z0-9#]+)*\s*$",
    re.I,
)


def _strip_trailing_tags(desc: str) -> str:
    """Убирает теги в конце описания (Real content. TurboConf ИР → Real content.)."""
    if not desc or len(desc) < 30:
        return desc
    tail = _FASTCODE_TAG_PATTERN.search(desc)
    if tail:
        return desc[: tail.start()].rstrip()
    return desc


def _detect_total_pages(opener: urllib.request.OpenerDirector) -> list[int]:
    """Detect total pages by following pagination. FastCode shows ~6 links per page (sliding window)."""
    html = _fetch_page(1, opener)
    seen: set[int] = {1}
    for m in _PAGE_RE.finditer(html):
        seen.add(int(m.group(1)))
    if not seen:
        return [1]
    current = max(seen)
    while True:
        time.sleep(0.5)  # be polite when probing pages
        html = _fetch_page(current, opener)
        found: set[int] = set()
        for m in _PAGE_RE.finditer(html):
            found.add(int(m.group(1)))
        if not found:
            break
        new_max = max(found)
        seen.update(found)
        # On last page, links don't include current (e.g. on p51 links are 46–50)
        if new_max < current:
            break
        if new_max <= current:
            break
        current = new_max
    total = max(seen)
    # If we requested 'current' and got only lower numbers, total is 'current'
    if current > total:
        total = current
    return list(range(1, total + 1))


def _get_opener() -> urllib.request.OpenerDirector:
    return get_opener_for_base_url("https://fastcode.im", "/Templates?Page=1", timeout=10)


def _fetch_page(page: int, opener: urllib.request.OpenerDirector) -> str:
    url = f"https://fastcode.im/Templates?Page={page}"
    return fetch_url(url, opener)


def _extract_desc_from_code(code: str) -> str:
    """Extract description from leading // comments in code."""
    lines = code.split("\n")
    parts = []
    for line in lines:
        s = line.strip()
        if s.startswith("//"):
            parts.append(s.lstrip("/").strip())
        elif parts:
            break
    return " ".join(parts).strip()


def _is_safe_fastcode_detail_url(href: str) -> str | None:
    """Return safe detail URL or None. Reject protocol-relative (//evil.com), javascript:, data:, etc."""
    h = (href or "").strip()
    if not h or "?" in h.split("#")[0]:
        return None
    base = "https://fastcode.im"
    # Relative path: /Templates/123/slug — safe
    if h.startswith("/") and not h.startswith("//"):
        return base + h.split("?")[0]
    # Absolute: only allow fastcode.im
    if h.lower().startswith("https://fastcode.im/"):
        return h.split("?")[0]
    return None


def _extract_detail_link_for_h3(h3: Any) -> str | None:
    """Find first /Templates/ID/slug link in block from this h3 until next h3."""
    for tag in h3.find_all_next():
        if tag.name == "h3" and tag != h3:
            break
        if tag.name != "a" or not tag.get("href"):
            continue
        href = tag["href"]
        if not _DETAIL_LINK_RE.search(href):
            continue
        full = _is_safe_fastcode_detail_url(href)
        if full:
            return full
    return None


def _extract_detail_links(soup: Any) -> dict[str, str]:
    """Build title -> detail_url mapping: for each h3, find link in its block."""
    mapping: dict[str, str] = {}
    for h3 in soup.find_all("h3"):
        title = h3.get_text(strip=True)
        if not title or title in mapping:
            continue
        url = _extract_detail_link_for_h3(h3)
        if url:
            mapping[title] = url
    return mapping


def parse_detail_page(html: str, title: str = "") -> tuple[str, str]:
    """Extract full description and code from detail page. Returns (desc, code).
    Собирает максимум текста для локального хранения (описание + документация)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    desc_parts: list[str] = []

    # h1 — заголовок
    h1 = soup.find("h1")
    if h1:
        h1_text = h1.get_text(strip=True)
        if h1_text:
            desc_parts.append(h1_text)

    # span.break-word — краткое описание
    for span in soup.find_all("span", class_=lambda c: c and "break-word" in c):
        t = span.get_text(strip=True)
        if t and len(t) > 30 and t not in desc_parts:
            desc_parts.append(t)
            break

    # параграфы и пояснения (в т.ч. между блоками кода) — вся документация
    skip = ("Разместил:", "Подробнее", "Копировать", "Копировано")
    for tag in soup.find_all(["p", "pre"]):
        if tag.name == "pre":
            continue  # не прерываем цикл — собираем p между pre-блоками
        t = tag.get_text(strip=True)
        if t and len(t) > 40 and t not in desc_parts:
            if not any(s in t for s in skip):
                desc_parts.append(t)

    desc = " ".join(desc_parts).strip()
    if not desc and h1:
        desc = h1.get_text(strip=True)

    # Убираем теги из описания (ИР, TurboConf и т.п.)
    if desc and title:
        cleaned = _strip_tag_suffix(desc, title)
        if cleaned == "" and desc != title:
            desc = title
        elif cleaned:
            desc = cleaned
    if desc:
        desc = _strip_trailing_tags(desc)

    blocks: list[str] = []
    for pre in soup.find_all("pre"):
        code = pre.get_text().strip()
        if code and len(code) > 20:
            blocks.append(code)
    # code в <code> — иногда дополнительный сниппет
    for code_tag in soup.find_all("code"):
        t = code_tag.get_text().strip()
        if t and len(t) > 40 and t not in blocks:
            if any(kw in t for kw in ("Процедура", "Функция", "Новый ", "Запрос")):
                blocks.append(t)
    code = "\n\n".join(blocks) if blocks else ""
    return (desc, code)


def parse_page(html: str) -> list[dict[str, Any]]:
    """Parse listing page into list of {title, description, code_snippet, detail_url?}."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    items: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    detail_links = _extract_detail_links(soup)

    h3_to_pre: dict = {}
    for pre in soup.find_all("pre"):
        h3 = pre.find_previous("h3")
        if not h3:
            continue
        title = h3.get_text(strip=True)
        if title and title not in h3_to_pre:
            h3_to_pre[title] = pre

    for h3 in soup.find_all("h3"):
        title = h3.get_text(strip=True)
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        pre = h3_to_pre.get(title)
        code = pre.get_text().strip() if pre else ""

        desc = ""
        for tag in h3.find_all_next():
            if tag == pre or (pre and tag.name == "pre"):
                break
            if tag.name == "h3" and tag != h3:
                break
            if tag.name == "span" and "break-word" in (tag.get("class") or []):
                desc = tag.get_text(strip=True)
                break
        if not desc and code:
            desc = _extract_desc_from_code(code)
        if not desc:
            desc = title
        desc = _strip_tag_suffix(desc, title) or desc or title
        desc = _strip_trailing_tags(desc) or desc

        item: dict[str, Any] = {
            "title": title,
            "description": desc or "",
            "code_snippet": code,
        }
        if title in detail_links:
            item["detail_url"] = detail_links[title]
        items.append(item)
    return items


def run_parse(
    out: Path,
    pages: list[int] | None = None,
    delay: float = 1.0,
    fetch_detail: bool = True,
) -> int:
    """Fetch listing pages, optionally fetch detail pages for full code.
    pages: explicit list or None to auto-detect from first page. Returns 0 on success."""
    opener = _get_opener()
    if pages is None or not pages:
        progress_line("parse-fastcode │ Detecting total pages...")
        try:
            pages = _detect_total_pages(opener)
        except Exception as e:
            logging.getLogger(__name__).debug("detect total pages failed: %s", e)
            pages = [1]
        progress_done(f"parse-fastcode │ detected {len(pages)} pages")
        time.sleep(delay)
    all_items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    list_err = 0
    detail_err = 0

    total_pages = len(pages)
    progress_line(f"parse-fastcode │ Listing 0/{total_pages} │ 0 items │ 0 err")

    for i, page in enumerate(pages):
        try:
            html = _fetch_page(page, opener)
        except Exception as e:
            logging.getLogger(__name__).debug("fetch page %s failed: %s", page, e)
            list_err += 1
            progress_done(f"parse-fastcode │ Page {page} fetch error")
            continue
        page_items = parse_page(html)
        added = 0
        for it in page_items:
            key = (it["title"] or "").strip()
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            all_items.append(it)
            added += 1
        progress_line(
            f"parse-fastcode │ Listing {i + 1}/{total_pages} │ {len(all_items)} items │ {list_err} err"
        )
        if i < len(pages) - 1:
            time.sleep(delay)

    if fetch_detail:
        to_fetch = [(idx, it) for idx, it in enumerate(all_items) if it.get("detail_url")]
        total_detail = len(to_fetch)
        if total_detail > 0:
            progress_done(f"parse-fastcode │ Detail 0/{total_detail} │ fetching full code...")
        for di, (idx, it) in enumerate(to_fetch):
            url = it.pop("detail_url", None)
            if not url:
                continue
            try:
                detail_html = fetch_url(url, opener)
                desc, code = parse_detail_page(detail_html, it.get("title", ""))
                if code:
                    all_items[idx]["code_snippet"] = code
                if desc:
                    all_items[idx]["description"] = desc
                    all_items[idx]["instruction"] = (
                        desc  # полный текст локально для сниппета и reference
                    )
                all_items[idx]["detail_url"] = url  # ссылка на документацию
            except Exception as e:
                logging.getLogger(__name__).debug("fetch detail %s failed: %s", url[:60], e)
                detail_err += 1
                all_items[idx]["detail_url"] = url  # сохраняем ссылку даже при ошибке
            progress_line(
                f"parse-fastcode │ Detail {di + 1}/{total_detail} │ {di + 1 - detail_err} ok │ {detail_err} err"
            )
            time.sleep(delay)

    for it in all_items:
        it["source_site"] = "fastcode.im"
        # instruction — полный текст для локального доступа; без detail — хотя бы из листинга
        if not it.get("instruction") and (it.get("description") or "").strip():
            it["instruction"] = it["description"]

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

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")

    ref_n = len(all_items) - snippets_n
    summary = f"parse-fastcode │ ✓ {len(all_items)} items ({snippets_n} snippets, {ref_n} ref) → {out.name}"
    if list_err or detail_err:
        summary += f" │ {list_err} list err, {detail_err} detail err"
    progress_done(summary)
    return 0
