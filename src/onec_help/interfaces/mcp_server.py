"""MCP server for 1C Help structured API, metadata, memory and diagnostics."""

import functools
import inspect
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Annotated, Any

from pydantic import BeforeValidator


def _coerce_str_to_list(v: Any) -> Any:
    """Allow MCP clients that serialize list params as JSON strings."""
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        return [v]
    return v


_StrList = Annotated[list[str], BeforeValidator(_coerce_str_to_list)]

from ..knowledge.platform_help_manager_templates import manager_help_hint_line  # noqa: E402
from ..runtime.mcp_metrics import record_request as _record_mcp_request  # noqa: E402
from ..search_store.indexer import _version_sort_key  # noqa: E402
from ..shared._utils import format_duration, mask_path_for_log, safe_error_message  # noqa: E402


def _record_mcp_tool(f):
    """Decorator: record MCP tool call (success/fail, duration, error) for dashboard metrics.
    Preserves f's signature so FastMCP can introspect parameters (no *args)."""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        name = f.__name__
        t0 = time.monotonic()
        try:
            out = f(*args, **kwargs)
            _record_mcp_request(name, True, duration_sec=time.monotonic() - t0)
            return out
        except Exception as e:
            _record_mcp_request(
                name,
                False,
                duration_sec=time.monotonic() - t0,
                error_msg=safe_error_message(e),
            )
            raise

    try:
        wrapper.__signature__ = inspect.signature(f)
    except (ValueError, TypeError):
        pass
    return wrapper


def _snippet_max_chars() -> int:
    """Snippet length for search results. From env_config."""
    from ..shared import env_config

    return env_config.get_mcp_snippet_max_chars()


def _max_topic_content_chars() -> int:
    """Max chars per topic preview in search_with_content/compact answer helpers. From env_config."""
    from ..shared import env_config

    return env_config.get_mcp_max_topic_chars()


MAX_QUERY_CHARS = 65536  # 64 KB
MAX_CODE_SNIPPET_CHARS = 65536  # 64 KB
_RATE_LIMIT_WINDOW_SEC = 60
_rate_timestamps: list[float] = []
_rate_lock = threading.Lock()


def _check_rate_limit() -> str | None:
    """Return error message if over rate limit, else None. MCP_RATE_LIMIT_PER_MIN=0 disables."""
    from ..shared import env_config

    limit = env_config.get_mcp_rate_limit_per_min()
    if limit <= 0:
        return None
    now = time.monotonic()
    with _rate_lock:
        _rate_timestamps[:] = [t for t in _rate_timestamps if now - t < _RATE_LIMIT_WINDOW_SEC]
        if len(_rate_timestamps) >= limit:
            return f"Rate limit exceeded ({limit} requests per minute). Try again later."
        _rate_timestamps.append(now)
    return None


def _truncate_if_needed(value: str, max_chars: int, name: str) -> tuple[str, str | None]:
    """Return (value, error) — truncate or error if over limit."""
    if len(value) <= max_chars:
        return (value, None)
    return ("", f"{name} exceeds {max_chars} chars (got {len(value)}). Shorten the input.")


# Prefer fastmcp; fallback to mcp package
try:
    from fastmcp import FastMCP

    _HAS_FASTMCP = True
except ImportError:
    FastMCP = None  # type: ignore
    _HAS_FASTMCP = False

try:
    from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware

    _HAS_ERROR_MIDDLEWARE = True
except ImportError:
    ErrorHandlingMiddleware = None  # type: ignore
    _HAS_ERROR_MIDDLEWARE = False

_HELP_PATH = None  # Path | None


def _get_cursor_docs_path() -> Path | None:
    """Root of cursor-examples docs for self-documenting MCP. MCP_CURSOR_DOCS_PATH or repo docs/."""
    env_path = os.environ.get("MCP_CURSOR_DOCS_PATH")
    if env_path:
        p = Path(env_path).resolve()
        if p.exists():
            return p
    # Development: src/onec_help/mcp_server.py -> repo root = parents[2]
    try:
        repo_docs = Path(__file__).resolve().parents[2] / "docs"
        if repo_docs.exists():
            return repo_docs
    except (IndexError, OSError):
        pass
    return None


def _read_cursor_doc(relative: str) -> str:
    """Read file from cursor-examples. relative like 'cursor-examples/rules/1c-mcp-workflow.mdc'."""
    root = _get_cursor_docs_path()
    if not root:
        return "Cursor docs path not set. Set MCP_CURSOR_DOCS_PATH to repo docs/ (e.g. /app/docs in Docker)."
    path = (root / relative).resolve()
    if not path.is_file() or not path.is_relative_to(root.resolve()):
        return f"File not found: {relative}"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        return f"Read error: {safe_error_message(e)}"


def _get_help_path() -> Path:
    if _HELP_PATH is None:
        from ..shared import env_config

        return Path(env_config.get_help_path()).resolve()
    return _HELP_PATH


