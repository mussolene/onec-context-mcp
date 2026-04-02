"""BSL (1C) code parsing utilities — extraction of procedures and functions."""

import re
from typing import Any

# Split by procedure/function end markers (avoid matching inside string literals with |)
_SPLIT_RE = re.compile(
    r"([^\|]КонецФункции|[^\|]КонецПроцедуры|[^\|]EndFunction|[^\|]EndProcedure)",
    re.IGNORECASE,
)
_HEAD_FUNC_RE = re.compile(
    r"(?:Функция|Процедура|[^\.\"]Function|Procedure)\s+(?P<name>[0-9a-zA-Zа-яА-Я_]+)?\s*\([\W\w.]*?\)",
    re.MULTILINE | re.IGNORECASE,
)


def get_functions(content: str) -> list[str]:
    """Split BSL module content by procedure/function boundaries.
    Returns list of alternating [prelude, proc1, end1, proc2, end2, ...] — split retains delimiters."""
    return _SPLIT_RE.split(content)


def extract_func_name(function: str) -> str | None:
    """Extract procedure/function name from BSL code block.
    If multiple declarations (e.g. in comments), returns the last one."""
    result: str | None = None
    for match in _HEAD_FUNC_RE.finditer(function):
        result = match.group("name")
    return result


def extract_procedures_and_functions(content: str) -> list[dict[str, Any]]:
    """Extract procedures and functions as list of {name, code, line_start}.
    Useful for chunking large .bsl for indexing or per-function snippets.
    Mirrors bsl_processor pairing: block = parts[i] + parts[i+1] (body + Конец*)."""
    parts = get_functions(content)
    items: list[dict[str, Any]] = []
    line_start = 1
    for i in range(0, len(parts) - 1, 2):
        block = (parts[i] or "") + (parts[i + 1] or "")
        if not block.strip():
            continue
        name = extract_func_name(block)
        if name:
            items.append({"name": name, "code": block.strip(), "line_start": line_start})
        line_start += block.count("\n") + 1
    return items
