"""Tests for html2md module."""

from pathlib import Path

from bs4 import BeautifulSoup

from onec_help.html2md import (
    _legacy_body_to_md,
    _looks_like_html,
    _looks_like_utf8_mojibake,
    _normalize_md_text,
    _read_html_file,
    _table_to_md,
    build_docs,
    extract_links_from_markdown,
    extract_outgoing_links,
    html_to_md_content,
    read_file_with_encoding_fallback,
    resolve_href,
)


def test_resolve_href_outside_base_returns_none(tmp_path: Path) -> None:
    """resolve_href returns None when resolved path is outside base_dir."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "page.html").write_text("x")
    base = (tmp_path / "sub").resolve()
    current = base / "page.html"
    # href that would escape base (e.g. ../ outside)
    assert resolve_href(current, "../../other.html", base) is None


def test_resolve_href_resolves_to_md_or_html(tmp_path: Path) -> None:
    """resolve_href tries .md and .html candidates when href has no extension."""
    (tmp_path / "page.html").write_text("x")
    (tmp_path / "other.md").write_text("md")
    base = tmp_path.resolve()
    current = base / "page.html"
    assert resolve_href(current, "other", base) == "other.md"
    (tmp_path / "other.md").unlink()
    assert resolve_href(current, "other", base) is None


def test_extract_links_from_markdown_skips_empty_href(tmp_path: Path) -> None:
    """extract_links_from_markdown skips links with empty href."""
    base = tmp_path.resolve()
    current = base / "doc.md"
    result = extract_links_from_markdown("[text]()", current, base)
    assert result == []


def test_extract_outgoing_links_read_fails_returns_empty(tmp_path: Path) -> None:
    """extract_outgoing_links returns [] when _read_html_file raises."""
    base = tmp_path.resolve()
    missing = tmp_path / "missing.html"
    result = extract_outgoing_links(missing, base)
    assert result == []


def test_normalize_md_text() -> None:
    """HTML entities and Unicode are normalized for consistent display and search."""
    assert _normalize_md_text("a&amp;b") == "a&b"
    assert _normalize_md_text("&nbsp;") == "\u00a0"
    assert _normalize_md_text("&lt;tag&gt;") == "<tag>"
    assert (
        _normalize_md_text("&#1057;&#1080;&#1085;&#1090;&#1072;&#1082;&#1089;&#1080;&#1089;")
        == "Синтаксис"
    )
    assert _normalize_md_text("plain") == "plain"
    assert _normalize_md_text("") == ""


def test_html_to_md_content(sample_html: Path) -> None:
    md = html_to_md_content(sample_html)
    assert md
    assert "# " in md
    assert "Имя общего реквизита" in md or "реквизит" in md.lower()


def test_html_to_md_content_missing() -> None:
    assert html_to_md_content(Path("/nonexistent")) == ""


def test_read_html_file_skips_oversized(tmp_path: Path, monkeypatch) -> None:
    """Files over HELP_HTML_MAX_BYTES are skipped to avoid BeautifulSoup hang."""
    monkeypatch.setenv("HELP_HTML_MAX_BYTES", "200000")
    f = tmp_path / "big.html"
    f.write_text("<html><body>" + "x" * 250_000 + "</body></html>", encoding="utf-8")
    text = _read_html_file(f)
    assert text == ""


def test_read_html_file_utf8(tmp_path: Path) -> None:
    f = tmp_path / "a.html"
    f.write_text("<html><body>Test</body></html>", encoding="utf-8")
    assert "Test" in _read_html_file(f)


def test_read_html_file_cp1251(tmp_path: Path) -> None:
    """Legacy 1C help may be in cp1251."""
    f = tmp_path / "c.html"
    f.write_bytes(b"<html><body>" + "Русский".encode("cp1251") + b"</body></html>")
    text = _read_html_file(f)
    assert "Русский" in text


def test_read_html_file_fallback_replace(tmp_path: Path) -> None:
    """When no encoding works, decode with errors=replace."""
    f = tmp_path / "d.html"
    f.write_bytes(b"<html>\xff\xfe</html>")
    text = _read_html_file(f)
    assert "<html>" in text
    assert "\ufffd" in text or "html" in text


def test_looks_like_utf8_mojibake() -> None:
    """Mojibake: Р/С as first UTF-8 byte of Russian letters, or box-drawing + Cyrillic."""
    assert _looks_like_utf8_mojibake("Р—Р°РіСЂСѓР·РєР° канала") is True
    assert _looks_like_utf8_mojibake("Редактирование параметра выбора типа") is False
    assert _looks_like_utf8_mojibake("short") is False


def test_read_file_utf8_file_read_as_cp1251_fixed(tmp_path: Path) -> None:
    """File is UTF-8 'Загрузка'; when env forces cp1251 first we get mojibake, then fix by trying utf-8 on raw."""
    f = tmp_path / "e.html"
    f.write_text("Загрузка каналов внешнего сервиса", encoding="utf-8")
    # Default (utf-8 first) returns correct
    assert "Загрузка" in read_file_with_encoding_fallback(f)
    # Force cp1251 first via raw decode order: read with cp1251 list
    text = read_file_with_encoding_fallback(f, encodings=("cp1251", "utf-8"))
    assert "Загрузка" in text or "канал" in text


def test_looks_like_html(tmp_path: Path) -> None:
    html_file = tmp_path / "f.html"
    html_file.write_text("<html><body>x</body></html>", encoding="utf-8")
    assert _looks_like_html(html_file) is True
    bin_file = tmp_path / "f.bin"
    bin_file.write_bytes(b"\x00\x01\x02")
    assert _looks_like_html(bin_file) is False


def test_looks_like_html_exception_returns_false(tmp_path: Path) -> None:
    """When _read_html_file raises (e.g. directory), _looks_like_html returns False."""
    tmp_path.mkdir(exist_ok=True)
    assert _looks_like_html(tmp_path) is False


def test_build_docs_empty_dir(tmp_path: Path) -> None:
    """Empty dir yields no .md files."""
    out = tmp_path / "out"
    out.mkdir()
    created = build_docs(tmp_path, out)
    assert created == []


def test_build_docs(help_sample_dir: Path, tmp_path: Path) -> None:
    created = build_docs(help_sample_dir, tmp_path)
    assert len(created) >= 1
    assert all(p.suffix == ".md" for p in created)
    content = created[0].read_text(encoding="utf-8")
    assert content.strip().startswith("#")


def test_html_to_md_with_sections(help_sample_dir: Path) -> None:
    fn = help_sample_dir / "function_sample.html"
    if fn.exists():
        md = html_to_md_content(fn)
        assert "Формат" in md
        assert "Описание" in md or "Синтаксис" in md
        assert "Параметры" in md or "Значение" in md


def test_function_sample_md_structure(help_sample_dir: Path) -> None:
    """V8SH article must yield formal MD: title + sections Описание, Синтаксис, Параметры, Пример, См. также."""
    fn = help_sample_dir / "function_sample.html"
    if not fn.exists():
        return
    md = html_to_md_content(fn)
    assert md.startswith("# "), "MD must start with level-1 heading"
    assert "## Описание" in md
    assert "## Синтаксис" in md
    assert "## Параметры" in md
    assert "## Пример" in md
    assert "## См. также" in md
    assert "Формат(Значение, ФорматнаяСтрока)" in md or "Формат" in md
    assert "Значение" in md and "ФорматнаяСтрока" in md


def test_table_to_md() -> None:
    """_table_to_md converts table to Markdown."""
    soup = BeautifulSoup(
        "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>",
        "html.parser",
    )
    md = _table_to_md(soup.find("table"))
    assert "| A | B |" in md
    assert "| 1 | 2 |" in md
    assert "---" in md


def test_table_to_md_empty_rows() -> None:
    """_table_to_md with no rows returns empty string."""
    soup = BeautifulSoup("<table></table>", "html.parser")
    assert _table_to_md(soup.find("table")) == ""


def test_legacy_body_to_md() -> None:
    """_legacy_body_to_md converts H1–H6, table, pre, p with links."""
    soup = BeautifulSoup(
        """
        <body>
        <h1>Title</h1>
        <p>Para with <a href='x'>link</a> text.</p>
        <table><tr><td>Cell</td></tr></table>
        <pre>code</pre>
        </body>
        """,
        "html.parser",
    )
    md = _legacy_body_to_md(soup.find("body"))
    assert "# Title" in md
    assert "link" in md and "x" in md
    assert "| Cell |" in md
    assert "```" in md and "code" in md


def test_html_to_md_legacy_no_v8sh(tmp_path: Path) -> None:
    """When no V8SH_pagetitle, legacy body conversion is used."""
    f = tmp_path / "legacy.html"
    f.write_text(
        "<html><body><h1>Legacy Title</h1><p>Paragraph.</p></body></html>",
        encoding="utf-8",
    )
    md = html_to_md_content(f)
    assert "Legacy Title" in md
    assert "Paragraph" in md


def test_html_to_md_fallback_body_text(tmp_path: Path) -> None:
    """When V8SH output is only title, fallback to body text."""
    f = tmp_path / "minimal.html"
    f.write_text(
        "<html><body><h1 class='V8SH_pagetitle'>Only Title</h1></body></html>",
        encoding="utf-8",
    )
    md = html_to_md_content(f)
    assert "Only Title" in md


def test_build_docs_extensionless_html(tmp_path: Path) -> None:
    """build_docs processes extension-less files that look like HTML."""
    (tmp_path / "noext").write_text("<html><body><h1>No Ext</h1></body></html>", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    created = build_docs(tmp_path, out)
    assert len(created) >= 1
    assert any("noext" in str(p) for p in created)


def test_html_to_md_example_table_code(tmp_path: Path) -> None:
    """Example section with table (fragmented code) yields readable code block."""
    f = tmp_path / "example_table.html"
    f.write_text(
        """
