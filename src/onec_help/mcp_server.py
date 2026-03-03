"""MCP server for 1C Help: search_1c_help, get_1c_help_topic, get_1c_function_info."""

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from ._utils import format_duration, safe_error_message


def _snippet_max_chars() -> int:
    """Snippet length for search results. env MCP_SNIPPET_MAX_CHARS (default 1200)."""
    try:
        v = os.environ.get("MCP_SNIPPET_MAX_CHARS", "1200")
        return max(100, min(5000, int(v)))
    except (TypeError, ValueError):
        return 1200


def _max_topic_content_chars() -> int:
    """Max chars per topic in get_1c_code_answer/search_with_content. env MCP_MAX_TOPIC_CHARS (default 4000)."""
    try:
        v = os.environ.get("MCP_MAX_TOPIC_CHARS", "4000")
        return max(500, min(50000, int(v)))
    except (TypeError, ValueError):
        return 4000


MAX_QUERY_CHARS = 65536  # 64 KB
MAX_CODE_SNIPPET_CHARS = 65536  # 64 KB
_RATE_LIMIT_REQUESTS = 120
_RATE_LIMIT_WINDOW_SEC = 60
_rate_timestamps: list[float] = []
_rate_lock = threading.Lock()


def _check_rate_limit() -> str | None:
    """Return error message if over rate limit, else None. MCP_RATE_LIMIT_PER_MIN=0 disables."""
    limit = 0
    try:
        limit = int(os.environ.get("MCP_RATE_LIMIT_PER_MIN", str(_RATE_LIMIT_REQUESTS)))
    except ValueError:
        limit = _RATE_LIMIT_REQUESTS
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

_HELP_PATH = None  # Path | None


def _get_help_path() -> Path:
    if _HELP_PATH is None:
        import os

        p = (os.environ.get("HELP_PATH") or "").strip()
        if p:
            return Path(p)
        # Default: data/ relative to cwd — out-of-box without env
        return Path("data").resolve()
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


