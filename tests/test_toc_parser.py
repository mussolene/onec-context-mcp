"""Tests for toc_parser (PackBlock TOC from hbk-viewer)."""

from onec_help.help_core.toc_parser import (
    load_toc_json,
    parse_toc_content,
    path_to_section_and_title_from_toc,
    save_toc_json,
    toc_chunks_to_flat,
    tokenize_toc,
)


def test_tokenize_empty():
    assert tokenize_toc("") == []


def test_tokenize_braces_and_comma():
    # Comma is filtered out (same as hbk-viewer Tokenizer)
    assert tokenize_toc(" { } , ") == ["{", "}"]


def test_tokenize_quoted_string():
    assert tokenize_toc('"hello"') == ['"hello"']
    # Escaped quote "" inside string becomes one token with inner quote
    assert tokenize_toc('"a""b"') == ['"a"b"']


def test_tokenize_bom_ignored():
    assert tokenize_toc("\ufeff{") == ["{"]


def test_parse_toc_content_empty():
    assert parse_toc_content("") == []


def test_parse_toc_content_minimal_table():
    # Minimal TableOfContent: { 0 } (chunkCount=0, no chunks)
    content = "{ 0 }"
    assert parse_toc_content(content) == []


def test_parse_toc_content_one_chunk():
    # TableOfContent: { chunkCount  chunk... }; chunk: { id parentId childCount [childIds] props };
    # props: { n1 n2  nameContainer  "htmlPath" }; nameContainer: { n1 n2  nameObject... }
    content = (
        "{ 1 "
        "{ 1 0 0 "
        '{ 1 2 { 2 1 { "ru" "Title RU" } { "en" "Title EN" } } "content/Page.html" } '
        "} "
        "}"
    )
    chunks = parse_toc_content(content)
    assert len(chunks) == 1
    assert chunks[0]["id"] == 1
    assert chunks[0]["parent_id"] == 0
    assert chunks[0]["html_path"] == "content/Page.html"
    assert chunks[0]["title_ru"] == "Title RU"
    assert chunks[0]["title_en"] == "Title EN"


def test_toc_chunks_to_flat_breadcrumb():
    chunks = [
        {"id": 1, "parent_id": 0, "html_path": "root.html", "title_ru": "Root", "title_en": "Root"},
        {
            "id": 2,
            "parent_id": 1,
            "html_path": "child.html",
            "title_ru": "Child",
            "title_en": "Child",
        },
    ]
    flat = toc_chunks_to_flat(chunks, infer_entity_type=False)
    assert len(flat) == 2
    by_path = {x["path"]: x for x in flat}
    assert by_path["root.html"]["breadcrumb"] == []
    assert by_path["child.html"]["breadcrumb"] == ["Root"]


def test_path_to_section_and_title_from_toc():
    flat = [
        {
            "path": "a/b.html",
            "title_ru": "B",
            "title_en": "B en",
            "breadcrumb": ["A", "B"],
            "entity_type": "topic",
        },
    ]
    path_to_section, path_to_title = path_to_section_and_title_from_toc(flat)
    assert path_to_section["a/b.html"] == ("A/B", ["A", "B"])
    assert path_to_title["a/b.html"] == "B"
    assert path_to_section.get("a/b") == ("A/B", ["A", "B"])
    assert path_to_title.get("a/b") == "B"


def test_path_to_section_and_title_from_toc_duplicate_path_last_wins():
    """When flat has duplicate paths, last occurrence wins for section and title."""
    flat = [
        {"path": "page.html", "title_ru": "First", "breadcrumb": ["A"], "entity_type": "topic"},
        {
            "path": "page.html",
            "title_ru": "Second",
            "breadcrumb": ["B", "Page"],
            "entity_type": "topic",
        },
    ]
    path_to_section, path_to_title = path_to_section_and_title_from_toc(flat)
    assert path_to_title["page.html"] == "Second"
    assert path_to_section["page.html"] == ("B/Page", ["B", "Page"])


def test_load_toc_json_missing(tmp_path):
    assert load_toc_json(tmp_path / "nonexistent.json") is None


def test_save_and_load_toc_json(tmp_path):
    flat = [
        {"path": "p.html", "title_ru": "T", "breadcrumb": [], "entity_type": "topic"},
    ]
    p = tmp_path / ".toc.json"
    save_toc_json(p, flat)
    assert p.exists()
    loaded = load_toc_json(p)
    assert loaded == flat
