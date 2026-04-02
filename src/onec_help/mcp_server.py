"""MCP server for 1C Help: search_1c_help, get_1c_help_topic, get_1c_function_info."""

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

from ._utils import format_duration, safe_error_message  # noqa: E402
from .mcp_metrics import record_request as _record_mcp_request  # noqa: E402


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
    from . import env_config

    return env_config.get_mcp_snippet_max_chars()


def _max_topic_content_chars() -> int:
    """Max chars per topic preview in search_with_content/compact answer helpers. From env_config."""
    from . import env_config

    return env_config.get_mcp_max_topic_chars()


MAX_QUERY_CHARS = 65536  # 64 KB
MAX_CODE_SNIPPET_CHARS = 65536  # 64 KB
_RATE_LIMIT_WINDOW_SEC = 60
_rate_timestamps: list[float] = []
_rate_lock = threading.Lock()


def _check_rate_limit() -> str | None:
    """Return error message if over rate limit, else None. MCP_RATE_LIMIT_PER_MIN=0 disables."""
    from . import env_config

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
        return f"Read error: {e}"


def _get_help_path() -> Path:
    if _HELP_PATH is None:
        from . import env_config

        return Path(env_config.get_help_path()).resolve()
    return _HELP_PATH


def _search(
    query: str,
    limit: int = 10,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    from .indexer import search_index

    return search_index(query, limit=limit, version=version, language=language)


def _search_keyword(
    query: str,
    limit: int = 15,
    version: str | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    from .indexer import search_index_keyword

    return search_index_keyword(query, limit=limit, version=version, language=language)


def _list_titles(limit: int = 100, path_prefix: str = "") -> list[dict[str, Any]]:
    from .indexer import list_index_titles

    return list_index_titles(limit=limit, path_prefix=path_prefix or "")


def _index_status() -> dict[str, Any]:
    from .indexer import get_index_status

    return get_index_status()


def _get_topic(
    topic_path: str,
    version: str | None = None,
    language: str | None = None,
    prefer_index: bool = False,
) -> str:
    from .indexer import get_topic_content

    base = _get_help_path()
    return get_topic_content(
        base,
        topic_path,
        version=version,
        language=language,
        prefer_index=prefer_index,
    )


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


def _format_memory_block(payload: dict[str, Any], *, compact: bool = False, include_code: bool = True) -> str:
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


def _select_memory_for_code_answer(items: list[dict[str, Any]], query: str, has_help_results: bool) -> list[dict[str, Any]]:
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


def _summarize_diagnostics_json(diagnostics_json: str | None) -> str:
    if not diagnostics_json:
        return ""
    try:
        payload = json.loads(diagnostics_json)
    except Exception:
        return ""
    items = payload if isinstance(payload, list) else payload.get("diagnostics", []) if isinstance(payload, dict) else []
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
        from . import redis_cache

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
    def search_1c_help(
        query: str,
        limit: int = 8,
        version: str | None = None,
        language: str | None = None,
        include_user_memory: bool = False,
    ) -> str:
        """Search 1C help by natural language (semantic). Returns list of relevant topics with title, path, and snippet.
        For exact API names use get_1c_api_answer or search_1c_help_keyword.
        query: search text (e.g. 'Формат', 'Запрос.ПакетПолучения', 'синтаксис ОбъединитьПериоды').
        limit: max results (default 8). version, language: optional filters.
        include_user_memory: if True, also search saved snippets and mark source.
        Tip: if results are irrelevant or low quality, try search_1c_help_keyword with exact API name (e.g. Тип.Метод)."""
        err = _check_rate_limit()
        if err:
            return err
        q, err = _truncate_if_needed(query or "", MAX_QUERY_CHARS, "query")
        if err:
            return err
        results = _search(q, limit=limit, version=version, language=language)
        memory_results: list[dict[str, Any]] = []
        if include_user_memory:
            try:
                from .memory import get_memory_store

                memory_results = get_memory_store().search_long(query, limit=min(5, limit))
            except Exception as e:
                logging.getLogger(__name__).debug("search_long failed: %s", e)
        if not results and not memory_results:
            return "No results found. Ensure build-index was run and Qdrant is available."
        lines = []
        idx = 1
        for r in results:
            meta = _format_result_meta(r)
            lines.append(f"{idx}. **{r.get('title', '')}**{meta} (path: {r.get('path', '')})")
            text = r.get("text", "")[: _snippet_max_chars()]
            lines.append(f"   {text}...")
            idx += 1
        for m in memory_results:
            payload = m.get("payload", {})
            lines.append(f"{idx}. " + _format_memory_block(payload))
            idx += 1
        return "\n".join(lines)

    @mcp.tool()
    @_record_mcp_tool
    def search_1c_help_keyword(
        query: str,
        limit: int = 10,
        version: str | None = None,
        language: str | None = None,
    ) -> str:
        """Search 1C help by exact substring/BM25 in title and text (e.g. 'Формат', 'РегистрНакопления.ОстаткиИОбороты').
        Use when semantic search misses specific API names or returns irrelevant results.
        query: the search string — pass exact API name or Type.Method (e.g. 'HTTPСоединение.Получить').
        For exact API answers prefer get_1c_api_answer. limit: max results (default 10). version, language: optional filters.
        Tip: if no matches, try search_1c_help for semantic search or synonym (e.g. ПакетПолучения → ВыполнитьПакет)."""
        err = _check_rate_limit()
        if err:
            return err
        q_raw = (query or "").strip()
        if not q_raw:
            return "Provide query (the search string, e.g. 'HTTPСоединение.Получить')."
        q, err = _truncate_if_needed(q_raw, MAX_QUERY_CHARS, "query")
        if err:
            return err
        results = _search_keyword(
            q,
            limit=limit,
            version=version,
            language=language,
        )
        results = _rank_keyword_results(q, results)
        if not results:
            return "No keyword matches. Try search_1c_help for semantic search."
        lines = []
        for i, r in enumerate(results, 1):
            meta = _format_result_meta(r)
            lines.append(f"{i}. **{r.get('title', '')}**{meta} (path: {r.get('path', '')})")
            text = r.get("text", "")[: _snippet_max_chars()]
            lines.append(f"   {text}...")
        return "\n".join(lines)

    @mcp.tool()
    @_record_mcp_tool
    def search_1c_help_with_content(
        query: str,
        limit: int = 3,
        version: str | None = None,
        language: str | None = None,
    ) -> str:
        """[DEPRECATED] Broad manual reading helper.
        Kept for backward compatibility only. Will be removed in a future version.
        query: search text. limit: max topics (default 3). version, language: optional filters."""
        err = _check_rate_limit()
        if err:
            return err
        q, err = _truncate_if_needed(query or "", MAX_QUERY_CHARS, "query")
        if err:
            return err
        results, _ = _hybrid_search(q, limit=limit, version=version, language=language)
        if not results:
            return "No results found. Ensure build-index was run and Qdrant is available."
        parts = []
        parts.append(
            "[DEPRECATED] Prefer get_1c_api_answer or search_1c_help_keyword + get_1c_help_topic. "
            "Use this legacy tool only for broad manual reading."
        )
        for _i, r in enumerate(results, 1):
            path = r.get("path", "")
            if not path:
                continue
            content = _get_topic(path, version=version, language=language, prefer_index=False)
            if content:
                max_chars = _max_topic_content_chars()
                if len(content) > max_chars:
                    content = content[:max_chars] + "\n\n..."
                parts.append(f"---\n## {path}\n\n{content}")
        return "\n\n".join(parts) if parts else "No content could be retrieved."

    @mcp.tool()
    @_record_mcp_tool
    def get_1c_api_answer(
        name: str,
        version: str | None = None,
        language: str | None = None,
        detail: str = "compact",
    ) -> str:
        """Compact exact-first answer for a 1C API/function/method.
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
        results = _rank_keyword_results(
            name_clean,
            _search_keyword(name_clean, limit=15, version=version, language=language),
        )
        if not results:
            return (
                f"No exact keyword matches for «{name_clean}». "
                f'Try search_1c_help_keyword(query="{name_clean}") or get_1c_help_topic(topic_path=<path>).'
            )
        best_priority = _match_priority(
            name_clean.lower(),
            (results[0].get("title") or "").strip().lower(),
            _result_path_stem(results[0]),
        )
        best = [
            result
            for result in results
            if _match_priority(
                name_clean.lower(),
                (result.get("title") or "").strip().lower(),
                _result_path_stem(result),
            )
            == best_priority
        ]
        if len(best) > 1 and best_priority <= 1 and not version:
            lines = [f"Several exact API matches for «{name_clean}». Refine by version or use get_1c_help_topic:"]
            for idx, result in enumerate(best[:5], 1):
                meta = _format_result_meta(result)
                lines.append(f"{idx}. **{result.get('title', '')}**{meta} (path: {result.get('path', '')})")
            return "\n".join(lines)
        topic = best[0]
        path = topic.get("path", "")
        if not path:
            return "Exact keyword hit has no topic path."
        content = _get_topic(path, version=version, language=language, prefer_index=False)
        if not content:
            return f"Topic content not found for {path}."
        if detail == "full":
            return content
        return _compact_api_answer(topic, content, max_chars=1200)

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
            from .memory import get_memory_store

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
    def search_1c_memory(
        query: str,
        limit: int = 5,
        domains: str | None = None,
    ) -> str:
        """Search only memory (snippets and standards). Returns blocks [пример] / [стандарт] by hybrid BM25+semantic search.
        query: search text. limit: max items (default 5). domains: optional filter — "standards", "snippets",
        "community_help", or comma-separated e.g. "standards,snippets" to get both; if omitted, searches all.
        Memory contains: BSP patterns, platform snippets, v8std coding standards.
        Use when you need dedicated context from standards/snippets."""
        err = _check_rate_limit()
        if err:
            return err
        return _search_memory_blocks(
            query,
            limit=limit,
            domains=domains,
            title="## Память (сниппеты и стандарты)",
            include_code=False,
        )

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
    def get_1c_help_topic(
        topic_path: str | None = None,
        path: str | None = None,
        version: str | None = None,
        language: str | None = None,
        prefer_index: bool = False,
    ) -> str:
        """Get full help topic content in Markdown by path. Path from search results (e.g. 'zif3_CryptoManager.md').
        Pass the topic path as **topic_path** or **path** (both accepted).
        Content is read from disk or from index if files were not persisted.
        version, language: optional filters when reading from index.
        prefer_index: if True, read only from index (skip disk).
        Tip: get path from search_1c_help or search_1c_help_keyword first."""
        err = _check_rate_limit()
        if err:
            return err
        topic = (topic_path or path or "").strip()
        if not topic:
            return "Provide topic_path or path (the help topic path from search results)."
        content = _get_topic(
            topic,
            version=version,
            language=language,
            prefer_index=prefer_index,
        )
        if content:
            try:
                from .memory import get_memory_store

                title = content.split("\n")[0].strip().lstrip("#").strip() or ""
                get_memory_store().write_event(
                    "get_topic",
                    {"topic_path": topic, "title": title},
                )
            except Exception as e:
                logging.getLogger(__name__).debug("write_event get_topic failed: %s", e)
            return content
        return "Topic not found."

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
        Note: snippet becomes searchable via search_1c_memory after memory flush (usually within seconds when MEMORY_ENABLED=1)."""
        err = _check_rate_limit()
        if err:
            return err
        cs, err = _truncate_if_needed(code_snippet or "", MAX_CODE_SNIPPET_CHARS, "code_snippet")
        if err:
            return err
        try:
            from . import env_config
            from .memory import get_memory_store

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
                        result = f"Snippet saved to memory. Could not write to SNIPPETS_DIR ({snippets_dir})."
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
        from .form_metadata import parse_form_xml

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
            "Catalogs", "Documents", "DataProcessors", "Reports",
            "CommonModules", "ExchangePlans", "InformationRegisters",
            "AccumulationRegisters", "AccountingRegisters", "CalculationRegisters",
            "BusinessProcesses", "Tasks", "ChartsOfCharacteristicTypes",
            "ChartsOfAccounts", "ChartsOfCalculationTypes", "Constants",
            "Enumerations", "SettingsStorages", "Subsystems", "Sequences",
            "ScheduledJobs", "WebServices", "HTTPServices", "ExternalDataSources",
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
        from .metadata_graph import get_metadata_config_versions

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
        if getattr(search_fn, "__name__", "") == "search_metadata_semantic" and (query or "").strip():
            try:
                from . import embedding, env_config
                from .indexer import get_collection_vector_size

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

    def _format_metadata_results(items: list[dict[str, Any]], *, default_version: str | None = None) -> str:
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
        """Exact-first metadata lookup by id/name/full_name/path."""
        err = _check_rate_limit()
        if err:
            return err
        q, err = _truncate_if_needed(query or "", MAX_QUERY_CHARS, "query")
        if err:
            return err
        try:
            from .metadata_graph import search_metadata_exact
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
        """Semantic metadata lookup for natural-language queries."""
        err = _check_rate_limit()
        if err:
            return err
        q, err = _truncate_if_needed(query or "", MAX_QUERY_CHARS, "query")
        if err:
            return err
        try:
            from .metadata_graph import search_metadata_semantic
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
        """Search requisites/tabular sections/commands inside matched metadata objects."""
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
            from .metadata_graph import get_metadata_config_versions, search_metadata_fields
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

        object_id: identifier from search_1c_metadata_exact/search_1c_metadata_semantic (payload.id, e.g. 'Document/РеализацияТоваровУслуг').
        config_version: optional filter (e.g. '3.0.184.16'). If omitted, returns first match across all loaded configs.
        """
        err = _check_rate_limit()
        if err:
            return err
        if not object_id or not object_id.strip():
            return "Provide non-empty object_id."
        try:
            from .metadata_graph import get_metadata_config_versions, get_metadata_object
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
        from .metadata_graph import _OBJECT_TYPE_RU, format_requisite_type_display

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
                                if isinstance(r, dict) else ""
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
    def get_1c_help_related(
        topic_path: str | None = None,
        path: str | None = None,
        version: str | None = None,
        language: str | None = None,
    ) -> str:
        """Get list of related topics for a given help topic path.
        Returns paths and titles from outgoing links in the topic.
        Pass the topic path as **topic_path** or **path** (e.g. 'Format971.md').
        version, language: optional filters when reading from index."""
        from .indexer import get_1c_help_related as _get_related

        topic = (topic_path or path or "").strip()
        if not topic:
            return "Provide topic_path or path (the help topic path from search results)."
        items = _get_related(
            topic,
            version=version,
            language=language,
        )
        if not items:
            # Fallback: surface unresolved link titles so the AI can follow up
            from .indexer import get_1c_help_unresolved_links as _get_unresolved

            unresolved = _get_unresolved(topic, version=version, language=language)
            if unresolved:
                lines = []
                for lnk in unresolved[:8]:
                    title = lnk.get("target_title") or lnk.get("link_text", "")
                    if not title:
                        continue
                    hits = _search_keyword(title, limit=1, version=version, language=language)
                    if hits and hits[0].get("path"):
                        lines.append(f"- **{title}** — `{hits[0]['path']}`")
                    else:
                        lines.append(f"- **{title}** (not found in index — try search_1c_help_keyword)")
                if lines:
                    return "Related topics (resolved from link titles):\n" + "\n".join(lines)
                return "No related topics found. Try search_1c_help_keyword with the topic name."
            stem = topic.split("/")[-1].replace(".html", "").replace(".md", "")
            return (
                "No related topics found for this path. outgoing_links may not be populated for all topics. "
                f"Try: search_1c_help_keyword(query=\"{stem}\") to find related topics by name."
            )
        lines = [f"- **{r.get('title', '')}** — `{r.get('path', '')}`" for r in items]
        return "\n".join(lines)

    @mcp.tool()
    @_record_mcp_tool
    def list_1c_help_titles(limit: int = 100, path_prefix: str = "") -> str:
        """List topic titles and paths for browsing. path_prefix: filter by path start.
        Paths in index have format '<version>/<stem>/<rel_path>' (e.g. '8.3.27.1859/shcntx_ru/zif/...').
        Use path_prefix like '8.3' to filter by version, or leave empty to browse all topics."""
        items = _list_titles(limit=limit, path_prefix=path_prefix)
        if not items:
            return "No topics in index or prefix filter too strict."
        lines = [
            f"{i}. **{r.get('title', '')}** — `{r.get('path', '')}`" for i, r in enumerate(items, 1)
        ]
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
        For best predictability pass exact path from search_1c_help_keyword. include_diff: if True, append unified diff."""
        from .indexer import compare_1c_help as _compare

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
        s = _index_status()
        err = s.get("error")
        if err:
            return f"Error: {err}"
        if not s.get("exists"):
            return "Index does not exist. Run ingest to index the help (e.g. docker compose exec mcp python -m onec_help ingest)."
        count = s.get("points_count")
        name = s.get("collection", "onec_help")
        lines = [
            f"Collection: **{name}**",
            f"Topics indexed: **{count}**",
            f"Embeddings: **{count}**",
        ]
        from . import env_config

        storage_path = env_config.get_qdrant_storage_path()
        if storage_path and os.path.isdir(storage_path):
            try:
                from ._utils import dir_size_on_disk

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
            from .indexer import get_all_collections_status

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
        except Exception:
            pass
        try:
            from .metadata_graph import get_metadata_config_summaries

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
            from .ingest import read_ingest_status, read_last_ingest_run

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
    def get_1c_context_bundle(
        query: str,
        config_version: str | None = None,
        file_uri: str | None = None,
        symbol_name: str | None = None,
        limit: int = 5,
    ) -> str:
        """Legacy broad context: combine help topics, memory and configuration metadata objects.
        Use when you need all three sources: help docs, memory (snippets/standards), AND config objects (Documents, Catalogs, Registers).
        For AI work prefer get_1c_task_context and explicit narrow tools; this tool is intentionally broader and more verbose.
        Returns topic snippets (not full content) — call get_1c_help_topic or get_1c_help_topics_bulk for full text.
        query: main search text or API name. config_version: e.g. '3.0.184.16'; optional if one config loaded.
        file_uri, symbol_name: accepted for context narrowing.
        limit: max items per source (default 5)."""
        err = _check_rate_limit()
        if err:
            return err
        q, err = _truncate_if_needed(query or "", MAX_QUERY_CHARS, "query")
        if err:
            return err
        try:
            from .context_builder import ContextRequest, build_context
        except Exception as e:  # pragma: no cover - import/runtime guard
            return f"Context builder is not available: {safe_error_message(e)}"

        ctx = build_context(
            ContextRequest(
                query=q,
                config_version=config_version,
                file_uri=file_uri,
                symbol_name=symbol_name,
                limit=limit,
            )
        )

        help_topics = ctx.get("help_topics") or []
        memory_items = ctx.get("memory") or []
        metadata_objects = ctx.get("metadata_objects") or []

        if not (help_topics or memory_items or metadata_objects):
            return "No context found: help index, memory and metadata graph returned no results."

        parts: list[str] = [f"## Legacy context bundle: {q}"]

        if help_topics:
            lines = []
            for i, h in enumerate(help_topics[:limit], 1):
                title = h.get("title", "")
                path = h.get("path", "")
                text = (h.get("text") or "")[: _snippet_max_chars()]
                lines.append(f"{i}. **{title}** — `{path}`\n   {text}...")
            parts.append("\n### Из справки\n\n" + "\n".join(lines))

        if memory_items:
            lines = []
            for i, m in enumerate(memory_items[:limit], 1):
                payload = m.get("payload", {}) or m
                title = payload.get("title", "") or payload.get("summary", "")[:80]
                domain = payload.get("domain", "")
                prefix = (
                    "[пример]"
                    if domain == "snippets"
                    else "[стандарт]"
                    if domain == "standards"
                    else "[memory]"
                )
                desc = payload.get("description", "") or payload.get("instruction", "") or ""
                lines.append(f"{i}. **{title}** {prefix}\n   {desc[: _snippet_max_chars()]}...")
            parts.append("\n### Сниппеты и стандарты\n\n" + "\n".join(lines))

        if metadata_objects:
            lines = []
            for i, obj in enumerate(metadata_objects[:limit], 1):
                ot = obj.get("object_type", "")
                name = obj.get("name", "")
                full = obj.get("full_name") or ""
                oid = obj.get("id", "")
                path = obj.get("path", "")
                line = f"{i}. **{ot} {name}**"
                if full:
                    line += f" — {full}"
                if oid:
                    line += f" (id: `{oid}`)"
                if path:
                    line += f" — `{path}`"
                lines.append(line)
            parts.append("\n### Объекты конфигурации\n\n" + "\n".join(lines))

        return "\n".join(parts)

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
            from .context_builder import ContextRequest, build_context
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
            context_lines.append(f"object: {local_context.get('object_type')} {local_context.get('object_name')}")
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
    def get_1c_function_info(
        name: str,
        path: str | None = None,
        choose_index: int | None = None,
    ) -> str:
        """Get description, syntax, parameters, return value for a 1C function/method.
        name: e.g. 'Формат', 'МенеджерКриптографии.Подписать'. path: optional exact topic path.
        When ambiguous (e.g. Формат → function vs format topic), use choose_index=1,2,... or search_1c_help_keyword for exact API.
        Tip: for exact API names always pass full Тип.Метод (e.g. HTTPСоединение.Получить). If no match, try search_1c_help_keyword with synonym."""
        name_clean = name.strip()
        if not name_clean:
            return "Provide a function or method name."
        if path:
            content = _get_topic(path)
            return content or "Topic not found."
        results = _rank_keyword_results(name_clean, _search_keyword(name_clean, limit=40))
        if not results:
            results = _search(name_clean, limit=40)
        name_lower = name_clean.lower()
        scored = [
            (
                result,
                _match_priority(
                    name_lower,
                    (result.get("title") or "").lower(),
                    _result_path_stem(result),
                ),
            )
            for result in results
        ]
        relevant = [(r, p) for r, p in scored if p <= 2]
        if not relevant:
            relevant = scored
        relevant.sort(
            key=lambda x: (
                x[1],
                _member_sort_key(name_lower, (x[0].get("title") or "").lower()),
            )
        )
        best_priority = relevant[0][1] if relevant else 3
        best = [r for r, p in relevant if p == best_priority]
        if best_priority == 3:
            lines = [
                f"No exact match for «{name_clean}».",
                f'Try: search_1c_help_keyword(query="{name_clean}"), then get_1c_help_topic(topic_path) for full content.',
                "For methods use full Тип.Метод (e.g. HTTPСоединение.Получить). Synonym? e.g. ПакетПолучения → ВыполнитьПакет.",
                "",
                "Keyword suggestions (from index):",
            ]
            for i, r in enumerate(relevant[:8], 1):
                lines.append(f"{i}. {r[0].get('title', '')} — `{r[0].get('path', '')}`")
            lines.append("")
            lines.append(
                "Call with path=<exact_path> or get_1c_function_info(name=..., choose_index=N) if one matches."
            )
            return "\n".join(lines)
        if len(best) > 1:
            idx = choose_index
            if idx is not None and 1 <= idx <= len(best):
                content = _get_topic(best[idx - 1]["path"])
                return content or "Topic not found."
            lines = [
                f"Several matches for «{name_clean}». Use choose_index (1–{len(best)}) to select:",
                "",
            ]
            for i, r in enumerate(best[:10], 1):
                lines.append(f"  {i}. {r.get('title', '')} — `{r.get('path', '')}`")
            lines.append("")
            lines.append("Example: get_1c_function_info(name=..., choose_index=2)")
            content = _get_topic(best[0]["path"])
            if content:
                lines.append("\n---\nContent of first match:\n\n" + content)
            return "\n".join(lines)
        if best:
            content = _get_topic(best[0]["path"])
            if content:
                return content
        return "No topic found for this name. Try search_1c_help or search_1c_help_keyword first."

    @mcp.tool()
    @_record_mcp_tool
    def get_1c_help_topics_bulk(
        paths: _StrList,
        max_chars_per_topic: int = 4000,
        version: str | None = None,
        language: str | None = None,
    ) -> str:
        """Get full content of multiple help topics in one call. More efficient than N separate get_1c_help_topic calls.
        paths: list of topic paths from search results (up to 10). Silently skips paths not found.
        max_chars_per_topic: truncation limit per topic (default 4000 from MCP_MAX_TOPIC_CHARS). 0 = no limit.
        version, language: optional filters when reading from index.
        Tip: get paths from search_1c_help_keyword or search_1c_help first."""
        err = _check_rate_limit()
        if err:
            return err
        if not paths:
            return "Provide at least one path in paths list."
        paths = paths[:10]  # hard limit
        parts: list[str] = []
        not_found: list[str] = []
        for p in paths:
            p = (p or "").strip()
            if not p:
                continue
            content = _get_topic(p, version=version, language=language, prefer_index=False)
            if content:
                if max_chars_per_topic > 0 and len(content) > max_chars_per_topic:
                    content = content[:max_chars_per_topic] + "\n\n..."
                parts.append(f"---\n## {p}\n\n{content}")
            else:
                not_found.append(p)
        if not parts:
            return "No topics found for the provided paths. Check paths from search results."
        result = "\n\n".join(parts)
        if not_found:
            result += f"\n\n*Not found ({len(not_found)}): {', '.join(not_found[:5])}*"
        return result

    @mcp.tool()
    @_record_mcp_tool
    def get_1c_quick_guide(task: str = "develop") -> str:
        """Returns a compact action guide for working with 1C/BSL using this MCP. Call this at the start of a 1C task to get the recommended workflow.
        task: 'develop' (default) — code examples, API lookup, snippets; 'refactor' — navigation and rename; 'test' — diagnostics and commit checklist; 'all' — full guide.
        This tool is designed for autonomous AI invocation (unlike the prompt version which targets user invocation)."""
        _guide_develop = (
            "1C-HELP DEVELOP WORKFLOW:\n"
            "1. Exact API (Тип.Метод) → get_1c_api_answer(name).\n"
            "2. General platform topic → search_1c_help_keyword('Тип.Метод') or search_1c_help(query) → get_1c_help_topic(topic_path=<path>).\n"
            "3. Local task context → get_1c_task_context(query, file_uri=..., symbol_name=...).\n"
            "4. Standards only → search_1c_standards(query). Snippets only → search_1c_snippets(query).\n"
            "5. Metadata exact → search_1c_metadata_exact(query). Metadata semantic → search_1c_metadata_semantic(query).\n"
            "6. Field lookup → search_1c_metadata_fields(object_query, field_query).\n"
            "7. Check index health: get_1c_help_index_status.\n"
            "8. Code validation happens in external lsp-bsl-bridge via document_diagnostics(uri).\n"
            "9. Save reusable verified code only: save_1c_snippet(code_snippet, description, title).\n"
            "Key pitfalls: ПрочитатьJSON→Структура (use ПрочитатьВСоответствие=Истина for Соответствие); "
            "HTTPСоединение.Получить server-only; НачатьТранзакцию needs Попытка+ОтменитьТранзакцию."
        )
        _guide_refactor = (
            "1C-HELP REFACTOR WORKFLOW:\n"
            "1. project_analysis(analysis_type='workspace_symbols', query='Name') — find symbol.\n"
            "2. symbol_explore(query='Name') or get_range_content(uri, start_line, ...) — see code.\n"
            "3. document_diagnostics(uri) — check after each edit.\n"
            "4. Rename: prepare_rename(uri, line, char) → rename(..., apply=True). Coords are 0-based.\n"
            "5. Batch edits: did_change_watched_files(language='bsl', changes_json=[{uri, type:2}]).\n"
            "URI: Docker → file:///projects/<path>. Cyrillic → URL-encode."
        )
        _guide_test = (
            "1C-HELP TEST WORKFLOW:\n"
            "1. document_diagnostics(uri) after every code edit — fix all ERROR/WARNING.\n"
            "2. URI: Docker → file:///projects/<path>; local → full file URI. Cyrillic → URL-encode.\n"
            "3. Before commit: (a) справка использована? (b) diagnostics без ERROR? (c) save_1c_snippet для нового кода?"
        )
        if task == "develop":
            return _guide_develop
        if task == "refactor":
            return _guide_refactor
        if task == "test":
            return _guide_test
        return f"{_guide_develop}\n\n{_guide_refactor}\n\n{_guide_test}"

    @mcp.prompt
    def how_to_use_1c_help_and_bsl_bridge(task: str = "all") -> str:
        """Human/onboarding prompt for using 1c-help with external lsp-bsl-bridge.
        Not the default AI route; for autonomous workflow use get_1c_quick_guide instead."""
        block_develop = """1c-HELP + external LSP — DEVELOP (human/onboarding prompt)
- AI-first route: get_1c_quick_guide(task="develop") first.
- Exact API: get_1c_api_answer(name).
- General platform lookup: search_1c_help_keyword("Тип.Метод") or search_1c_help(query) → get_1c_help_topic(topic_path=<path>).
- Local anti-hallucination context: get_1c_task_context(query, file_uri=..., symbol_name=...).
- Correct: get_1c_help_topic(topic_path="Format971.md"). Wrong: get_1c_help_topic(path=...).
- Need standards/snippets explicitly: search_1c_standards(query), search_1c_snippets(query), or legacy search_1c_memory(query, domains="standards,snippets").
- Metadata exact: search_1c_metadata_exact(query). Metadata semantic: search_1c_metadata_semantic(query). Fields: search_1c_metadata_fields(object_query, field_query).
- Empty or poor help results: first call get_1c_help_index_status to verify index.
- Save reusable verified code only: save_1c_snippet(code_snippet, description, title).
- get_form_metadata(xml_content): pass full Form.xml with all xmlns declarations. get_module_info(uri_or_path): path to Module.bsl or ObjectModule.bsl.
- URI (external lsp-bsl-bridge): Docker → file:///projects/<path>; Cyrillic in path → URL-encoding. After edit: document_diagnostics(uri) until no ERROR/WARNING."""
        block_refactor = """external LSP-BSL-BRIDGE — REFACTOR (human/onboarding prompt)
- URI: file:///projects/<path> (Docker). Cyrillic in path must be URL-encoded (e.g. /МойМодуль/ → /%D0%9C%D0%BE%D0%B9%D0%9C%D0%BE%D0%B4%D1%83%D0%BB%D1%8C/).
- Main navigation: project_analysis(analysis_type="workspace_symbols", query="Name") → symbol_explore(query="Name") or get_range_content(uri, start_line, ...). definition/hover/call_graph often return empty — they require exact symbol position (0-based line/character) and may not find all symbols; use as optional, not primary.
- Coordinates are 0-based (line 0 = first line). Use "Recommended hover coordinate" from project_analysis output.
- Flow: project_analysis → edit one file → document_diagnostics(uri) → after batch: did_change_watched_files(language="bsl", changes_json=[{"uri":"file:///...", "type":2}]).
- Rename: prepare_rename(uri, line, character) then rename(..., new_name, apply=True). Coordinates 0-based from project_analysis."""
        block_test = """external LSP-BSL-BRIDGE — TEST (human/onboarding prompt)
- After any code edit: document_diagnostics(uri) → fix until no ERROR/WARNING. URI: file:///projects/<path> (Docker) or full file URI locally; Cyrillic paths → URL-encoding.
- Checklist before commit: get_1c_quick_guide used? document_diagnostics clean (no ERROR/WARNING)? save_1c_snippet only for reusable verified code?"""
        if task == "develop":
            return block_develop
        if task == "refactor":
            return block_refactor
        if task == "test":
            return block_test
        return """Human/onboarding guide for 1c-help + external lsp-bsl-bridge. For AI work prefer get_1c_quick_guide and call this prompt only when you need a long manual reference. For a shorter block pass task=develop|refactor|test.

---
1) WHEN TO USE WHICH MCP
- Only 1c-help: API reference, code examples, form/module metadata (get_module_info, get_form_metadata), version comparison (compare_1c_help), saving snippets (save_1c_snippet).
- Also use external lsp-bsl-bridge: after editing code (document_diagnostics), navigation (project_analysis, symbol_explore), refactoring (prepare_rename, rename), after batch edits (did_change_watched_files).

---
2) 1c-HELP — ORDER OF CALLS
- Exact API: get_1c_api_answer(name) first for Тип.Метод. General platform topics: search_1c_help(query) or search_1c_help_keyword with exact API name (e.g. "МенеджерКриптографии.Подписать") → get_1c_help_topic(topic_path=<path>) using path from results. IMPORTANT: parameter is topic_path, not path. Example: get_1c_help_topic(topic_path="8.3.27/shcntx_ru/...CryptoManager.html").
- Task-local context: get_1c_task_context(query, file_uri=..., symbol_name=...).
- Need explicit standards/snippets: search_1c_standards(query), search_1c_snippets(query), or legacy search_1c_memory(query, domains="standards,snippets").
- Empty or poor results: call get_1c_help_index_status first to check index health → then search_1c_help_keyword with exact Тип.Метод.
- After working code: save_1c_snippet(code_snippet, description, title) only for reusable verified code.
- get_form_metadata(xml_content): pass full Form.xml with all xmlns; truncated XML returns empty attributes. get_module_info(uri_or_path): path to Module.bsl or ObjectModule.bsl.
- For methods always use full Тип.Метод in search_1c_help_keyword and get_1c_function_info.
- Use search_1c_memory(domains=...) only as umbrella legacy tool when separate standards/snippets routes are not enough.

---
3) LSP-BSL-BRIDGE — ORDER OF CALLS
- After any code edit: document_diagnostics(uri) → fix until no ERROR/WARNING.
- URI (single format): Docker (volume .:/projects) → file:///projects/<path>; locally → full file URI. Paths with Cyrillic MUST be URL-encoded: /МойМодуль/ → /%D0%9C%D0%BE%D0%B9%D0%9C%D0%BE%D0%B4%D1%83%D0%BB%D1%8C/
- Coordinates are 0-based (first line = 0, first character = 0). Use "Recommended hover coordinate" from project_analysis output for definition/hover/call_graph.
- Navigation (primary): project_analysis(analysis_type="workspace_symbols", query="SymbolName") → symbol_explore(query="SymbolName") or get_range_content(uri, start_line, start_character, end_line, end_character). definition, hover, call_graph, call_hierarchy often return empty — they require exact symbol position and may fail even with correct coords; treat as optional.
- Refactoring: project_analysis first → edit one file → document_diagnostics → after batch: did_change_watched_files(language="bsl", changes_json=[{"uri":"file:///...", "type":2}]).

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
- get_1c_metadata_object(object_id, config_version=None): details for one object (requisites, tabular sections). Pass config_version from metadata search to avoid ambiguity.
- get_1c_task_context(query, file_uri=None, symbol_name=None, diagnostics_json=None): compact anti-hallucination context for AI.

---
6) LIMITS
- query and xml_content: up to 64 KB. Topic content preview: MCP_MAX_TOPIC_CHARS (default 4000). Full topic: get_1c_help_topic(topic_path). Bulk topics: get_1c_help_topics_bulk(paths=[...]). Full report: docs/mcp-1c-help-tools-report.md."""

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
2. Тема/keyword: search_1c_help_keyword("Тип.Метод") → get_1c_help_topic(topic_path=<path>)
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
    """Fast entry point: run MCP without loading the full CLI (python -m onec_help.mcp_server)."""
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
    from . import env_config

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
