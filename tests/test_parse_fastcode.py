"""Tests for parse_fastcode."""

from unittest.mock import MagicMock, patch

from onec_help.knowledge.loaders.parse_fastcode import (
    _detect_total_pages,
    _extract_detail_links,
    _is_safe_fastcode_detail_url,
    _strip_tag_suffix,
    _strip_trailing_tags,
    parse_detail_page,
    parse_page,
    run_parse,
)


def test_detect_total_pages_sliding_window() -> None:
    """_detect_total_pages follows pagination when FastCode shows ~6 links per page (51 total)."""
    TOTAL = 51

    def fake_html(page: int) -> str:
        # Sliding window: on page p show links to p-2..p+3 (excluding p), capped to 1..TOTAL
        links = []
        for delta in range(-2, 4):
            if delta == 0:
                continue
            q = page + delta
            if 1 <= q <= TOTAL:
                links.append(q)
        return " ".join(f"?Page={p}" for p in links)

    fetch_calls: list[int] = []

    def mock_fetch(p: int, _opener) -> str:
        fetch_calls.append(p)
        return fake_html(p)

    with (
        patch("onec_help.knowledge.loaders.parse_fastcode._fetch_page", side_effect=mock_fetch),
        patch("onec_help.knowledge.loaders.parse_fastcode.time.sleep"),
    ):
        opener = MagicMock()
        pages = _detect_total_pages(opener)

    assert len(pages) == TOTAL, f"Expected {TOTAL} pages, got {len(pages)}"
    assert pages[0] == 1 and pages[-1] == TOTAL
    # Sliding window (~5 links/page): ~18 probes for 51 pages is expected
    assert len(fetch_calls) <= 25, f"Too many probes: {fetch_calls}"


def test_is_safe_fastcode_detail_url_relative() -> None:
    """Relative /Templates/123/slug is allowed."""
    assert (
        _is_safe_fastcode_detail_url("/Templates/123/slug")
        == "https://fastcode.im/Templates/123/slug"
    )


def test_is_safe_fastcode_detail_url_absolute() -> None:
    """Absolute https://fastcode.im/... is allowed."""
    assert (
        _is_safe_fastcode_detail_url("https://fastcode.im/Templates/456/foo")
        == "https://fastcode.im/Templates/456/foo"
    )


def test_is_safe_fastcode_detail_url_rejects_protocol_relative() -> None:
    """Protocol-relative //evil.com/... is rejected."""
    assert _is_safe_fastcode_detail_url("//evil.com/Templates/1/x") is None


def test_is_safe_fastcode_detail_url_rejects_other_host() -> None:
    """Other hosts are rejected."""
    assert _is_safe_fastcode_detail_url("https://other.com/Templates/1/x") is None


def test_is_safe_fastcode_detail_url_rejects_javascript() -> None:
    """javascript: scheme is rejected."""
    assert _is_safe_fastcode_detail_url("javascript:alert(1)") is None


def test_is_safe_fastcode_detail_url_rejects_query() -> None:
    """URLs with query string are rejected (stricter)."""
    assert _is_safe_fastcode_detail_url("/Templates/1/x?foo=1") is None


def test_strip_tag_suffix_title_plus_tags() -> None:
    """Description = title + tags (TurboConf ИР) is stripped to empty."""
    assert _strip_tag_suffix("ИР Найти в спискеTurboConf ИР", "ИР Найти в списке") == ""


def test_strip_tag_suffix_real_content_unchanged() -> None:
    """Real description is not modified."""
    desc = "При использовании Git эта команда адаптера открывает инструмент."
    assert _strip_tag_suffix(desc, "ИР Найти фрагмент") == desc


def test_strip_trailing_tags() -> None:
    """Trailing TurboConf ИР is removed from long description."""
    desc = "При использовании Git эта команда адаптера. TurboConf ИР"
    assert _strip_trailing_tags(desc) == "При использовании Git эта команда адаптера."


def test_parse_detail_page_extracts_instruction() -> None:
    """parse_detail_page extracts full description for local storage."""
    html = """
    <html><body>
    <h1>Проверка счета на групповой</h1>
    <span class="break-word">Описание для проверки проводок по счетам-группам.</span>
    <p>Дополнительный параграф с подробной документацией для локального доступа.</p>
    <pre>Процедура Проверить()
        // код
    КонецПроцедуры</pre>
    </body></html>
    """
    desc, code = parse_detail_page(html, "Проверка счета")
    assert "Проверка счета на групповой" in desc
    assert "проводок по счетам-группам" in desc
    assert "документаци" in desc  # подробной документацией/документации
    assert "Процедура Проверить" in code


def test_parse_page() -> None:
    """parse_page extracts items from FastCode listing HTML."""
    html = """
    <html><body>
    <h3>Запрос проверки</h3>
    <span class="break-word">Описание запроса для проверки данных.</span>
    <pre>Запрос = Новый Запрос;
    Запрос.Текст = "ВЫБРАТЬ 1";</pre>
    <a href="/Templates/123/query-check">Читать</a>
    </body></html>
    """
    items = parse_page(html)
    assert len(items) >= 1
    assert items[0]["title"] == "Запрос проверки"
    assert "запроса" in items[0].get("description", "").lower() or "Описание" in items[0].get(
        "description", ""
    )
    assert "Новый Запрос" in items[0].get("code_snippet", "")


def test_extract_detail_links() -> None:
    """_extract_detail_links maps title to detail URL from h3+link structure."""
    from bs4 import BeautifulSoup

    html = """
    <html><body>
    <h3>Мой шаблон</h3>
    <a href="/Templates/456/my-template">Ссылка</a>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    links = _extract_detail_links(soup)
    assert "Мой шаблон" in links
    assert "fastcode.im/Templates/456" in links["Мой шаблон"]


def test_run_parse_fastcode_mocked(tmp_path) -> None:
    """run_parse with mocked fetch produces JSON output."""
    import json

    listing_html = """
    <html><body>
    <h3>Проверка счета</h3>
    <span class="break-word">Проверка проводок.</span>
    <a href="/Templates/789/check">Детали</a>
    </body></html>
    """
    detail_html = """
    <html><body>
    <h1>Проверка счета на групповой</h1>
    <p>Описание.</p>
    <pre>Процедура Проверить() КонецПроцедуры</pre>
    </body></html>
    """
    out = tmp_path / "fastcode_snippets.json"

    with (
        patch("onec_help.knowledge.loaders.parse_fastcode._get_opener", return_value=MagicMock()),
        patch(
            "onec_help.knowledge.loaders.parse_fastcode._fetch_page",
            side_effect=lambda _p, _o: listing_html,
        ),
        patch(
            "onec_help.knowledge.loaders.parse_fastcode.fetch_url",
            side_effect=lambda _url, _o: detail_html,
        ),
        patch("onec_help.knowledge.loaders.parse_fastcode.time.sleep"),
    ):
        result = run_parse(out, pages=[1], fetch_detail=True)

    assert result == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) >= 1
    assert any("Проверка" in (i.get("title") or "") for i in data)
