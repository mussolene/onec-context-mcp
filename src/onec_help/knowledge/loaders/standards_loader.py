"""Collect standards docs (v8-code-style markdown) for load-standards."""

import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ...shared._http import get_ssl_context

_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def _first_heading(content: str) -> str:
    """Extract first # heading from markdown."""
    m = _HEADING_RE.search(content)
    return m.group(1).strip() if m else ""


def _first_paragraph(content: str) -> str:
    """Extract first non-empty paragraph (up to 200 chars)."""
    lines = content.strip().split("\n")
    para: list[str] = []
    for line in lines:
        line = line.strip()
        if line.startswith("#") or line.startswith("|") or line.startswith("-"):
            if para:
                break
            continue
        if not line:
            if para:
                break
            continue
        para.append(line)
        if len(" ".join(para)) >= 200:
            break
    return " ".join(para)[:300].strip()


_GITHUB_REPO_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


def fetch_repo_archive(
    repo_url: str, subpath: str = "docs", branch: str = "master"
) -> tuple[Path, Path]:
    """Download GitHub repo as zip, extract to temp dir.
    Returns (path_to_subpath, temp_dir). Caller must shutil.rmtree(temp_dir) when done.
    Only https://github.com/ is allowed (SSRF protection)."""
    # Normalize: github.com/owner/repo or owner/repo
    if "github.com" in repo_url:
        base = (
            repo_url.rstrip("/")
            .replace("https://github.com/", "")
            .replace("http://github.com/", "")
        )
    else:
        base = repo_url
    if base.endswith(".git"):
        base = base[:-4]
    parts = base.strip("/").split("/")
    owner, repo = (parts[0], parts[1]) if len(parts) >= 2 else ("", base)
    if not owner or not repo:
        raise ValueError(f"Invalid repo URL: {repo_url}")
    if not _GITHUB_REPO_RE.match(owner) or not _GITHUB_REPO_RE.match(repo):
        raise ValueError(
            f"Invalid owner/repo (only alphanumeric, underscore, hyphen, dot): {owner}/{repo}"
        )
    zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
    if not zip_url.lower().startswith("https://"):
        raise ValueError("Only https:// scheme allowed (SSRF protection)")
    req = Request(zip_url, headers={"User-Agent": "onec_help/1.0"})
    with urlopen(req, timeout=60, context=get_ssl_context()) as resp:
        data = resp.read()
    tmp = Path(tempfile.mkdtemp(prefix="onec_standards_"))
    try:
        zip_path = tmp / "repo.zip"
        zip_path.write_bytes(data)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp)
        zip_path.unlink()
        # Archive extracts to owner-repo-master/ or owner-repo-main/
        extracted = next((p for p in tmp.iterdir() if p.is_dir()), None)
        if not extracted:
            raise RuntimeError("Empty archive")
        target = extracted / subpath if subpath else extracted
        if not target.exists() or not target.is_dir():
            raise RuntimeError(f"Subpath '{subpath}' not found in {extracted.name}")
        return target, tmp
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def collect_from_folder(dir_path: Path) -> list[dict[str, Any]]:
    """Collect standards from folder: *.md (recursive).
    Returns list of {title, description, code_snippet} for memory upsert."""
    items: list[dict[str, Any]] = []
    for f in dir_path.rglob("*.md"):
        if f.name.lower() == "readme.md":
            continue
        try:
            raw = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not raw.strip():
            continue
        title = _first_heading(raw) or f.stem
        desc = _first_paragraph(raw)
        rel = str(f.relative_to(dir_path)).replace("\\", "/")
        items.append(
            {
                "title": title,
                "description": desc,
                "code_snippet": raw.strip(),
                "source_ref": rel,
            }
        )
    return items