def _search(
    query: str,
    limit: int = 10,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    from ..search_store.indexer import search_index

    return search_index(query, limit=limit, version=version, language=language)


def _search_keyword(
    query: str,
    limit: int = 15,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    from ..search_store.indexer import search_index_keyword

    return search_index_keyword(query, limit=limit, version=version, language=language)


def _list_titles(limit: int = 100, path_prefix: str = "") -> list[dict[str, Any]]:
    from ..search_store.indexer import list_index_titles

    return list_index_titles(limit=limit, path_prefix=path_prefix or "")


def _index_status() -> dict[str, Any]:
    from ..search_store.indexer import get_index_status

    return get_index_status()


def _api_index_status() -> dict[str, Any]:
    from ..knowledge.help_structured import API_MEMBERS_COLLECTION_NAME
    from ..search_store.indexer import get_index_status

    return get_index_status(collection=API_MEMBERS_COLLECTION_NAME)


def _get_topic(
    topic_path: str,
    version: str | None = None,
    language: str | None = None,
    prefer_index: bool = True,
) -> str:
    from ..search_store.indexer import get_topic_content

    base = _get_help_path()
    return get_topic_content(
        base,
        topic_path,
        version=version,
        language=language,
        prefer_index=prefer_index,
    )


def _search_api_objects(
    query: str,
    limit: int = 10,
    version: str | None = None,
    language: str | None = None,
    query_vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    from ..knowledge.help_structured import search_api_objects

    return search_api_objects(
        query, limit=limit, version=version, language=language, query_vector=query_vector
    )


def _search_api_members(
    query: str,
    limit: int = 10,
    version: str | None = None,
    language: str | None = None,
    query_vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    from ..knowledge.help_structured import search_api_members

    return search_api_members(
        query, limit=limit, version=version, language=language, query_vector=query_vector
    )


def _get_api_object(
    name: str,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    from ..knowledge.help_structured import get_api_object

    return get_api_object(name, version=version, language=language)


def _get_api_member(
    name: str,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    from ..knowledge.help_structured import get_api_member

    return get_api_member(name, version=version, language=language)


def _search_official_examples(
    query: str,
    limit: int = 5,
    version: str | None = None,
    language: str | None = None,
    query_vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    from ..knowledge.help_structured import search_official_examples

    return search_official_examples(
        query, limit=limit, version=version, language=language, query_vector=query_vector
    )


def _search_api_topics(
    query: str,
    limit: int = 5,
    version: str | None = None,
    language: str | None = None,
    query_vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    from ..knowledge.help_structured import search_api_topics
    from ..shared.qdrant_errors import is_qdrant_unreachable_error

    try:
        return search_api_topics(
            query, limit=limit, version=version, language=language, query_vector=query_vector
        )
    except Exception as exc:
        if is_qdrant_unreachable_error(exc):
            return []
        raise


def _get_api_related(
    name: str,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    from ..knowledge.help_structured import get_api_related

    return get_api_related(name, version=version, language=language)


def _normalize_api_related_items(
    items: list[dict[str, Any]], *, max_items: int = 50
) -> list[dict[str, Any]]:
    """Dedupe see-also links and drop parser crumbs (e.g. ", метод")."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        target = str(item.get("target_name") or "").strip()
        if not target:
            continue
        if re.match(r"^,\s*(метод|свойство|конструктор)\b", target, flags=re.IGNORECASE):
            continue
        if target.startswith(",") and len(target) < 32:
            continue
        if len(target) <= 2 and not any(c.isalnum() for c in target):
            continue
        kind = str(item.get("link_kind") or "related")
        key = (target.lower(), kind.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= max_items:
            break
    return out


def _write_snippet_to_file(
    base_dir: Path,
    code_snippet: str,
    description: str = "",
    title: str = "Snippet",
) -> str | None:
    """Write snippet as .md with frontmatter to base_dir. Returns relative path or None."""
    safe = re.sub(r"[^\w\s\-]", "", title)
    safe = re.sub(r"\s+", "_", safe.strip()) or "snippet"
    safe = safe[:60]
    fname = f"{safe}_{int(time.time())}.md"
    out = base_dir / fname
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        t = title.replace("\n", " ").replace('"', "'")
        d = description.replace("\n", " ").replace('"', "'")
        content = f"""---
title: "{t}"
description: "{d}"
---

```bsl
{code_snippet}
```
"""
        out.write_text(content, encoding="utf-8")
        return fname
    except (OSError, ValueError):
        return None


def _path_parts(uri_or_path: str) -> tuple[str, ...]:
    """Extract path parts from URI or path string for structure parsing."""
    raw = uri_or_path.strip()
    if raw.startswith("file://"):
        from urllib.parse import unquote, urlparse

        parsed = urlparse(raw)
        path_str = unquote(parsed.path)
        if len(path_str) >= 3 and path_str[0] == "/" and path_str[2] == ":":
            path_str = path_str[1:]  # Windows: /C:/...
        raw = path_str
    # Normalize separators and split
    normalized = raw.replace("\\", "/").strip("/")
    return tuple(p for p in normalized.split("/") if p)


_CODE_BLOCK_RE = re.compile(r"```(\w*)\s*\n(.*?)```", re.DOTALL)


def _extract_code_blocks(md_text: str) -> list[str]:
    """Extract code blocks (bsl, 1c, or generic) from markdown."""
    blocks: list[str] = []
    for m in _CODE_BLOCK_RE.finditer(md_text):
        lang, code = m.group(1), m.group(2)
        if lang in ("", "bsl", "1c", "1s") or "bsl" in lang.lower():
            blocks.append(code.strip())
        elif not lang or lang in ("text", "plain"):
            blocks.append(code.strip())
        else:
            blocks.append(code.strip())
    return blocks


# Паттерн Тип.Метод для сохранения полной строки при извлечении токенов
_TYPE_METHOD_RE = re.compile(r"[А-Яа-яA-Za-z][А-Яа-яA-Za-z0-9]*\.[А-Яа-яA-Za-z][А-Яа-яA-Za-z0-9]*")


def _extract_keyword_tokens(query: str) -> list[str]:
    """Extract CamelCase/Cyrillic identifiers and Type.Method patterns for keyword search."""
    tokens: list[str] = []
    seen: set[str] = set()

    # 1. Type.Method целиком (HTTPСоединение.Получить, Запрос.ВыполнитьПакет)
    for m in _TYPE_METHOD_RE.finditer(query):
        s = m.group(0)
        if s not in seen and len(s) >= 5:
            tokens.append(s)
            seen.add(s.lower())

    # 2. Обычные CamelCase/кириллические идентификаторы (≥3 символа)
    for m in re.finditer(r"[А-Яа-яA-Za-z][А-Яа-яA-Za-z0-9]*", query):
        s = m.group(0)
        sl = s.lower()
        if len(s) >= 3 and sl not in seen:
            tokens.append(s)
            seen.add(sl)

    return tokens[:8]


def _looks_like_exact_api_query(query: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-zА-Яа-я_][\wА-Яа-я]*\.[\wА-Яа-я]+", (query or "").strip()))


def _result_path_stem(result: dict[str, Any]) -> str:
    path = (result.get("path") or "").strip().lower()
    if not path:
        return ""
    return Path(path).stem.lower()


def _match_priority(query_lower: str, title_lower: str, path_stem_lower: str = "") -> int:
    """Lower = better. 0=exact, 1=startswith, 2=contains, 3=no match."""
    candidates = [item for item in (title_lower, path_stem_lower) if item]
    if any(candidate == query_lower for candidate in candidates):
        return 0
    if any(
        candidate.startswith(query_lower + suffix)
        for candidate in candidates
        for suffix in (" (", " [", " —", ":")
    ):
        return 0
    if any(
        candidate.startswith(query_lower + suffix)
        for candidate in candidates
        for suffix in (" ", "(")
    ):
        return 1
    for candidate in candidates:
        if not candidate.startswith(query_lower):
            continue
        tail = candidate[len(query_lower) : len(query_lower) + 1]
        if tail and (tail.isalnum() or tail == "_"):
            return 2
        return 1
    if any(query_lower in candidate for candidate in candidates):
        return 2
    return 3


def _is_member_title(query_lower: str, title_lower: str) -> bool:
    """True if the title looks like 'Type.Name ...' (object property/method)."""
    idx = title_lower.find(query_lower)
    return idx > 0 and title_lower[idx - 1] == "."


def _member_sort_key(query_lower: str, title_lower: str) -> bool:
    is_member = _is_member_title(query_lower, title_lower)
    if "." in query_lower:
        return not is_member
    return is_member


def _rank_keyword_results(query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query_lower = (query or "").strip().lower()
    if not query_lower:
        return results
    indexed = list(enumerate(results))
    indexed.sort(
        key=lambda item: (
            _match_priority(
                query_lower,
                (item[1].get("title") or "").strip().lower(),
                _result_path_stem(item[1]),
            ),
            _member_sort_key(query_lower, (item[1].get("title") or "").strip().lower()),
            item[0],
        )
    )
    return [result for _, result in indexed]


# Порог score семантики: ниже — добавлять подсказку про keyword-поиск
_SEMANTIC_LOW_SCORE_THRESHOLD = 0.48


def _should_show_low_score_hint(
    results: list[dict[str, Any]],
    memory_parts: list[str],
    meta: dict[str, Any],
) -> bool:
    """True if we should suggest keyword search (low semantic relevance, no keyword hits)."""
    return (
        not meta.get("has_keyword_hits", False)
        and (meta.get("top_semantic_score") or 0) < _SEMANTIC_LOW_SCORE_THRESHOLD
        and bool(results or memory_parts)
    )


def _format_result_meta(r: dict[str, Any]) -> str:
    """Return compact metadata suffix for a search result: entity_type and top breadcrumb level."""
    parts: list[str] = []
    et = (r.get("entity_type") or "").strip()
    if et:
        parts.append(et)
    bc = r.get("breadcrumb")
    if bc and isinstance(bc, list) and len(bc) >= 2:
        # Show last 2 levels: e.g. "Объекты > HTTPСоединение"
        parts.append(" > ".join(str(x) for x in bc[-2:]))
    return f" [{', '.join(parts)}]" if parts else ""


def _memory_domain_label(domain: str) -> str:
    if domain == "snippets":
        return "пример"
    if domain == "community_help":
        return "инструкция"
    if domain == "standards":
        return "стандарт"
    return domain.strip()


def _compact_text(value: str, max_chars: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _compact_code(value: str, max_chars: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _format_memory_block(
    payload: dict[str, Any], *, compact: bool = False, include_code: bool = True
) -> str:
    """Format one memory item as markdown block; compact mode trims prose and omits code by default."""
    code = payload.get("code_snippet", "")
    instruction = payload.get("instruction", "")
    desc = payload.get("description", "") or (payload.get("summary", "") or "")[:200]
    title = payload.get("title", "") or desc[:60]
    d = payload.get("domain", "")
    label = _memory_domain_label(d)
    src = f" [{label}]" if label else ""
    body = instruction if instruction else desc
    detail_url = payload.get("detail_url")
    source_site = payload.get("source_site", "")
    source = payload.get("source", "")
    link_line = ""
    if detail_url:
        attr = (
            "FastCode"
            if source_site == "fastcode.im"
            else (
                "HelpF" + (f" ({source})" if source else "")
                if source_site == "helpf.pro"
                else "Источник"
            )
        )
        link_line = f"{attr}: {detail_url}"
    if compact:
        lines = [f"### {title}{src}"]
        if body:
            lines.append(_compact_text(body, 220))
        if include_code and code:
            lines.append(f"```bsl\n{_compact_code(code, 500)}\n```")
        if link_line:
            lines.append(link_line)
        return "\n\n".join(lines)
    block_base = f"### {title}{src}\n\n{body}"
    if include_code and code:
        block_base += f"\n\n```bsl\n{code}\n```"
    if link_line:
        block_base += f"\n\n{link_line}"
    return block_base


def _memory_matches_query(payload: dict[str, Any], query: str) -> bool:
    haystack = " ".join(
        str(payload.get(key, ""))
        for key in ("title", "description", "summary", "instruction", "code_snippet")
    ).lower()
    tokens = [token.lower() for token in _extract_keyword_tokens(query) if len(token) >= 4]
    if not tokens:
        return bool(haystack.strip())
    return any(token in haystack for token in tokens)


def _select_memory_for_code_answer(
    items: list[dict[str, Any]], query: str, has_help_results: bool
) -> list[dict[str, Any]]:
    ordered = _order_memory_for_display(
        items,
        max_standards=1 if has_help_results else 2,
        max_snippets=1 if has_help_results else 2,
        max_community=0 if has_help_results else 1,
        max_total=2 if has_help_results else 3,
    )
    matched = [item for item in ordered if _memory_matches_query(item.get("payload") or {}, query)]
    return matched or ([] if has_help_results else ordered[:2])


def _compact_help_block(
    result: dict[str, Any],
    content: str,
    *,
    code_only: bool,
    max_chars: int,
) -> str:
    title = (result.get("title") or result.get("path") or "Topic").strip()
    path = result.get("path", "")
    meta = _format_result_meta(result)
    header = f"### {title}{meta}"
    if path:
        header += f"\npath: {path}"
    if code_only:
        blocks = _extract_code_blocks(content)
        if blocks:
            code = "\n\n".join(f"```bsl\n{block}\n```" for block in blocks[:2])
            return f"{header}\n\n{code}"
    excerpt = content
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars].rstrip() + "\n\n..."
    return f"{header}\n\n{excerpt}"


def _compact_api_answer(result: dict[str, Any], content: str, *, max_chars: int = 1200) -> str:
    lines = [_compact_help_block(result, content, code_only=False, max_chars=max_chars)]
    blocks = _extract_code_blocks(content)
    if blocks:
        lines.append("#### Код")
        lines.append(f"```bsl\n{_compact_code(blocks[0], 700)}\n```")
    return "\n\n".join(lines)


def _structured_platform_version_key(version_str: str) -> tuple[int, ...]:
    """Ascending sort tiebreak: prefer newer ingested platform help version."""
    return tuple(-p for p in _version_sort_key(version_str))


def _structured_api_sort_key(
    query: str, item: dict[str, Any]
) -> tuple[int, int, bool, tuple[int, ...], str]:
    query_lower = (query or "").strip().lower()
    name_lower = str(item.get("name") or "").strip().lower()
    title_lower = str(item.get("title") or "").strip().lower()
    priority = _match_priority(query_lower, name_lower or title_lower, "")
    # If no name match, check if query appears in item content.
    # 0 = query/suffix in full_name (stronger), 1 = query in text/summary only, 2 = no match.
    content_no_match = 2
    if priority == 3 and query_lower:
        fn_lower = str(item.get("full_name") or "").lower()
        # Check direct substring and also suffixes (e.g. "вызватьисключение" → suffix "исключение")
        fn_match = query_lower in fn_lower
        if not fn_match and len(query_lower) > 6:
            for start in range(1, len(query_lower) - 5):
                sfx = query_lower[start:]
                if len(sfx) >= 6 and sfx in fn_lower:
                    fn_match = True
                    break
        if fn_match:
            content_no_match = 0
        else:
            rest = " ".join(
                [
                    str(item.get("summary") or ""),
                    str(item.get("text") or ""),
                ]
            ).lower()
            if query_lower in rest:
                content_no_match = 1
    return (
        priority,
        content_no_match,
        _member_sort_key(query_lower, name_lower or title_lower),
        _structured_platform_version_key(str(item.get("version") or "")),
        str(item.get("topic_path") or item.get("path") or ""),
    )


def _no_documented_api_member_message(name: str) -> str:
    """Exact member lookup is only against ingested platform help (no fuzzy fill-in)."""
    return (
        f"«{name}» нет в индексе справки платформы как метод или функция встроенного API "
        "(используется только точное совпадение с выгруженной справкой). "
        "Проверьте орфографию и полное имя Тип.Метод; прикладные символы в справку не входят. "
        "Поиск по смыслу по статьям API — search_1c_api."
    )


def _no_documented_api_answer_message(name: str) -> str:
    """Neither api_members nor api_objects (type) matched the exact name."""
    return (
        f"«{name}» нет в индексе справки платформы как тип, метод или функция встроенного API "
        "(точное совпадение с выгруженной structured help). "
        "Проверьте орфографию и полное имя Тип.Метод; прикладные символы в справку не входят. "
        "Поиск по смыслу — search_1c_api."
    )


def _no_documented_api_object_message(name: str) -> str:
    """Exact object/type lookup is only against ingested platform help."""
    return (
        f"«{name}» нет в индексе справки платформы как объект или тип встроенного API "
        "(точное совпадение имени в structured help). Проверьте написание; по смыслу — search_1c_api."
    )


def _format_structured_api_object(
    item: dict[str, Any],
    *,
    include_path: bool = True,
    include_rich_sections: bool = False,
) -> str:
    lines = [f"### {item.get('name') or item.get('title') or 'API'}"]
    if item.get("page_descriptor"):
        lines.append(str(item.get("page_descriptor")))
    meta: list[str] = []
    if item.get("kind"):
        meta.append(str(item.get("kind")))
    vs = item.get("versions")
    if isinstance(vs, list) and len(vs) > 1:
        meta.append(", ".join(str(v) for v in vs))
    elif item.get("version"):
        meta.append(str(item.get("version")))
    if item.get("entity_type") and item.get("entity_type") != item.get("kind"):
        meta.append(str(item.get("entity_type")))
    if meta:
        lines.append(f"[{', '.join(meta)}]")
    if include_path and item.get("topic_path"):
        lines.append(f"path: {item.get('topic_path')}")
    if item.get("summary"):
        lines.append(str(item.get("summary")))
    if include_rich_sections and item.get("description"):
        lines.append("#### Описание")
        lines.append(str(item.get("description")))
    source_sections = item.get("source_sections") or {}
    syntax_val = (
        str(item.get("syntax") or "").strip() or str(source_sections.get("syntax") or "").strip()
    )
    if syntax_val:
        lines.append("#### Синтаксис")
        lines.append(f"```text\n{syntax_val}\n```")
    params = item.get("params") or []
    if not params and source_sections.get("params"):
        raw_p = source_sections.get("params")
        if isinstance(raw_p, list):
            params = raw_p
        elif isinstance(raw_p, str) and raw_p.strip():
            from ..knowledge.help_structured import _parse_param_lines

            params = _parse_param_lines(raw_p)
    if params:
        lines.append("#### Параметры")
        for param in params[:10]:
            if isinstance(param, dict):
                p_name = param.get("name") or "—"
                p_type = param.get("type") or "—"
                lines.append(f"- **{p_name}** ({p_type})")
    returns_val = (
        str(item.get("returns") or "").strip() or str(source_sections.get("returns") or "").strip()
    )
    if returns_val:
        lines.append("#### Возвращаемое значение")
        lines.append(returns_val)
    if item.get("platform_since"):
        lines.append("#### Использование в версии")
        lines.append(str(item.get("platform_since")))
    if item.get("availability"):
        lines.append("#### Доступность")
        lines.append(str(item.get("availability")))
    if include_rich_sections and item.get("restrictions"):
        lines.append("#### Ограничения")
        lines.append(str(item.get("restrictions")))
    if include_rich_sections and item.get("notes"):
        lines.append("#### Примечание")
        lines.append(str(item.get("notes")))
    if include_rich_sections:
        for heading, label in (
            ("note", "Примечание"),
            ("fields", "Поля"),
            ("see_also", "См. также"),
            ("example", "Пример"),
        ):
            value = str(source_sections.get(heading) or "").strip()
            if value:
                lines.append(f"#### {label}")
                lines.append(value)
    return "\n\n".join(lines)


_QUESTION_VERSION_MARKERS = (
    "с какой версии",
    "начиная с какой версии",
    "в какой версии",
    "с версии",
    "когда появился",
    "когда доступен",
)
_QUESTION_EXAMPLE_MARKERS = (
    "пример",
    "как использовать",
    "как выполнить",
    "как получить",
    "как сделать",
)
_QUESTION_RESTRICTION_MARKERS = (
    "доступен ли",
    "можно ли",
    "ограничени",
    "только на сервере",
    "только на клиенте",
    "интерактивный ввод",
    "доступность",
)
_QUESTION_HEADINGS: dict[str, tuple[str, ...]] = {
    "version": ("Доступность", "Использование в версии", "Примечание", "Описание"),
    "restriction": ("Доступность", "Примечание", "Описание"),
    "example": ("Пример", "Описание"),
    "general": ("Описание", "Синтаксис", "Доступность", "Пример"),
}


def _classify_help_question(question: str) -> str:
    q = (question or "").strip().lower()
    if any(marker in q for marker in _QUESTION_VERSION_MARKERS):
        return "version"
    if any(marker in q for marker in _QUESTION_EXAMPLE_MARKERS):
        return "example"
    if any(marker in q for marker in _QUESTION_RESTRICTION_MARKERS):
        return "restriction"
    return "general"


def _extract_question_api_names(question: str) -> list[str]:
    tokens = _extract_keyword_tokens(question)
    extra = re.findall(
        r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9_]*(?:\.[A-Za-zА-Яа-яЁё0-9_]+)?",
        question or "",
    )
    seen: set[str] = set()
    out: list[str] = []
    for token in [*tokens, *extra]:
        value = token.strip()
        if len(value) < 3:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out[:8]


def _dedup_structured_hits(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in items:
        key = (
            str(item.get("full_name") or item.get("name") or item.get("title") or ""),
            str(item.get("version") or ""),
            str(item.get("topic_path") or item.get("path") or ""),
        )
        dedup[key] = item
    return list(dedup.values())


def _question_structured_sort_key(
    question: str,
    intent: str,
    item: dict[str, Any],
) -> tuple[int, int, int, bool, tuple[int, ...], str]:
    query = (question or "").strip()
    if intent == "version":
        has_fact = bool(item.get("platform_since") or item.get("availability"))
    elif intent == "restriction":
        has_fact = bool(item.get("availability"))
    else:
        has_fact = bool(item.get("summary"))
    # Try both full question and individual API name tokens — use the best (lowest) match.
    # Only use tokens that start with an uppercase letter (proper API names, not common words).
    api_tokens = [t for t in _extract_question_api_names(query) if t and t[0].isupper()]
    candidates_to_try = [query] + api_tokens
    best_priority = min(_structured_api_sort_key(t, item)[0] for t in candidates_to_try if t)
    item_name = str(item.get("name") or item.get("title") or "").lower()
    best_member = min(int(_member_sort_key(t.lower(), item_name)) for t in candidates_to_try if t)
    # For priority-3 items (no name match), check if query keywords appear in item content.
    # 0 = keyword in full_name (stronger signal), 1 = keyword in text/summary only, 2 = no match.
    content_no_match = 2
    if best_priority == 3:
        words = [w for w in re.split(r"\W+", query.lower()) if len(w) >= 6]
        if words:
            fn_lower = str(item.get("full_name") or "").lower()
            if any(w in fn_lower for w in words):
                content_no_match = 0
            else:
                rest = " ".join(
                    [
                        str(item.get("summary") or ""),
                        str(item.get("description") or ""),
                        str(item.get("text") or ""),
                    ]
                ).lower()
                if any(w in rest for w in words):
                    content_no_match = 1
    return (
        best_priority,
        content_no_match,
        best_member,
        not has_fact,
        _structured_platform_version_key(str(item.get("version") or "")),
        str(item.get("topic_path") or ""),
    )


def _search_help_question_candidates(
    question: str,
    *,
    version: str | None,
    language: str | None,
) -> list[dict[str, Any]]:
    names = _extract_question_api_names(question)
    items: list[dict[str, Any]] = []
    for name in names:
        items.extend(_get_api_member(name, version=version, language=language))
        items.extend(_get_api_object(name, version=version, language=language))
    items.extend(_search_api_members(question, limit=5, version=version, language=language))
    items.extend(_search_api_objects(question, limit=3, version=version, language=language))
    # Include general documentation topics so conceptual articles are reachable.
    items.extend(_search_api_topics(question, limit=4, version=version, language=language))
    return _dedup_structured_hits(items)


_DCS_HELP_ROUTE_MARKERS = (
    "скд",
    "системыкомпоновки",
    "компоновк",
    "схемакомпоновкиданных",
    "процессоркомпоновки",
    "процессорвывода",
    "наборданныхзапрос",
    "макеткомпоновки",
    "компоновщикмакета",
    "компоновщикнастроек",
)


def _question_needs_dcs_structured_route(question: str) -> bool:
    q = re.sub(r"\s+", "", (question or "").lower())
    return any(m in q for m in _DCS_HELP_ROUTE_MARKERS)


def _answer_help_via_dcs_structured_search(
    question_clean: str,
    *,
    version: str | None,
    language: str | None,
    detail: str,
) -> str | None:
    """Prefer structured API search for data composition (СКД) questions."""
    if not _question_needs_dcs_structured_route(question_clean):
        return None
    search_q = question_clean
    ql = question_clean.lower()
    if "скд" in ql and "компонов" not in ql:
        search_q = f"компоновка данных {question_clean}"
    routed = _dedup_structured_hits(
        sorted(
            _search_api_members(search_q, limit=10, version=version, language=language)
            + _search_api_objects(search_q, limit=6, version=version, language=language),
            key=lambda item: _structured_api_sort_key(search_q, item),
        )
    )
    if not routed:
        return None
    best = routed[0]
    fact = _extract_fact_from_structured(best, "general", detail=detail)
    if not fact:
        return None
    return _format_question_answer(
        question_clean,
        answer=fact,
        candidate=best,
    )


def _extract_markdown_heading_section(content: str, headings: tuple[str, ...]) -> str:
    if not content:
        return ""
    heading_pattern = "|".join(re.escape(h) for h in headings)
    pattern = re.compile(rf"(?ms)^#+\s*(?:{heading_pattern})\s*:?\s*$\n(.*?)(?=^#+\s|\Z)")
    chunks = [m.group(1).strip() for m in pattern.finditer(content) if m.group(1).strip()]
    if not chunks:
        return ""
    return "\n\n".join(chunks[:2]).strip()


def _extract_fact_from_topic(content: str, intent: str) -> str:
    section = _extract_markdown_heading_section(
        content, _QUESTION_HEADINGS.get(intent, _QUESTION_HEADINGS["general"])
    )
    if section:
        return section[:1600]
    compact = " ".join((content or "").split())
    if not compact:
        return ""
    return compact[:1200]


def _extract_fact_from_structured(
    item: dict[str, Any], intent: str, *, detail: str = "compact"
) -> str:
    source_sections = item.get("source_sections") or {}
    if intent == "example":
        return ""
    if intent == "version":
        for value in (
            item.get("platform_since"),
            source_sections.get("platform_since"),
            item.get("availability"),
            item.get("restrictions"),
            source_sections.get("availability"),
            item.get("notes"),
            source_sections.get("note"),
            item.get("description"),
        ):
            text = str(value or "").strip()
            if text:
                return text
        return ""
    if intent == "restriction":
        for value in (
            item.get("restrictions"),
            item.get("availability"),
            item.get("notes"),
            source_sections.get("note"),
            item.get("description"),
        ):
            text = str(value or "").strip()
            if text:
                return text
        return ""
    if detail == "full":
        return _format_structured_api_object(item, include_rich_sections=True)
    note_top = str(item.get("notes") or "").strip()
    note_src = str(source_sections.get("note") or "").strip()
    note_parts: list[str] = []
    if note_top:
        note_parts.append(note_top)
    if note_src and note_src != note_top:
        note_parts.append(note_src)
    note_block = "\n\n".join(note_parts).strip()
    parts = [
        str(item.get("summary") or "").strip(),
        str(item.get("description") or "").strip(),
        str(item.get("returns") or "").strip(),
        str(item.get("platform_since") or "").strip(),
        str(item.get("page_descriptor") or "").strip(),
        str(item.get("availability") or "").strip(),
        str(item.get("restrictions") or "").strip(),
    ]
    if note_block:
        parts.append(f"Примечание:\n{note_block}")
    text = "\n\n".join(part for part in parts if part).strip()
    return text[:1600] if text else ""


def _format_question_answer(
    question: str,
    *,
    answer: str,
    candidate: dict[str, Any] | None = None,
) -> str:
    lines = [f"Вопрос: {question}", "", f"Ответ: {answer.strip()}"]
    if candidate:
        api_name = candidate.get("full_name") or candidate.get("name") or candidate.get("title")
        if api_name:
            lines.append(f"API: {api_name}")
        meta: list[str] = []
        cvs = candidate.get("versions")
        if isinstance(cvs, list) and len(cvs) > 1:
            meta.append(", ".join(str(v) for v in cvs))
        elif candidate.get("version"):
            meta.append(str(candidate.get("version")))
        if candidate.get("topic_path"):
            meta.append(f"path: {candidate.get('topic_path')}")
        if meta:
            lines.append("Источник: " + " | ".join(meta))
    return "\n".join(lines)


def _summarize_diagnostics_json(diagnostics_json: str | None) -> str:
    if not diagnostics_json:
        return ""
    try:
        payload = json.loads(diagnostics_json)
    except Exception:
        return ""
    items = (
        payload
        if isinstance(payload, list)
        else payload.get("diagnostics", [])
        if isinstance(payload, dict)
        else []
    )
    if not isinstance(items, list):
        return ""
    errors = 0
    warnings = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "")).lower()
        code = str(item.get("code", "")).lower()
        if severity in {"1", "error"} or "error" in code:
            errors += 1
        elif severity in {"2", "warning"} or "warn" in code:
            warnings += 1
    if not (errors or warnings):
        return ""
    return f"errors: {errors}, warnings: {warnings}"


def _order_memory_for_display(
    items: list[dict[str, Any]],
    max_standards: int = 2,
    max_snippets: int = 2,
    max_community: int = 1,
    max_total: int = 6,
) -> list[dict[str, Any]]:
    """Reorder memory search results so standards and snippets appear first when available."""
    by_domain: dict[str, list[dict[str, Any]]] = {
        "standards": [],
        "snippets": [],
        "community_help": [],
        "": [],
    }
    for m in items:
        d = ((m.get("payload") or {}).get("domain") or "").strip()
        if d not in by_domain:
            by_domain[d] = []
        by_domain[d].append(m)
    out: list[dict[str, Any]] = []
    out.extend(by_domain.get("standards", [])[:max_standards])
    out.extend(by_domain.get("snippets", [])[:max_snippets])
    out.extend(by_domain.get("community_help", [])[:max_community])
    seen_ids: set[tuple[str, str]] = set()
    for x in out:
        p = x.get("payload") or {}
        key = (p.get("title") or (p.get("description") or "")[:80], p.get("domain", ""))
        seen_ids.add(key)
    for m in items:
        if len(out) >= max_total:
            break
        p = m.get("payload") or {}
        key = (p.get("title") or (p.get("description") or "")[:80], p.get("domain", ""))
        if key not in seen_ids:
            seen_ids.add(key)
            out.append(m)
    return out[:max_total]


_RRF_K = 60  # Reciprocal Rank Fusion constant


def _hybrid_search(
    query: str,
    limit: int = 10,
    version: str | None = None,
    language: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Semantic + keyword search merged with RRF (Reciprocal Rank Fusion).
    Returns (results, metadata) where metadata has: has_keyword_hits, top_semantic_score."""
    # Semantic list
    semantic_list = _search(query, limit=limit * 2, version=version, language=language)
    top_semantic_score = 0.0
    for r in semantic_list:
        sc = r.get("score")
        if sc is not None and isinstance(sc, (int, float)):
            top_semantic_score = max(top_semantic_score, float(sc))

    # Keyword list (merged from tokens, dedup by path, first occurrence wins)
    keyword_seen: set[str] = set()
    keyword_list: list[dict[str, Any]] = []
    for token in _extract_keyword_tokens(query):
        for r in _search_keyword(token, limit=5, version=version, language=language):
            p = r.get("path", "")
            if p and p not in keyword_seen:
                keyword_seen.add(p)
                keyword_list.append(r)
    has_keyword_hits = bool(keyword_list)

    # RRF: score = sum 1/(k + rank) over lists where doc appears
    rrf_scores: dict[str, float] = {}
    path_to_doc: dict[str, dict[str, Any]] = {}

    for rank, r in enumerate(semantic_list, 1):
        p = r.get("path", "")
        if p:
            rrf_scores[p] = rrf_scores.get(p, 0) + 1 / (_RRF_K + rank)
            path_to_doc[p] = r

    for rank, r in enumerate(keyword_list, 1):
        p = r.get("path", "")
        if p:
            rrf_scores[p] = rrf_scores.get(p, 0) + 1 / (_RRF_K + rank)
            path_to_doc[p] = r  # keyword overwrites if same path (prefer keyword payload)

    results = sorted(
        path_to_doc.values(),
        key=lambda x: -rrf_scores.get(x.get("path", ""), 0),
    )[:limit]
    meta = {
        "has_keyword_hits": has_keyword_hits,
        "top_semantic_score": top_semantic_score,
    }
    return (results, meta)


def _mcp_error_to_redis_callback(error: Exception, context: Any) -> None:
    """Record MCP errors (transport/protocol, not tool-level) to Redis for dashboard.
    Tool-level errors are already recorded by _record_mcp_tool."""
    method = getattr(context, "method", None) or "_request"
    if method == "tools/call":
        return  # tool handler already recorded via decorator
    try:
        from ..runtime import redis_cache

        redis_cache.mcp_request_record(
            tool_name=method[:64],
            success=False,
            error_msg=safe_error_message(error),
        )
    except Exception:
        pass


def _build_mcp_app(help_path: Path) -> Any:
    """Build FastMCP app with all tools registered. Used by run_mcp and by tests (in-memory client)."""
    global _HELP_PATH
    _HELP_PATH = help_path.resolve()

    if not _HAS_FASTMCP:
        raise RuntimeError("fastmcp required: pip install fastmcp")

    # Raise anyio default thread pool capacity so FastMCP can dispatch many sync tools concurrently.
    # Default is 40, which becomes the bottleneck for 1000+ agents.
    try:
        from anyio import to_thread as _anyio_to_thread

        _anyio_to_thread.current_default_thread_limiter().total_tokens = 500
    except Exception:
        pass  # anyio not available in test context or API differs — not fatal

    mcp = FastMCP("1C Help")
    if _HAS_ERROR_MIDDLEWARE and ErrorHandlingMiddleware is not None:
        mcp.add_middleware(ErrorHandlingMiddleware(error_callback=_mcp_error_to_redis_callback))

    @mcp.tool()
    @_record_mcp_tool
    def search_1c_api(
        query: str,
        limit: int = 10,
        version: str | None = None,
        language: str | None = None,
        include_examples: bool = True,
    ) -> str:
        """Search structured 1C platform help across API members, objects and official examples.
        Use for exact API names, synonyms and natural-language API lookup without topic-layer fallback."""
        err = _check_rate_limit()
        if err:
            return err
        q = (query or "").strip()
        if not q:
            return "Provide query, for example HTTPСоединение.Получить or интерактивный ввод криптографии."
        q, err = _truncate_if_needed(q, MAX_QUERY_CHARS, "query")
        if err:
            return err

        from ..knowledge.help_structured import API_MEMBERS_COLLECTION_NAME
        from ..search_store import embedding
        from ..search_store.indexer import get_collection_vector_size

        _coll_dim = get_collection_vector_size(collection=API_MEMBERS_COLLECTION_NAME)
        _qv = embedding.get_embedding(
            q, target_dimension=_coll_dim if _coll_dim is not None else None
        )

        members = sorted(
            _search_api_members(
                q,
                limit=max(limit, 5),
                version=version,
                language=language,
                query_vector=_qv,
            ),
            key=lambda item: _structured_api_sort_key(q, item),
        )
        objects = sorted(
            _search_api_objects(
                q,
                limit=max(4, limit // 2),
                version=version,
                language=language,
                query_vector=_qv,
            ),
            key=lambda item: _structured_api_sort_key(q, item),
        )
        examples = (
            _search_official_examples(
                q,
                limit=max(2, min(limit, 4)),
                version=version,
                language=language,
                query_vector=_qv,
            )
            if include_examples
            else []
        )

        sections: list[str] = []
        if members:
            lines = []
            for idx, item in enumerate(members[:limit], 1):
                meta = _format_result_meta(
                    {
                        "entity_type": item.get("entity_type") or item.get("kind"),
                        "breadcrumb": item.get("breadcrumb") or [],
                    }
                )
                lines.append(
                    f"{idx}. **{item.get('full_name') or item.get('name') or item.get('title') or ''}**{meta}"
                )
                summary = str(item.get("summary") or item.get("description") or "").strip()
                if summary:
                    lines.append(f"   {summary[: _snippet_max_chars()]}...")
            sections.append("## API members\n" + "\n".join(lines))
        if objects:
            lines = []
            for idx, item in enumerate(objects[: max(3, min(limit, 6))], 1):
                meta = _format_result_meta(
                    {
                        "entity_type": item.get("entity_type") or item.get("kind"),
                        "breadcrumb": item.get("breadcrumb") or [],
                    }
                )
                lines.append(f"{idx}. **{item.get('name') or item.get('title') or ''}**{meta}")
                summary = str(item.get("summary") or item.get("description") or "").strip()
                if summary:
                    lines.append(f"   {summary[: _snippet_max_chars()]}...")
            sections.append("## API objects\n" + "\n".join(lines))
        if examples:
            lines = []
            for idx, item in enumerate(examples[: max(2, min(limit, 4))], 1):
                title = item.get("title") or item.get("api_name") or "Example"
                lines.append(f"{idx}. **{title}**")
                description = str(item.get("description") or "").strip()
                if description:
                    lines.append(f"   {description[: _snippet_max_chars()]}...")
            sections.append("## Official examples\n" + "\n".join(lines))
        if not sections:
            return "No structured API results found. Rebuild structured help index or уточните запрос/version."
        return "\n\n".join(sections)

    @mcp.tool()
    @_record_mcp_tool
    def get_1c_api_answer(
        name: str,
        version: str | None = None,
        language: str | None = None,
        detail: str = "compact",
    ) -> str:
        """Compact answer for a 1C API/function/method from structured help (exact name in index only).
        Use for exact API names like HTTPСоединение.Получить or Формат.
        detail: compact (default) or full."""
        err = _check_rate_limit()
        if err:
            return err
        name_clean, err = _truncate_if_needed((name or "").strip(), MAX_QUERY_CHARS, "name")
        if err:
            return err
        if not name_clean:
            return "Provide API name, for example HTTPСоединение.Получить."
        structured = _get_api_member(name_clean, version=version, language=language)
        structured = sorted(structured, key=lambda item: _structured_api_sort_key(name_clean, item))
        if not structured:
            structured = _get_api_object(name_clean, version=version, language=language)
            structured = sorted(
                structured, key=lambda item: _structured_api_sort_key(name_clean, item)
            )
        if structured:
            best_item = structured[0]
            if detail == "full" and best_item.get("topic_path"):
                return _format_structured_api_object(best_item, include_rich_sections=True)
            return _format_structured_api_object(best_item, include_rich_sections=detail == "full")
        return _no_documented_api_answer_message(name_clean)

    @mcp.tool()
    @_record_mcp_tool
    def get_1c_api_object(
        name: str,
        version: str | None = None,
        language: str | None = None,
    ) -> str:
        """Structured API object/type from onec_help_api_objects (exact name match to ingested help only)."""
        err = _check_rate_limit()
        if err:
            return err
        name_clean, err = _truncate_if_needed((name or "").strip(), MAX_QUERY_CHARS, "name")
        if err:
            return err
        if not name_clean:
            return "Provide API name, for example HTTPСоединение.Получить."
        structured = _get_api_object(name_clean, version=version, language=language)
        structured = sorted(structured, key=lambda item: _structured_api_sort_key(name_clean, item))
        if not structured:
            return _no_documented_api_object_message(name_clean)
        return _format_structured_api_object(structured[0])

    @mcp.tool()
    @_record_mcp_tool
    def get_1c_api_related(
        name: str,
        version: str | None = None,
        language: str | None = None,
    ) -> str:
        """Get related API names (currently see-also links) for one API member or object."""
        err = _check_rate_limit()
        if err:
            return err
        name_clean, err = _truncate_if_needed((name or "").strip(), MAX_QUERY_CHARS, "name")
        if err:
            return err
        if not name_clean:
            return "Provide API name, for example HTTPСоединение.Получить."
        related = _normalize_api_related_items(
            _get_api_related(name_clean, version=version, language=language)
        )
        if not related:
            return f"No related API links found for «{name_clean}»."
        lines = [f"Related API for **{name_clean}**:"]
        for idx, item in enumerate(related, 1):
            target = item.get("target_name") or "—"
            kind = item.get("link_kind") or "related"
            path = item.get("topic_path") or ""
            lines.append(f"{idx}. **{target}** [{kind}] (path: {path})")
        return "\n".join(lines)

    @mcp.tool()
    @_record_mcp_tool
    def answer_1c_help_question(
        question: str,
        version: str | None = None,
        language: str | None = None,
        detail: str = "compact",
    ) -> str:
        """Answer a natural-language question against 1C platform help.
        Use for questions like 'с какой версии доступно', 'можно ли использовать', 'покажи пример'.
        For exact API names, get_1c_api_answer(name) is still faster."""
        err = _check_rate_limit()
        if err:
            return err
        question_clean, err = _truncate_if_needed(
            (question or "").strip(), MAX_QUERY_CHARS, "question"
        )
        if err:
            return err
        if not question_clean:
            return "Provide a question, for example: с какой версии доступен метод HTTPСоединение.Получить."

        intent = _classify_help_question(question_clean)
        if intent == "example":
            examples = _search_official_examples(
                question_clean,
                limit=3,
                version=version,
                language=language,
            )
            if examples:
                best = examples[0]
                description = str(best.get("description") or "").strip()
                code_raw = str(best.get("code") or "").strip()
                if len(code_raw) >= 5:
                    code = _compact_code(code_raw, 1200)
                    answer = description or "Найден официальный пример."
                    return _format_question_answer(
                        question_clean,
                        answer=f"{answer}\n\n```bsl\n{code}\n```",
                        candidate={
                            "full_name": best.get("full_name")
                            or best.get("api_name")
                            or best.get("title"),
                            "version": best.get("version"),
                            "topic_path": best.get("topic_path"),
                        },
                    )

        dcs_answer = _answer_help_via_dcs_structured_search(
            question_clean,
            version=version,
            language=language,
            detail=detail,
        )
        if dcs_answer:
            return dcs_answer

        candidates = sorted(
            _search_help_question_candidates(
                question_clean,
                version=version,
                language=language,
            ),
            key=lambda item: _question_structured_sort_key(question_clean, intent, item),
        )
        if candidates:
            best = candidates[0]
            best_sort = _question_structured_sort_key(question_clean, intent, best)
            # Reject only pure semantic hits with no name match and no content keyword match.
            # best_sort = (priority, content_no_match, member, no_fact, path)
            # content_no_match: 0=in full_name, 1=in text/summary, 2=no match at all
            pure_noise = best_sort[0] >= 3 and best_sort[1] >= 2
            if not pure_noise:
                fact = _extract_fact_from_structured(best, intent, detail=detail)
                if fact:
                    return _format_question_answer(
                        question_clean,
                        answer=fact,
                        candidate=best,
                    )

        return (
            "Не удалось уверенно ответить по structured help layer. "
            "Уточните API-имя или передайте version, например 8.3.27.1859."
        )

    def _search_memory_blocks(
        query: str,
        *,
        limit: int,
        domains: str | None = None,
        title: str = "## Память",
        include_code: bool = False,
    ) -> str:
        q, err = _truncate_if_needed(query or "", MAX_QUERY_CHARS, "query")
        if err:
            return err
        try:
            from ..knowledge.memory import get_memory_store

            store = get_memory_store()
            fetch = max(limit * 2, 10)
            all_items: list[dict[str, Any]] = []
            if domains:
                domain_list = [s.strip() for s in domains.split(",") if s.strip()]
                if domain_list:
                    per_domain = max(2, (fetch + len(domain_list) - 1) // len(domain_list))
                    for domain in domain_list:
                        all_items.extend(store.search_long(q, limit=per_domain, domain=domain))
                else:
                    all_items = store.search_long(q, limit=fetch)
            else:
                all_items = store.search_long(q, limit=fetch)

            seen: set[tuple[str, str]] = set()
            unique: list[dict[str, Any]] = []
            for item in all_items:
                payload = item.get("payload") or {}
                key = (
                    str(payload.get("title") or (payload.get("description") or "")[:80]),
                    str(payload.get("domain") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                unique.append(item)

            ordered = _order_memory_for_display(
                unique,
                max_standards=max(2, limit // 2),
                max_snippets=max(2, limit // 2),
                max_community=max(1, limit // 3),
                max_total=limit,
            )
            blocks = [
                _format_memory_block(
                    item.get("payload") or {},
                    compact=True,
                    include_code=include_code,
                )
                for item in ordered
            ]
            if not blocks:
                return (
                    "Ничего не найдено в памяти. Выполните load-snippets и load-standards; "
                    "проверьте get_1c_help_index_status (коллекция onec_help_memory)."
                )
            return title + "\n\n" + "\n\n".join(blocks)
        except Exception as e:
            logging.getLogger(__name__).debug("search memory helper failed: %s", e)
            return "Ошибка поиска по памяти."

    @mcp.tool()
    @_record_mcp_tool
    def search_1c_standards(query: str, limit: int = 5) -> str:
        """Search only standards in memory (v8std, v8-code-style, ITS articles loaded into memory)."""
        err = _check_rate_limit()
        if err:
            return err
        return _search_memory_blocks(
            query,
            limit=limit,
            domains="standards",
            title="## Стандарты",
            include_code=False,
        )

    @mcp.tool()
    @_record_mcp_tool
    def search_1c_snippets(query: str, limit: int = 5) -> str:
        """Search only code snippets/examples in memory."""
        err = _check_rate_limit()
        if err:
            return err
        return _search_memory_blocks(
            query,
            limit=limit,
            domains="snippets,community_help",
            title="## Сниппеты",
            include_code=True,
        )

    @mcp.tool()
    @_record_mcp_tool
    def save_1c_snippet(
        code_snippet: str,
        description: str = "",
        title: str = "",
        write_to_files: bool | None = None,
    ) -> str:
        """Save a 1C code snippet to user memory for future context.
        code_snippet: the code to remember. description: short explanation. title: optional short label for search.
        write_to_files: if True, also write to SNIPPETS_DIR as .md (default: SAVE_SNIPPET_TO_FILES env).
        Note: snippet becomes searchable via search_1c_snippets / search_1c_standards after memory flush (usually within seconds when MEMORY_ENABLED=1)."""
        err = _check_rate_limit()
        if err:
            return err
        cs, err = _truncate_if_needed(code_snippet or "", MAX_CODE_SNIPPET_CHARS, "code_snippet")
        if err:
            return err
        if not (cs or "").strip():
            return "Provide a non-empty code_snippet."
        try:
            from ..knowledge.memory import get_memory_store
            from ..shared import env_config

            payload: dict[str, Any] = {
                "code_snippet": cs,
                "description": description,
            }
            if title:
                payload["title"] = title
            get_memory_store().write_event(
                "save_snippet",
                payload,
            )
            result = "Snippet saved to memory."

            do_write_files = write_to_files
            if do_write_files is None:
                do_write_files = env_config.get_save_snippet_to_files()
            if do_write_files:
                snippets_dir = env_config.get_snippets_dir()
                if snippets_dir:
                    out_path = _write_snippet_to_file(
                        Path(snippets_dir),
                        code_snippet=cs,
                        description=description,
                        title=title or "Snippet",
                    )
                    if out_path:
                        result = f"Snippet saved to memory and to {out_path}."
                    else:
                        result = (
                            "Snippet saved to memory. Could not write to SNIPPETS_DIR "
                            f"({mask_path_for_log(snippets_dir)})."
                        )
                else:
                    result = "Snippet saved to memory. SNIPPETS_DIR not set — skip file write."
            return result
        except Exception as e:
            return f"Failed to save: {safe_error_message(e)}"

    @mcp.tool()
    @_record_mcp_tool
    def get_form_metadata(xml_content: str) -> str:
        """Parse Form.xml content and return attributes and commands.
        xml_content: raw XML of Form.xml — must be complete with all xmlns declarations
        (v8, cfg, xs, etc.). Parser expects elements with local names Attribute (form attributes)
        and Command (form commands); other formats (e.g. FormAttribute only) may yield empty lists."""
        err = _check_rate_limit()
        if err:
            return err
        xc, err = _truncate_if_needed(xml_content or "", MAX_QUERY_CHARS, "xml_content")
        if err:
            return err
        from ..knowledge.form_metadata import parse_form_xml

        data = parse_form_xml(xc)
        err = data.get("error")
        if err:
            return f"Parse error: {err}"
        lines = ["**Attributes:**"]
        for a in data.get("attributes", []):
            lines.append(f"- {a.get('name', '')}: {a.get('type', '')}")
        lines.append("\n**Commands:**")
        for c in data.get("commands", []):
            lines.append(f"- {c.get('name', '')} → {c.get('action', '')}")
        return "\n".join(lines) if lines else "No attributes or commands found."

    @mcp.tool()
    @_record_mcp_tool
    def get_module_info(uri_or_path: str) -> str:
        """Infer module type and context from file path.
        uri_or_path: path or file URI to Module.bsl / ObjectModule.bsl.
        Returns: module_type (FormModule|ObjectModule|...), form_name, object_name if detectable."""
        parts = _path_parts(uri_or_path)
        name = parts[-1] if parts else ""
        _MODULE_NAMES = {
            "ObjectModule.bsl": "ObjectModule",
            "Module.bsl": "FormModule",
            "ManagerModule.bsl": "ManagerModule",
            "RecordSetModule.bsl": "RecordSetModule",
            "CommonModule.bsl": "CommonModule",
            "ManagedApplicationModule.bsl": "ManagedApplicationModule",
            "OrdinaryApplicationModule.bsl": "OrdinaryApplicationModule",
            "SessionModule.bsl": "SessionModule",
            "ExternalConnectionModule.bsl": "ExternalConnectionModule",
            "CommandModule.bsl": "CommandModule",
            "HTTPServiceModule.bsl": "HTTPServiceModule",
            "WSDLModule.bsl": "WSDLModule",
        }
        module_type = _MODULE_NAMES.get(name, "Unknown")
        form_name = ""
        object_name = ""
        if "Forms" in parts:
            idx = parts.index("Forms")
            if idx + 1 < len(parts):
                form_name = parts[idx + 1]
            if module_type == "Unknown":
                module_type = "FormModule"
        _OBJ_TYPES = (
            "Catalogs",
            "Documents",
            "DataProcessors",
            "Reports",
            "CommonModules",
            "ExchangePlans",
            "InformationRegisters",
            "AccumulationRegisters",
            "AccountingRegisters",
            "CalculationRegisters",
            "BusinessProcesses",
            "Tasks",
            "ChartsOfCharacteristicTypes",
            "ChartsOfAccounts",
            "ChartsOfCalculationTypes",
            "Constants",
            "Enumerations",
            "SettingsStorages",
            "Subsystems",
            "Sequences",
            "ScheduledJobs",
            "WebServices",
            "HTTPServices",
            "ExternalDataSources",
        )
        for obj_type in _OBJ_TYPES:
            if obj_type in parts:
                idx = parts.index(obj_type)
                if idx + 1 < len(parts):
                    object_name = parts[idx + 1]
                break
        if name == "ObjectModule.bsl":
            module_type = "ObjectModule"
        lines = [f"**Module type:** {module_type}"]
        if form_name:
            lines.append(f"**Form:** {form_name}")
        if object_name:
            lines.append(f"**Object:** {object_name}")
        return "\n".join(lines)

    def _search_metadata_across_versions(
        query: str,
        *,
        config_version: str | None,
        object_type: str | None,
        limit: int,
        search_fn: Any,
    ) -> tuple[list[dict[str, Any]], str | None]:
        from ..knowledge.metadata_graph import get_metadata_config_versions

        cfg_ver = (config_version or "").strip()
        if cfg_ver:
            return search_fn(
                query,
                type_filter=object_type,
                config_version=cfg_ver,
                limit=limit,
            ), cfg_ver
        versions = get_metadata_config_versions()
        if not versions:
            return [], None
        if len(versions) == 1:
            only_version = versions[0]
            return search_fn(
                query,
                type_filter=object_type,
                config_version=only_version,
                limit=limit,
            ), only_version
        per_ver = max(1, (limit + len(versions) - 1) // len(versions))
        items: list[dict[str, Any]] = []
        query_vector: list[float] | None = None
        if (
            getattr(search_fn, "__name__", "") == "search_metadata_semantic"
            and (query or "").strip()
        ):
            try:
                from ..search_store import embedding
                from ..search_store.indexer import get_collection_vector_size
                from ..shared import env_config

                coll_dim = get_collection_vector_size(
                    collection="onec_config_metadata",
                    qdrant_host=env_config.get_qdrant_host(),
                    qdrant_port=env_config.get_qdrant_port(),
                )
                if coll_dim is not None:
                    query_vector = embedding.get_embedding(
                        (query or "").strip(),
                        target_dimension=coll_dim,
                    )
            except Exception:
                query_vector = None
        for ver in versions:
            kwargs: dict[str, Any] = {
                "type_filter": object_type,
                "config_version": ver,
                "limit": per_ver,
            }
            if query_vector is not None:
                kwargs["query_vector"] = query_vector
            items.extend(search_fn(query, **kwargs))
        return items[:limit], None

    def _format_metadata_results(
        items: list[dict[str, Any]], *, default_version: str | None = None
    ) -> str:
        lines: list[str] = []
        for i, obj in enumerate(items, 1):
            ot = obj.get("object_type", "")
            name = obj.get("name", "")
            full = obj.get("full_name") or ""
            oid = obj.get("id", "")
            path = obj.get("path", "")
            ver = obj.get("config_version") or default_version or ""
            line = f"{i}. **{ot} {name}**"
            if full:
                line += f" — {full}"
            if oid:
                line += f" (id: `{oid}`)"
            if path:
                line += f" — `{path}`"
            if ver:
                line += f" (config_version: `{ver}`)"
            lines.append(line)
        return "\n".join(lines)

    @mcp.tool()
    @_record_mcp_tool
    def search_1c_metadata_exact(
        query: str,
        config_version: str | None = None,
        object_type: str | None = None,
        limit: int = 20,
    ) -> str:
        """Exact-first metadata lookup by id/name/full_name/path.
        Index id uses EnglishType.Name (e.g. Document.РеализацияТоваровУслуг) — KD2/Qdrant payload id, not query language.
        Normalizes dotted BSL/query-like strings; segments after the configuration object name are ignored for graph lookup.
        Disambiguate same name across types with object_type. Manager methods/properties: get_1c_api_object with templates
        in onec_help.knowledge.platform_help_manager_templates (synced to structured help api_objects). Root: get_1c_api_answer("Глобальный контекст.Метаданные")."""
        err = _check_rate_limit()
        if err:
            return err
        q, err = _truncate_if_needed(query or "", MAX_QUERY_CHARS, "query")
        if err:
            return err
        if not q.strip():
            return "Provide a non-empty query (object id, name, path, or synonym)."
        try:
            from ..knowledge.metadata_graph import search_metadata_exact
        except Exception as e:  # pragma: no cover - import/runtime guard
            return f"Metadata graph module is not available: {safe_error_message(e)}"
        items, resolved_version = _search_metadata_across_versions(
            q,
            config_version=config_version,
            object_type=object_type,
            limit=limit,
            search_fn=search_metadata_exact,
        )
        if not items:
            return (
                "No exact metadata objects found. "
                "Use search_1c_metadata_semantic for natural-language search or verify config_version."
            )
        return _format_metadata_results(items[:limit], default_version=resolved_version)

    @mcp.tool()
    @_record_mcp_tool
    def search_1c_metadata_semantic(
        query: str,
        config_version: str | None = None,
        object_type: str | None = None,
        limit: int = 20,
    ) -> str:
        """Semantic metadata lookup for natural-language queries.
        Pass object_type (e.g. Document, Catalog) to narrow results. For object names or Type.Name (or dotted Russian/English metadata paths), exact matches are prepended before vector search."""
        err = _check_rate_limit()
        if err:
            return err
        q, err = _truncate_if_needed(query or "", MAX_QUERY_CHARS, "query")
        if err:
            return err
        if not q.strip():
            return "Provide a non-empty natural-language query for metadata search."
        try:
            from ..knowledge.metadata_graph import search_metadata_semantic
        except Exception as e:  # pragma: no cover - import/runtime guard
            return f"Metadata graph module is not available: {safe_error_message(e)}"
        items, resolved_version = _search_metadata_across_versions(
            q,
            config_version=config_version,
            object_type=object_type,
            limit=limit,
            search_fn=search_metadata_semantic,
        )
        if not items:
            return (
                "No semantic metadata objects found. "
                "Ensure metadata-graph-build was run or try search_1c_metadata_exact."
            )
        return _format_metadata_results(items[:limit], default_version=resolved_version)

    @mcp.tool()
    @_record_mcp_tool
    def search_1c_metadata_fields(
        object_query: str,
        field_query: str,
        config_version: str | None = None,
        object_type: str | None = None,
        limit: int = 10,
        exact_object_first: bool = True,
    ) -> str:
        """Search fields inside matched metadata objects: requisites, register dimensions/resources,
        standard properties, tabular section columns, commands. field_query matches field name or synonym."""
        err = _check_rate_limit()
        if err:
            return err
        object_query, err = _truncate_if_needed(object_query or "", MAX_QUERY_CHARS, "object_query")
        if err:
            return err
        field_query, err = _truncate_if_needed(field_query or "", MAX_QUERY_CHARS, "field_query")
        if err:
            return err
        try:
            from ..knowledge.metadata_graph import (
                get_metadata_config_versions,
                search_metadata_fields,
            )
        except Exception as e:  # pragma: no cover - import/runtime guard
            return f"Metadata graph module is not available: {safe_error_message(e)}"

        versions: list[str] = []
        cfg_ver = (config_version or "").strip()
        if cfg_ver:
            versions = [cfg_ver]
        else:
            versions = get_metadata_config_versions()
            if not versions:
                return "Metadata graph is empty. Run metadata-graph-build for your config export first."
        items: list[dict[str, Any]] = []
        per_ver = max(1, (limit + len(versions) - 1) // len(versions))
        for version_item in versions:
            items.extend(
                search_metadata_fields(
                    object_query,
                    field_query,
                    config_version=version_item,
                    type_filter=object_type,
                    limit=per_ver,
                    exact_object_first=exact_object_first,
                )
            )
        if not items:
            return (
                "No metadata fields found. Verify object name/config_version or try search_1c_metadata_semantic "
                "to find the object first."
            )
        lines = []
        for idx, item in enumerate(items[:limit], 1):
            line = (
                f"{idx}. **{item.get('field_name', '')}**"
                f" — {item.get('field_group', '')}"
                f" in **{item.get('object_type', '')} {item.get('object_name', '')}**"
            )
            field_synonym = item.get("field_synonym") or ""
            field_type = item.get("field_type") or ""
            if field_synonym:
                line += f" — {field_synonym}"
            if field_type:
                line += f" — {field_type}"
            ts = item.get("field_tabular_section") or ""
            if ts:
                line += f" [ТЧ: `{ts}`]"
            object_id = item.get("object_id") or ""
            if object_id:
                line += f" (object_id: `{object_id}`)"
            cfg = item.get("config_version") or ""
            if cfg:
                line += f" (config_version: `{cfg}`)"
            lines.append(line)
        return "\n".join(lines)

    @mcp.tool()
    @_record_mcp_tool
    def get_1c_metadata_object(
        object_id: str,
        config_version: str | None = None,
    ) -> str:
        """Get detailed info about a single configuration object from metadata graph.

        object_id: identifier from search_1c_metadata_exact/search_1c_metadata_semantic (payload.id, e.g. 'Document.РеализацияТоваровУслуг'). Legacy 'Type/Name' is accepted until reindex.
        config_version: optional filter (e.g. '3.0.184.16'). If omitted, returns first match across all loaded configs.
        """
        err = _check_rate_limit()
        if err:
            return err
        if not object_id or not object_id.strip():
            return "Provide non-empty object_id."
        try:
            from ..knowledge.metadata_graph import get_metadata_config_versions, get_metadata_object
        except Exception as e:  # pragma: no cover - import/runtime guard
            return f"Metadata graph module is not available: {safe_error_message(e)}"

        cfg_ver = (config_version or "").strip()
        if not cfg_ver:
            versions = get_metadata_config_versions()
            if len(versions) == 1:
                cfg_ver = versions[0]
            # Если версий несколько — ищем без фильтра (вернёт первое совпадение).

        obj = get_metadata_object(
            object_id.strip(),
            config_version=cfg_ver or None,
        )
        if not obj:
            return (
                "Объект метаданных не найден. "
                "Выполните metadata-graph-build для выгрузки конфигурации и укажите верный config_version."
            )
        from ..knowledge.metadata_graph import _OBJECT_TYPE_RU, format_requisite_type_display

        type_ru = _OBJECT_TYPE_RU.get(obj.get("object_type", ""), obj.get("object_type", ""))
        lines = [
            f"**ID:** `{obj.get('id', '')}`",
            f"**Тип:** {type_ru}",
            f"**Имя:** {obj.get('name', '')}",
        ]
        full = obj.get("full_name")
        if full:
            lines.append(f"**Представление:** {full}")
        path = obj.get("path")
        if path:
            lines.append(f"**Путь:** `{path}`")
        parent_id = obj.get("parent_id")
        if parent_id:
            lines.append(f"**Родительский объект:** `{parent_id}`")
        form_ids = obj.get("form_ids") or []
        if form_ids:
            lines.append("\n**Формы:**")
            for fid in form_ids:
                lines.append(f"- `{fid}`")
        cfg_name = obj.get("config_name")
        cfg_ver = obj.get("config_version")
        if cfg_name or cfg_ver:
            lines.append(f"**Конфигурация:** {cfg_name or ''} (версия {cfg_ver or ''})")
        plat = obj.get("platform_version")
        if plat:
            lines.append(f"**Платформа:** {plat}")
        attrs = obj.get("attributes") or {}
        if attrs:
            reqs = attrs.get("requisites") or []
            tabs = attrs.get("tabular_sections") or []
            if reqs:
                lines.append("\n**Реквизиты:**")
                for r in reqs:
                    name = r.get("name") if isinstance(r, dict) else str(r)
                    disp = (
                        format_requisite_type_display(r, append_raw_in_brackets=True)
                        if isinstance(r, dict)
                        else ""
                    )
                    if disp:
                        lines.append(f"- {name}: {disp}")
                    else:
                        lines.append(f"- {name}")
            if tabs:
                lines.append("\n**Табличные части:**")
                for t in tabs:
                    name = t.get("name") if isinstance(t, dict) else str(t)
                    lines.append(f"\n**{name}:**")
                    reqs_ts = (t.get("requisites") or []) if isinstance(t, dict) else []
                    for r in reqs_ts:
                        if isinstance(r, dict):
                            rname = r.get("name") or ""
                            disp = (
                                format_requisite_type_display(r, append_raw_in_brackets=True)
                                if isinstance(r, dict)
                                else ""
                            )
                            if disp:
                                lines.append(f"  - {rname}: {disp}")
                            else:
                                lines.append(f"  - {rname}")
                        else:
                            lines.append(f"  - {r}")
                    if not reqs_ts:
                        lines.append("  (реквизиты не извлечены)")
            form_reqs = attrs.get("form_requisites") or []
            form_cmds = attrs.get("form_commands") or []
            if form_reqs:
                lines.append("\n**Реквизиты формы:**")
                for r in form_reqs:
                    name = r.get("name") if isinstance(r, dict) else str(r)
                    disp = (
                        format_requisite_type_display(r, append_raw_in_brackets=True)
                        if isinstance(r, dict)
                        else ""
                    )
                    if disp:
                        lines.append(f"- {name}: {disp}")
                    else:
                        lines.append(f"- {name}")
            if form_cmds:
                lines.append("\n**Команды формы:**")
                for c in form_cmds:
                    name = c.get("name") if isinstance(c, dict) else str(c)
                    action = (c.get("action") or "").strip() if isinstance(c, dict) else ""
                    title = (c.get("title") or "").strip() if isinstance(c, dict) else ""
                    part = f"- {name}"
                    if action and action != name:
                        part += f" → {action}"
                    if title:
                        part += f" ({title})"
                    lines.append(part)
            for k, v in sorted(attrs.items()):
                if (
                    k
                    not in (
                        "requisites",
                        "tabular_sections",
                        "form_requisites",
                        "form_commands",
                        "parent_id",
                    )
                    and v
                ):
                    lines.append(f"\n**{k}:** {v}")
        return "\n".join(lines)

    @mcp.tool()
    @_record_mcp_tool
    def compare_1c_help(
        topic_path_or_query: str,
        version_left: str,
        version_right: str,
        language: str | None = None,
        include_diff: bool = False,
    ) -> str:
        """Compare a help topic between two platform versions.
        topic_path_or_query: path from search (with or without version prefix) or short query (e.g. 'CryptoManager'). For short queries server uses keyword search first (path/title match) and prefers results with a meaningful title (not Untitled); then semantic fallback.
        version_left, version_right: platform versions, e.g. '8.2.19.130', '8.3.27.1859'.
        For best predictability pass an exact path from the internal topic index when available. include_diff: if True, append unified diff."""
        from ..search_store.indexer import compare_1c_help as _compare

        return _compare(
            topic_path_or_query,
            version_left,
            version_right,
            language=language,
            include_diff=include_diff,
        )

    @mcp.tool()
    @_record_mcp_tool
    def get_1c_help_index_status() -> str:
        """Returns index status (topics count, collection, versions, languages) and ingest progress.
        When ingest is running: current file, ETA, speed, errors."""
        s = _api_index_status()
        err = s.get("error")
        if err:
            return f"Error: {err}"
        if not s.get("exists"):
            return "Index does not exist. Run ingest to index the help (e.g. docker compose exec mcp python -m onec_help ingest)."
        count = s.get("points_count")
        name = s.get("collection", "onec_help_api_members")
        lines = [
            f"Collection: **{name}**",
            f"Structured API entries: **{count}**",
            f"Embeddings: **{count}**",
        ]
        from ..shared import env_config

        storage_path = env_config.get_qdrant_storage_path()
        if storage_path and os.path.isdir(storage_path):
            try:
                from ..shared._utils import dir_size_on_disk

                total = dir_size_on_disk(storage_path)
                lines.append(f"DB size: **{total / (1024 * 1024):.1f} MB**")
            except OSError:
                pass
        if s.get("versions"):
            lines.append(f"Versions (sample): {', '.join(s['versions'])}")
        if s.get("languages"):
            lines.append(f"Languages (sample): {', '.join(s['languages'])}")

        # Memory and metadata collections: point counts for verification
        try:
            from ..search_store.indexer import get_all_collections_status

            for coll in get_all_collections_status():
                if coll.get("name") == "onec_help_memory":
                    _mem_count = coll.get("points_count")
                    if _mem_count is not None:
                        lines.append("")
                        lines.append(
                            f"Memory (**onec_help_memory**): **{_mem_count}** points (snippets + standards)"
                        )
                elif coll.get("name") == "onec_config_metadata":
                    _meta_count = coll.get("points_count")
                    if _meta_count is not None:
                        lines.append("")
                        lines.append(
                            f"Metadata (**onec_config_metadata**): **{_meta_count}** points"
                        )
                elif coll.get("name") == "onec_help_api_members":
                    _api_count = coll.get("points_count")
                    if _api_count is not None:
                        lines.append("")
                        lines.append(
                            f"Structured API members (**onec_help_api_members**): **{_api_count}** points"
                        )
                elif coll.get("name") == "onec_help_api_objects":
                    _obj_count = coll.get("points_count")
                    if _obj_count is not None:
                        lines.append("")
                        lines.append(
                            f"Structured API objects (**onec_help_api_objects**): **{_obj_count}** points"
                        )
                elif coll.get("name") == "onec_help_examples":
                    _examples_count = coll.get("points_count")
                    if _examples_count is not None:
                        lines.append("")
                        lines.append(
                            f"Official examples (**onec_help_examples**): **{_examples_count}** points"
                        )
                elif coll.get("name") == "onec_help_api_links":
                    _links_count = coll.get("points_count")
                    if _links_count is not None:
                        lines.append("")
                        lines.append(
                            f"API links (**onec_help_api_links**): **{_links_count}** points"
                        )
        except Exception:
            pass
        try:
            from ..knowledge.metadata_graph import get_metadata_config_summaries

            summaries = get_metadata_config_summaries()
            if summaries:
                lines.append("")
                lines.append("Configs loaded:")
                for s in summaries:
                    lines.append(f"  - {s['config_name']} (v{s['config_version']})")
        except Exception:
            pass

        # Ingest status: current run or last completed
        ingest = None
        try:
            from ..runtime.ingest import read_ingest_status, read_last_ingest_run

            ingest = read_ingest_status()
            if not ingest:
                ingest = read_last_ingest_run()
        except Exception as e:
            logging.getLogger(__name__).debug("read_ingest_status failed: %s", e)
        if ingest:
            status = ingest.get("status", "")
            if status == "in_progress":
                lines.append("")
                lines.append("**Ingest in progress**")
                done = ingest.get("done_tasks", 0)
                total = ingest.get("total_tasks", 0)
                pts = ingest.get("total_points", 0) + (ingest.get("current_task_points") or 0)
                est_pts = ingest.get("estimated_total_points") or 0
                ctp = ingest.get("current_task_points") or 0
                cte = ingest.get("current_task_estimated_total") or 0
                if est_pts > 0 and pts > 0:
                    pct = min(100, int(100 * pts / est_pts))
                    lines.append(f"Progress: {pts}/{est_pts} pts ({pct}%)")
                elif cte > 0 and ctp > 0:
                    pct = int(100 * ctp / cte)
                    lines.append(f"Progress: {ctp}/{cte} pts ({pct}%)")
                elif total > 0:
                    pct = int(100 * done / total)
                    lines.append(f"Progress: {done}/{total} tasks ({pct}%)")
                if pts > 0:
                    lines.append(f"Indexed: {pts} pts")
                if ctp > 0 and cte > 0:
                    pct_cur = int(100 * ctp / cte)
                    lines.append(f"Current file: {ctp}/{cte} pts ({pct_cur}%)")
                elapsed = ingest.get("elapsed_sec")
                if elapsed is not None:
                    lines.append(f"Elapsed: {format_duration(elapsed)}")
                eta = ingest.get("eta_sec")
                if eta is not None and eta >= 0:
                    lines.append(f"ETA: {format_duration(eta)}")
                speed = ingest.get("embedding_speed_pts_per_sec")
                if speed is not None:
                    lines.append(f"Speed: {speed} pts/s")
                current_list = ingest.get("current") or []
                if current_list:
                    c = current_list[0]
                    lines.append(
                        f"Current: {c.get('version', '')}/{c.get('language', '')} {c.get('path', '')} [{c.get('stage', '')}]"
                    )
                failed = ingest.get("failed_tasks") or []
                if failed:
                    lines.append(f"Failed: {len(failed)}")
                    for ft in failed[:5]:
                        lines.append(
                            f"  - {ft.get('path', '?')}: {(ft.get('error', '') or '')[:80]}"
                        )
            else:
                total_sec = ingest.get("total_elapsed_sec")
                total_pts = ingest.get("total_points", 0)
                failed_count = ingest.get("failed_count", 0) or len(
                    ingest.get("failed_tasks") or []
                )
                lines.append("")
                lines.append("**Last ingest**")
                if total_sec is not None:
                    lines.append(f"Completed in {format_duration(total_sec)}, {total_pts} pts")
                else:
                    lines.append(f"Completed, {total_pts} pts")
                if failed_count > 0:
                    lines.append(f"Failed: {failed_count} file(s)")

        return "\n".join(lines)

    @mcp.tool()
    @_record_mcp_tool
    def get_1c_task_context(
        query: str,
        file_uri: str | None = None,
        symbol_name: str | None = None,
        diagnostics_json: str | None = None,
        config_version: str | None = None,
    ) -> str:
        """Build minimal AI task context from local file hints, metadata, help and memory.
        Use when you need a compact anti-hallucination context for a concrete 1C task."""
        err = _check_rate_limit()
        if err:
            return err
        q, err = _truncate_if_needed(query or "", MAX_QUERY_CHARS, "query")
        if err:
            return err
        try:
            from ..knowledge.context_builder import ContextRequest, build_context
        except Exception as e:  # pragma: no cover - import/runtime guard
            return f"Context builder is not available: {safe_error_message(e)}"

        ctx = build_context(
            ContextRequest(
                query=q,
                config_version=config_version,
                file_uri=file_uri,
                symbol_name=symbol_name,
                limit=2,
            )
        )
        help_topics = ctx.get("help_topics") or []
        memory_items = ctx.get("memory") or []
        metadata_objects = ctx.get("metadata_objects") or []
        local_context = ctx.get("local_context") or {}
        if not (help_topics or memory_items or metadata_objects or local_context):
            return "No task context found."

        parts = [f"## Task context: {q}"]
        query_type = ctx.get("query_type")
        if query_type:
            parts.append(f"type: {query_type}")
        context_lines: list[str] = []
        if local_context.get("module_type") and local_context.get("module_type") != "Unknown":
            context_lines.append(f"module: {local_context.get('module_type')}")
        if local_context.get("object_type") and local_context.get("object_name"):
            context_lines.append(
                f"object: {local_context.get('object_type')} {local_context.get('object_name')}"
            )
        if local_context.get("form_name"):
            context_lines.append(f"form: {local_context.get('form_name')}")
        if local_context.get("symbol_name"):
            context_lines.append(f"symbol: {local_context.get('symbol_name')}")
        if context_lines:
            parts.append("context: " + "; ".join(context_lines))
        diagnostics_summary = _summarize_diagnostics_json(diagnostics_json)
        if diagnostics_summary:
            parts.append("diagnostics: " + diagnostics_summary)

        if metadata_objects:
            lines = []
            for item in metadata_objects[:2]:
                line = f"- {item.get('object_type', '')} {item.get('name', '')}".strip()
                if item.get("id"):
                    line += f" ({item.get('id')})"
                if item.get("full_name"):
                    line += f" — {item.get('full_name')}"
                lines.append(line)
            parts.append("### Metadata\n" + "\n".join(lines))

        if help_topics:
            lines = []
            for item in help_topics[:2]:
                title = item.get("title", "")
                path = item.get("path", "")
                meta = _format_result_meta(item)
                text = _compact_text(item.get("text", ""), 220)
                lines.append(f"- **{title}**{meta} ({path})")
                if text:
                    lines.append(f"  {text}")
            parts.append("### Help\n" + "\n".join(lines))

        if memory_items:
            blocks = [
                _format_memory_block(
                    (item.get("payload") or item),
                    compact=True,
                    include_code=False,
                )
                for item in memory_items[:1]
            ]
            parts.append("### Memory\n" + "\n\n".join(blocks))

        return "\n\n".join(parts)

    @mcp.tool()
    @_record_mcp_tool
    def get_1c_quick_guide(task: str = "develop") -> str:
        """Returns a compact action guide for working with 1C/BSL using this MCP. Call this at the start of a 1C task to get the recommended workflow.
        task: 'develop' (default) — code examples, API lookup, snippets; 'refactor' — navigation and rename; 'test' — diagnostics and commit checklist; 'all' — full guide.
        This tool is designed for autonomous AI invocation (unlike the prompt version which targets user invocation)."""
        _guide_develop = (
            "1C-HELP DEVELOP WORKFLOW:\n"
            '1. Exact API (Тип.Метод) → get_1c_api_answer(name); full sections → get_1c_api_answer(name, detail="full"). Natural-language help → answer_1c_help_question(question). Structured object/type → get_1c_api_object(name). Related API → get_1c_api_related(name).\n'
            "2. Broad structured lookup (members, objects, official examples) → search_1c_api(query); examples only → search_1c_api(query, include_examples=True).\n"
            "3. Local task context → get_1c_task_context(query, file_uri=..., symbol_name=...).\n"
            "4. Standards only → search_1c_standards(query). Curated snippets only → search_1c_snippets(query).\n"
            "5. Config metadata (KD2 graph): search_1c_metadata_exact, search_1c_metadata_semantic, search_1c_metadata_fields. "
            "Dotted BSL/query-like strings map to graph ids using the configuration object name only (first segment after the type prefix). "
            "Same name under different types: pass object_type. " + manager_help_hint_line() + "\n"
            "6. Check index health: get_1c_help_index_status.\n"
            "7. Validate .bsl with BSL Language Server: CLI `java -jar … analyze` (see docs/cursor-examples/bsl-language-server-local) or `make bsl-start` for optional Docker; IDE BSL extension also works.\n"
            "8. Save reusable verified code only: save_1c_snippet(code_snippet, description, title).\n"
            "Key pitfalls: ПрочитатьJSON→Структура (use ПрочитатьВСоответствие=Истина for Соответствие); "
            "HTTPСоединение.Получить server-only; НачатьТранзакцию needs Попытка+ОтменитьТранзакцию."
        )
        _guide_refactor = (
            "1C-HELP REFACTOR WORKFLOW:\n"
            "1. Find symbols: IDE go-to-symbol, or search repo (rg/git grep) for procedure/function names.\n"
            "2. Read/edit modules with clear paths (Documents/…/ObjectModule.bsl, Forms/…/Module.bsl).\n"
            "3. After edits: run BSL LS analyze on changed paths (CLI JAR or `make bsl-start` stack).\n"
            "4. Rename/refactor in Configurator or IDE; keep modules consistent with metadata from 1c-help.\n"
            "5. Prefer small commits; re-run analyze on touched .bsl trees."
        )
        _guide_test = (
            "1C-HELP TEST WORKFLOW:\n"
            "1. After every .bsl edit: BSL LS `analyze` (or IDE diagnostics) — fix Error/Warning per team policy.\n"
            "2. Paths: use workspace-relative paths; Cyrillic paths are fine on disk — encode only if you embed file URIs.\n"
            "3. Before commit: (a) справка использована? (b) BSL LS clean enough? (c) save_1c_snippet только для проверенного переиспользуемого кода?"
        )
        if task == "develop":
            return _guide_develop
        if task == "refactor":
            return _guide_refactor
        if task == "test":
            return _guide_test
        return f"{_guide_develop}\n\n{_guide_refactor}\n\n{_guide_test}"

    @mcp.prompt
    def how_to_use_1c_help_and_bsl_ls(task: str = "all") -> str:
        """Human/onboarding prompt: 1c-help MCP + BSL Language Server (CLI/IDE), not a second MCP.
        Not the default AI route; for autonomous workflow use get_1c_quick_guide instead."""
        block_develop = """1c-HELP + BSL LS — DEVELOP (human/onboarding prompt)
- AI-first route: get_1c_quick_guide(task="develop") first.
- Exact API: get_1c_api_answer(name); rich sections: get_1c_api_answer(name, detail="full"). Natural-language question: answer_1c_help_question(question). Structured object: get_1c_api_object(name). Broad structured lookup: search_1c_api(query); official examples section: search_1c_api(query, include_examples=True).
- Local anti-hallucination context: get_1c_task_context(query, file_uri=..., symbol_name=...).
- Standards: search_1c_standards(query). Curated snippets: search_1c_snippets(query).
- Metadata exact: search_1c_metadata_exact(query). Metadata semantic: search_1c_metadata_semantic(query). Fields: search_1c_metadata_fields(object_query, field_query).
- Empty or poor help results: first call get_1c_help_index_status to verify index.
- Save reusable verified code only: save_1c_snippet(code_snippet, description, title).
- get_form_metadata(xml_content): pass full Form.xml with all xmlns declarations. get_module_info(uri_or_path): path to Module.bsl or ObjectModule.bsl.
- After editing .bsl: run BSL Language Server — CLI `java -jar … analyze` (see docs/cursor-examples/bsl-language-server-local/SKILL.md), or your IDE’s BSL extension, or optional Docker `make bsl-start` in this repo."""
        block_refactor = """BSL LS + репозиторий — REFACTOR (human/onboarding prompt)
- Навигация: поиск по проекту (rg/git grep), «перейти к символу» в IDE, чтение модулей по путям выгрузки (Documents/…/ObjectModule.bsl, Forms/…/Module.bsl).
- После правок: `analyze` на затронутые каталоги или файлы .bsl (JAR BSL LS) либо диагностики IDE.
- Рефакторинг имён и структуры — в конфигураторе или инструментах IDE; метаданные сверяйте с 1c-help (search_1c_metadata_*, get_1c_metadata_object)."""
        block_test = """BSL LS — TEST (human/onboarding prompt)
- После правок .bsl: прогон BSL LS analyze (или панель проблем IDE) — устранить Error и значимые Warning по политике команды.
- Чеклист перед коммитом: использован get_1c_quick_guide? BSL LS без критичных замечаний? save_1c_snippet только для проверенного переиспользуемого кода?"""
        if task == "develop":
            return block_develop
        if task == "refactor":
            return block_refactor
        if task == "test":
            return block_test
        return """Human/onboarding guide for 1c-help + BSL Language Server (CLI/IDE). For AI work prefer get_1c_quick_guide; use this prompt for a long manual. Shorter blocks: task=develop|refactor|test.

---
1) ЧТО ГДЕ
- Только MCP 1c-help: справка платформы, примеры, метаданные конфигурации (KD2), сниппеты, стандарты, compare_1c_help, save_1c_snippet.
- BSL LS не входит в MCP этого репозитория: статический анализ и форматирование — через exec-JAR (`analyze`/`format`), расширение IDE или опционально `make bsl-start` (Docker).

---
2) 1c-HELP — ORDER OF CALLS
- Exact API: get_1c_api_answer(name) first for Тип.Метод; use detail="full" for full structured sections. Natural-language factual question: answer_1c_help_question(question, version=...). Structured truth-source: get_1c_api_object(name). Broad structured lookup: search_1c_api(query); examples block: search_1c_api(query, include_examples=True).
- Task-local context: get_1c_task_context(query, file_uri=..., symbol_name=...).
- Explicit standards/snippets: search_1c_standards(query), search_1c_snippets(query).
- Empty or poor results: call get_1c_help_index_status first to check index health → then search_1c_api with exact Тип.Метод or short natural-language reformulation.
- After working code: save_1c_snippet(code_snippet, description, title) only for reusable verified code.
- get_form_metadata(xml_content): pass full Form.xml with all xmlns; truncated XML returns empty attributes. get_module_info(uri_or_path): path to Module.bsl or ObjectModule.bsl.
- For methods always use full Тип.Метод in get_1c_api_answer.

---
3) BSL LANGUAGE SERVER — ПРАКТИКА
- JAR: см. docs/cursor-examples/bsl-language-server-local/SKILL.md (`analyze -s <dir> -r json -o <existing-dir>`, `format -s <path>`).
- В репозитории 1c_hbk_helper: опционально `make fetch-bsl-ls-docker-deps` затем `make bsl-start` — отдельный контейнер с BSL LS (не путать с MCP 1c-help на :8050).
- Семантику платформы при спорах сверяйте с 1c-help, а не только с замечаниями LS.

---
4) COMMON 1C PITFALLS
- ПрочитатьJSON: returns Структура by default. For Соответствие: ПрочитатьJSON(reader, , , Истина) or use ПрочитатьВСоответствие=Истина parameter.
- HTTPСоединение.Получить: server-side only. Not available on thin client or web client.
- Transactions: НачатьТранзакцию MUST be in Попытка block with ОтменитьТранзакцию in Исключение.
- Запрос in loop: avoid Запрос.Выполнить() inside loops — causes N separate DB queries. Move query outside loop.
- ФоновоеЗадание.ПолучитьПоследнее: returns Неопределено if no previous job. Always check before accessing result.
- РасписаниеРегламентногоЗадания: set Ложь for all unused period fields, otherwise job may not start.
- УстановитьПривилегированныйРежим: don't use for every operation — it disables RLS for the entire procedure.

---
5) METADATA (1c-help)
- search_1c_metadata_exact(query, config_version=None, object_type=None, limit=20): exact-first object lookup.
- search_1c_metadata_semantic(query, config_version=None, object_type=None, limit=20): natural-language object lookup.
- search_1c_metadata_fields(object_query, field_query, config_version=None, object_type=None): field/requisite lookup.
- get_1c_metadata_object(object_id, config_version=None): details for one object (requisites, tabular sections). object_id is payload.id (EnglishType.ObjectName, e.g. Document.Sales). Pass config_version from metadata search to avoid ambiguity.
- get_1c_task_context(query, file_uri=None, symbol_name=None, diagnostics_json=None): compact anti-hallucination context for AI.

---
6) LIMITS
- query and xml_content: up to 64 KB. Full report: docs/archive/mcp-1c-help-tools-report.md."""

    @mcp.prompt
    def get_mcp_guides_bundle() -> str:
        """Returns all guides in one block for human onboarding or IDE restore.
        Not part of the default AI workflow; prefer get_1c_quick_guide for autonomous use."""
        parts = [
            "=== workflow ===\n" + _read_cursor_doc("cursor-examples/rules/1c-mcp-workflow.mdc"),
            "=== tools_tips ===\n"
            + _read_cursor_doc("cursor-examples/rules/1c-mcp-tools-report.mdc"),
            "=== tools_summary ===\n"
            + _read_cursor_doc("cursor-examples/1c-mcp-tools-report/SKILL.md"),
        ]
        return "\n\n".join(parts)

    @mcp.prompt
    def get_1c_common_pitfalls() -> str:
        """Returns a structured list of common 1C/BSL coding pitfalls with wrong vs. correct examples. Call when writing or reviewing 1C code to avoid typical mistakes."""
        return """\
# Типичные ловушки 1С/BSL — шпаргалка

## 1. ПрочитатьJSON → Структура вместо Соответствия
```bsl
// Неверно — вернёт Структуру (ключи без спецсимволов, порядок потеряется):
Рез = ПрочитатьJSON(Поток);

// Верно — получить Соответствие:
Рез = ПрочитатьJSON(Поток, , , Истина);
// или
Чтение = Новый ЧтениеJSON;
Чтение.УстановитьСтроку(СтрокаJSON);
Рез = ПрочитатьJSON(Чтение, Истина);
```

## 2. HTTPСоединение — только на сервере
```bsl
// Неверно — вызов с клиента или формы без директивы:
&НаКлиенте
Процедура ПроверитьСоединение()
    Соед = Новый HTTPСоединение("example.com"); // ошибка на клиенте!

// Верно — переносить на сервер:
&НаСервере
Функция ПолучитьДанные()
    Соед = Новый HTTPСоединение("example.com");
```

## 3. НачатьТранзакцию без Попытки
```bsl
// Неверно:
НачатьТранзакцию();
ОбъектЗаписи.Записать();
ЗафиксироватьТранзакцию();

// Верно:
НачатьТранзакцию();
Попытка
    ОбъектЗаписи.Записать();
    ЗафиксироватьТранзакцию();
Исключение
    ОтменитьТранзакцию();
    ВызватьИсключение;
КонецПопытки;
```

## 4. Запрос.Выполнить() внутри цикла
```bsl
// Неверно — N запросов к БД:
Для Каждого Строка Из Массив Цикл
    Запрос = Новый Запрос("ВЫБРАТЬ ... ГДЕ Ссылка = &Ссылка");
    Запрос.УстановитьПараметр("Ссылка", Строка);
    Рез = Запрос.Выполнить();
КонецЦикла;

// Верно — один запрос с массивом:
Запрос = Новый Запрос("ВЫБРАТЬ ... ГДЕ Ссылка В (&Массив)");
Запрос.УстановитьПараметр("Массив", Массив);
Рез = Запрос.Выполнить();
```

## 5. ФоновоеЗадание.ПолучитьПоследнее() → Неопределено
```bsl
// Неверно:
ФЗ = ФоновыеЗадания.ПолучитьПоследнее(Ключ);
Статус = ФЗ.Состояние; // ошибка если ФЗ = Неопределено

// Верно:
ФЗ = ФоновыеЗадания.ПолучитьПоследнее(Ключ);
Если ФЗ <> Неопределено Тогда
    Статус = ФЗ.Состояние;
КонецЕсли;
```

## 6. РасписаниеРегламентногоЗадания — неполные настройки
```bsl
// Неверно — задание может не запуститься если не все поля заполнены:
Расписание = Новый РасписаниеРегламентногоЗадания;
Расписание.ПериодПовтораВДень = 3600;
// Остальные поля по умолчанию Неопределено — поведение непредсказуемо

// Верно — явно задать все используемые поля:
Расписание = Новый РасписаниеРегламентногоЗадания;
Расписание.ПериодПовтораВДень = 3600;
Расписание.ДатаОкончания = '00010101'; // без ограничения
Расписание.ДниНедели = 127; // все дни
```

## 7. УстановитьПривилегированныйРежим — отключает RLS для всей процедуры
```bsl
// Неверно — использовать везде «для удобства»:
УстановитьПривилегированныйРежим(Истина);
// ... весь код без RLS ...
УстановитьПривилегированныйРежим(Ложь);

// Верно — оборачивать только минимально необходимый блок:
УстановитьПривилегированныйРежим(Истина);
ЗначениеДляСистемы = ПолучитьСистемноеЗначение();
УстановитьПривилегированныйРежим(Ложь);
```

## 8. СтрокаСоединения — путаница между СтрокиОчистить и Строки (метод таблицы значений)
```bsl
// Неверно — СтрокиОчистить очищает строки в таблице:
ТЗ.СтрокиОчистить(); // удаляет ВСЕ строки!

// Если нужно очистить значения в конкретной строке:
Для Каждого КолонкаТЗ Из ТЗ.Колонки Цикл
    Строка[КолонкаТЗ.Имя] = КолонкаТЗ.ТипЗначения.ПривестиЗначение(Неопределено);
КонецЦикла;
```

## 9. ОбщийМодуль без явной директивы контекста
```bsl
// Неверно — без директив 1С определяет контекст по настройкам модуля:
// В общем модуле с «Клиент» и «Сервер» — функции дублируются
Функция МояФункция() // вызовется и на клиенте и на сервере

// Верно — явно указать директиву или вынести в отдельный модуль:
&НаСервере
Функция МояФункцияНаСервере()
```

## 10. Сравнение дат: неправильный пустой год
```bsl
// Неверно — пустая дата это '00010101' в 1С, а не '':
Если Дата = "" Тогда // всегда Ложь — дата никогда не равна строке

// Верно:
Если НЕ ЗначениеЗаполнено(Дата) Тогда
// или
Если Дата = '00010101' Тогда
```

## 11. Узкий маршрут вместо общего answer-tool
1. Точный API: get_1c_api_answer("Тип.Метод")
2. Широкий structured lookup: search_1c_api("Тип.Метод") или search_1c_api("натуральный вопрос по API")
3. Стандарты: search_1c_standards(query)
4. Сниппеты: search_1c_snippets(query)
5. Метаданные: search_1c_metadata_exact / search_1c_metadata_semantic / search_1c_metadata_fields
"""

    return mcp


def _create_multi_transport_app(mcp: "FastMCP", mcp_path: str = "/mcp") -> "Any":
    """Create a single ASGI app that serves both streamable-http and SSE transports.

    Routes:
      {mcp_path}          → streamable-http (modern MCP, used by Cursor / Claude Code)
      /sse                → SSE transport endpoint (legacy clients)
      /messages           → SSE message POST endpoint

    Both transports share the same FastMCP instance and single lifespan.
    """
    from contextlib import asynccontextmanager

    try:
        from fastmcp.server.http import (
            SseServerTransport,
            StreamableHTTPASGIApp,
            StreamableHTTPSessionManager,
            create_base_app,
        )
        from starlette.requests import Request
        from starlette.responses import Response
        from starlette.routing import Mount, Route
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("fastmcp>=2.0 required for multi-transport mode") from exc

    sse_path = "/sse"
    message_path = "/messages"

    # --- streamable-http ---
    session_manager = StreamableHTTPSessionManager(
        app=mcp._mcp_server,
        json_response=False,
        stateless=False,
    )
    streamable_app = StreamableHTTPASGIApp(session_manager)

    # --- SSE ---
    sse_transport = SseServerTransport(message_path)

    async def _handle_sse_raw(scope: "Any", receive: "Any", send: "Any") -> Response:
        async with sse_transport.connect_sse(scope, receive, send) as streams:
            await mcp._mcp_server.run(
                streams[0],
                streams[1],
                mcp._mcp_server.create_initialization_options(),
            )
        return Response()

    async def sse_endpoint(request: Request) -> Response:
        return await _handle_sse_raw(request.scope, request.receive, request._send)

    routes = [
        Route(mcp_path, endpoint=streamable_app),
        Route(sse_path, endpoint=sse_endpoint, methods=["GET"]),
        Mount(message_path, app=sse_transport.handle_post_message),
    ]
    # Extra routes registered on the FastMCP instance (e.g. health-check)
    routes.extend(mcp._get_additional_http_routes())

    @asynccontextmanager
    async def lifespan(app: "Any"):  # type: ignore[override]
        async with mcp._lifespan_manager(), session_manager.run():
            yield

    combined = create_base_app(routes=routes, middleware=[], lifespan=lifespan)
    combined.state.fastmcp_server = mcp
    combined.state.transport_type = "multi"
    return combined


def run_mcp(
    help_path: Path,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8050,
    path: str = "/mcp",
) -> None:
    """Run MCP server. help_path: directory with .md or HTML.
    transport: stdio | sse | http | streamable-http | multi.
    'multi' serves both streamable-http (at path) and SSE (/sse + /messages) simultaneously.
    For http/sse/streamable-http/multi, host/port/path are used."""
    mcp = _build_mcp_app(help_path)
    _log = logging.getLogger(__name__)
    if transport == "multi":
        path_val = (path or "/mcp").rstrip("/") or "/mcp"
        port_int = int(port) if port is not None else 8050
        _log.info(
            "MCP multi-transport on %s:%s — streamable-http at %s, SSE at /sse",
            host,
            port_int,
            path_val,
        )
        try:
            import uvicorn

            asgi_app = _create_multi_transport_app(mcp, mcp_path=path_val)
            uvicorn.run(asgi_app, host=host, port=port_int, log_level="info")
        except Exception as e:
            _log.exception("MCP server exited: %s", safe_error_message(e))
            raise
    elif transport in ("sse", "http", "streamable-http"):
        path_val = (path or "/mcp").rstrip("/") or "/mcp"
        port_int = int(port) if port is not None else 8050
        _log.info("MCP listening on %s:%s%s (%s)", host, port_int, path_val, transport)
        try:
            mcp.run(transport=transport, host=host, port=port_int, path=path_val)
        except Exception as e:
            _log.exception("MCP server exited: %s", safe_error_message(e))
            raise
    else:
        mcp.run(transport="stdio")


def _main() -> None:
    """Fast entry point: run MCP without loading the full CLI (python -m onec_help.interfaces.mcp_server)."""
    import argparse
    import sys

    p = argparse.ArgumentParser(
        description="Run 1C Help MCP server (fast startup, no CLI). Use same args as 'onec_help mcp'."
    )
    p.add_argument(
        "directory",
        nargs="?",
        default="data",
        help="Help data directory (default: data or HELP_PATH)",
    )
    p.add_argument(
        "--transport",
        default=None,
        help="MCP transport: stdio, sse, http, streamable-http, multi (default: env MCP_TRANSPORT or streamable-http). 'multi' serves streamable-http + SSE simultaneously.",
    )
    p.add_argument("--host", default=None, help="Host for HTTP (default: env MCP_HOST or 0.0.0.0)")
    p.add_argument("--port", type=int, default=None, help="Port (default: env MCP_PORT or 8050)")
    p.add_argument("--path", default=None, help="URL path (default: env MCP_PATH or /mcp)")
    args = p.parse_args()
    from ..shared import env_config

    transport = (args.transport or env_config.get_mcp_transport()).strip()
    host = (args.host or env_config.get_mcp_host()).strip()
    port = args.port if args.port is not None else env_config.get_mcp_port()
    path = (args.path or env_config.get_mcp_path()).strip()
    run_mcp(
        help_path=Path(args.directory).resolve(),
        transport=transport,
        host=host,
        port=port,
        path=path,
    )
    sys.exit(0)


if __name__ == "__main__":
    _main()
