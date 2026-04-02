"""Tests for form_metadata (Form.xml parsing)."""

from pathlib import Path

from onec_help.knowledge.form_metadata import _text, get_form_metadata, parse_form_xml


def test_get_form_metadata_minimal(tmp_path: Path) -> None:
    """Parse minimal Form.xml with one attribute and one command."""
    form = tmp_path / "Form.xml"
    form.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Attributes>
    <Attribute name="Объект" id="1">
      <Type><v8:Type>DataProcessorObject.X</v8:Type></Type>
    </Attribute>
  </Attributes>
  <Commands>
    <Command name="Выполнить" id="1">
      <Action>Выполнить</Action>
    </Command>
  </Commands>
</Form>""",
        encoding="utf-8",
    )
    data = get_form_metadata(form)
    assert "error" not in data
    assert len(data["attributes"]) == 1
    assert data["attributes"][0]["name"] == "Объект"
    assert "DataProcessorObject.X" in data["attributes"][0]["type"]
    assert len(data["commands"]) == 1
    assert data["commands"][0]["name"] == "Выполнить"
    assert data["commands"][0]["action"] == "Выполнить"


def test_get_form_metadata_not_found() -> None:
    """Returns error when file does not exist."""
    data = get_form_metadata(Path("/nonexistent/Form.xml"))
    assert "error" in data
    assert data["attributes"] == []
    assert data["commands"] == []


def test_text_none_returns_empty() -> None:
    """_text(None) returns empty string."""
    assert _text(None) == ""


def test_parse_form_xml_invalid_returns_error() -> None:
    """Invalid XML returns error dict with empty attributes/commands."""
    data = parse_form_xml("<invalid")
    assert "error" in data
    assert data["attributes"] == []
    assert data["commands"] == []


def test_get_form_metadata_unicode_error(tmp_path: Path) -> None:
    """File with invalid UTF-8 returns error dict."""
    form = tmp_path / "Form.xml"
    form.write_bytes(b"\xff\xfe\xfd")
    data = get_form_metadata(form)
    assert "error" in data
    assert data["attributes"] == []
    assert data["commands"] == []


def test_form_metadata_fallback_without_defusedxml() -> None:
    """When defusedxml is not available, form_metadata uses xml.etree.ElementTree."""
    import importlib
    import sys
    from unittest.mock import patch

    import onec_help.knowledge.form_metadata as fm

    # Force the ImportError path (use standard ET)
    with patch.dict(sys.modules, {"defusedxml": None, "defusedxml.ElementTree": None}):
        importlib.reload(fm)
        data = fm.parse_form_xml(
            """<?xml version="1.0"?><Form xmlns="http://v8.1c.ru/8.3/xcf/logform">
            <Attributes/><Commands/></Form>"""
        )
        assert "error" not in data
        assert data["attributes"] == []
        assert data["commands"] == []
    importlib.reload(fm)


def test_parse_form_xml_content() -> None:
    """Parse Form.xml from string content."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Form xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:v8="http://v8.1c.ru/8.1/data/core">
  <Attributes>
    <Attribute name="Объект" id="1">
      <Type><v8:Type>cfg:DataProcessorObject.X</v8:Type></Type>
    </Attribute>
  </Attributes>
  <Commands>
    <Command name="Выполнить" id="1"><Action>Выполнить</Action></Command>
  </Commands>
</Form>"""
    data = parse_form_xml(xml)
    assert "error" not in data
    assert data["attributes"][0]["name"] == "Объект"
    assert data["commands"][0]["name"] == "Выполнить"
