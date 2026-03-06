"""Tests for parse_helpf."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import onec_help.parse_helpf as parse_helpf_module
from onec_help.parse_helpf import (
    _extract_faq_links,
    _extract_file_links,
    _extract_freelance_links,
    _extract_help_links,
    _is_title_plus_noise,
    parse_faq_detail,
    parse_file_detail,
    run_parse,
)


def test_extract_faq_links_absolute_path() -> None:
    """Extract FAQ links with absolute href /faq/view/ID.html (page 1)."""
    html = '<a href="/faq/view/1922.html">Программная проверка счета</a>'
    items = _extract_faq_links(html)
    assert len(items) == 1
    assert items[0][0] == "Программная проверка счета"
    assert items[0][1] == "https://helpf.pro/faq/view/1922.html"


def test_extract_faq_links_relative_path() -> None:
    """Extract FAQ links with relative href faq/view/ID.html (page 2+)."""
    html = '<a href="faq/view/1912.html">Другой FAQ</a>'
    items = _extract_faq_links(html)
    assert len(items) == 1
    assert items[0][1] == "https://helpf.pro/faq/view/1912.html"


def test_extract_file_links() -> None:
    """Extract file links with /file/view/ or file/view/."""
    html = '<a href="file/view/some-file.html">Полезный файл</a>'
    items = _extract_file_links(html)
    assert len(items) == 1
    assert items[0][1] == "https://helpf.pro/file/view/some-file.html"


def test_extract_help_links() -> None:
    """_extract_help_links extracts /help/view/ or help/view/ links."""
    html = '<a href="help/view/12345.html">Статья справки</a>'
    items = _extract_help_links(html)
    assert len(items) == 1
    assert "12345" in items[0][1]
    assert items[0][0] == "Статья справки"


def test_extract_freelance_links() -> None:
    """_extract_freelance_links extracts /freelance/view/ links, skips short titles."""
    html = '<a href="freelance/view/99.html">Проект на фрилансе</a>'
    items = _extract_freelance_links(html)
    assert len(items) == 1
    assert "99" in items[0][1]
    assert items[0][0] == "Проект на фрилансе"


def test_is_title_plus_noise() -> None:
    """_is_title_plus_noise: desc equals title or title + short tail."""
    assert _is_title_plus_noise("", "") is True
    assert _is_title_plus_noise("Same", "Same") is True
    assert _is_title_plus_noise("Title", "Other") is False
    assert _is_title_plus_noise("Title <tags>", "Title") is True
    assert _is_title_plus_noise("Title" + " x" * 40, "Title") is False
    assert _is_title_plus_noise("Заголовок Категория", "Заголовок") is True


def test_extract_faq_links_regex_fallback() -> None:
    """When BeautifulSoup finds no <a> with matching href, regex fallback extracts URLs."""
    # HTML without proper <a> structure (e.g. JS-rendered or bot-blocked)
    html = """<div>Some text and hidden link: "/faq/view/9999.html"</div>"""
    items = _extract_faq_links(html)
    assert len(items) == 1
    assert items[0][1] == "https://helpf.pro/faq/view/9999.html"
    assert "9999" in items[0][0]


def test_extract_faq_links_skips_query_in_href_fallback() -> None:
    """_extract_faq_links skips href with ? in soup path; regex fallback still finds URL."""
    html = '<a href="/faq/view/1922.html?foo=1">Title</a>'
    items = _extract_faq_links(html)
    assert len(items) == 1
    assert items[0][0] == "HelpF #1922"


def test_extract_faq_links_skips_short_title_fallback() -> None:
    """_extract_faq_links skips short title in soup; regex fallback adds entry."""
    html = '<a href="/faq/view/99.html">Ab</a>'
    items = _extract_faq_links(html)
    assert len(items) == 1
    assert "99" in items[0][0]


def test_extract_file_links_skips_submit_button_title_fallback() -> None:
    """_extract_file_links skips 'Подробнее' in soup; regex fallback adds entry."""
    html = '<a href="/file/view/x.html">Подробнее</a>'
    items = _extract_file_links(html)
    assert len(items) == 1
    assert items[0][1] == "https://helpf.pro/file/view/x.html"


def test_detect_faq_pages_via_run_parse_pages_none(tmp_path: Path) -> None:
    """run_parse with pages=None calls _detect_faq_pages (html with 'на N страницах')."""
    listing_html = '<html><body>на 2 страницах <a href="/faq/view/1.html">One</a></body></html>'
    out = tmp_path / "out.json"

    def mock_fetch_url(url: str, _opener) -> str:
        return listing_html if "faq" in url else "<html><body></body></html>"

    with (
        patch.object(parse_helpf_module, "_get_opener", return_value=MagicMock()),
        patch.object(parse_helpf_module, "fetch_url", side_effect=mock_fetch_url),
        patch("time.sleep"),
    ):
        run_parse(out, source="faq", pages=None, fetch_detail=False, max_items=10)
    assert out.exists()
    data = __import__("json").loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list)


def test_is_title_plus_noise_true() -> None:
    """Title + short tag suffix is noise."""
    assert _is_title_plus_noise("ИР Найти в спискеTurboConf ИР", "ИР Найти в списке") is True


def test_is_title_plus_noise_false_long_rest() -> None:
    """Long rest is real content."""
    assert (
        _is_title_plus_noise(
            "Заголовок При использовании Git эта команда адаптера открывает инструмент.",
            "Заголовок",
        )
        is False
    )


def test_parse_faq_detail() -> None:
    """parse_faq_detail extracts description and code."""
    html = """
    <html><body>
    <h1>Программная проверка счета на групповой</h1>
    <p>Как известно делать проводки по счетам-группам нельзя.</p>
    <pre>Процедура ПриЗаписи(Отказ)
        Запрос = Новый Запрос;
    КонецПроцедуры</pre>
    </body></html>
    """
    desc, code = parse_faq_detail(html, "Проверка")
    assert "проверка счета" in desc.lower()
    assert "проводки" in desc
    assert "Процедура ПриЗаписи" in code


def test_parse_faq_detail_skips_razmestil() -> None:
    """parse_faq_detail skips 'Разместил:' paragraphs."""
    html = """
    <html><body><h1>Тема</h1>
    <p>Разместил: User1 Дата: 01.01.2020</p>
    <p>Реальный контент с полезной информацией для разработчика.</p>
    </body></html>
    """
    desc, code = parse_faq_detail(html, "Тема")
    assert "Разместил" not in desc
    assert "Реальный контент" in desc


def test_parse_faq_detail_includes_h1_and_skips_pohozhie() -> None:
    """parse_faq_detail always includes h1, skips 'Похожие FAQ' footer."""
    html = """
    <html><body>
    <h1>Программная проверка счета на групповой</h1>
    <span class="break-word">Краткое описание проверки проводок.</span>
    <p>Основной текст инструкции для разработчика 1С.</p>
    <p>Похожие FAQ: другие темы на эту же тему.</p>
    </body></html>
    """
    desc, code = parse_faq_detail(html, "Другой заголовок")
    assert "Программная проверка счета" in desc
    assert "Краткое описание" in desc
    assert "Основной текст инструкции" in desc
    assert "Похожие FAQ" not in desc


def test_parse_file_detail() -> None:
    """parse_file_detail extracts from File page."""
    html = """
    <html><body>
    <p>Конфигурация 1с для учета оргтехники и ТМЦ в офисе.</p>
    </body></html>
    """
    desc, code = parse_file_detail(html, "Учет оргтехники")
    assert "Учет оргтехники" in desc
    assert "оргтехники" in desc
    assert code == ""


def test_run_parse_faq_mocked(tmp_path: Path) -> None:
    """run_parse with mocked fetch produces JSON output."""
    import json

    listing_html = """
    <html><body>
    <a href="/faq/view/1922.html">Программная проверка счета</a>
    </body></html>
    """
    detail_html = """
    <html><body>
    <h1>Программная проверка счета на групповой</h1>
    <p>Как известно делать проводки по счетам-группам нельзя.</p>
    </body></html>
    """
    out = tmp_path / "faq_snippets.json"

    def mock_faq_listing(_p: int, _o) -> str:
        return listing_html

    orig = parse_helpf_module._SOURCE_CONFIG["faq"]
    patched_faq = (mock_faq_listing, orig[1], orig[2], orig[3])
    patched_config = {**parse_helpf_module._SOURCE_CONFIG, "faq": patched_faq}

    with (
        patch.object(parse_helpf_module, "_get_opener", return_value=MagicMock()),
        patch.object(parse_helpf_module, "_SOURCE_CONFIG", patched_config),
        patch.object(
            parse_helpf_module,
            "fetch_url",
            side_effect=lambda _url, _o: detail_html,
        ),
        patch("time.sleep"),
    ):
        result = run_parse(out, source="faq", pages=[1], fetch_detail=True, max_items=2)

    assert result == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) >= 1
    assert any("проверка" in (i.get("title") or "").lower() for i in data)


def test_run_parse_file_mocked(tmp_path: Path) -> None:
    """run_parse with source=file and mocked fetch."""
    import json

    listing_html = """
    <html><body>
    <a href="/file/view/test-file.html">Тестовый файл</a>
    </body></html>
    """
    detail_html = """
    <html><body>
    <p>Описание файла для тестирования парсера HelpF.</p>
    </body></html>
    """
    out = tmp_path / "file_snippets.json"

    def mock_file_listing(_p: int, _o) -> str:
        return listing_html

    orig = parse_helpf_module._SOURCE_CONFIG["file"]
    patched_file = (mock_file_listing, orig[1], orig[2], orig[3])
    patched_config = {**parse_helpf_module._SOURCE_CONFIG, "file": patched_file}

    with (
        patch.object(parse_helpf_module, "_get_opener", return_value=MagicMock()),
        patch.object(parse_helpf_module, "_SOURCE_CONFIG", patched_config),
        patch.object(
            parse_helpf_module,
            "fetch_url",
            side_effect=lambda _url, _o: detail_html,
        ),
        patch("time.sleep"),
    ):
        result = run_parse(out, source="file", pages=[1], fetch_detail=True, max_items=2)

    assert result == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) >= 1
