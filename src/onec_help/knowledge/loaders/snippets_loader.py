"""Collect snippets from folder (analogous to help ingest from the help core)."""

import re
from pathlib import Path
from typing import Any

from .. import bsl_utils

_BSL_EXTENSIONS = {".bsl", ".1c"}
_CODE_BLOCK_RE = re.compile(r"```(?:bsl|1c)?\s*\n(.*?)```", re.DOTALL)
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_PER_FUNCTION_MIN_LINES = 50  # only split .bsl by functions if >= this many lines


def _parse_md_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Extract YAML frontmatter and body. Returns (params, body)."""
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content
    raw = match.group(1)
    params: dict[str, str] = {}
    for line in raw.split("\n"):
        if ":" in line:
            k, _, v = line.partition(":")
            key = k.strip().lower()
            val = v.strip().strip("'\"").strip()
            if key in ("title", "description"):
                params[key] = val
    body = content[match.end() :]
    return params, body


def _extract_code_from_md(body: str) -> str:
    """Extract first bsl/1c code block from markdown body."""
    match = _CODE_BLOCK_RE.search(body)
    if match:
        return match.group(1).strip()
    return ""


def collect_from_folder(
    dir_path: Path,
    per_function: bool = False,
    per_function_min_lines: int = _PER_FUNCTION_MIN_LINES,
) -> list[dict[str, Any]]:
    """Collect snippets from folder: *.bsl, *.1c, *.md (recursive).
    Returns list of {title, description, code_snippet}.

    per_function: if True, split large .bsl by procedures/functions (each as snippet).
    per_function_min_lines: only split when file has >= this many lines."""
    items: list[dict[str, Any]] = []

    def add_item(title: str, description: str, code: str) -> None:
        if not code:
            return
        t = (title or "Snippet").strip()
        items.append({"title": t, "description": (description or "").strip(), "code_snippet": code})

    for ext in _BSL_EXTENSIONS:
        for f in dir_path.rglob(f"*{ext}"):
            try:
                raw = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if not raw.strip():
                continue
            if per_function and raw.count("\n") >= per_function_min_lines:
                for proc in bsl_utils.extract_procedures_and_functions(raw):
                    name = proc.get("name", "")
                    if name:
                        add_item(f"{f.stem}.{name}", "", proc["code"])
            else:
                add_item(f.stem, "", raw.strip())

    for f in dir_path.rglob("*.md"):
        if f.name.lower() == "readme.md":
            continue
        try:
            raw = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        params, body = _parse_md_frontmatter(raw)
        code = _extract_code_from_md(body)
        if not code:
            continue
        title = params.get("title", f.stem)
        desc = params.get("description", "")
        add_item(title, desc, code)

    return items