def run_mcp(
    help_path: Path,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8050,
    path: str = "/mcp",
) -> None:
    """Run MCP server. help_path: directory with .md or HTML.
    transport: stdio | sse | http | streamable-http. For http/sse, host/port/path used."""
    global _HELP_PATH
    _HELP_PATH = help_path.resolve()

    if not _HAS_FASTMCP:
        raise RuntimeError("fastmcp required: pip install fastmcp")

    mcp = FastMCP("1C Help")

    @mcp.tool()
    def search_1c_help(
        query: str,
        limit: int = 8,
        version: str | None = None,
        language: str | None = None,
        include_user_memory: bool = False,
    ) -> str:
        """Search 1C help by natural language (semantic). Returns list of relevant topics with title, path, and snippet.
        For code answers prefer get_1c_code_answer. For exact API names use search_1c_help_keyword.
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
        suffix = " [help]" if memory_results else ""
        for r in results:
            lines.append(f"{idx}. **{r.get('title', '')}** (path: {r.get('path', '')}){suffix}")
            text = r.get("text", "")[: _snippet_max_chars()]
            lines.append(f"   {text}...")
            idx += 1
        for m in memory_results:
            payload = m.get("payload", {})
            title = payload.get("title", "") or payload.get("summary", "")[:80]
            d = payload.get("domain", "")
            src = (
                " [пример]"
                if d == "snippets"
                else (" [инструкция]" if d == "community_help" else " [memory]")
            )
            lines.append(f"{idx}. **{title}**{src}")
            lines.append(f"   {str(payload)[: _snippet_max_chars()]}...")
            idx += 1
        return "\n".join(lines)

    @mcp.tool()
    def search_1c_help_keyword(
        query: str,
        limit: int = 10,
        version: str | None = None,
        language: str | None = None,
    ) -> str:
        """Search 1C help by exact substring/BM25 in title and text (e.g. 'Формат', 'ПроцессорВыводаРезультатаКомпоновкиДанныхВКоллекциюЗначений').
        Use when semantic search misses specific API names or returns irrelevant results.
        For code answers prefer get_1c_code_answer. For method names like Type.Method (e.g. HTTPСоединение.Получить) pass the full string.
        limit: max results (default 10). version, language: optional filters.
        Tip: if no matches, try search_1c_help for semantic search or synonym (e.g. ПакетПолучения → ВыполнитьПакет)."""
        err = _check_rate_limit()
        if err:
            return err
        q, err = _truncate_if_needed((query or "").strip(), MAX_QUERY_CHARS, "query")
        if err:
            return err
        results = _search_keyword(
            q,
            limit=limit,
            version=version,
            language=language,
        )
        if not results:
            return "No keyword matches. Try search_1c_help for semantic search."
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.get('title', '')}** (path: {r.get('path', '')})")
            text = r.get("text", "")[: _snippet_max_chars()]
            lines.append(f"   {text}...")
        return "\n".join(lines)

    @mcp.tool()
    def search_1c_help_with_content(
        query: str,
        limit: int = 3,
        version: str | None = None,
        language: str | None = None,
    ) -> str:
        """Search 1C help and return full content of top results in one call.
        Combines semantic + keyword search, then get_topic for each result.
        query: search text. limit: max topics with full content (default 3).
        version, language: optional filters.
        Tip: if results are irrelevant, try search_1c_help_keyword with exact API name (Тип.Метод)."""
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
    def get_1c_code_answer(
        query: str,
        limit: int = 3,
        include_memory: bool = True,
        code_only: bool = False,
        version: str | None = None,
        language: str | None = None,
    ) -> str:
        """Get code-ready answer from 1C help in one call. Best for: 'вывод СКД в таблицу', 'Формат', etc.
        Combines semantic + keyword search, full topic content, and memory. Prefer over search+get_topic chain.
        Traps: ПрочитатьJSON returns Structure by default — use ПрочитатьВСоответствие=Истина for Соответствие (Получить). HTTPСоединение.Получить — server only.
        query: natural language or API name. limit: max topics (default 3). include_memory: also search saved snippets. code_only: if True, return primarily code blocks from help.
        Tip: if results are irrelevant, call search_1c_help_keyword with exact API name (Тип.Метод), then get_1c_help_topic for full content."""
        err = _check_rate_limit()
        if err:
            return err
        q, err = _truncate_if_needed(query or "", MAX_QUERY_CHARS, "query")
        if err:
            return err
        results, meta = _hybrid_search(q, limit=limit, version=version, language=language)
        memory_parts: list[str] = []
        if include_memory:
            try:
                from .memory import get_memory_store

                for m in get_memory_store().search_long(q, limit=min(5, limit)):
                    payload = m.get("payload", {}) or {}
                    code = payload.get("code_snippet", "")
                    instruction = payload.get("instruction", "")
                    desc = payload.get("description", "") or payload.get("summary", "")[:200]
                    title = payload.get("title", "") or desc[:60]
                    d = payload.get("domain", "")
                    src = (
                        " [пример]"
                        if d == "snippets"
                        else (" [инструкция]" if d == "community_help" else "")
                    )
                    body = instruction if instruction else desc
                    link_line = ""
                    detail_url = payload.get("detail_url")
                    source_site = payload.get("source_site", "")
                    source = payload.get("source", "")
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
                        link_line = f"\n\n{attr}: {detail_url}"
                    block_base = (
                        f"### {title}{src}\n\n{body}\n\n```bsl\n{code}\n```"
                        if code
                        else f"### {title}{src}\n\n{body}"
                    )
                    block = block_base + link_line
                    memory_parts.append(block)
            except Exception as e:
                logging.getLogger(__name__).debug("get_1c_code_answer memory block failed: %s", e)
        if not results and not memory_parts:
            return (
                "No results. Ensure index exists (get_1c_help_index_status). "
                "Try search_1c_help_keyword with exact API name (e.g. ПроцессорВыводаРезультатаКомпоновкиДанныхВКоллекциюЗначений)."
            )
        parts: list[str] = [f"## Запрос: {q}"]
        if _should_show_low_score_hint(results, memory_parts, meta):
            parts.append(
                "*При нерелевантных результатах попробуйте search_1c_help_keyword с точным именем API (напр. Тип.Метод).*"
            )
        if memory_parts:
            parts.append("\n### Из памяти\n\n" + "\n\n".join(memory_parts))
        if results:
            help_blocks = []
            for r in results:
                path = r.get("path", "")
                if not path:
                    continue
                content = _get_topic(path, version=version, language=language, prefer_index=False)
                if content:
                    max_chars = _max_topic_content_chars()
                    if code_only:
                        blocks = _extract_code_blocks(content)
                        if blocks:
                            block_text = "\n\n".join(f"```bsl\n{b}\n```" for b in blocks)
                            help_blocks.append(f"---\n## {path}\n\n{block_text}")
                        else:
                            help_blocks.append(f"---\n## {path}\n\n{content[:max_chars]}...")
                    else:
                        if len(content) > max_chars:
                            content = content[:max_chars] + "\n\n..."
                        help_blocks.append(f"---\n## {path}\n\n{content}")
            if help_blocks:
                parts.append("\n### Из справки\n\n" + "\n\n".join(help_blocks))
        return "\n".join(parts)

    @mcp.tool()
    def get_1c_help_topic(
        topic_path: str,
        version: str | None = None,
        language: str | None = None,
        prefer_index: bool = False,
    ) -> str:
        """Get full help topic content in Markdown by path. Path from search results (e.g. 'zif3_CryptoManager.md').
        Content is read from disk or from index if files were not persisted.
        version, language: optional filters when reading from index.
        prefer_index: if True, read only from index (skip disk).
        Tip: get path from search_1c_help or search_1c_help_keyword first. Use topic_path (not path) parameter."""
        err = _check_rate_limit()
        if err:
            return err
        content = _get_topic(
            topic_path,
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
                    {"topic_path": topic_path, "title": title},
                )
            except Exception as e:
                logging.getLogger(__name__).debug("write_event get_topic failed: %s", e)
            return content
        return "Topic not found."

    @mcp.tool()
    def save_1c_snippet(
        code_snippet: str,
        description: str = "",
        title: str = "",
        write_to_files: bool | None = None,
    ) -> str:
        """Save a 1C code snippet to user memory for future context.
        code_snippet: the code to remember. description: short explanation. title: optional short label for search.
        write_to_files: if True, also write to SNIPPETS_DIR as .md (default: SAVE_SNIPPET_TO_FILES env)."""
        err = _check_rate_limit()
        if err:
            return err
        cs, err = _truncate_if_needed(code_snippet or "", MAX_CODE_SNIPPET_CHARS, "code_snippet")
        if err:
            return err
        try:
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
                do_write_files = os.environ.get("SAVE_SNIPPET_TO_FILES", "").lower() in (
                    "1",
                    "true",
                    "yes",
                )
            if do_write_files:
                snippets_dir = os.environ.get("SNIPPETS_DIR", "").strip()
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
    def get_form_metadata(xml_content: str) -> str:
        """Parse Form.xml content and return attributes and commands.
        xml_content: raw XML of Form.xml — must be complete with all xmlns declarations
        (v8, cfg, xs, etc.). Truncated XML without namespaces causes Parse error."""
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
    def get_module_info(uri_or_path: str) -> str:
        """Infer module type and context from file path.
        uri_or_path: path or file URI to Module.bsl / ObjectModule.bsl.
        Returns: module_type (FormModule|ObjectModule|...), form_name, object_name if detectable."""
        parts = _path_parts(uri_or_path)
        name = parts[-1] if parts else ""
        module_type = (
            "ObjectModule"
            if name == "ObjectModule.bsl"
            else "FormModule"
            if name == "Module.bsl"
            else "Unknown"
        )
        form_name = ""
        object_name = ""
        if "Forms" in parts:
            idx = parts.index("Forms")
            if idx + 1 < len(parts):
                form_name = parts[idx + 1]
            if module_type == "Unknown":
                module_type = "FormModule"
        for obj_type in ("DataProcessors", "Catalogs", "Documents"):
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

    @mcp.tool()
    def get_1c_help_related(
        topic_path: str,
        version: str | None = None,
        language: str | None = None,
    ) -> str:
        """Get list of related topics for a given help topic path.
        Returns paths and titles from outgoing links in the topic.
        topic_path: path from search results (e.g. 'Format971.md').
        version, language: optional filters when reading from index."""
        from .indexer import get_1c_help_related as _get_related

        items = _get_related(
            topic_path,
            version=version,
            language=language,
        )
        if not items:
            return "No related topics found for this path."
        lines = [f"- **{r.get('title', '')}** — `{r.get('path', '')}`" for r in items]
        return "\n".join(lines)

    @mcp.tool()
    def list_1c_help_titles(limit: int = 100, path_prefix: str = "") -> str:
        """List topic titles and paths for browsing. path_prefix: filter by path start (e.g. 'zif' for command-line params)."""
        items = _list_titles(limit=limit, path_prefix=path_prefix)
        if not items:
            return "No topics in index or prefix filter too strict."
        lines = [
            f"{i}. **{r.get('title', '')}** — `{r.get('path', '')}`" for i, r in enumerate(items, 1)
        ]
        return "\n".join(lines)

    @mcp.tool()
    def compare_1c_help(
        topic_path_or_query: str,
        version_left: str,
        version_right: str,
        language: str | None = None,
        include_diff: bool = False,
    ) -> str:
        """Compare a help topic between two platform versions.
        Prefer topic_path (e.g. 'objects/.../CryptoManager.md') from search results —
        using a query can return a different topic due to semantic search.
        topic_path_or_query: path or search query. version_left, version_right: e.g. '8.3.27.1859'.
        include_diff: if True, append unified diff of the two versions."""
        from .indexer import compare_1c_help as _compare

        return _compare(
            topic_path_or_query,
            version_left,
            version_right,
            language=language,
            include_diff=include_diff,
        )

    @mcp.tool()
    def trigger_reindex() -> str:
        """Trigger full reindex (ingest) in the background. Use when help sources changed.
        Returns immediately; indexing runs asynchronously. Check progress with get_1c_help_index_status."""
        import subprocess
        import sys

        try:
            subprocess.Popen(
                [sys.executable, "-m", "onec_help", "ingest"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return "Reindex started in background. Check get_1c_help_index_status for progress."
        except Exception as e:
            return f"Failed to start reindex: {safe_error_message(e)}"

    @mcp.tool()
    def get_1c_help_index_status() -> str:
        """Returns index status (topics count, collection, versions, languages) and ingest progress.
        When ingest is running: current file, ETA, speed, errors. Use after trigger_reindex to check progress."""
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
        storage_path = os.environ.get("QDRANT_STORAGE_PATH")
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

    def _match_priority(name_lower: str, title_lower: str) -> int:
        """Lower = better. 0=exact, 1=startswith+space/(, 2=in, 3=no match."""
        if title_lower == name_lower:
            return 0
        if title_lower.startswith(name_lower + " ") or title_lower.startswith(name_lower + "("):
            return 1
        if name_lower in title_lower:
            return 2
        return 3

    @mcp.tool()
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
        results = _search_keyword(name_clean, limit=20)
        if not results:
            results = _search(name_clean, limit=20)
        name_lower = name_clean.lower()
        scored = [(r, _match_priority(name_lower, (r.get("title") or "").lower())) for r in results]
        relevant = [(r, p) for r, p in scored if p <= 2]
        if not relevant:
            relevant = scored
        relevant.sort(key=lambda x: x[1])
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

    if transport in ("sse", "http", "streamable-http"):
        path_val = (path or "/mcp").rstrip("/") or "/mcp"
        mcp.run(transport=transport, host=host, port=port, path=path_val)
    else:
        mcp.run(transport="stdio")
