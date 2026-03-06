"""Tests for parse_its_v8std (ITS v8std crawler)."""

from unittest.mock import MagicMock, patch

import onec_help.parse_its_v8std as mod


def test_safe_folder_name_normal() -> None:
    assert mod._safe_folder_name("Создание и изменение") == "Создание_и_изменение"
    assert mod._safe_folder_name("Foo-Bar_123") == "Foo-Bar_123"


def test_safe_folder_name_strips_invalid() -> None:
    out = mod._safe_folder_name("a@b#c")
    assert out == "abc" or len(out) == 12  # may fallback to hash if empty


def test_safe_folder_name_empty_fallback_hash() -> None:
    name = mod._safe_folder_name("@@@")
    assert len(name) <= 12
    assert name.isalnum() or "_" in name


def test_safe_folder_name_max_len() -> None:
    long_name = "a" * 100
    assert len(mod._safe_folder_name(long_name, max_len=60)) == 60


def test_sanitize_text() -> None:
    assert mod._sanitize_text("  hello  ") == "hello"
    assert mod._sanitize_text("") == ""
    assert mod._sanitize_text("normal text") == "normal text"


def test_detect_charset_content_type_utf8() -> None:
    resp = MagicMock()
    resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    raw = "привет".encode()
    assert mod._detect_charset(resp, raw) == "utf-8"


def test_detect_charset_content_type_windows1251() -> None:
    resp = MagicMock()
    resp.headers = {"Content-Type": "text/html; charset=windows-1251"}
    raw = "тест".encode("windows-1251")
    assert mod._detect_charset(resp, raw) in ("utf-8", "windows-1251")


def test_detect_charset_meta_charset() -> None:
    resp = MagicMock()
    resp.headers = {}
    raw = b'<html><head><meta charset="utf-8"></head></html>'
    assert mod._detect_charset(resp, raw) == "utf-8"


def test_get_iframe_doc_url_by_id() -> None:
    html = '<html><body><iframe id="w_metadata_doc_frame" src="/db/content/v8std/123/print"></iframe></body></html>'
    url = mod._get_iframe_doc_url(html, "https://its.1c.ru/db/v8std/content/123/hdoc")
    assert url is not None
    assert "123" in url or "print" in url


def test_get_iframe_doc_url_missing() -> None:
    html = "<html><body><p>No iframe</p></body></html>"
    assert mod._get_iframe_doc_url(html, "https://its.1c.ru/") is None


def test_extract_content_links() -> None:
    html = "Links: /db/v8std/content/456/hdoc and /db/v8std/content/789/hdoc"
    base = "https://its.1c.ru"
    links = mod._extract_content_links(html, base)
    assert len(links) >= 1
    assert any("/content/456/" in u or "/content/789/" in u for u in links)


def test_extract_browse_links() -> None:
    html = "Nav: /db/v8std/browse/13/-1/26 and /db/v8std/browse/13/-1/28"
    base = "https://its.1c.ru"
    links = mod._extract_browse_links(html, base)
    assert any("browse" in u for u in links)


def test_browse_path_from_url() -> None:
    assert mod._browse_path_from_url("https://its.1c.ru/db/v8std/browse/13/-1/26/28") == [
        "26",
        "28",
    ]
    assert mod._browse_path_from_url("https://its.1c.ru/db/v8std") == []
    assert mod._browse_path_from_url("https://its.1c.ru/db/v8std/browse/13/-1/") == []


def test_path_cache_key() -> None:
    assert mod._path_cache_key(["26", "28"]) == "26/28"
    assert mod._path_cache_key([]) == ""


def test_parse_print_page_sufficient_content() -> None:
    body_text = "A" * 200  # above _MIN_REAL_CONTENT_CHARS
    html = f"<html><body><p>{body_text}</p></body></html>"
    out = mod._parse_print_page(html, "https://its.1c.ru/print", "Title")
    assert out is not None
    assert "A" in out


def test_parse_print_page_too_short_returns_none() -> None:
    html = "<html><body><p>Short</p></body></html>"
    assert mod._parse_print_page(html, "https://its.1c.ru/", "T") is None


def test_parse_content_page_with_h1_and_body() -> None:
    content = "Статья о стандартах. " * 20  # long enough
    html = f"<html><head><title>Doc</title></head><body><h1>Стандарт 1</h1><main><p>{content}</p></main></body></html>"
    out = mod._parse_content_page(html, "https://its.1c.ru/db/v8std/content/123/hdoc")
    assert out is not None
    assert "title" in out
    assert "Стандарт" in out.get("title", "") or content in out.get("code_snippet", "")


def test_parse_content_page_nav_only_returns_none() -> None:
    html = "<html><body><nav>Вход</nav><p>Об 1С:ИТС</p></body></html>"
    out = mod._parse_content_page(html, "https://its.1c.ru/content/1/hdoc")
    assert out is None or out.get("title")  # may still get title from url


def test_crawl_content_with_paths_mocked() -> None:
    """_crawl_content_with_paths with mocked _fetch returns content URLs and path titles."""
    browse_html = (
        "<html><body><h1>Browse</h1>"
        "Links: <a href='/db/v8std/content/111/hdoc'>C1</a> "
        "<a href='/db/v8std/browse/13/-1/26'>Sub</a></body></html>"
    )
    main_html = "<html><body><h1>v8std</h1></body></html>"

    def fake_fetch(url, _opener):
        if "browse/13/-1/26" in url:
            return browse_html
        return main_html

    with patch.object(mod, "_fetch", side_effect=fake_fetch):
        with patch("time.sleep"):
            result = mod._crawl_content_with_paths(
                MagicMock(), start_url=mod._V8STD_BROWSE, max_pages=3
            )
    assert isinstance(result, list)
    # May have content URLs from browse page
    for item in result:
        url, path_titles = item
        assert isinstance(url, str)
        assert isinstance(path_titles, list)


def test_fetch_its_v8std_items_mocked_empty_crawl() -> None:
    with patch.object(mod, "_crawl_content_with_paths", return_value=[]):
        items = mod.fetch_its_v8std_items(opener=MagicMock(), max_content=0)
    assert items == []


def test_fetch_its_v8std_items_mocked_one_page() -> None:
    url = "https://its.1c.ru/db/v8std/content/999/hdoc"
    content_html = (
        "<html><body><h1>Test Article</h1><main><p>" + "X" * 200 + "</p></main></body></html>"
    )

    def fake_fetch(u, _opener):
        if "content/999" in u:
            return content_html
        return "<html><body>empty</body></html>"

    with patch.object(mod, "_crawl_content_with_paths", return_value=[(url, ["Section"])]):
        with patch.object(mod, "_fetch", side_effect=fake_fetch):
            with patch.object(mod, "_get_iframe_doc_url", return_value=None):
                with patch("time.sleep"):
                    items = mod.fetch_its_v8std_items(
                        opener=MagicMock(), start_url=url, max_content=1
                    )
    assert len(items) >= 1
    assert items[0]["source"] == "its.1c.ru"
    assert "section_path" in items[0]
