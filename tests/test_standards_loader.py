"""Tests for standards_loader."""

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from onec_help.knowledge.loaders.standards_loader import (
    _first_heading,
    _first_paragraph,
    collect_from_folder,
    fetch_repo_archive,
)


def test_first_heading_no_match_returns_empty() -> None:
    """When no # heading, return empty string."""
    assert _first_heading("Plain text\n\nMore") == ""


def test_first_paragraph_skips_table_and_list() -> None:
    """Paragraph stops at | or - at line start."""
    content = "# Title\n\nFirst para here.\n\n| Col |\n|-|\nSecond"
    assert "First para" in _first_paragraph(content)


def test_first_paragraph_limits_length() -> None:
    """Paragraph truncated at 200 chars then 300 total."""
    content = "# H\n\n" + ("word " * 60)
    result = _first_paragraph(content)
    assert len(result) <= 300


def test_collect_from_folder_md(tmp_path: Path) -> None:
    """Collect *.md files with title from heading."""
    (tmp_path / "rule1.md").write_text(
        "# Проверка транзакций\n\nПосле начала транзакции нужен блок Попытка-Исключение.",
        encoding="utf-8",
    )
    items = collect_from_folder(tmp_path)
    assert len(items) == 1
    assert items[0]["title"] == "Проверка транзакций"
    assert "транзакции" in items[0]["description"] or "Попытка" in items[0]["description"]
    assert "code_snippet" in items[0]


def test_collect_skips_readme(tmp_path: Path) -> None:
    """README.md is skipped."""
    (tmp_path / "README.md").write_text("# Doc\n\nContent", encoding="utf-8")
    assert collect_from_folder(tmp_path) == []


def test_collect_empty(tmp_path: Path) -> None:
    """Empty folder returns empty list."""
    assert collect_from_folder(tmp_path) == []


def test_collect_skips_unreadable_file(tmp_path: Path) -> None:
    """When read_text raises OSError, that file is skipped."""
    (tmp_path / "a.md").write_text("# A\n\nContent", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n\nContent", encoding="utf-8")
    orig = Path.read_text

    def read_text_raise_for_a(self, *args, **kwargs):
        if self.name == "a.md":
            raise OSError("permission")
        return orig(self, *args, **kwargs)

    with patch.object(Path, "read_text", read_text_raise_for_a):
        items = collect_from_folder(tmp_path)
    assert len(items) == 1
    assert items[0]["title"] == "B"


def test_fetch_repo_archive_non_github_url_raises() -> None:
    """Non-GitHub URL hits else branch; invalid owner/repo pattern raises (lines 59, 66-68)."""
    with patch("onec_help.knowledge.loaders.standards_loader.urlopen"):
        with pytest.raises(ValueError) as exc_info:
            fetch_repo_archive("https://example.com/foo/bar", branch="main")
    msg = str(exc_info.value).lower()
    assert "invalid" in msg or "owner" in msg or "alphanumeric" in msg


def test_fetch_repo_archive_non_github_url_with_dot_git() -> None:
    """Non-GitHub URL ending with .git hits line 61 (base = base[:-4])."""
    with patch("onec_help.knowledge.loaders.standards_loader.urlopen"):
        with pytest.raises(ValueError) as exc_info:
            fetch_repo_archive("https://example.com/foo/repo.git", branch="main")
    assert "invalid" in str(exc_info.value).lower() or "owner" in str(exc_info.value).lower()


def test_fetch_repo_archive_extract_fails_cleans_up() -> None:
    """When ZipFile.extractall raises, temp dir is cleaned up and exception re-raised (lines 91-93)."""
    with patch("onec_help.knowledge.loaders.standards_loader.urlopen") as mock_urlopen:
        resp = MagicMock()
        resp.read.return_value = b"fake"
        mock_urlopen.return_value.__enter__.return_value = resp
        mock_urlopen.return_value.__exit__.return_value = None
        with patch("onec_help.knowledge.loaders.standards_loader.zipfile.ZipFile") as mock_zip:
            zf = MagicMock()
            zf.extractall.side_effect = OSError("disk full")
            mock_zip.return_value.__enter__.return_value = zf
            mock_zip.return_value.__exit__.return_value = None
            with pytest.raises(OSError, match="disk full"):
                fetch_repo_archive("https://github.com/owner/repo", subpath="docs")


def test_fetch_repo_archive(tmp_path: Path) -> None:
    """fetch_repo_archive extracts zip and returns (subpath_dir, temp_dir)."""
    # Create minimal zip: repo-master/docs/rule.md
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("v8-code-style-master/docs/rule.md", "# Имя переменной\n\nОписание.")
    buf.seek(0)
    data = buf.getvalue()

    def fake_urlopen(*args, **kwargs):
        return io.BytesIO(data)

    with patch("onec_help.knowledge.loaders.standards_loader.urlopen", side_effect=fake_urlopen):
        target, temp_dir = fetch_repo_archive(
            "https://github.com/1C-Company/v8-code-style", subpath="docs"
        )
    assert target.is_dir()
    assert (target / "rule.md").exists()
    items = collect_from_folder(target)
    assert len(items) == 1
    assert "Имя переменной" in items[0]["title"]
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)


def test_fetch_repo_archive_rejects_invalid_owner() -> None:
    """Invalid owner (e.g. path traversal) raises ValueError."""
    import pytest

    with pytest.raises(ValueError, match="Invalid owner/repo"):
        fetch_repo_archive("https://github.com/../evil/repo")


def test_fetch_repo_archive_has_https_validation() -> None:
    """AUDIT-005: fetch_repo_archive enforces https scheme (SSRF protection)."""
    import onec_help.knowledge.loaders.standards_loader as sl

    src = Path(sl.__file__).read_text()
    assert 'startswith("https://")' in src
    assert "SSRF" in src