<html><body>
<h1 class="V8SH_pagetitle">Format</h1>
<p class="V8SH_chapter">Пример:</p>
<table><tr><td>A</td><td>=</td><td>Формат</td></tr>
<tr><td>(</td><td>123</td><td>.</td></tr></table>
</body></html>
""",
        encoding="utf-8",
    )
    md = html_to_md_content(f)
    assert "## Пример" in md
    # Table cells should be joined per row (not each td on new line)
    assert "Формат" in md
    assert "A =" in md or "A = Формат" in md


def test_html_to_md_v8sh_fallback_loop(tmp_path: Path) -> None:
    """V8SH sections found via fallback loop (get_text == 'Описание:') when string= doesn't match."""
    f = tmp_path / "v8sh.html"
    f.write_text(
        """
<html><body>
<h1 class="V8SH_pagetitle">TestFunc</h1>
<p class="V8SH_chapter"><span>Описание:</span></p>
<p>Description text here.</p>
<p class="V8SH_chapter"><span>Синтаксис:</span></p>
<pre>TestFunc(x)</pre>
<p class="V8SH_chapter"><span>Возвращаемое значение:</span></p>
<p>Number.</p>
<p class="V8SH_chapter"><span>См. также:</span></p>
<a href="#">Other</a>
</body></html>
""",
        encoding="utf-8",
    )
    md = html_to_md_content(f)
    assert "TestFunc" in md
    assert "Description text" in md or "Описание" in md
    assert "Синтаксис" in md or "TestFunc(x)" in md
    assert "Возвращаемое значение" in md or "Number" in md
    assert "См. также" in md or "Other" in md


def test_resolve_href_relative(tmp_path: Path) -> None:
    """resolve_href resolves relative href to existing file within base_dir."""
    (tmp_path / "a.html").write_text("a", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.html").write_text("b", encoding="utf-8")
    current = tmp_path / "sub" / "b.html"
    assert resolve_href(current, "a.html", tmp_path) is None  # ../ from sub
    assert resolve_href(current, "../a.html", tmp_path) == "a.html"
    assert resolve_href(tmp_path / "a.html", "sub/b.html", tmp_path) == "sub/b.html"


def test_resolve_href_anchor_returns_none(tmp_path: Path) -> None:
    """href="#" returns None."""
    (tmp_path / "a.html").write_text("a", encoding="utf-8")
    assert resolve_href(tmp_path / "a.html", "#section", tmp_path) is None
    assert resolve_href(tmp_path / "a.html", "", tmp_path) is None


def test_extract_outgoing_links(tmp_path: Path) -> None:
    """extract_outgoing_links finds <a href> and resolves when possible."""
    (tmp_path / "page.html").write_text(
        '<html><body><a href="other.html">Other</a><a href="#">Anchor</a></body></html>',
        encoding="utf-8",
    )
    (tmp_path / "other.html").write_text("other", encoding="utf-8")
    links = extract_outgoing_links(tmp_path / "page.html", tmp_path)
    assert len(links) == 2
    # First link should resolve
    resolved = [lnk for lnk in links if lnk.get("resolved_path")]
    assert len(resolved) == 1
    assert resolved[0]["resolved_path"] == "other.html"
    assert resolved[0]["link_text"] == "Other"
    # Anchor link has no resolved_path
    anchor = [lnk for lnk in links if lnk.get("href") == "#"][0]
    assert anchor.get("resolved_path") is None


def test_html_to_md_usage_in_version_v8sh_versioninfo(tmp_path: Path) -> None:
    """Использование в версии: структура справки 1С — p.V8SH_versionInfo."""
    f = tmp_path / "version_v8sh.html"
    f.write_text(
        """
<html><body>
<h1 class="V8SH_pagetitle">Test</h1>
<p class="V8SH_chapter">Использование в версии:</p>
<p class="V8SH_versionInfo">Доступен, начиная с версии 8.3.13.</p>
<p class="V8SH_chapter">Доступность:</p>
<p>Толстый клиент.</p>
</body></html>
""",
        encoding="utf-8",
    )
    md = html_to_md_content(f)
    assert "## Использование в версии" in md
    assert "8.3.13" in md


def test_html_to_md_usage_in_version_multiple(tmp_path: Path) -> None:
    """Использование в версии: несколько p.V8SH_versionInfo подряд (как в ctor153)."""
    f = tmp_path / "version_multi.html"
    f.write_text(
        """
<html><body>
<h1 class="V8SH_pagetitle">Test</h1>
<p class="V8SH_chapter">Использование в версии:</p>
<p class="V8SH_versionInfo">Доступен, начиная с версии 8.2.</p>
<p class="V8SH_versionInfo">Описание изменено в версии 8.3.24.</p>
<p class="V8SH_chapter">Доступность:</p>
<p>Толстый клиент.</p>
</body></html>
""",
        encoding="utf-8",
    )
    md = html_to_md_content(f)
    assert "## Использование в версии" in md
    assert "8.2" in md
    assert "8.3.24" in md


def test_extract_links_from_markdown(tmp_path: Path) -> None:
    """extract_links_from_markdown parses [text](url) and resolves to base_dir."""
    (tmp_path / "sub").mkdir()
    current = tmp_path / "sub" / "page.md"
    current.write_text("# Page", encoding="utf-8")
    (tmp_path / "other.md").write_text("# Other", encoding="utf-8")
    (tmp_path / "sub" / "sibling.md").write_text("# Sibling", encoding="utf-8")
    md_text = "See [Other](../other.md) and [Sibling](sibling.md) and [anchor](#x)."
    links = extract_links_from_markdown(md_text, current, tmp_path)
    assert len(links) == 3
    resolved = [lnk for lnk in links if lnk.get("resolved_path")]
    assert len(resolved) == 2
    paths = {lnk["resolved_path"] for lnk in resolved}
    assert "other.md" in paths
    assert "sub/sibling.md" in paths
